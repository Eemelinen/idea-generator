"""Claim verification (IF-208), API re-query and conflicts (IF-209). No network: every page here is
synthetic, served by FakeWeb, and every API answer is an IF-200 recording (RecordedApis)."""

import hashlib
import json
import shutil
from datetime import UTC, date, datetime

import pytest

import verify_claims
from ideaforge import db, validate_file, verify
from ideaforge.fi import prh, requery
from ideaforge.fi.http import FiDataError
from ideaforge.schemas import BaseLocation, default_base_location
from ideaforge.verify import Fetcher, FetchError, HttpResponse

from conftest import FIXTURES

RUN_ID = "20261023-120000-test-idea"


class FakeWeb:
    """Synthetic HTTP: url → HttpResponse or exception; robots.txt is 404 unless given."""

    def __init__(self, pages: dict):
        self.pages = pages
        self.calls: list[str] = []

    def __call__(self, url: str) -> HttpResponse:
        self.calls.append(url)
        page = self.pages.get(url)
        if page is None:
            return HttpResponse(404, "not found", "text/html")
        if isinstance(page, Exception):
            raise page
        return page


def html(body: str) -> HttpResponse:
    return HttpResponse(200, f"<html><head><title>t</title></head><body><main>{body}</main></body></html>")


# ---------------------------------------------------------------- matching


def substituted(text: str, k: int) -> str:
    """`text` with k characters replaced by '#', spread out so no shifted window scores better."""
    chars = list(text)
    for i in range(k):
        chars[i * 9 + 4] = "#"
    return "".join(chars)


QUOTE100 = "abcdefghij" * 10  # synthetic 100-character quote


@pytest.mark.parametrize(("subs", "score", "matches"), [(10, 90.0, True), (11, 89.0, False)])
def test_threshold_boundary(subs, score, matches):
    page = f"Synthetic page header. {substituted(QUOTE100, subs)} Synthetic footer."
    assert verify.quote_score(QUOTE100, page) == score
    assert verify.quote_matches(QUOTE100, page) is matches


def test_normalization_whitespace_case_diacritics_and_punctuation():
    quote = "Rääkkylän väkiluku on noin 2 000 asukasta – kunta kertoo “virallisesti”."
    page = "RAAKKYLAN   vakiluku on\nnoin 2\u00a0000\tasukasta - kunta kertoo \"virallisesti\"."
    assert verify.normalize(quote) == verify.normalize(page)
    assert verify.quote_score(quote, page) == 100.0


def test_short_page_does_not_contain_a_longer_quote():
    # partial_ratio would align "650" inside the quote and score 100.
    assert verify.quote_score("Hinta 650 € / viikko, sisältää liinavaatteet.", "650") < 90
    assert verify.quote_score("anything", "") == 0.0


# ---------------------------------------------------------------- source typing


@pytest.mark.parametrize(
    ("url", "official"),
    [
        ("https://www.vero.fi/yritykset/", True),
        ("https://vero.fi", True),
        ("https://avoindata.prh.fi/fi/ytj", True),
        ("https://notvero.fi/x", False),
        ("https://vero.fi.example.com/x", False),
        ("https://ec.europa.eu/eurostat/web/main", True),
        ("https://ec.europa.eu/eurostat", True),
        ("https://ec.europa.eu/info/business", False),
        ("https://ec.europa.eu/eurostatistics", False),
        ("https://example.fi/mokki-123", False),
    ],
)
def test_official_domain_matching(url, official):
    assert verify.is_official(url) is official


def _claim(**kw):
    data = json.loads((FIXTURES / "claims.json").read_text(encoding="utf-8"))[0]
    data.update(kw)
    return verify.Claim.model_validate(data)


def test_source_typing():
    assert verify.source_type(_claim(source_url="https://www.vero.fi/a", source_type="news")) == "official"
    assert verify.source_type(_claim(source_url="https://pxdata.stat.fi/PXWeb/api/v1/x", source_type="api")) == "api"
    assert verify.source_type(_claim(source_url="https://example.fi/a", source_type="vendor")) == "vendor"


def test_run_official_domains_add_the_base_location_sites():
    """IF-703: the base's sites and Leader group are official through the run's list only."""
    base = BaseLocation(municipality="Esimerkki", region="Synthetic region",
                        official_domains=["example-kunta.fi"], leader_group={"name": "Synthetic", "domain": "leader.example.fi"})  # fmt: skip
    official = verify.official_domains(base)
    assert official[: len(verify.config.domains().official)] == verify.config.domains().official
    assert official[-2:] == ["example-kunta.fi", "leader.example.fi"]
    assert verify.official_domains() == verify.config.domains().official
    town = _claim(source_url="https://www.example-kunta.fi/palvelut", source_type="news")
    assert verify.source_type(town) == "news"
    assert verify.source_type(town, official) == "official"
    assert verify.is_official("https://leader.example.fi/hanke", official)
    assert not verify.is_official("https://www.raakkyla.fi/", official)


def test_run_base_location_reads_the_spec(active_run):
    assert verify.run_base_location(active_run) is None  # no spec: the global list only
    spec = json.loads((FIXTURES / "spec.json").read_text(encoding="utf-8"))
    (active_run / "00_spec.json").write_text(json.dumps(spec), encoding="utf-8")
    # a spec written before D-009 loads with the schema default, like IdeaSpec
    assert verify.run_base_location(active_run) == default_base_location()
    base = {"municipality": "Esimerkki", "region": "Synthetic region", "official_domains": ["example-kunta.fi"]}
    (active_run / "00_spec.json").write_text(json.dumps(spec | {"base_location": base}), encoding="utf-8")
    assert verify.run_base_location(active_run) == BaseLocation.model_validate(base)


