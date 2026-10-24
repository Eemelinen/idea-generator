"""Stage 3 claim verification: fetch each source, cache its text, fuzzy-match the quote.

`verify_run` turns the candidate-claim blocks of runs/<run_id>/02_research/*.md into
03_claims/<dimension>.json, fetches every cited page (robots.txt respected, 10 s timeout, text
cached in cache/<sha256(url)>.txt and recorded in the `sources` table), marks a claim `verified`
only when its quote matches the page text at rapidfuzz partial_ratio ≥ 90, types allow-listed
official domains as `official`, and writes 03_claims/verified.json plus the `claims` rows.
In a back-test run (`new_run.py --as-of`), a claim whose `published_date` is after the as-of date
is `unverified` with the flag `after_as_of`, and its source is not fetched.

API claims (IF-209): a `source_type: api` claim citing a URL of one of the `fi` tools is not
fetched as a page; `ideaforge.fi.requery` re-runs the query and the claim stays `verified` only if
its value is in the answer (exact for an integer count, ±1 % for a float) or, without a value, its
quote matches the answer's text. A mismatch or a URL that is not a client call → `unverified`
with `api_mismatch`; a failed re-query → `unfetchable`. An `api` claim on any other URL is
fetched and quote-matched like a page.

Extracted claims (IF-211): the claim extractor's candidate claims for a research file
(03_claims/extracted/<stem>.json, `ideaforge.extract`) join that file's parsed claims and are
verified the same way.

Conflicts (IF-210): `detect_conflicts` groups verified claims of one dimension whose statements
are similar (rapidfuzz token_sort_ratio ≥ 80) and whose values differ by more than 25 %, as long
as they cite different sources (for an `api` claim, another table or endpoint) and their
statements name the same years, quarters, months and
capitalised names (IF-216: on the first live run every pair from one source, and every pair that
differed only in the period or the area, was a time series or a breakdown, not a conflict); every
claim of a group becomes `conflict` and is kept, and the groups go to 03_claims/conflicts.json in
preference order (official > api > industry > news > forum > vendor, then the newest) for the
synthesizer.

The HTTP layers are plain callables (`HttpGet`, `ideaforge.fi.http.Transport`) so tests inject
synthetic pages and the IF-200 recordings and never touch the network.
"""

from __future__ import annotations

import hashlib
import os
import re
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import lxml.etree
import lxml.html
import requests
import trafilatura
from pydantic import TypeAdapter
from rapidfuzz import fuzz

from ideaforge import config, db, extract, runs
from ideaforge.fi import requery
from ideaforge.fi.http import Transport
from ideaforge.schemas import CandidateClaim, Claim, ConflictGroup, SourceType
from ideaforge.validate_file import candidate_claims, normalize_url

USER_AGENT = "ideaforge/0.1 (local business-idea validator; claim quote verification)"
TIMEOUT_S = 10
MATCH_THRESHOLD = 90.0
# Flags this module owns: recomputed on every run, never taken from a research agent.
FETCH_FLAGS = ("unfetchable", "robots_disallowed")
AS_OF_FLAG = "after_as_of"
API_FLAG = "api_mismatch"
OWNED_FLAGS = (*FETCH_FLAGS, AS_OF_FLAG, API_FLAG)
# API re-query (IF-209): an integer (a count) must match exactly, a float within ±1 %.
FLOAT_TOLERANCE = 0.01
# Conflicts (IF-210): similar statements (token_sort_ratio ≥ 80) whose values differ by > 25 %.
CONFLICT_SIMILARITY = 80.0
CONFLICT_DIFFERENCE = 0.25
SOURCE_PREFERENCE: tuple[SourceType, ...] = ("official", "api", "industry", "news", "forum", "vendor")
CONFLICTS_FILE = "conflicts.json"
# HTML is reduced to its text; other text types (text/*, JSON, XML) are matched as they are;
# anything else (PDF, images) is unfetchable.
HTML_TYPES = ("", "text/html", "application/xhtml+xml")
TEXT_TYPES = ("text/", "application/json", "application/xml")
TEXT_SUFFIXES = ("+json", "+xml")
# A page whose only text asks for JavaScript is a JS-only page, not its content.
JS_ONLY_RE = re.compile(r"enable javascript|javascript (?:is )?(?:required|disabled)|ota javascript käyttöön", re.I)
JS_ONLY_MAX_CHARS = 300
# lxml refuses a str that declares its own encoding (common in XHTML); the text is already decoded.
XML_DECL_RE = re.compile(r"^\ufeff?\s*<\?xml[^>]*\?>")


