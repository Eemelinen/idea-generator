"""Claim-extraction pass (IF-211): uncited-sentence detection, the request, the extractor's output
checks and its claims verified like parsed ones. Every research file and page here is synthetic."""

import json

import pytest

import extract_claims
from ideaforge import agents, db, extract, guard, validate_file, verify
from ideaforge.verify import HttpResponse

RUN_ID = "20261023-120000-test-idea"

# Synthetic research file: the first figure sentence has a candidate claim, the second cites the
# same page with another quote, the third cites a page no claim cites.
PRICING_MD = """# pricing

Synthetic summary of cabin prices near Rääkkylä.

## Findings

A two-person lakeside cabin near Rääkkylä is listed at 650 EUR per week [src: https://example.fi/mokki-123].
> Hinta 650 € / viikko, sisältää liinavaatteet ja loppusiivouksen.

The same host rents a sauna cabin at 90 EUR per night [src: https://example.fi/mokki-123/].
> Saunamökki 90 € / yö.

Cabin hosts in the area include linen and final cleaning in the price [src: https://example.fi/mokki-456].

## Candidate claims

```json
[
  {
    "claim_id": "pricing-001",
    "dimension": "pricing",
    "statement": "A two-person lakeside cabin near Rääkkylä is listed at 650 EUR per week.",
    "value": 650,
    "unit": "EUR/week",
    "source_url": "https://example.fi/mokki-123",
    "source_title": "Mökki 123",
    "quote": "Hinta 650 € / viikko, sisältää liinavaatteet ja loppusiivouksen.",
    "published_date": null,
    "source_type": "vendor",
    "confidence": 0.7,
    "flags": []
  }
]
```

## Gaps

- No published prices for remote-work cabins [src: https://example.fi/gaps-are-not-checked].
"""

COVERED_MD = """# gtm

Synthetic summary.

## Findings

The host lists its cabins on one booking platform [src: https://example.fi/gtm-page].

## Candidate claims

```json
[
  {
    "claim_id": "gtm-001",
    "dimension": "gtm",
    "statement": "The host lists its cabins on one booking platform.",
    "source_url": "https://example.fi/gtm-page",
    "source_title": "Synthetic GTM page",
    "quote": "Varaa mökki varausalustalta.",
    "source_type": "vendor",
    "confidence": 0.6
  }
]
```

## Gaps

- None.
"""


def claim(claim_id, url, quote, *, value=None, unit=None, dimension="pricing", statement="Synthetic statement."):
    return {
        "claim_id": claim_id,
        "dimension": dimension,
        "statement": statement,
        "value": value,
        "unit": unit,
        "source_url": url,
        "source_title": "Synthetic page",
        "quote": quote,
        "published_date": None,
        "source_type": "vendor",
        "confidence": 0.6,
        "flags": [],
    }


SAUNA = claim("pricing-101", "https://example.fi/mokki-123", "Saunamökki 90 € / yö.", value=90, unit="EUR/night")
LINEN = claim("pricing-102", "https://example.fi/mokki-456", "Liinavaatteet ja loppusiivous sisältyvät hintaan.")


class FakeWeb:
    """Synthetic HTTP: url → HttpResponse; anything else (robots.txt included) is 404."""

    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        return self.pages.get(url) or HttpResponse(404, "not found", "text/html")


def html(body):
    return HttpResponse(200, f"<html><head><title>t</title></head><body><main>{body}</main></body></html>")


def web():
    return FakeWeb(
        {
            "https://example.fi/mokki-123": html(
                "<p>Hinta 650 € / viikko, sisältää liinavaatteet ja loppusiivouksen.</p><p>Saunamökki 90 € / yö.</p>"
            ),
            "https://example.fi/mokki-456": html("<p>Synthetic page without the quoted sentence.</p>"),
            "https://example.fi/gtm-page": html("<p>Varaa mökki varausalustalta.</p>"),
        }
    )