def test_verify_run_types_the_run_base_domains_official(active_run):
    """A claim on the base's own site is typed official in the run based there, and the same
    domain in another run's base (the founder default's raakkyla.fi) is not."""
    db.init()
    db.create_run(RUN_ID, "test idea", idea_id="test-idea")
    spec = json.loads((FIXTURES / "spec.json").read_text(encoding="utf-8"))
    base = {"municipality": "Esimerkki", "region": "Synthetic region", "official_domains": ["example-kunta.fi"]}
    (active_run / "00_spec.json").write_text(json.dumps(spec | {"base_location": base}), encoding="utf-8")
    md = research_md(
        "regulation",
        [{"claim_id": "regulation-001", "statement": "Synthetic zoning claim.", "source_url": "https://www.example-kunta.fi/kaava",
          "quote": "Synthetic zoning rule text.", "source_type": "news"},
         {"claim_id": "regulation-002", "statement": "Synthetic other-town claim.", "source_url": "https://www.raakkyla.fi/kaava",
          "quote": "Synthetic zoning rule text.", "source_type": "news"}],
    )  # fmt: skip
    (active_run / "02_research" / "regulation.md").write_text(md, encoding="utf-8")
    page = html("<p>Synthetic zoning rule text.</p>")
    web = FakeWeb({"https://www.example-kunta.fi/kaava": page, "https://www.raakkyla.fi/kaava": page})
    claims = {c.claim_id: c for c in verify.verify_run(RUN_ID, web).claims}
    assert (claims["regulation-001"].verification, claims["regulation-001"].source_type) == ("verified", "official")
    assert (claims["regulation-002"].verification, claims["regulation-002"].source_type) == ("verified", "news")


# ---------------------------------------------------------------- fetching


def test_cache_hits_skip_the_network(project):
    url = "https://example.fi/page"
    web = FakeWeb({url: html("<p>Synthetic page text about cabins.</p>")})
    f = Fetcher(web, record_sources=False)
    first = f.get(url)
    assert first.status == "ok" and not first.from_cache
    assert f.get(url) is first
    assert web.calls == ["https://example.fi/robots.txt", url]

    cached = verify.cache_path(url)
    assert cached.parent == project / "cache" and cached.stem == hashlib.sha256(url.encode()).hexdigest()
    assert "Synthetic page text" in cached.read_text(encoding="utf-8")

    web2 = FakeWeb({})
    again = Fetcher(web2, record_sources=False).get(url)
    assert again.from_cache and again.text == first.text
    assert web2.calls == []


def test_robots_disallowed_page_is_never_fetched(project):
    url = "https://blocked.example.fi/private/page"
    web = FakeWeb(
        {
            "https://blocked.example.fi/robots.txt": HttpResponse(200, "User-agent: *\nDisallow: /private/\n", "text/plain"),
            url: html("<p>should not be read</p>"),
        }
    )
    f = Fetcher(web, record_sources=False)
    assert f.get(url).status == "robots_disallowed"
    assert url not in web.calls
    assert f.get("https://blocked.example.fi/public").status == "unfetchable"  # allowed, then 404
    assert web.calls.count("https://blocked.example.fi/robots.txt") == 1


@pytest.mark.parametrize(
    ("robots", "allowed"),
    [
        (HttpResponse(403, "forbidden"), False),
        (HttpResponse(401, "auth"), False),
        (HttpResponse(404, "none"), True),
        (HttpResponse(503, "down"), True),
        (FetchError("timeout"), True),
        (HttpResponse(200, "User-agent: ideaforge\nDisallow: /\n", "text/plain"), False),
        (HttpResponse(200, "User-agent: otherbot\nDisallow: /\n", "text/plain"), True),
    ],
)
def test_robots_txt_semantics(project, robots, allowed):
    web = FakeWeb({"https://r.example.fi/robots.txt": robots})
    assert Fetcher(web, record_sources=False).robots_allowed("https://r.example.fi/a") is allowed


@pytest.mark.parametrize(
    "response",
    [
        HttpResponse(403, "<html><body>Forbidden</body></html>"),
        HttpResponse(500, "error"),
        HttpResponse(200, "<html><body><div id='root'></div><noscript>You need to enable JavaScript to run this app.</noscript></body></html>"),
        HttpResponse(200, "<html><body><script>render()</script></body></html>"),
        HttpResponse(200, "%PDF-1.7 binary", "application/pdf"),
        FetchError("ReadTimeout: timed out after 10 s"),
        ValueError("synthetic unexpected error"),
    ],
)
def test_unfetchable_pages(project, response):
    url = "https://u.example.fi/page"
    page = Fetcher(FakeWeb({url: response}), record_sources=False).get(url)
    assert page.status == "unfetchable" and page.text is None
    assert not verify.cache_path(url).exists()


@pytest.mark.parametrize("ctype", ["application/json; charset=utf-8", "application/ld+json", "text/csv", "text/markdown"])
def test_text_responses_are_used_as_is(project, ctype):
    url = "https://pxdata.stat.fi/PXWeb/api/v1/fi/synthetic.px"
    page = Fetcher(FakeWeb({url: HttpResponse(200, '{"value": [1975]}', ctype)}), record_sources=False).get(url)
    assert page.status == "ok" and page.text == '{"value": [1975]}'


def test_quote_outside_the_main_content_still_matches(project):
    url = "https://example.fi/sidebar"
    body = (
        "<article><h1>Synthetic article</h1>" + "<p>Long synthetic main text about lakeside cabins.</p>" * 20
        + "</article><aside><p>Synthetic info box: kunnan asukasluku on 1 975.</p></aside>"
    )
    page = Fetcher(FakeWeb({url: html(body)}), record_sources=False).get(url)
    assert verify.quote_matches("kunnan asukasluku on 1 975", page.text)
    assert not list(verify.cache_path(url).parent.glob("*.tmp"))


XHTML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">\n'
    '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>t</title></head>'
    "<body><p>Synthetic XHTML page. Arvonlisäverovelvollisuuden alaraja on 20 000 euroa tilikaudessa.</p></body></html>"
)


@pytest.mark.parametrize("ctype", ["text/html; charset=utf-8", "application/xhtml+xml"])
def test_xhtml_with_an_encoding_declaration_is_parsed(project, ctype):
    # lxml rejects a str that declares its encoding; the declaration must not make the page unfetchable.
    url = "https://www.vero.fi/synthetic-xhtml"
    page = Fetcher(FakeWeb({url: HttpResponse(200, "﻿" + XHTML, ctype)}), record_sources=False).get(url)
    assert page.status == "ok"
    assert verify.quote_matches("Arvonlisäverovelvollisuuden alaraja on 20 000 euroa tilikaudessa.", page.text)
    assert "<?xml" not in page.text