class FetchError(Exception):
    """A network-level failure (timeout, DNS, refused connection)."""


@dataclass(frozen=True)
class HttpResponse:
    status: int
    text: str
    content_type: str = "text/html"


HttpGet = Callable[[str], HttpResponse]

_ssl_ready = False


def requests_get(url: str) -> HttpResponse:
    """The real fetcher: GET with the ideaforge UA and a 10 s timeout, via the OS trust store."""
    global _ssl_ready
    if not _ssl_ready:
        import truststore  # TLS interception on the dev machine (TICKETS.md plan note 9)

        truststore.inject_into_ssl()
        _ssl_ready = True
    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_S)
    except requests.RequestException as e:
        raise FetchError(f"{type(e).__name__}: {e}") from e
    content_type = r.headers.get("Content-Type", "")
    if "charset" not in content_type.lower() and content_type.startswith("text/"):
        # requests assumes ISO-8859-1 for text/* without a charset; Finnish pages are mostly UTF-8.
        r.encoding = r.apparent_encoding
    return HttpResponse(status=r.status_code, text=r.text, content_type=content_type)


# ---------------------------------------------------------------- quote matching


_PUNCT = str.maketrans(
    {
        "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'",
        "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u00ab": '"', "\u00bb": '"',
        "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-", "\u2212": "-",
        "\u00ad": None,  # soft hyphen
    }
)


def normalize(text: str) -> str:
    """Casefold, strip diacritics (ä → a), unify quotes and dashes, collapse whitespace."""
    text = unicodedata.normalize("NFKD", text.translate(_PUNCT))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.casefold().split())


def quote_score(quote: str, text: str) -> float:
    """Best fuzzy match of the quote inside the text, 0–100.

    partial_ratio aligns the shorter string inside the longer one, so a page shorter than the
    quote would "contain" it; that case falls back to the plain ratio.
    """
    q, t = normalize(quote), normalize(text)
    if not q or not t:
        return 0.0
    if len(t) < len(q):
        return fuzz.ratio(q, t)
    return fuzz.partial_ratio(q, t)


def quote_matches(quote: str, text: str) -> bool:
    return quote_score(quote, text) >= MATCH_THRESHOLD


# ---------------------------------------------------------------- source typing


