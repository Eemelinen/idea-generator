"""The golden-set schema and the eval checker (IF-502).

tests/fixtures/eval/*.synthetic.yaml and the runs built here are synthetic (TICKETS.md plan
note 14): invented ideas, facts, URLs and claims that exercise the logic, never research. The
committed golden set in tests/golden/ is IF-501's; until then it may be empty.
"""

import json

import eval_check
import pytest
from conftest import FIXTURES, REPO
from pydantic import ValidationError

from ideaforge import db, golden, guard, runs
from ideaforge.schemas import Claim, GoldenIdea, MustFindFact

EVAL_FIXTURES = FIXTURES / "eval"
BERRY, SAUNA, PIZZA = "berry-drying.synthetic", "sauna-cabins.synthetic", "wood-fired-pizza.synthetic"


def fact(**fields) -> dict:
    return {"fact": "A synthetic fact", "source_urls": ["https://example.invalid/synthetic/a"]} | fields


def golden_idea(**fields) -> dict:
    return {
        "idea": "Synthetic idea",
        "expected_verdicts": ["PIVOT"],
        "must_find": [fact(), fact(fact="Another synthetic fact")],
    } | fields


def claim(claim_id: str, verification: str = "verified", **fields) -> dict:
    return {
        "claim_id": claim_id,
        "dimension": claim_id.rsplit("-", 1)[0],
        "statement": "A synthetic statement.",
        "source_url": f"https://example.invalid/synthetic/{claim_id}",
        "source_title": "Synthetic source",
        "quote": "synthetic quote",
        "retrieved_at": "2026-10-23T10:30:00+00:00",
        "source_type": "news",
        "confidence": 0.8,
        "verification": verification,
    } | fields


def score_sheet(verdict: str, cited: dict[str, list[str]], ue_ids: list[str] = ()) -> dict:
    return {
        "scores": [
            {"dimension": dim, "proposed_score": 3, "justification": "synthetic", "supporting_claim_ids": ids,
             "final_score": 3}
            for dim, ids in cited.items()
        ],
        "weighted_total": 3.0,
        "verdict": verdict,
        "unit_economics": {"input_claim_ids": list(ue_ids)},
    }


def make_run(run_id: str, idea: str, claims: list[dict] | None = None, sheet: dict | None = None):
    run_dir = runs.create_run_dir(run_id, idea)
    db.create_run(run_id, idea, idea_id=runs.slugify(idea, 30), stages=runs.STAGES)
    if claims is not None:
        (run_dir / "03_claims" / "verified.json").write_text(json.dumps(claims), encoding="utf-8")
    if sheet is not None:
        (run_dir / "04_scores.json").write_text(json.dumps(sheet), encoding="utf-8")
    return run_dir


def ideas() -> dict[str, GoldenIdea]:
    return dict(golden.load_all(EVAL_FIXTURES))


@pytest.fixture
def eval_runs(project):
    """Synthetic runs for the fixture golden set: berry drying passes, sauna cabins fails all
    three checks (and has an older passing run that must be ignored), pizza has no run."""
    db.init()
    g = ideas()
    make_run(
        "20261023-090000-synthetic-berry-drying",
        g[BERRY].idea,
        claims=[
            claim("competition-001", statement="A synthetic Drying service and Competitor nearby."),
            claim("regulation-001", source_url="http://www.example.invalid/synthetic/notification/#section"),
            claim("market-001", "unverified"),
        ],
        sheet=score_sheet("NO_GO", {"competition": ["competition-001"], "regulation": ["regulation-001"]}),
    )
    make_run(
        "20261023-080000-synthetic-sauna-cabins",
        g[SAUNA].idea,
        claims=[claim("pricing-001", source_url="https://example.invalid/synthetic/price")],
        sheet=score_sheet("GO", {"pricing": ["pricing-001"]}),
    )
    make_run(
        "20261023-100000-synthetic-sauna-cabins",
        g[SAUNA].idea,
        claims=[
            claim("pricing-001", statement="A synthetic cabin costs 80 EUR per night."),
            # the keyword fact matches, but only through an unverified claim
            claim("regulation-001", "unverified", statement="Synthetic rantarakentaminen needs a permit."),
            claim("market-001", "conflict", source_url="https://example.invalid/synthetic/count"),
        ],
        sheet=score_sheet(
            "PIVOT", {"pricing": ["pricing-001"], "market": ["market-001"]}, ue_ids=["pricing-001", "gtm-009"]
        ),
    )