def test_trafilatura_extract_is_the_fallback_when_lxml_fails(project, monkeypatch):
    def unparsable(html):
        raise ValueError("synthetic lxml failure")

    monkeypatch.setattr(verify, "page_text", unparsable)
    paragraph = "<p>Synthetic fallback paragraph about lakeside cabins and their weekly rental prices in summer.</p>"
    text = verify.extract_text(html(paragraph * 5))
    assert text and "Synthetic fallback paragraph" in text


def test_failed_cache_write_leaves_no_temp_file(project, monkeypatch):
    url = "https://example.fi/disk-full"

    def no_rename(src, dst):
        raise OSError("synthetic rename failure")

    monkeypatch.setattr(verify.os, "replace", no_rename)
    with pytest.raises(OSError):
        Fetcher(FakeWeb({url: html("<p>Synthetic page text.</p>")}), record_sources=False).get(url)
    cached = verify.cache_path(url)
    assert not cached.exists() and not list(cached.parent.glob("*.tmp"))


def test_summary_groups_by_research_file_not_claim_dimension():
    # A file whose claims name another dimension is reported under its own stem, once.
    claim = _claim(claim_id="pricing-001", dimension="pricing", verification="verified")
    result = verify.VerifyResult([claim], {"market": [claim], "gtm": []}, [])
    assert verify.summary(result).splitlines() == [
        "gtm: 0 claims",
        "market: 1 verified, 0 unverified (0 unfetchable, 0 robots-disallowed)",
        "total: 1/1 verified",
    ]


def test_requests_get_sends_ua_and_timeout(monkeypatch):
    seen = {}

    class Resp:
        status_code, text, headers, encoding, apparent_encoding = 200, "ok", {"Content-Type": "text/html; charset=utf-8"}, "utf-8", "utf-8"

    def fake_get(url, headers, timeout):
        seen.update(url=url, headers=headers, timeout=timeout)
        return Resp()

    monkeypatch.setattr(verify, "_ssl_ready", True)
    monkeypatch.setattr(verify.requests, "get", fake_get)
    assert verify.requests_get("https://example.fi/") == HttpResponse(200, "ok", "text/html; charset=utf-8")
    assert seen["timeout"] == 10 and seen["headers"]["User-Agent"] == verify.USER_AGENT

    def boom(url, headers, timeout):
        raise verify.requests.ConnectTimeout("synthetic timeout")

    monkeypatch.setattr(verify.requests, "get", boom)
    with pytest.raises(FetchError):
        verify.requests_get("https://example.fi/")


# ---------------------------------------------------------------- whole run

# Synthetic research file: one claim per outcome. URLs are example/test hosts, except the
# vero.fi URL, whose page is served by FakeWeb, never fetched for real.
REGULATION_MD = """# regulation

Synthetic research file for tests.

## Findings

Synthetic findings.

## Candidate claims

```json
[
  {"claim_id": "regulation-001", "dimension": "regulation", "statement": "Synthetic VAT threshold claim.",
   "value": 20000, "unit": "EUR", "source_url": "https://www.vero.fi/synthetic-alv",
   "source_title": "Synthetic", "quote": "Arvonlisäverovelvollisuuden alaraja on 20 000 euroa tilikaudessa.",
   "source_type": "news", "confidence": 0.9, "flags": []},
  {"claim_id": "regulation-002", "dimension": "regulation", "statement": "Synthetic misquoted claim.",
   "source_url": "https://www.vero.fi/synthetic-alv", "source_title": "Synthetic",
   "quote": "Elinkeinotoiminnan verotus on kokonaan poistettu pienyrittäjiltä.",
   "source_type": "official", "confidence": 0.5, "flags": ["unfetchable"]},
  {"claim_id": "regulation-003", "dimension": "regulation", "statement": "Synthetic robots claim.",
   "source_url": "https://blocked.example.fi/private/x", "source_title": "Synthetic",
   "quote": "Some quote.", "source_type": "industry", "confidence": 0.5, "flags": ["permit_impossible"]},
  {"claim_id": "regulation-004", "dimension": "regulation", "statement": "Synthetic 403 claim.",
   "source_url": "https://forbidden.example.fi/x", "source_title": "Synthetic",
   "quote": "Some other quote.", "source_type": "news", "confidence": 0.5, "flags": []}
]
```

## Gaps

- None.
"""

BROKEN_MD = """# gtm

## Candidate claims

```json
[{"claim_id": "gtm-001"
```

## Gaps
"""


def synthetic_web():
    return FakeWeb(
        {
            "https://example.fi/mokki-123": html(
                "<h1>Mökki 123</h1><p>Hinta 650 € / viikko, sisältää liinavaatteet ja loppusiivouksen.</p>"
            ),
            "https://www.vero.fi/synthetic-alv": html(
                "<p>Synthetic page. Arvonlisäverovelvollisuuden alaraja on 20 000 euroa tilikaudessa.</p>"
            ),
            "https://blocked.example.fi/robots.txt": HttpResponse(200, "User-agent: *\nDisallow: /private/\n", "text/plain"),
            "https://forbidden.example.fi/x": HttpResponse(403, "Forbidden"),
        }
    )


@pytest.fixture
def run(active_run):
    db.init()
    db.create_run(RUN_ID, "test idea", idea_id="test-idea")
    research = active_run / "02_research"
    shutil.copy(FIXTURES / "02_research" / "pricing.md", research / "pricing.md")
    (research / "regulation.md").write_text(REGULATION_MD, encoding="utf-8")
    (research / "gtm.md").write_text(BROKEN_MD, encoding="utf-8")
    return active_run