def domain_matches(url: str, entry: str) -> bool:
    """`vero.fi` matches vero.fi and any subdomain; `ec.europa.eu/eurostat` also needs the path."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower().rstrip(".")
    entry_host, _, entry_path = entry.lower().partition("/")
    if host != entry_host and not host.endswith("." + entry_host):
        return False
    if not entry_path:
        return True
    path = parts.path.lower().strip("/")
    entry_path = entry_path.strip("/")
    return path == entry_path or path.startswith(entry_path + "/")


def is_official(url: str, official: list[str] | None = None) -> bool:
    entries = config.domains().official if official is None else official
    return any(domain_matches(url, e) for e in entries)


def source_type(claim: Claim) -> SourceType:
    """Allow-listed official domain → `official`; `api` stays `api` (IF-209 re-queries it)."""
    if claim.source_type != "api" and is_official(claim.source_url):
        return "official"
    return claim.source_type


# ---------------------------------------------------------------- fetching


@dataclass(frozen=True)
class Page:
    url: str
    status: Literal["ok", "unfetchable", "robots_disallowed"]
    retrieved_at: datetime
    text: str | None = None
    detail: str = ""
    from_cache: bool = False


def cache_path(url: str) -> Path:
    return config.CACHE_DIR / f"{hashlib.sha256(url.encode('utf-8')).hexdigest()}.txt"


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def page_text(html: str) -> str:
    """All visible text of an HTML page, not just trafilatura's main-content extract.

    A quote from an info box, table or sidebar is still on the page, and boilerplate around it
    cannot make a wrong quote match. Scripts and styles are dropped first so a JS-only page stays
    empty (its <noscript> notice remains for JS_ONLY_RE).
    """
    tree = lxml.html.fromstring(XML_DECL_RE.sub("", html, count=1))
    for el in tree.xpath("//script|//style|//template"):
        el.drop_tree()
    return trafilatura.html2txt(tree, clean=False)


def extract_text(resp: HttpResponse) -> str | None:
    """Readable text of a response, or None when there is none to match against."""
    ctype = resp.content_type.split(";", 1)[0].strip().lower()
    if ctype in HTML_TYPES:
        try:
            text = page_text(resp.text)
        except (ValueError, lxml.etree.LxmlError):  # markup lxml cannot parse: let trafilatura try
            text = None
        text = text or trafilatura.extract(resp.text, favor_recall=True, include_tables=True)
    elif ctype.startswith(TEXT_TYPES) or ctype.endswith(TEXT_SUFFIXES):
        text = resp.text
    else:
        return None
    text = (text or "").strip()
    if not text or (len(text) <= JS_ONLY_MAX_CHARS and JS_ONLY_RE.search(text)):
        return None
    return text


@dataclass
class Fetcher:
    """Fetches pages once per URL: cache first, then robots.txt, then the page itself."""

    http_get: HttpGet = requests_get
    record_sources: bool = True
    _pages: dict[str, Page] = field(default_factory=dict)
    _robots: dict[str, RobotFileParser | None] = field(default_factory=dict)

    def get(self, url: str) -> Page:
        if url not in self._pages:
            self._pages[url] = self._load(url)
        return self._pages[url]

    def _load(self, url: str) -> Page:
        cached = cache_path(url)
        if cached.is_file():
            fetched_at = datetime.fromtimestamp(cached.stat().st_mtime, UTC).replace(microsecond=0)
            text = cached.read_text(encoding="utf-8")
            self._record(url, text, fetched_at, None, keep_existing=True)
            return Page(url, "ok", fetched_at, text, "cache hit", from_cache=True)

        if not self.robots_allowed(url):
            return Page(url, "robots_disallowed", _now(), detail="robots.txt disallows this URL")

        fetched_at = _now()
        try:
            resp = self.http_get(url)
        except Exception as e:  # one bad source must not cost the whole run its verified.json
            self._record(url, None, fetched_at, None)
            return Page(url, "unfetchable", fetched_at, detail=f"{type(e).__name__}: {e}")
        if resp.status >= 400:
            self._record(url, None, fetched_at, resp.status)
            return Page(url, "unfetchable", fetched_at, detail=f"HTTP {resp.status}")
        try:
            text = extract_text(resp)
        except Exception as e:
            text, problem = None, f"text extraction failed: {type(e).__name__}: {e}"
        else:
            problem = f"no extractable text ({resp.content_type or 'no type'})"
        if text is None:
            self._record(url, None, fetched_at, resp.status)
            return Page(url, "unfetchable", fetched_at, detail=problem)
        # Write then rename, so a killed run never leaves a truncated page that counts as cached.
        cached.parent.mkdir(parents=True, exist_ok=True)
        tmp = cached.with_name(f"{cached.name}.{os.getpid()}.tmp")
        try:
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, cached)
        finally:
            tmp.unlink(missing_ok=True)
        self._record(url, text, fetched_at, resp.status)
        return Page(url, "ok", fetched_at, text)

    def robots_allowed(self, url: str) -> bool:
        """urllib.robotparser semantics: 401/403 on robots.txt → disallow all, other 4xx → allow all.

        A robots.txt that cannot be fetched at all (network error, 5xx) allows the page fetch,
        which then fails or succeeds on its own.
        """
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            parser: RobotFileParser | None = RobotFileParser(origin + "/robots.txt")
            try:
                resp = self.http_get(origin + "/robots.txt")
            except Exception:  # unreachable robots.txt: see robots_allowed docstring
                parser = None
            else:
                if resp.status in (401, 403):
                    parser.disallow_all = True
                elif resp.status >= 400:
                    parser = None
                else:
                    parser.parse(resp.text.splitlines())
            self._robots[origin] = parser
        parser = self._robots[origin]
        return parser is None or parser.can_fetch(USER_AGENT, url)

    def _record(
        self, url: str, text: str | None, fetched_at: datetime, status: int | None, keep_existing: bool = False
    ) -> None:
        if not self.record_sources:
            return
        if keep_existing and _source_known(url):
            return
        path = cache_path(url)
        try:
            rel = path.relative_to(config.ROOT).as_posix()
        except ValueError:
            rel = str(path)
        db.upsert_source(
            url,
            (urlsplit(url).hostname or "").lower(),
            content_sha=hashlib.sha256(text.encode("utf-8")).hexdigest() if text is not None else None,
            cache_path=rel if text is not None else None,
            fetched_at=fetched_at.isoformat(),
            http_status=status,
        )


def _source_known(url: str) -> bool:
    with db.session() as conn:
        return conn.execute("SELECT 1 FROM sources WHERE url=?", (url,)).fetchone() is not None


# ---------------------------------------------------------------- API re-query (IF-209)


@dataclass(frozen=True)
class ApiResult:
    url: str
    status: Literal["ok", "unfetchable", "not_a_query"]
    retrieved_at: datetime
    answer: requery.Answer | None = None
    detail: str = ""


@dataclass
class Requerier:
    """Re-runs each cited API URL once per verification run (the clients cache for 24 h)."""

    transport: Transport | None = None
    record_sources: bool = True
    _results: dict[str, ApiResult] = field(default_factory=dict)

    def get(self, url: str) -> ApiResult:
        if url not in self._results:
            self._results[url] = self._load(url)
        return self._results[url]

    def _load(self, url: str) -> ApiResult:
        try:
            answer = requery.requery(url, self.transport)
        except requery.NotAQuery as e:
            return ApiResult(url, "not_a_query", _now(), detail=str(e))
        except Exception as e:  # one bad query must not cost the whole run its verified.json
            fetched_at = _now()
            self._record(url, None, fetched_at)
            return ApiResult(url, "unfetchable", fetched_at, detail=f"{type(e).__name__}: {e}")
        self._record(url, answer.text, answer.response.retrieved_at)
        return ApiResult(url, "ok", answer.response.retrieved_at, answer)

    def _record(self, url: str, text: str | None, fetched_at: datetime) -> None:
        if not self.record_sources:
            return
        db.upsert_source(
            url,
            (urlsplit(url).hostname or "").lower(),
            content_sha=hashlib.sha256(text.encode("utf-8")).hexdigest() if text is not None else None,
            cache_path=None,  # the answer lives in the client's own cache/<api>/
            fetched_at=fetched_at.isoformat(),
            http_status=200 if text is not None else None,
        )


def value_matches(claimed: float, actual: int | float) -> bool:
    """Exact for an integer (a count), within ±1 % for a float."""
    if isinstance(actual, int):
        return claimed == actual
    return abs(claimed - actual) <= FLOAT_TOLERANCE * abs(actual)


def api_confirms(claim: Claim, answer: requery.Answer) -> bool:
    """The claim's value is in the answer; a claim without a value needs its quote in the answer."""
    if claim.value is None:
        return quote_matches(claim.quote, answer.text)
    return any(value_matches(claim.value, v) for v in answer.values)


