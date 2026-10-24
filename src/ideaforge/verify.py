"""Stage 3 claim verification: fetch each source, cache its text, fuzzy-match the quote.

`verify_run` turns the candidate-claim blocks of runs/<run_id>/02_research/*.md into
03_claims/<dimension>.json, fetches every cited page (robots.txt respected, 10 s timeout, text
cached in cache/<sha256(url)>.txt and recorded in the `sources` table), marks a claim `verified`
only when its quote matches the page text at rapidfuzz partial_ratio ≥ 90, types allow-listed
official domains as `official`, and writes 03_claims/verified.json plus the `claims` rows.
In a back-test run (`new_run.py --as-of`), a claim whose `published_date` is after the as-of date
is `unverified` with the flag `after_as_of`, and its source is not fetched.

The HTTP layer is a plain callable (`HttpGet`) so tests inject synthetic pages and never touch
the network. API re-query and conflict detection (IF-209) build on this module.
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

from ideaforge import agents, config, db, runs
from ideaforge.schemas import CandidateClaim, Claim, SourceType
from ideaforge.validate_file import candidate_claims

USER_AGENT = "ideaforge/0.1 (local business-idea validator; claim quote verification)"
TIMEOUT_S = 10
MATCH_THRESHOLD = 90.0
# Flags this module owns: recomputed on every run, never taken from a research agent.
FETCH_FLAGS = ("unfetchable", "robots_disallowed")
AS_OF_FLAG = "after_as_of"
OWNED_FLAGS = (*FETCH_FLAGS, AS_OF_FLAG)
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


_CLAIMS = TypeAdapter(list[Claim])


def _write_claims(path: Path, claims: list[Claim]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_CLAIMS.dump_json(claims, indent=2) + b"\n")


def parse_run(
    run_dir: Path, retrieved_at: datetime, only: set[str] | None = None
) -> tuple[dict[str, list[Claim]], list[str]]:
    """Candidate claims of every 02_research/*.md (or only the stems in `only`), written to
    03_claims/<stem>.json (pending)."""
    parsed: dict[str, list[Claim]] = {}
    warnings: list[str] = []

    # Debate mini-research files (mini-<n>-<dim>.md) come after the stage-2 files, in task order,
    # so a reused claim id never displaces a stage-2 claim (verify_run keeps the first).
    def order(p: Path) -> tuple[int, str]:
        mini = agents.parse_mini_stem(p.stem)
        return (mini[0], p.name) if mini else (0, p.name)

    paths = sorted((run_dir / "02_research").glob("*.md"), key=order)
    if only is not None:
        missing = sorted(only - {p.stem for p in paths})
        if missing:
            raise FileNotFoundError(f"no 02_research/{missing[0]}.md")
        paths = [p for p in paths if p.stem in only]
    for md_path in paths:
        candidates, problems = candidate_claims(md_path.read_text(encoding="utf-8"))
        warnings.extend(f"{md_path.name}: {p}" for p in problems)
        claims = [_fill(c, retrieved_at) for c in candidates]
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


def verify_run(run_id: str, http_get: HttpGet | None = None, *, only: Iterable[str] | None = None) -> VerifyResult:
    """Parse, fetch, match and persist one run's claims (files first, then the DB).

    `http_get` defaults to the real `requests_get`; tests pass a synthetic one. With `only` (file
    stems such as `mini-1-pricing`, a debate's mini-research), just those files are parsed and
    verified and added to the existing verified.json; every other claim in it keeps its state and
    `retrieved_at`, so the evidence under the score sheet does not move during a debate.
    In a back-test run a claim published after the as-of date is rejected before any fetch.
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
        others = {p.stem for p in (run_dir / "03_claims").glob("*.json")} - stems - {"verified"}
        # Claims these files contributed last time are replaced; an id another file holds stays.
        replaced = _file_claim_ids(run_dir, stems) - _file_claim_ids(run_dir, others)
        kept = [c for c in _CLAIMS.validate_json(ledger.read_bytes()) if c.claim_id not in replaced]
    parsed, warnings = parse_run(run_dir, _now(), stems)
    as_of = run_as_of(run_id)

    fetcher = Fetcher(http_get or requests_get)
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
            page = fetcher.get(c.source_url)
            if page.status != "ok":
                warnings.append(f"{c.claim_id}: {page.status} {c.source_url} ({page.detail})")
            verified.append(verify_claim(c, page))
            by_file[stem].append(verified[-1])

    _write_claims(ledger, verified)
    db.upsert_claims(run_id, verified[len(kept):])
    return VerifyResult(verified, by_file, warnings)


def summary(result: VerifyResult) -> str:
    """One line per research file (even one without claims): counts and fetch flags."""
    lines = []
    for stem in sorted(result.by_file):
        cs = result.by_file[stem]
        if not cs:
            lines.append(f"{stem}: 0 claims")
            continue
        n = {s: sum(c.verification == s for c in cs) for s in ("verified", "unverified")}
        f = {fl: sum(fl in c.flags for c in cs) for fl in OWNED_FLAGS}
        late = f", {f[AS_OF_FLAG]} after as-of" if f[AS_OF_FLAG] else ""
        lines.append(
            f"{stem}: {n['verified']} verified, {n['unverified']} unverified"
            f" ({f['unfetchable']} unfetchable, {f['robots_disallowed']} robots-disallowed{late})"
        )
    total = len(result.claims)
    ok = sum(c.verification == "verified" for c in result.claims)
    lines.append(f"total: {ok}/{total} verified")
    return "\n".join(lines)