def test_verify_run_end_to_end(run):
    web = synthetic_web()
    result = verify.verify_run(RUN_ID, web)

    # 03_claims/<dim>.json: parsed, pending, retrieved_at filled, agent-set fetch flags dropped.
    pricing = json.loads((run / "03_claims" / "pricing.json").read_text(encoding="utf-8"))
    assert [c["verification"] for c in pricing] == ["pending"]
    assert pricing[0]["retrieved_at"]
    regulation = json.loads((run / "03_claims" / "regulation.json").read_text(encoding="utf-8"))
    assert regulation[1]["flags"] == []
    assert json.loads((run / "03_claims" / "gtm.json").read_text(encoding="utf-8")) == []
    assert any("gtm.md" in w and "does not parse" in w for w in result.warnings)

    claims = {c["claim_id"]: c for c in json.loads((run / "03_claims" / "verified.json").read_text(encoding="utf-8"))}
    assert set(claims) == {"pricing-001", "regulation-001", "regulation-002", "regulation-003", "regulation-004"}
    assert claims["pricing-001"]["verification"] == "verified"
    assert claims["pricing-001"]["source_type"] == "vendor"
    assert claims["regulation-001"]["verification"] == "verified"
    assert claims["regulation-001"]["source_type"] == "official"
    assert (claims["regulation-002"]["verification"], claims["regulation-002"]["flags"]) == ("unverified", [])
    assert claims["regulation-003"]["verification"] == "unverified"
    assert claims["regulation-003"]["flags"] == ["permit_impossible", "robots_disallowed"]
    assert (claims["regulation-004"]["verification"], claims["regulation-004"]["flags"]) == ("unverified", ["unfetchable"])

    # One fetch per URL, robots.txt once per host.
    assert web.calls.count("https://www.vero.fi/synthetic-alv") == 1
    assert "https://blocked.example.fi/private/x" not in web.calls

    with db.session() as conn:
        rows = {r["claim_id"]: r for r in conn.execute("SELECT * FROM claims WHERE run_id=?", (RUN_ID,))}
        sources = {r["url"]: r for r in conn.execute("SELECT * FROM sources")}
    assert rows["regulation-001"]["verification"] == "verified"
    assert json.loads(rows["regulation-003"]["flags"]) == ["permit_impossible", "robots_disallowed"]
    ok = sources["https://www.vero.fi/synthetic-alv"]
    assert (ok["domain"], ok["http_status"]) == ("www.vero.fi", 200)
    assert ok["cache_path"] == verify.cache_path("https://www.vero.fi/synthetic-alv").relative_to(run.parents[1]).as_posix()
    bad = sources["https://forbidden.example.fi/x"]
    assert (bad["http_status"], bad["cache_path"], bad["content_sha"]) == (403, None, None)

    summary = verify.summary(result)
    assert "gtm: 0 claims" in summary
    assert "regulation: 1 verified, 3 unverified (1 unfetchable, 1 robots-disallowed)" in summary
    assert summary.endswith("total: 2/5 verified")


def test_rerun_uses_the_cache_and_retries_failures(run):
    verify.verify_run(RUN_ID, synthetic_web())
    web = synthetic_web()
    verify.verify_run(RUN_ID, web)
    assert "https://example.fi/mokki-123" not in web.calls
    assert "https://www.vero.fi/synthetic-alv" not in web.calls
    assert "https://forbidden.example.fi/x" in web.calls
    claims = {c["claim_id"]: c for c in json.loads((run / "03_claims" / "verified.json").read_text(encoding="utf-8"))}
    assert claims["pricing-001"]["verification"] == claims["regulation-001"]["verification"] == "verified"
    with db.session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM claims WHERE run_id=?", (RUN_ID,)).fetchone()[0] == 5


def test_script_main(run, monkeypatch, capsys):
    monkeypatch.setattr(verify, "requests_get", synthetic_web())
    assert verify_claims.main([RUN_ID]) == 0
    out, err = capsys.readouterr()
    assert "total: 2/5 verified" in out
    assert "warning: regulation-004: unfetchable https://forbidden.example.fi/x (HTTP 403)" in err
    assert (run / "03_claims" / "verified.json").is_file()


def test_script_rejects_unknown_runs(project, capsys):
    assert verify_claims.main(["not a run id"]) == 1
    assert verify_claims.main(["20261023-120000-missing"]) == 1
    assert "does not exist" in capsys.readouterr().err


# ---------------------------------------------------------------- back-test (IF-503)

# Synthetic back-test research file: one claim published before the as-of date, one after it,
# one undated; all three quotes are on their (synthetic) pages.
AS_OF_MD = """# pricing

## Candidate claims

```json
[
  {"claim_id": "pricing-001", "dimension": "pricing", "statement": "Synthetic early price.",
   "value": 650, "unit": "EUR/week", "source_url": "https://example.fi/mokki-123", "source_title": "Synthetic",
   "quote": "Hinta 650 € / viikko, sisältää liinavaatteet ja loppusiivouksen.", "published_date": "2024-06-01",
   "source_type": "vendor", "confidence": 0.8, "flags": []},
  {"claim_id": "pricing-002", "dimension": "pricing", "statement": "Synthetic later price.",
   "value": 650, "unit": "EUR/week", "source_url": "https://example.fi/mokki-456", "source_title": "Synthetic",
   "quote": "Hinta 650 € / viikko, sisältää liinavaatteet ja loppusiivouksen.", "published_date": "2024-07-01",
   "source_type": "vendor", "confidence": 0.8, "flags": ["after_as_of"]},
  {"claim_id": "pricing-003", "dimension": "pricing", "statement": "Synthetic undated price.",
   "value": 650, "unit": "EUR/week", "source_url": "https://example.fi/mokki-789", "source_title": "Synthetic",
   "quote": "Hinta 650 € / viikko, sisältää liinavaatteet ja loppusiivouksen.",
   "source_type": "vendor", "confidence": 0.8, "flags": ["after_as_of"]}
]
```

## Gaps

- None.
"""


def as_of_web():
    page = html("<p>Hinta 650 € / viikko, sisältää liinavaatteet ja loppusiivouksen.</p>")
    return FakeWeb({f"https://example.fi/mokki-{n}": page for n in (123, 456, 789)})


@pytest.fixture
def as_of_run(active_run):
    db.init()
    db.create_run(RUN_ID, "test idea", idea_id="test-idea", as_of="2024-06-30")
    (active_run / "02_research" / "pricing.md").write_text(AS_OF_MD, encoding="utf-8")
    return active_run