def verify_api_claim(claim: Claim, result: ApiResult) -> Claim:
    """The claim with retrieved_at, flags and verification set from the re-queried answer."""
    flags = [f for f in claim.flags if f not in OWNED_FLAGS]
    if result.answer is not None and api_confirms(claim, result.answer):
        verification = "verified"
    else:
        verification = "unverified"
        flags.append("unfetchable" if result.status == "unfetchable" else API_FLAG)
    return claim.model_copy(
        update={
            "source_type": source_type(claim),
            "retrieved_at": result.retrieved_at,
            "flags": flags,
            "verification": verification,
        }
    )


def requery_warning(claim: Claim, result: ApiResult) -> str | None:
    if result.answer is None:
        flag = "unfetchable" if result.status == "unfetchable" else API_FLAG
        return f"{claim.claim_id}: {flag} {claim.source_url} ({result.detail})"
    if api_confirms(claim, result.answer):
        return None
    what = f"value {claim.value:g}" if claim.value is not None else "quote"
    return f"{claim.claim_id}: {API_FLAG} {claim.source_url} ({what} not in the re-queried answer)"


# ---------------------------------------------------------------- conflicts (IF-210)


def statements_similar(a: str, b: str) -> bool:
    return fuzz.token_sort_ratio(normalize(a), normalize(b)) >= CONFLICT_SIMILARITY