# ---------------------------------------------------------------- the golden files


def test_every_committed_golden_file_validates():
    """Zero files is fine until IF-501 adds the golden set."""
    committed = golden.load_all(REPO / "tests" / "golden")
    for gid, g in committed:
        assert isinstance(g, GoldenIdea), gid


def test_synthetic_fixtures_validate():
    loaded = golden.load_all(EVAL_FIXTURES)
    assert [gid for gid, _ in loaded] == [BERRY, SAUNA, PIZZA]
    assert golden.load_all(EVAL_FIXTURES, limit=2) == loaded[:2]


@pytest.mark.parametrize(
    "fields",
    [
        {"idea": ""},
        {"idea": "  padded idea"},
        {"idea": "two\nlines"},
        {"idea": "it's quoted"},
        {"idea": "costs $5"},
        {"idea": "a #hashtag"},
        {"expected_verdicts": []},
        {"expected_verdicts": ["GO", "GO"]},
        {"expected_verdicts": ["MAYBE"]},
        {"must_find": [fact()]},
        {"must_find": [fact(), fact(), fact(), fact()]},
        {"must_find": [fact(source_urls=[]), fact()]},
        {"must_find": [fact(source_urls=["example.invalid/x"]), fact()]},
        {"must_find": [fact(fact=" "), fact()]},
        {"must_find": [fact(dimensions=["weather"]), fact()]},
        {"must_find": [fact(keywords=[""]), fact()]},
        {"surprise": True},
    ],
)
def test_golden_schema_rejects(fields):
    with pytest.raises(ValidationError):
        GoldenIdea.model_validate(golden_idea(**fields))


@pytest.mark.parametrize("idea", ["Cabins <<deluxe>> by the lake", "Cabins >(lake)", "A curl salon"])
def test_an_idea_the_guard_would_refuse_is_invalid(tmp_path, idea):
    """/eval passes the idea to new_run.py verbatim, so the guard must accept that command."""
    GoldenIdea.model_validate(golden_idea(idea=idea))  # the schema alone lets these through
    (tmp_path / "x.yaml").write_text(json.dumps(golden_idea(idea=idea)), encoding="utf-8")
    with pytest.raises(golden.GoldenError, match=r"^x\.yaml: /eval could not pass the idea"):
        golden.load_all(tmp_path)


def test_the_new_run_command_of_every_fixture_passes_the_guard(project):
    """Strict mode: the project fixture removes the dev marker and HARNESS_LOOP."""
    for _, g in golden.load_all(EVAL_FIXTURES):
        assert guard.check_bash({"tool_input": {"command": golden.new_run_command(g.idea)}}) is None


def test_golden_schema_accepts_a_minimal_idea():
    g = GoldenIdea.model_validate(golden_idea())
    assert g.notes is None and g.must_find[0].keywords == [] and g.must_find[0].dimensions == []


def test_invalid_and_duplicate_golden_files_name_the_file(tmp_path):
    (tmp_path / "a.yaml").write_text("idea: [unclosed\n", encoding="utf-8")
    with pytest.raises(golden.GoldenError, match=r"^a\.yaml"):
        golden.load_all(tmp_path)
    (tmp_path / "a.yaml").write_text(json.dumps(golden_idea(expected_verdicts=["SOON"])), encoding="utf-8")
    with pytest.raises(golden.GoldenError, match=r"^a\.yaml"):
        golden.load_all(tmp_path)
    (tmp_path / "a.yaml").write_text(json.dumps(golden_idea()), encoding="utf-8")
    (tmp_path / "b.yaml").write_text(json.dumps(golden_idea()), encoding="utf-8")
    with pytest.raises(golden.GoldenError, match=r"b\.yaml has the same idea text as a\.yaml"):
        golden.load_all(tmp_path, limit=1)  # a broken file past the limit still fails