def test_claim_after_the_as_of_date_is_unverified(as_of_run):
    web = as_of_web()
    result = verify.verify_run(RUN_ID, web)
    claims = {c["claim_id"]: c for c in json.loads((as_of_run / "03_claims" / "verified.json").read_text(encoding="utf-8"))}
    assert (claims["pricing-001"]["verification"], claims["pricing-001"]["flags"]) == ("verified", [])
    # The quote is on its page, but the page is later than the back-test: rejected, never fetched.
    assert (claims["pricing-002"]["verification"], claims["pricing-002"]["flags"]) == ("unverified", ["after_as_of"])
    assert claims["pricing-002"]["retrieved_at"] and claims["pricing-002"]["source_type"] == "vendor"
    assert "https://example.fi/mokki-456" not in web.calls
    # Undated: not known to be later, so verified, and an agent-set after_as_of flag is dropped.
    assert (claims["pricing-003"]["verification"], claims["pricing-003"]["flags"]) == ("verified", [])
    assert "pricing-002: after_as_of (published 2024-07-01, as of 2024-06-30)" in result.warnings
    assert "pricing: 2 verified, 1 unverified (0 unfetchable, 0 robots-disallowed, 1 after as-of)" in verify.summary(result)
    with db.session() as conn:
        row = conn.execute("SELECT verification, flags FROM claims WHERE claim_id='pricing-002'").fetchone()
    assert (row["verification"], json.loads(row["flags"])) == ("unverified", ["after_as_of"])


def test_claim_on_the_as_of_date_passes():
    claim = verify.Claim.model_validate(
        json.loads(AS_OF_MD.split("```json")[1].split("```")[0])[0] | {"retrieved_at": "2026-10-23T12:00:00+00:00"}
    )
    assert claim.published_date == date(2024, 6, 1)
    assert not verify.after_as_of(claim, date(2024, 6, 1))
    assert verify.after_as_of(claim, date(2024, 5, 31))
    assert not verify.after_as_of(claim, None)


def test_without_as_of_a_later_claim_verifies(active_run):
    db.init()
    db.create_run(RUN_ID, "test idea", idea_id="test-idea")
    (active_run / "02_research" / "pricing.md").write_text(AS_OF_MD, encoding="utf-8")
    result = verify.verify_run(RUN_ID, as_of_web())
    assert all(c.verification == "verified" and c.flags == [] for c in result.claims)


def test_script_main_back_test(as_of_run, monkeypatch, capsys):
    monkeypatch.setattr(verify, "requests_get", as_of_web())
    assert verify_claims.main([RUN_ID]) == 0
    out, err = capsys.readouterr()
    assert "1 after as-of" in out and "total: 2/3 verified" in out
    assert "warning: pricing-002: after_as_of" in err


# ---------------------------------------------------------------- API re-query (IF-209)

PXWEB_11RA_CITE = (
    "https://pxdata.stat.fi/PXWeb/api/v1/fi/StatFin/vaerak/11ra.px"
    "?alue_23_20260101=KU707,MK12&contentscode=vaerak-vaesto&timeperiod_y=2021,2022,2023,2024,2025"
)
LUKE_CITE = (
    "https://statdb.luke.fi/PXWeb/api/v1/fi/LUKE/maa/muuyri/0100_muuyri.px"
    "?INFO=TILA_KPL&A=2020,2023&ELY=SSS,ELY09&RAJ=SUUR_TOIM,KAIK_YRI&TOL=TOL_YHT,MATK"
)
PRH_55 = "https://avoindata.prh.fi/opendata-ytj-api/v3/companies?mainBusinessLine=55&location=R%C3%A4%C3%A4kkyl%C3%A4"
PRH_NAME = "https://avoindata.prh.fi/opendata-ytj-api/v3/companies?name=R%C3%A4%C3%A4kkyl%C3%A4n"
EUROSTAT_NIGHTS = (
    "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/tour_occ_ninat"
    "?geo=FI&unit=NR&c_resid=TOTAL&nace_r2=I551-I553&sinceTimePeriod=2019&lang=EN"
)
EUROSTAT_DOWN = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/tour_occ_ninat?geo=SE&lang=EN"


def _api_key(method, url, body):
    return json.dumps([method, url, body], ensure_ascii=False, sort_keys=True)


class RecordedApis:
    """Replays every IF-200 recording (tests/fixtures/api); a request that was not recorded fails
    the test, except the URLs in `down`, which fail like an HTTP error of the live API."""

    def __init__(self, down=()):
        self.down = set(down)
        self.calls: list[tuple[str, str]] = []
        self.responses = {}
        for meta_path in (FIXTURES / "api").glob("*/*.meta.json"):
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            data_path = meta_path.with_name(meta_path.name.removesuffix(".meta.json") + ".json")
            self.responses[_api_key(meta["method"], meta["url"], meta["request"])] = json.loads(
                data_path.read_text(encoding="utf-8")
            )

    def __call__(self, method, url, body):
        self.calls.append((method, url))
        if url in self.down:
            raise FiDataError(f"{method} {url} → HTTP 503: synthetic outage")
        key = _api_key(method, url, body)
        if key not in self.responses:
            raise AssertionError(f"not recorded: {method} {url} {json.dumps(body, ensure_ascii=False)}")
        return self.responses[key]


def research_md(dimension: str, claims: list[dict]) -> str:
    """A minimal synthetic research file whose claims default to source_type api."""
    full = [
        {"source_title": "Synthetic", "source_type": "api", "confidence": 0.9, "flags": []}
        | {"dimension": dimension}
        | c
        for c in claims
    ]
    return f"# {dimension}\n\n## Candidate claims\n\n```json\n{json.dumps(full, ensure_ascii=False, indent=1)}\n```\n\n## Gaps\n\n- None.\n"