def values_conflict(a: float, b: float) -> bool:
    """The values differ by more than 25 % of the smaller one (100 vs 126: yes; 100 vs 124: no)."""
    low = min(abs(a), abs(b))
    if low == 0:
        return a != b
    return abs(a - b) / low > CONFLICT_DIFFERENCE


def _units_compatible(a: str | None, b: str | None) -> bool:
    """Equal units, or a unit missing on either side: 2100 persons and 2.1 thousand persons are
    different units, not a conflict."""
    if a is None or b is None or not a.strip() or not b.strip():
        return True
    return normalize(a) == normalize(b)


_MONTHS = (
    r"January|February|March|April|May|June|July|August|September|October|November|December"
    r"|(?:tammi|helmi|maalis|huhti|touko|kesä|heinä|elo|syys|loka|marras|joulu)\w*"
)
# What a statement is about besides its value: a year (2025, 2025Q1, 2025M07), a quarter, a month,
# or a capitalised word (an area, a platform, a group: Rääkkylä, Finland, Airbnb, Finnish).
QUALIFIER_RE = re.compile(rf"\b(?:(?:19|20)\d{{2}}(?:Q[1-4]|M\d{{2}})?|Q[1-4]|{_MONTHS})\b|\b[A-ZÅÄÖ][\w-]*")


# Capitalised only because they start the sentence.
_NOT_QUALIFIERS = frozenset(
    "a an the in on at by for from of to since during until after before according there this these "
    "that its it their under over with without per each every all some most no".split()
)


def qualifiers(statement: str) -> set[str]:
    return {q.casefold() for q in QUALIFIER_RE.findall(statement)} - _NOT_QUALIFIERS


def _source(claim: Claim) -> str:
    """The claim's source for conflict checks: an `api` claim's table or endpoint (its URL without
    the query, which only selects cells), any other claim's normalized URL."""
    url = normalize_url(claim.source_url)
    return url.split("?", 1)[0] if claim.source_type == "api" else url


def in_conflict(a: Claim, b: Claim) -> bool:
    """Two readings of one quantity that disagree. Two claims on one source are two cells or two
    facts of it, and statements naming another period or area are a series, not a conflict."""
    return (
        a.dimension == b.dimension
        and a.value is not None
        and b.value is not None
        and _units_compatible(a.unit, b.unit)
        and values_conflict(a.value, b.value)
        and _source(a) != _source(b)
        and qualifiers(a.statement) == qualifiers(b.statement)
        and statements_similar(a.statement, b.statement)
    )