# ---------------------------------------------------------------- matching


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("https://www.Example.invalid/x/", "http://example.invalid/x"),
        ("https://example.invalid/x#part", "https://example.invalid/x"),
        ("https://example.invalid/x?id=1", "https://example.invalid/x/?id=1"),
    ],
)
def test_normalize_url_ignores_scheme_www_slash_and_fragment(a, b):
    assert golden.normalize_url(a) == golden.normalize_url(b)


def test_normalize_url_keeps_path_and_query():
    assert golden.normalize_url("https://example.invalid/x?id=1") != golden.normalize_url("https://example.invalid/x?id=2")
    assert golden.normalize_url("https://example.invalid/x") != golden.normalize_url("https://example.invalid/y")


def test_a_fact_is_found_by_url_or_by_every_keyword():
    by_url = MustFindFact.model_validate(fact(source_urls=["https://example.invalid/synthetic/market-001"]))
    by_keywords = MustFindFact.model_validate(fact(keywords=["Ranta", "permit"]))
    c = Claim.model_validate(claim("market-001", statement="A synthetic rantarakentaminen PERMIT."))
    assert golden.finds(by_url, c) and golden.finds(by_keywords, c)
    in_quote = Claim.model_validate(claim("market-002", quote="synthetic ranta permit quote"))
    assert golden.finds(by_keywords, in_quote)
    one_keyword = Claim.model_validate(claim("market-003", statement="A synthetic ranta plot."))
    assert not golden.finds(by_keywords, one_keyword)
    assert not golden.finds(MustFindFact.model_validate(fact()), one_keyword)  # no keywords, other URL


def test_only_verified_claims_of_the_listed_dimensions_find_a_fact():
    f = MustFindFact.model_validate(fact(keywords=["permit"], dimensions=["regulation"]))
    for state in ("unverified", "conflict", "pending"):
        assert not golden.finds(f, Claim.model_validate(claim("regulation-001", state, statement="a permit")))
    assert golden.finds(f, Claim.model_validate(claim("regulation-001", statement="a permit")))
    assert not golden.finds(f, Claim.model_validate(claim("market-001", statement="a permit")))


# ---------------------------------------------------------------- checks on runs


def test_latest_run_is_the_newest_with_that_idea_text(eval_runs):
    g = ideas()
    assert golden.latest_run(g[SAUNA].idea) == "20261023-100000-synthetic-sauna-cabins"
    assert golden.latest_run(g[BERRY].idea) == "20261023-090000-synthetic-berry-drying"
    assert golden.latest_run(g[PIZZA].idea) is None


def test_run_state(eval_runs, monkeypatch):
    assert golden.run_state(None) == "none"
    assert golden.run_state("20261023-090000-synthetic-berry-drying") == "incomplete"
    monkeypatch.setattr(runs, "is_complete", lambda run_id, stage, status=None: True)
    assert golden.run_state("20261023-090000-synthetic-berry-drying") == "complete"


def test_a_run_that_meets_all_three_checks_passes(eval_runs):
    r = golden.check(BERRY, ideas()[BERRY])
    assert r.error is None and r.passed
    assert r.verdict == "NO_GO" and r.verdict_ok
    assert r.found == {
        "A synthetic competitor already dries berries nearby": ["competition-001"],
        "A synthetic food-premises notification is required": ["regulation-001"],
    }
    assert r.unverified_cited == []


def test_each_check_fails_on_its_own(eval_runs):
    r = golden.check(SAUNA, ideas()[SAUNA])
    assert r.run_id == "20261023-100000-synthetic-sauna-cabins"
    assert not r.passed
    assert r.verdict == "PIVOT" and not r.verdict_ok
    # found by keywords; the count is only in a conflict claim, the permit only in an unverified one
    assert r.missing_facts == ["A synthetic count of holiday homes", "A synthetic shoreline building permit"]
    assert r.found["A synthetic cabin price per night"] == ["pricing-001"]
    # score citations and unit-economics inputs both count; unknown ids too
    assert r.unverified_cited == ["market-001 (conflict)", "gtm-009 (unknown)"]


def test_an_explicit_run_id_overrides_the_lookup(eval_runs):
    r = golden.check(SAUNA, ideas()[SAUNA], "20261023-080000-synthetic-sauna-cabins")
    assert r.verdict_ok and r.unverified_cited == [] and not r.passed  # two facts still missing