# Synthetic research claims on the recorded API answers: the values are the recorded ones
# (11ra Rääkkylä 2025: 1830; PRH industry 55 in Rääkkylä: 1 company, name search: 54; Eurostat
# 2025: 23293003; Luke North Karelia diversified tourism farms 2020: 652) or deliberately wrong.
API_CLAIMS = {
    "location": [
        {"claim_id": "location-001", "statement": "Rääkkylä had 1830 residents at the end of 2025.",
         "value": 1830, "unit": "persons", "source_url": PXWEB_11RA_CITE,
         "quote": "Rääkkylä,KU707,Väestö 31.12.,vaerak-vaesto,2025,2025,1830"},
        {"claim_id": "location-002", "statement": "Rääkkylä had 1950 residents in 2025.",
         "value": 1950, "unit": "persons", "source_url": PXWEB_11RA_CITE,
         "quote": "Rääkkylä,KU707,Väestö 31.12.,vaerak-vaesto,2025,2025,1950"},
        {"claim_id": "location-003", "statement": "North Karelia's population is in StatFin table 11ra.",
         "source_url": PXWEB_11RA_CITE, "quote": "MK12 Pohjois-Karjala,MK12,Väestö 31.12.,vaerak-vaesto,2025,2025,161418"},
        {"claim_id": "location-004", "statement": "North Karelia had 652 diversified farms in tourism in 2020.",
         "value": 652, "unit": "farms", "source_url": LUKE_CITE, "quote": "652"},
        {"claim_id": "location-005", "statement": "A StatFin folder.", "value": 3, "unit": "tables",
         "source_url": "https://pxdata.stat.fi/PXWeb/api/v1/fi/StatFin/vaerak/", "quote": "11ra.px"},
    ],
    "competition": [
        {"claim_id": "competition-001", "statement": "One accommodation company is registered in Rääkkylä.",
         "value": 1, "unit": "companies", "source_url": PRH_55, "quote": "count: 1"},
        {"claim_id": "competition-002", "statement": "55 companies have Rääkkylän in their name.",
         "value": 55, "unit": "companies", "source_url": PRH_NAME, "quote": "count: 55"},
        {"claim_id": "competition-003", "statement": "A PRH call the client never makes.",
         "value": 1, "unit": "companies", "source_url": PRH_55 + "&foo=bar", "quote": "count: 1"},
        {"claim_id": "competition-004", "statement": "Another API, not one of the fi tools.",
         "value": 7, "unit": "cabins", "source_url": "https://api.example.fi/cabins", "quote": "\"cabins\": 7"},
    ],
    "market": [
        {"claim_id": "market-001", "statement": "Finland had 23293003 nights in tourist accommodation in 2025.",
         "value": 23293003, "unit": "nights", "source_url": EUROSTAT_NIGHTS, "quote": "23293003"},
        {"claim_id": "market-002", "statement": "Sweden's nights in tourist accommodation.",
         "value": 1000, "unit": "nights", "source_url": EUROSTAT_DOWN, "quote": "1000"},
    ],
}  # fmt: skip


@pytest.fixture
def api_run(active_run):
    db.init()
    db.create_run(RUN_ID, "test idea", idea_id="test-idea")
    for dim, claims in API_CLAIMS.items():
        (active_run / "02_research" / f"{dim}.md").write_text(research_md(dim, claims), encoding="utf-8")
    return active_run


def api_web():
    return FakeWeb({"https://api.example.fi/cabins": HttpResponse(200, '{"cabins": 7}', "application/json")})


def test_api_claims_are_requeried_through_the_fi_clients(api_run):
    apis = RecordedApis(down={EUROSTAT_DOWN})
    web = api_web()
    result = verify.verify_run(RUN_ID, web, fi_transport=apis)
    claims = {c.claim_id: c for c in result.claims}

    def state(cid):
        return claims[cid].verification, claims[cid].flags

    assert state("location-001") == ("verified", [])  # count, exact
    assert state("location-002") == ("unverified", ["api_mismatch"])  # 1950 is not in the answer
    assert state("location-003") == ("verified", [])  # no value: the quote is in the answer's CSV
    assert state("location-004") == ("verified", [])  # Luke, same client
    assert state("location-005") == ("unverified", ["api_mismatch"])  # a folder, not a table query
    assert state("competition-001") == ("verified", [])
    assert state("competition-002") == ("unverified", ["api_mismatch"])  # the recorded count is 54
    assert state("competition-003") == ("unverified", ["api_mismatch"])  # not a PRH client call
    assert state("competition-004") == ("verified", [])  # other API: fetched and quote-matched
    assert state("market-001") == ("verified", [])
    assert state("market-002") == ("unverified", ["unfetchable"])
    assert all(claims[c].source_type == "api" for c in claims)

    # Each cited URL is re-run once: 11ra's metadata and query once for three claims; nothing is
    # requested for a URL that is not a client call; no fi URL goes through the page fetcher.
    assert apis.calls.count(("POST", "https://pxdata.stat.fi/PXWeb/api/v1/fi/StatFin/vaerak/11ra.px")) == 1
    assert apis.calls.count(("GET", "https://pxdata.stat.fi/PXWeb/api/v1/fi/StatFin/vaerak/11ra.px")) == 1
    assert not any("foo=bar" in url or url.endswith("/vaerak/") for _, url in apis.calls)
    assert web.calls == ["https://api.example.fi/robots.txt", "https://api.example.fi/cabins"]

    assert "location-002: api_mismatch " + PXWEB_11RA_CITE + " (value 1950 not in the re-queried answer)" in result.warnings
    assert any(w.startswith("competition-003: api_mismatch ") and "never sends 'foo'" in w for w in result.warnings)
    assert any(w.startswith("market-002: unfetchable ") and "HTTP 503" in w for w in result.warnings)
    summary = verify.summary(result)
    assert "competition: 2 verified, 2 unverified (0 unfetchable, 0 robots-disallowed, 2 api mismatch)" in summary
    assert "market: 1 verified, 1 unverified (1 unfetchable, 0 robots-disallowed)" in summary

    with db.session() as conn:
        sources = {r["url"]: r for r in conn.execute("SELECT * FROM sources")}
        row = conn.execute("SELECT verification, flags FROM claims WHERE claim_id='location-002'").fetchone()
    assert (row["verification"], json.loads(row["flags"])) == ("unverified", ["api_mismatch"])
    assert sources[PRH_55]["http_status"] == 200 and sources[PRH_55]["content_sha"]
    assert (sources[EUROSTAT_DOWN]["http_status"], sources[EUROSTAT_DOWN]["content_sha"]) == (None, None)


def test_api_rerun_uses_the_client_cache(api_run):
    verify.verify_run(RUN_ID, api_web(), fi_transport=RecordedApis(down={EUROSTAT_DOWN}))
    apis = RecordedApis(down={EUROSTAT_DOWN})
    result = verify.verify_run(RUN_ID, api_web(), fi_transport=apis)
    assert [url for _, url in apis.calls] == [EUROSTAT_DOWN]  # only the failed one is asked again
    assert {c.claim_id for c in result.claims if c.verification == "verified"} >= {"location-001", "market-001"}