@pytest.fixture
def run(active_run):
    db.init()
    db.create_run(RUN_ID, "test idea", idea_id="test-idea")
    (active_run / "02_research" / "pricing.md").write_text(PRICING_MD, encoding="utf-8")
    (active_run / "02_research" / "gtm.md").write_text(COVERED_MD, encoding="utf-8")
    return active_run


def write_output(run_dir, stem, claims):
    path = agents.extracted_output(run_dir, stem)
    path.write_text(json.dumps(claims, ensure_ascii=False), encoding="utf-8")
    return path


# ---------------------------------------------------------------- detection


def test_sourced_sentences_skip_the_summary_candidates_and_gaps():
    found = validate_file.sourced_sentences(PRICING_MD)
    assert [s.urls for s in found] == [
        ("https://example.fi/mokki-123",),
        ("https://example.fi/mokki-123",),  # trailing slash normalized
        ("https://example.fi/mokki-456",),
    ]
    assert {s.section for s in found} == {"findings"}
    assert [s.quote for s in found] == [
        "Hinta 650 € / viikko, sisältää liinavaatteet ja loppusiivouksen.",
        "Saunamökki 90 € / yö.",
        None,
    ]


def test_only_the_quote_of_a_paragraphs_last_sentence_is_its_quote():
    md = "# x\n\n## Findings\n\nFirst fact here [src: https://a.fi/1]. Second fact 12 here [src: https://a.fi/2].\n> 12 here\n"
    first, second = validate_file.sourced_sentences(md)
    assert (first.urls, first.quote) == (("https://a.fi/1",), None)
    assert (second.urls, second.quote) == (("https://a.fi/2",), "12 here")


def test_a_sentence_is_covered_by_a_claim_with_its_url_and_quote():
    sentences = [s.sentence for s in extract.uncovered(PRICING_MD)]
    assert len(sentences) == 2
    assert "sauna cabin" in sentences[0] and "linen" in sentences[1]
    extra = [verify.CandidateClaim.model_validate(c) for c in (SAUNA, LINEN)]
    assert extract.uncovered(PRICING_MD, extra) == []
    # The right URL with another quote does not cover a figure sentence.
    wrong_quote = verify.CandidateClaim.model_validate(SAUNA | {"quote": "Hinta 650 € / viikko."})
    assert len(extract.uncovered(PRICING_MD, [wrong_quote, extra[1]])) == 1


def test_files_without_uncovered_sentences_need_no_extractor():
    assert extract.uncovered(COVERED_MD) == []
    assert extract.uncovered("# x\n\nSummary only.\n\n## Candidate claims\n\n## Gaps\n") == []


# ---------------------------------------------------------------- the request


def test_request_lists_only_files_with_uncovered_sentences(run, capsys):
    assert extract_claims.main([RUN_ID]) == 0
    out = capsys.readouterr().out
    assert "extract: 02_research/pricing.md: 2 sentence(s) without a candidate claim" in out
    assert "→ 03_claims/extracted/pricing.json (ids from pricing-101)" in out
    assert "gtm" not in out
    assert f"request: runs/{RUN_ID}/03_claims/extracted/request.json" in out

    path = agents.extract_request(run)
    validate_file.validate_path(path)  # kind inferred: extraction_request
    request = extract.load_request(run)
    (entry,) = request.files
    assert (entry.stem, entry.dimension, entry.first_claim_id) == ("pricing", "pricing", "pricing-101")
    assert entry.research_sha256 == extract.digest(PRICING_MD)
    assert [s.urls for s in entry.sentences] == [["https://example.fi/mokki-123"], ["https://example.fi/mokki-456"]]


def test_nothing_to_extract(run, capsys):
    (run / "02_research" / "pricing.md").unlink()
    assert extract_claims.main([RUN_ID]) == 0
    assert capsys.readouterr().out.strip() == "nothing to extract"
    assert extract.load_request(run).files == []


def test_unknown_run_or_no_research_dir(project, capsys):
    assert extract_claims.main(["../etc"]) == 1
    assert extract_claims.main(["20261023-120000-missing"]) == 1
    assert "02_research" in capsys.readouterr().err