def preference_key(claim: Claim) -> tuple[int, int, float, str]:
    """official > api > industry > news > forum > vendor, then the newest published (undated last),
    then the latest retrieved, then the claim id."""
    published = -claim.published_date.toordinal() if claim.published_date else 0
    return (SOURCE_PREFERENCE.index(claim.source_type), published, -claim.retrieved_at.timestamp(), claim.claim_id)


def detect_conflicts(claims: Iterable[Claim]) -> list[ConflictGroup]:
    """Groups of verified (or already conflict) claims linked by `in_conflict`, each in
    preference order. Claims without a value never conflict. Pairs are compared within a
    dimension, which holds a few dozen claims at most, so no full-text prefilter is needed."""
    pool = [c for c in claims if c.verification in ("verified", "conflict") and c.value is not None]
    parent = {c.claim_id: c.claim_id for c in pool}

    def root(cid: str) -> str:
        while parent[cid] != cid:
            parent[cid] = parent[parent[cid]]
            cid = parent[cid]
        return cid

    for i, a in enumerate(pool):
        for b in pool[i + 1 :]:
            if in_conflict(a, b):
                parent[root(b.claim_id)] = root(a.claim_id)
    groups: dict[str, list[Claim]] = {}
    for c in pool:
        groups.setdefault(root(c.claim_id), []).append(c)
    out = [
        ConflictGroup(dimension=g[0].dimension, claim_ids=[c.claim_id for c in sorted(g, key=preference_key)])
        for g in groups.values()
        if len(g) > 1
    ]
    return sorted(out, key=lambda g: (g.dimension, g.claim_ids[0]))


def mark_conflicts(claims: list[Claim], groups: list[ConflictGroup], changeable: set[str] | None = None) -> list[Claim]:
    """Every grouped claim set to `conflict` (and kept); with `changeable`, only those ids change."""
    ids = {cid for g in groups for cid in g.claim_ids}
    return [
        c.model_copy(update={"verification": "conflict"})
        if c.claim_id in ids and (changeable is None or c.claim_id in changeable)
        else c
        for c in claims
    ]


# ---------------------------------------------------------------- claims


def after_as_of(claim: Claim, as_of: date | None) -> bool:
    """A back-test claim from a source published after the as-of date. An undated source passes:
    the date is unknown, not later (the back-test header asks the agent for dated sources)."""
    return as_of is not None and claim.published_date is not None and claim.published_date > as_of


def reject_after_as_of(claim: Claim, retrieved_at: datetime) -> Claim:
    """The claim `unverified` with `after_as_of`, without fetching its source."""
    flags = [f for f in claim.flags if f not in OWNED_FLAGS]
    return claim.model_copy(
        update={
            "source_type": source_type(claim),
            "retrieved_at": retrieved_at,
            "flags": [*flags, AS_OF_FLAG],
            "verification": "unverified",
        }
    )


def verify_claim(claim: Claim, page: Page) -> Claim:
    """The claim with source_type, retrieved_at, flags and verification set from the page."""
    flags = [f for f in claim.flags if f not in OWNED_FLAGS]
    if page.status == "ok" and page.text is not None and quote_matches(claim.quote, page.text):
        verification = "verified"
    else:
        verification = "unverified"
        if page.status != "ok":
            flags.append(page.status)
    return claim.model_copy(
        update={
            "source_type": source_type(claim),
            "retrieved_at": page.retrieved_at,
            "flags": flags,
            "verification": verification,
        }
    )


@dataclass
class VerifyResult:
    claims: list[Claim]
    # Verified claims per research file stem, including files that yielded no claims. Grouped by
    # file, not by claim.dimension, which an agent may set to something other than its stem.
    by_file: dict[str, list[Claim]]
    warnings: list[str]
    conflicts: list[ConflictGroup] = field(default_factory=list)


_CLAIMS = TypeAdapter(list[Claim])
_CONFLICTS = TypeAdapter(list[ConflictGroup])


def _write_claims(path: Path, claims: list[Claim]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_CLAIMS.dump_json(claims, indent=2) + b"\n")