@pytest.mark.parametrize(
    ("claimed", "actual", "matches"),
    [
        (1830, 1830, True),
        (1830.0, 1830, True),
        (1831, 1830, False),  # an integer is a count: exact
        (1829.9, 1830, False),
        (101.0, 100.0, True),  # a float: within ±1 %
        (99.0, 100.0, True),
        (101.01, 100.0, False),
        (98.98, 100.0, False),
        (0.0, 0.0, True),
    ],
)
def test_api_value_tolerance(claimed, actual, matches):
    assert verify.value_matches(claimed, actual) is matches


def test_a_mismatched_float_is_unverified():
    # Synthetic answer with float cells (an average, a share), as a statistics table returns them.
    answer = requery.Answer("eurostat", [12.5, 3.2], "value\n12.5\n3.2\n", None)
    ok = verify.ApiResult("https://example.invalid/", "ok", datetime(2026, 10, 24, tzinfo=UTC), answer)
    near = _claim(source_type="api", value=12.6)
    far = _claim(source_type="api", value=12.7)
    assert verify.verify_api_claim(near, ok).verification == "verified"
    assert (verify.verify_api_claim(far, ok).verification, verify.verify_api_claim(far, ok).flags) == (
        "unverified",
        ["api_mismatch"],
    )


@pytest.mark.parametrize(
    ("url", "call"),
    [
        (
            PXWEB_11RA_CITE,
            requery.PxWebCall(
                "statfin/vaerak/11ra.px",
                {"alue_23_20260101": ["KU707", "MK12"], "contentscode": ["vaerak-vaesto"],
                 "timeperiod_y": ["2021", "2022", "2023", "2024", "2025"]},
                "fi",
            ),
        ),
        ("https://statdb.luke.fi/PXWeb/api/v1/en/LUKE/maa/muuyri/0100_muuyri.px",
         requery.PxWebCall("luke/maa/muuyri/0100_muuyri.px", {}, "en")),
        (PRH_55, requery.PrhCall(prh.Criteria(industry="55", municipality="Rääkkylä"))),
        (PRH_NAME + "&page=2", requery.PrhCall(prh.Criteria(name="Rääkkylän", page=2))),
        (
            EUROSTAT_NIGHTS,
            requery.EurostatCall(
                "tour_occ_ninat",
                {"geo": ["FI"], "unit": ["NR"], "c_resid": ["TOTAL"], "nace_r2": ["I551-I553"]},
                "EN", "2019", None,
            ),
        ),
    ],
)  # fmt: skip
def test_requery_parses_cited_urls_back_into_client_calls(url, call):
    assert requery.parse(url) == call


@pytest.mark.parametrize(
    "url",
    [
        "https://pxdata.stat.fi/PXWeb/api/v1/fi/StatFin/vaerak/",
        "https://pxdata.stat.fi/PXWeb/api/v1/fi/StatFin/vaerak/11ra.px?alue_23_20260101=",
        PRH_55 + "&foo=bar",
        PRH_55 + "&mainBusinessLine=56",
        PRH_NAME + "&page=two",
        "https://avoindata.prh.fi/opendata-ytj-api/v3/companies?mainBusinessLine=I55",
        "https://avoindata.prh.fi/opendata-ytj-api/v3/companies?page=2",
        EUROSTAT_NIGHTS.replace("lang=EN", "lang=FI"),
        "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/tour%20occ?geo=FI",
        "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/",
        "https://example.fi/api?x=1",
    ],
)
def test_requery_refuses_urls_that_are_not_client_calls(url):
    with pytest.raises(requery.NotAQuery):
        requery.parse(url)


def test_api_of_names_only_the_fi_apis():
    assert requery.api_of(PXWEB_11RA_CITE) == "pxweb"
    assert requery.api_of(LUKE_CITE) == "pxweb"
    assert requery.api_of(PRH_55) == "prh"
    assert requery.api_of(EUROSTAT_NIGHTS) == "eurostat"
    assert requery.api_of("https://www.stat.fi/til/vaerak/") is None
    assert requery.api_of("https://ec.europa.eu/eurostat/web/main") is None


# ---------------------------------------------------------------- conflicts (IF-210)

T_RETRIEVED = "2026-10-23T12:00:00+00:00"


def conflict_claim(cid, value, statement="Rääkkylä has {v} summer cottages.", **kw):
    data = {
        "claim_id": cid,
        "dimension": cid.split("-")[0],
        "statement": statement.format(v=value),
        "value": value,
        "unit": "cottages",
        "source_url": f"https://example.fi/{cid}",
        "source_title": "Synthetic",
        "quote": "Synthetic quote.",
        "retrieved_at": T_RETRIEVED,
        "source_type": "news",
        "confidence": 0.8,
        "verification": "verified",
    }
    return verify.Claim.model_validate(data | kw)


@pytest.mark.parametrize(("other", "conflict"), [(124, False), (126, True), (76, True), (80, False)])
def test_conflict_needs_more_than_25_percent_difference(other, conflict):
    claims = [conflict_claim("market-001", 100), conflict_claim("market-002", other)]
    groups = verify.detect_conflicts(claims)
    assert bool(groups) is conflict
    marked = verify.mark_conflicts(claims, groups)
    assert {c.verification for c in marked} == ({"conflict"} if conflict else {"verified"})


def test_non_numeric_claims_are_ignored():
    claims = [
        conflict_claim("market-001", 100),
        conflict_claim("market-002", None, statement="Rääkkylä has many summer cottages."),
        conflict_claim("market-003", None, statement="Rääkkylä has few summer cottages."),
    ]
    assert verify.detect_conflicts(claims) == []


@pytest.mark.parametrize(
    "other",
    [
        conflict_claim("location-001", 200),  # another dimension
        conflict_claim("market-002", 200, statement="The sauna rental costs {v} euros per evening."),  # dissimilar
        conflict_claim("market-002", 200, unit="EUR"),  # another unit
        conflict_claim("market-002", 200, verification="unverified"),  # never verified
    ],
)
def test_no_conflict_across_dimensions_statements_units_or_unverified(other):
    assert verify.detect_conflicts([conflict_claim("market-001", 100), other]) == []


