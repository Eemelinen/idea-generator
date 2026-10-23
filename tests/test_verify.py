"""Claim verification (IF-208). No network: every page here is synthetic, served by FakeWeb."""

import hashlib
import json
import shutil

import pytest

import verify_claims
from ideaforge import db, verify
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
    ],
)
def test_unfetchable_pages(project, response):
    url = "https://u.example.fi/page"
    page = Fetcher(FakeWeb({url: response}), record_sources=False).get(url)
    assert page.status == "unfetchable" and page.text is None
    assert not verify.cache_path(url).exists()


def test_text_responses_are_used_as_is(project):
    url = "https://pxdata.stat.fi/PXWeb/api/v1/fi/synthetic.px"
    page = Fetcher(FakeWeb({url: HttpResponse(200, '{"value": [1975]}', "application/json; charset=utf-8")}), record_sources=False).get(url)
    assert page.status == "ok" and page.text == '{"value": [1975]}'


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
    assert "regulation: 1 verified, 3 unverified (1 unfetchable, 1 robots-disallowed)" in summary
    assert summary.endswith("total: 2/5 verified")


def test_rerun_uses_the_cache_and_retries_failures(run):
    verify.verify_run(RUN_ID, synthetic_web())
    web = synthetic_web()
    verify.verify_run(RUN_ID, web)
    assert "https://example.fi/mokki-123" not in web.calls
    assert "https://www.vero.fi/synthetic-alv" not in web.calls
    assert "https://forbidden.example.fi/x" in web.calls
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