def test_files_of_one_dimension_get_separate_id_blocks(run):
    (run / "02_research" / "mini-1-pricing.md").write_text(PRICING_MD.replace("pricing-001", "pricing-002"), encoding="utf-8")
    request, _ = extract.write_request(RUN_ID)
    assert [(f.stem, f.first_claim_id) for f in request.files] == [("pricing", "pricing-101"), ("mini-1-pricing", "pricing-201")]


def test_an_extracted_file_is_not_listed_again_until_its_research_file_changes(run, capsys):
    extract.write_request(RUN_ID)
    write_output(run, "pricing", [SAUNA])
    request, notes = extract.write_request(RUN_ID)
    assert extract.pending(run, request) == [] and notes == []
    assert [f.stem for f in request.files] == ["pricing"]  # kept, so the guard and hook still know it
    assert extract_claims.main([RUN_ID]) == 0
    assert capsys.readouterr().out.strip() == "nothing to extract"

    (run / "02_research" / "pricing.md").write_text(PRICING_MD.replace("90 EUR", "95 EUR"), encoding="utf-8")
    request, notes = extract.write_request(RUN_ID)
    assert notes == ["pricing.json: removed, pricing.md changed since it was extracted"]
    assert not agents.extracted_output(run, "pricing").exists()
    assert [f.stem for f in extract.pending(run, request)] == ["pricing"]


# ---------------------------------------------------------------- verification


def test_extracted_claims_are_verified_like_parsed_ones(run):
    extract.write_request(RUN_ID)
    write_output(run, "pricing", [SAUNA, LINEN])
    w = web()
    result = verify.verify_run(RUN_ID, w)
    assert result.warnings == []

    claims = {c["claim_id"]: c for c in json.loads((run / "03_claims" / "verified.json").read_text(encoding="utf-8"))}
    assert set(claims) == {"pricing-001", "pricing-101", "pricing-102", "gtm-001"}
    assert claims["pricing-101"]["verification"] == "verified"  # its quote is on the page
    assert claims["pricing-101"]["retrieved_at"]
    assert claims["pricing-102"]["verification"] == "unverified"  # its quote is not
    parsed = json.loads((run / "03_claims" / "pricing.json").read_text(encoding="utf-8"))
    assert [c["claim_id"] for c in parsed] == ["pricing-001", "pricing-101", "pricing-102"]
    assert {c["verification"] for c in parsed} == {"pending"}
    # The page is fetched once for the parsed and the extracted claim.
    assert w.calls.count("https://example.fi/mokki-123") == 1
    with db.session() as conn:
        rows = {r["claim_id"]: r["verification"] for r in conn.execute("SELECT * FROM claims WHERE run_id=?", (RUN_ID,))}
    assert rows["pricing-101"] == "verified" and rows["pricing-102"] == "unverified"
    assert "pricing: 2 verified, 1 unverified" in verify.summary(result)


def test_extracted_claims_that_break_the_rules_are_dropped_with_a_warning(run):
    extract.write_request(RUN_ID)
    write_output(
        run,
        "pricing",
        [
            SAUNA,
            SAUNA,  # duplicate id
            claim("pricing-001", "https://example.fi/mokki-456", "Synthetic."),  # the file's own id
            claim("pricing-103", "https://example.fi/never-cited", "Synthetic."),
            claim("gtm-101", "https://example.fi/mokki-456", "Synthetic.", dimension="gtm"),
            claim("pricing-104", "https://example.fi/gaps-are-not-checked", "Synthetic."),
        ],
    )
    result = verify.verify_run(RUN_ID, web())
    assert {c.claim_id for c in result.by_file["pricing"]} == {"pricing-001", "pricing-101"}
    joined = "\n".join(result.warnings)
    assert "claim pricing-101: duplicate claim id" in joined
    assert "claim pricing-001: claim id already in the run" in joined
    assert "claim pricing-103: source_url https://example.fi/never-cited is not in a [src: …] tag" in joined
    assert "claim gtm-101: dimension 'gtm', expected 'pricing'" in joined
    assert "claim pricing-104:" in joined  # a URL cited only under ## Gaps does not count