def test_missing_run_or_files_are_failures_not_crashes(eval_runs):
    g = ideas()
    assert golden.check(PIZZA, g[PIZZA]).error == "no run with this idea text"
    make_run("20261023-110000-synthetic-pizza", g[PIZZA].idea, claims=[])
    r = golden.check(PIZZA, g[PIZZA])
    assert r.error == "no 04_scores.json" and not r.passed
    (runs.run_dir(r.run_id) / "04_scores.json").write_text("{}", encoding="utf-8")
    assert golden.check(PIZZA, g[PIZZA]).error.startswith("invalid 04_scores.json")
    (runs.run_dir(r.run_id) / "04_scores.json").write_text(json.dumps(score_sheet("PIVOT", {})), encoding="utf-8")
    (runs.run_dir(r.run_id) / "03_claims" / "verified.json").unlink()
    assert golden.check(PIZZA, g[PIZZA]).error == "no 03_claims/verified.json"


def test_summary_table(eval_runs):
    g = ideas()
    text = golden.summary([golden.check(gid, idea) for gid, idea in g.items()])
    lines = text.splitlines()
    assert lines[0].startswith("| golden idea | run | verdict | expected | verdict ok | must-find |")
    assert lines[2] == (
        f"| {BERRY} | 20261023-090000-synthetic-berry-drying | NO_GO (3.00) | NO_GO, PIVOT | yes | 2/2 | 0 | PASS |"
    )
    assert lines[3] == f"| {SAUNA} | 20261023-100000-synthetic-sauna-cabins | PIVOT (3.00) | GO | no | 1/3 | 2 | FAIL |"
    assert lines[4] == f"| {PIZZA} | - | - | PIVOT | - | - | - | FAIL |"
    assert f"- {SAUNA}: verdict PIVOT not in GO" in lines
    assert f"- {SAUNA}: must-find fact not among the verified claims: A synthetic count of holiday homes" in lines
    assert f"- {SAUNA}: score sheet cites claims that are not verified: market-001 (conflict), gtm-009 (unknown)" in lines
    assert f"- {PIZZA}: no run with this idea text" in lines
    assert lines[-1] == "passed: 1 of 3"


# ---------------------------------------------------------------- CLI


def test_cli_prints_the_table_and_exits_2_on_a_failure(eval_runs, capsys):
    assert eval_check.main(["--golden-dir", str(EVAL_FIXTURES)]) == 2
    assert capsys.readouterr().out.strip().endswith("passed: 1 of 3")


def test_cli_exits_0_when_every_checked_idea_passes(eval_runs, capsys):
    assert eval_check.main(["--golden-dir", str(EVAL_FIXTURES), "--limit", "1"]) == 0
    out = capsys.readouterr().out
    assert BERRY in out and SAUNA not in out and "passed: 1 of 1" in out


def test_cli_plan_lists_runs_without_the_answer_key(eval_runs, capsys):
    assert eval_check.main(["--plan", "--golden-dir", str(EVAL_FIXTURES)]) == 0
    lines = capsys.readouterr().out.splitlines()
    g = ideas()
    assert lines == [
        f"{BERRY}\tincomplete\t20261023-090000-synthetic-berry-drying\t{g[BERRY].idea}",
        f"{SAUNA}\tincomplete\t20261023-100000-synthetic-sauna-cabins\t{g[SAUNA].idea}",
        f"{PIZZA}\tnone\t-\t{g[PIZZA].idea}",
    ]
    text = "\n".join(lines)
    for idea in g.values():
        for f in idea.must_find:
            assert f.fact not in text and not any(u in text for u in f.source_urls)
    assert "NO_GO" not in text and "GO\t" not in text


def test_cli_with_no_golden_files_exits_0(project, tmp_path, capsys):
    assert eval_check.main(["--golden-dir", str(tmp_path)]) == 0
    assert "no golden ideas" in capsys.readouterr().out


def test_cli_invalid_golden_file_exits_1(project, tmp_path, capsys):
    (tmp_path / "bad.yaml").write_text("idea: ''\n", encoding="utf-8")
    assert eval_check.main(["--golden-dir", str(tmp_path)]) == 1
    assert "bad.yaml" in capsys.readouterr().err


def test_cli_rejects_a_limit_below_1(project):
    with pytest.raises(SystemExit):
        eval_check.main(["--limit", "0"])