def test_a_missing_unit_still_conflicts():
    claims = [conflict_claim("market-001", 100), conflict_claim("market-002", 200, unit=None)]
    assert len(verify.detect_conflicts(claims)) == 1


def test_conflict_groups_are_in_preference_order():
    claims = [
        conflict_claim("market-001", 100, source_type="vendor"),
        conflict_claim("market-002", 200, source_type="news", published_date="2024-01-01"),
        conflict_claim("market-003", 300, source_type="news", published_date="2025-01-01"),
        conflict_claim("market-004", 400, source_type="official"),
        conflict_claim("market-005", 500, source_type="api"),
        conflict_claim("market-006", 600, source_type="forum"),
        conflict_claim("market-007", 700, source_type="industry"),
    ]
    groups = verify.detect_conflicts(claims)
    assert groups == [
        verify.ConflictGroup(
            dimension="market",
            claim_ids=["market-004", "market-005", "market-007", "market-003", "market-002", "market-006", "market-001"],
        )
    ]


def test_linked_conflicts_form_one_group_and_others_stay_verified():
    claims = [
        conflict_claim("market-001", 100),
        conflict_claim("market-002", 130),  # vs 001: 30 %
        conflict_claim("market-003", 160),  # vs 002: 23 %, vs 001: 60 %
        conflict_claim("market-004", 101, statement="North Karelia has {v} sauna rafts."),
    ]
    groups = verify.detect_conflicts(claims)
    # same type, undated, retrieved together: the claim id breaks the tie
    assert [g.claim_ids for g in groups] == [["market-001", "market-002", "market-003"]]
    states = {c.claim_id: c.verification for c in verify.mark_conflicts(claims, groups)}
    assert states == {"market-001": "conflict", "market-002": "conflict", "market-003": "conflict", "market-004": "verified"}


CONFLICT_MD = research_md(
    "market",
    [
        {"claim_id": "market-001", "statement": "Rääkkylä has 100 summer cottages.", "value": 100, "unit": "cottages",
         "source_url": "https://example.fi/cottages-a", "quote": "Rääkkylässä on 100 kesämökkiä.", "source_type": "news"},
        {"claim_id": "market-002", "statement": "Rääkkylä has 126 summer cottages.", "value": 126, "unit": "cottages",
         "source_url": "https://www.vero.fi/synthetic-cottages", "quote": "Rääkkylässä on 126 kesämökkiä.",
         "source_type": "news"},
        {"claim_id": "market-003", "statement": "Rääkkylä has 124 summer saunas.", "value": 124, "unit": "saunas",
         "source_url": "https://example.fi/cottages-a", "quote": "Rääkkylässä on 100 kesämökkiä.", "source_type": "news"},
    ],
)  # fmt: skip


def conflict_web():
    return FakeWeb(
        {
            "https://example.fi/cottages-a": html("<p>Rääkkylässä on 100 kesämökkiä.</p>"),
            "https://www.vero.fi/synthetic-cottages": html("<p>Rääkkylässä on 126 kesämökkiä.</p>"),
            "https://example.fi/cottages-b": html("<p>Rääkkylässä on 90 kesämökkiä.</p>"),
        }
    )


def test_verify_run_marks_conflicts_and_records_the_preference_order(active_run):
    db.init()
    db.create_run(RUN_ID, "test idea", idea_id="test-idea")
    (active_run / "02_research" / "market.md").write_text(CONFLICT_MD, encoding="utf-8")
    result = verify.verify_run(RUN_ID, conflict_web())
    states = {c.claim_id: c.verification for c in result.claims}
    assert states == {"market-001": "conflict", "market-002": "conflict", "market-003": "verified"}
    # vero.fi is allow-listed: market-002 is typed official and so preferred.
    expected = [{"dimension": "market", "claim_ids": ["market-002", "market-001"]}]
    assert json.loads((active_run / "03_claims" / "conflicts.json").read_text(encoding="utf-8")) == expected
    validate_file.validate_path(active_run / "03_claims" / "conflicts.json")  # kind inferred: conflicts
    ledger = {c["claim_id"]: c["verification"] for c in json.loads((active_run / "03_claims" / "verified.json").read_text("utf-8"))}
    assert ledger == states
    with db.session() as conn:
        assert conn.execute("SELECT verification FROM claims WHERE claim_id='market-001'").fetchone()[0] == "conflict"
    summary = verify.summary(result)
    assert "market: 1 verified, 2 conflict, 0 unverified" in summary
    assert "conflicts: 1 group(s) in 03_claims/conflicts.json" in summary


def test_mini_research_conflict_leaves_the_kept_claims_alone(active_run, monkeypatch):
    # Both verification runs fetch in the same second, so preference_key ties market-001 and
    # market-101 on retrieved_at and orders them by id instead of by the wall clock.
    fixed = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(verify, "_now", lambda: fixed)
    db.init()
    db.create_run(RUN_ID, "test idea", idea_id="test-idea")
    research = active_run / "02_research"
    (research / "market.md").write_text(CONFLICT_MD, encoding="utf-8")
    verify.verify_run(RUN_ID, conflict_web())
    mini = research_md(
        "market",
        [{"claim_id": "market-101", "statement": "Rääkkylä has 90 summer cottages.", "value": 90, "unit": "cottages",
          "source_url": "https://example.fi/cottages-b", "quote": "Rääkkylässä on 90 kesämökkiä.", "source_type": "news"}],
    )  # fmt: skip
    (research / "mini-1-market.md").write_text(mini, encoding="utf-8")
    result = verify.verify_run(RUN_ID, conflict_web(), only=["mini-1-market"])
    states = {c.claim_id: c.verification for c in result.claims}
    # 90 vs 126 conflicts: the new claim becomes conflict; the kept claims keep their state.
    assert states == {"market-001": "conflict", "market-002": "conflict", "market-003": "verified", "market-101": "conflict"}
    groups = json.loads((active_run / "03_claims" / "conflicts.json").read_text(encoding="utf-8"))
    assert groups == [{"dimension": "market", "claim_ids": ["market-002", "market-001", "market-101"]}]