def parse_run(
    run_dir: Path, retrieved_at: datetime, only: set[str] | None = None
) -> tuple[dict[str, list[Claim]], list[str]]:
    """Candidate claims of every 02_research/*.md (or only the stems in `only`), plus the claim
    extractor's for that file (IF-211), written to 03_claims/<stem>.json (pending)."""
    parsed: dict[str, list[Claim]] = {}
    warnings: list[str] = []

    # Debate mini-research files come after the stage-2 files, so verify_run keeps the first.
    paths = extract.research_files(run_dir)
    if only is not None:
        missing = sorted(only - {p.stem for p in paths})
        if missing:
            raise FileNotFoundError(f"no 02_research/{missing[0]}.md")
        paths = [p for p in paths if p.stem in only]
    for md_path in paths:
        md = md_path.read_text(encoding="utf-8")
        candidates, problems = candidate_claims(md)
        extracted, extract_problems = extract.extracted_claims(run_dir, md_path.stem, md)
        warnings.extend(f"{md_path.name}: {p}" for p in problems)
        warnings.extend(extract_problems)
        claims = [_fill(c, retrieved_at) for c in [*candidates, *extracted]]
        parsed[md_path.stem] = claims
        _write_claims(run_dir / "03_claims" / f"{md_path.stem}.json", claims)
    return parsed, warnings


def _file_claim_ids(run_dir: Path, stems: Iterable[str]) -> set[str]:
    ids: set[str] = set()
    for stem in stems:
        path = run_dir / "03_claims" / f"{stem}.json"
        if path.is_file():
            ids |= {c.claim_id for c in _CLAIMS.validate_json(path.read_bytes())}
    return ids


def _fill(c: CandidateClaim, retrieved_at: datetime) -> Claim:
    data = c.model_dump()
    data["retrieved_at"] = data["retrieved_at"] or retrieved_at
    data["flags"] = [f for f in data["flags"] if f not in OWNED_FLAGS]
    data["verification"] = "pending"
    return Claim.model_validate(data)


def run_as_of(run_id: str) -> date | None:
    """The back-test date of the run's `runs` row (`new_run.py --as-of`), or None."""
    with db.session() as conn:
        row = conn.execute("SELECT as_of FROM runs WHERE run_id=?", (run_id,)).fetchone()
    return date.fromisoformat(row["as_of"]) if row is not None and row["as_of"] else None


def load_conflicts(run_dir: Path) -> list[ConflictGroup]:
    """03_claims/conflicts.json, or no groups when it does not exist (a run verified before IF-210)."""
    path = run_dir / "03_claims" / CONFLICTS_FILE
    return _CONFLICTS.validate_json(path.read_bytes()) if path.is_file() else []