def test_a_stale_or_broken_extraction_is_ignored(run):
    extract.write_request(RUN_ID)
    write_output(run, "pricing", [SAUNA])
    (run / "02_research" / "pricing.md").write_text(PRICING_MD + "\n", encoding="utf-8")
    result = verify.verify_run(RUN_ID, web())
    assert [c.claim_id for c in result.by_file["pricing"]] == ["pricing-001"]
    assert any("is not for the current pricing.md" in w for w in result.warnings)

    extract.write_request(RUN_ID)
    agents.extracted_output(run, "pricing").write_text("[{]", encoding="utf-8")
    result = verify.verify_run(RUN_ID, web())
    assert [c.claim_id for c in result.by_file["pricing"]] == ["pricing-001"]
    assert any("is not a list of candidate claims" in w for w in result.warnings)


def test_ids_from_other_extractions_count_as_taken(run):
    (run / "02_research" / "mini-1-pricing.md").write_text(PRICING_MD.replace("pricing-001", "pricing-002"), encoding="utf-8")
    extract.write_request(RUN_ID)
    write_output(run, "pricing", [SAUNA])
    assert "pricing-101" in validate_file.claim_ids_elsewhere(run, "mini-1-pricing")
    write_output(run, "mini-1-pricing", [SAUNA])
    problems = extract.extracted_problems(agents.extracted_output(run, "mini-1-pricing"))
    assert problems == ["03_claims/extracted/mini-1-pricing.json: claim pricing-101: claim id already in the run; number new ids up from first_claim_id"]


# ---------------------------------------------------------------- hook and guard

EXTRACTOR = {"agent_id": "x1", "agent_type": "claim-extractor"}


def test_subagent_stop_hook_validates_every_requested_output(run):
    with pytest.raises(SystemExit):
        validate_file.auto(EXTRACTOR, stop=False)  # no request yet
    extract.write_request(RUN_ID)
    with pytest.raises(SystemExit) as exc:
        validate_file.auto(EXTRACTOR, stop=False)  # the output is missing
    assert exc.value.code == 2

    write_output(run, "pricing", [claim("pricing-103", "https://example.fi/never-cited", "Synthetic.")])
    with pytest.raises(SystemExit):
        validate_file.auto(EXTRACTOR, stop=False)
    assert validate_file.auto(EXTRACTOR | {"stop_hook_active": True}, stop=False) == 0
    marker = run / "VALIDATION_FAILED_claim-extractor"
    assert "is not in a [src: …] tag" in marker.read_text(encoding="utf-8")

    write_output(run, "pricing", [])  # no new claim is a valid answer
    assert validate_file.auto(EXTRACTOR, stop=False) == 0
    assert not marker.exists()
    validate_file.validate_path(agents.extracted_output(run, "pricing"))  # kind inferred: extracted


def write(path, **hook):
    return {"tool_name": "Write", "tool_input": {"file_path": str(path)}, **hook}


def test_the_extractor_writes_only_the_requested_outputs(run, project):
    (project / ".ideaforge-dev").touch()  # dev mode never relaxes subagents
    assert "may only write the output files" in guard.check_write(write(agents.extracted_output(run, "pricing"), **EXTRACTOR))
    extract.write_request(RUN_ID)
    assert guard.check_write(write(agents.extracted_output(run, "pricing"), **EXTRACTOR)) is None
    for other in (
        agents.extract_request(run),
        agents.extracted_output(run, "gtm"),
        run / "02_research" / "pricing.md",
        run / "03_claims" / "verified.json",
        project / "cache" / "a.txt",
    ):
        assert "may only write the output files" in guard.check_write(write(other, **EXTRACTOR)), other


def test_the_extractor_needs_an_active_run(project):
    assert "no active run" in guard.check_write(write(project / "runs" / "x" / "a.json", **EXTRACTOR))