def verify_run(
    run_id: str,
    http_get: HttpGet | None = None,
    *,
    only: Iterable[str] | None = None,
    fi_transport: Transport | None = None,
) -> VerifyResult:
    """Parse, fetch, match and persist one run's claims (files first, then the DB).

    `http_get` defaults to the real `requests_get` and `fi_transport` to each `fi` client's live
    transport; tests pass synthetic pages and the IF-200 recordings. With `only` (file
    stems such as `mini-1-pricing`, a debate's mini-research), just those files are parsed and
    verified and added to the existing verified.json; every other claim in it keeps its state and
    `retrieved_at`, so the evidence under the score sheet does not move during a debate.
    In a back-test run a claim published after the as-of date is rejected before any fetch.
    Conflicts are detected over the whole ledger; with `only`, just the new claims change to
    `conflict` (a kept claim keeps its state), but every group is written to conflicts.json.
    """
    run_dir = runs.run_dir(run_id)
    if not (run_dir / "02_research").is_dir():
        raise FileNotFoundError(f"{run_dir / '02_research'} does not exist")
    ledger = run_dir / "03_claims" / "verified.json"
    kept: list[Claim] = []
    stems = None if only is None else set(only)
    if stems is not None:
        if not ledger.is_file():
            raise FileNotFoundError(f"{ledger} does not exist; verify the whole run first")
        others = {p.stem for p in (run_dir / "03_claims").glob("*.json")} - stems - {"verified", Path(CONFLICTS_FILE).stem}
        # Claims these files contributed last time are replaced; an id another file holds stays.
        replaced = _file_claim_ids(run_dir, stems) - _file_claim_ids(run_dir, others)
        kept = [c for c in _CLAIMS.validate_json(ledger.read_bytes()) if c.claim_id not in replaced]
    parsed, warnings = parse_run(run_dir, _now(), stems)
    as_of = run_as_of(run_id)

    fetcher = Fetcher(http_get or requests_get)
    requerier = Requerier(fi_transport)
    verified: list[Claim] = list(kept)
    by_file: dict[str, list[Claim]] = {stem: [] for stem in parsed}
    seen_ids: set[str] = {c.claim_id for c in kept}
    for stem, claims in parsed.items():
        for c in claims:
            if c.claim_id in seen_ids:
                warnings.append(f"{stem}.md: duplicate claim id {c.claim_id} skipped")
                continue
            seen_ids.add(c.claim_id)
            if after_as_of(c, as_of):
                warnings.append(f"{c.claim_id}: {AS_OF_FLAG} (published {c.published_date}, as of {as_of})")
                verified.append(reject_after_as_of(c, c.retrieved_at))
                by_file[stem].append(verified[-1])
                continue
            if c.source_type == "api" and requery.api_of(c.source_url):
                result = requerier.get(c.source_url)
                if (warning := requery_warning(c, result)) is not None:
                    warnings.append(warning)
                verified.append(verify_api_claim(c, result))
                by_file[stem].append(verified[-1])
                continue
            page = fetcher.get(c.source_url)
            if page.status != "ok":
                warnings.append(f"{c.claim_id}: {page.status} {c.source_url} ({page.detail})")
            verified.append(verify_claim(c, page))
            by_file[stem].append(verified[-1])

    conflicts = detect_conflicts(verified)
    new_ids = {c.claim_id for c in verified[len(kept) :]}
    verified = mark_conflicts(verified, conflicts, None if stems is None else new_ids)
    by_id = {c.claim_id: c for c in verified}
    by_file = {stem: [by_id[c.claim_id] for c in cs] for stem, cs in by_file.items()}

    _write_claims(ledger, verified)
    conflicts_path = run_dir / "03_claims" / CONFLICTS_FILE
    conflicts_path.write_bytes(_CONFLICTS.dump_json(conflicts, indent=2) + b"\n")
    db.upsert_claims(run_id, verified[len(kept):])
    return VerifyResult(verified, by_file, warnings, conflicts)


def summary(result: VerifyResult) -> str:
    """One line per research file (even one without claims): counts and fetch flags."""
    lines = []
    for stem in sorted(result.by_file):
        cs = result.by_file[stem]
        if not cs:
            lines.append(f"{stem}: 0 claims")
            continue
        n = {s: sum(c.verification == s for c in cs) for s in ("verified", "conflict", "unverified")}
        f = {fl: sum(fl in c.flags for c in cs) for fl in OWNED_FLAGS}
        conflict = f", {n['conflict']} conflict" if n["conflict"] else ""
        late = f", {f[AS_OF_FLAG]} after as-of" if f[AS_OF_FLAG] else ""
        api = f", {f[API_FLAG]} api mismatch" if f[API_FLAG] else ""
        lines.append(
            f"{stem}: {n['verified']} verified{conflict}, {n['unverified']} unverified"
            f" ({f['unfetchable']} unfetchable, {f['robots_disallowed']} robots-disallowed{late}{api})"
        )
    total = len(result.claims)
    ok = sum(c.verification == "verified" for c in result.claims)
    lines.append(f"total: {ok}/{total} verified")
    if result.conflicts:
        lines.append(f"conflicts: {len(result.conflicts)} group(s) in 03_claims/{CONFLICTS_FILE}")
    return "\n".join(lines)

