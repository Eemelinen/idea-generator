import json
import re
import shutil
from datetime import datetime
from pathlib import Path

import pytest
import status as status_cli
from conftest import FIXTURES, SYNTHETIC_RUN

from ideaforge import db, meta, report, review, runs, status
from ideaforge.schemas import RunMeta

GOLDEN_RUN = FIXTURES / "status" / "status_run.golden.txt"
GOLDEN_RECENT = FIXTURES / "status" / "status_recent.golden.txt"


def test_recent_runs_golden(synthetic_run, capsys):
    assert status_cli.main([]) == 0
    assert capsys.readouterr().out == GOLDEN_RECENT.read_text(encoding="utf-8")


def test_run_golden(synthetic_run, capsys):
    assert status_cli.main([SYNTHETIC_RUN]) == 0
    assert capsys.readouterr().out == GOLDEN_RUN.read_text(encoding="utf-8")


def test_limit(synthetic_run, capsys):
    assert status_cli.main(["--limit", "1"]) == 0
    out = capsys.readouterr().out
    assert SYNTHETIC_RUN in out and "berry-drying" not in out


def test_no_runs(project, capsys):
    assert status_cli.main([]) == 0
    assert capsys.readouterr().out == "no runs yet; start one with /validate <idea>\n"


@pytest.mark.parametrize("run_id", ["not a run id", "20261023-120000-missing"])
def test_bad_or_unknown_run(project, capsys, run_id):
    assert status_cli.main([run_id]) == 1
    assert capsys.readouterr().err.startswith("error: ")


def test_kill_flags_fire_only_on_verified_claims(synthetic_run):
    with db.session() as conn:
        rows = conn.execute("SELECT * FROM claims WHERE run_id=?", (SYNTHETIC_RUN,)).fetchall()
    lines = status.kill_flag_lines(rows, set())
    assert lines[:2] == [
        "free_good_enough_substitute: competition-001, killcause-002",
        "permit_impossible: regulation-001",
    ]
    assert "  no_evidence_anyone_pays: killcause-003 conflict" in lines
    assert not any("robots_disallowed" in line or "unfetchable" in line for line in lines)


def test_run_only_on_disk(project):
    run_id = "20261023-120000-disk-only"
    runs.create_run_dir(run_id, "disk only")
    db.init()
    out = status.run_status(run_id)
    assert "not in the database" in out
    assert "markers\nnone" in out
    assert "usage: 0 tool calls" in out


def test_stage_line_folds_research():
    rows = [
        {"stage": "intake", "status": "done"},
        {"stage": "research:market", "status": "done"},
        {"stage": "research:pricing", "status": "failed"},
        {"stage": "verify", "status": "pending"},
    ]
    assert status.stage_line(rows) == "intake done · research: 1 done, 1 failed · verify pending"
    assert status.stage_line([]) == "no stages"


def test_run_only_in_db(project):
    run_id = "20261023-120000-db-only"
    db.init()
    db.create_run(run_id, "db only idea", idea_id="db-only", stages=["intake"])
    out = status.run_status(run_id)
    assert "idea: db only idea" in out
    assert "warning: runs/20261023-120000-db-only does not exist" in out
    assert any(line.split()[:2] == ["intake", "pending"] for line in out.splitlines() if line.strip())
    assert "markers" not in out and "usage:" not in out


def test_odd_flags_are_ignored():
    rows = [
        {"claim_id": "a-001", "verification": "verified", "flags": "null"},
        {"claim_id": "a-002", "verification": "verified", "flags": '[{"x": 1}, "permit_impossible"]'},
        {"claim_id": "a-003", "verification": "verified", "flags": "not json"},
    ]
    assert status.kill_flag_lines(rows, set()) == ["permit_impossible: a-002"]


# ---------------------------------------------------------------- reviews and diff (IF-504/505)

STATUS_FIXTURES = FIXTURES / "status"
GOLDEN_DIFF = STATUS_FIXTURES / "status_diff.golden.txt"
GOLDEN_TREND = STATUS_FIXTURES / "status_reviews.golden.txt"
RUN_V1 = "20261023-110000-sauna-cabins"
RUN_V2 = "20261023-110000-sauna-cabins-v2"
OPUS = {"orchestrator": "opus", "research_subagent": "opus", "synthesizer": "opus", "debate_judge": "opus"}


def make_run(run_id, *, created, config_commit="a" * 40, models=OPUS, scores=None, report=True,
             idea_id="sauna-cabins", version=1, parent=None, config_dirty=False, write_meta=True):
    """A run row + directory with a synthetic meta.json, 04_scores.json and 05_report.md
    (values invented for logic tests, TICKETS.md plan note 14)."""
    db.init()
    db.create_run(run_id, "Sauna-and-lake cabin rentals", idea_id=idea_id, version=version, parent=parent)
    with db.session() as conn:
        conn.execute("UPDATE runs SET created_at=? WHERE run_id=?", (created, run_id))
    run_dir = runs.create_run_dir(run_id, "Sauna-and-lake cabin rentals")
    if write_meta:
        meta.write(run_dir, RunMeta(
            run_id=run_id, idea_id=idea_id, version=version, parent_run_id=parent,
            created_at=datetime.fromisoformat(created), config_commit=config_commit,
            config_dirty=config_dirty, models=models, budget_preset="standard",
        ))
    if scores:
        shutil.copy(STATUS_FIXTURES / scores, run_dir / "04_scores.json")
    if report:
        (run_dir / "05_report.md").write_text("# Sauna cabins: Ideaforge report\n", encoding="utf-8")
    return run_dir


@pytest.fixture
def version_pair(project):
    """v1 under opus; v2 (a child run) after a prompt change and a synthesizer/judge downgrade."""
    make_run(RUN_V1, created="2026-10-23T11:00:00+00:00", scores="scores_v1.synthetic.json")
    make_run(
        RUN_V2, created="2026-10-24T11:00:00+00:00", scores="scores_v2.synthetic.json",
        config_commit="b" * 40, version=2, parent=RUN_V1,
        models={**OPUS, "synthesizer": "sonnet", "debate_judge": "sonnet"},
    )


def test_sections_match_the_report_template():
    template = (Path(report.__file__).parent / "templates" / "report.md.j2").read_text(encoding="utf-8")
    headings = [h.split(":")[0].strip() for h in re.findall(r"^## (.+)$", template, re.MULTILINE)]
    assert headings == list(review.SECTIONS.values())


def test_parse_entries():
    assert review.parse(["verdict=4", "risks=2:too generic: no mitigation ", "sources= 5 :"]) == {
        "verdict": (4, None),
        "risks": (2, "too generic: no mitigation"),
        "sources": (5, None),
    }


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        ("verdict", "expected section=score"),
        ("Verdict=4", "expected section=score"),
        ("summary=4", "unknown section 'summary'"),
        ("verdict=0", "whole number 1–5"),
        ("verdict=6", "whole number 1–5"),
        ("verdict=3.5", "whole number 1–5"),
        ("verdict=", "whole number 1–5"),
    ],
)
def test_parse_rejects(entry, message):
    with pytest.raises(review.ReviewError, match=message):
        review.parse([entry])


def test_parse_rejects_a_section_twice():
    with pytest.raises(review.ReviewError, match="given twice"):
        review.parse(["verdict=4", "verdict=3"])


def test_review_lists_sections_then_stores(version_pair, capsys):
    assert status_cli.main([RUN_V1, "--review"]) == 0
    out = capsys.readouterr().out
    assert out.startswith(f"review of runs/{RUN_V1}/05_report.md")
    for section, heading in review.SECTIONS.items():
        assert any(line.split()[:1] == [section] and heading in line and line.endswith("-") for line in out.splitlines())

    assert status_cli.main([RUN_V1, "--review", "verdict=4", "risks=2:too generic"]) == 0
    assert capsys.readouterr().out.startswith(f"stored 2 review score(s) for {RUN_V1}; not scored yet: score_table,")
    with db.session() as conn:
        rows = conn.execute("SELECT section, score, note FROM reviews WHERE run_id=? ORDER BY section", (RUN_V1,))
        assert [tuple(r) for r in rows] == [("risks", 2, "too generic"), ("verdict", 4, None)]

    # Scoring again replaces; sections left out keep their scores.
    assert status_cli.main([RUN_V1, "--review", "verdict=3"]) == 0
    capsys.readouterr()
    assert review.stored(RUN_V1) == {"verdict": (3, None), "risks": (2, "too generic")}
    assert status_cli.main([RUN_V1, "--review"]) == 0
    out = capsys.readouterr().out
    assert any(line.startswith("risks") and line.endswith("2 (too generic)") for line in out.splitlines())

    entries = [f"{s}=5" for s in review.SECTIONS]
    assert status_cli.main([RUN_V1, "--review", *entries]) == 0
    assert capsys.readouterr().out.endswith("; every section is scored\n")


def test_bad_review_stores_nothing(version_pair, capsys):
    assert status_cli.main([RUN_V1, "--review", "verdict=4", "risks=9"]) == 1
    assert "risks: the score must be a whole number 1–5" in capsys.readouterr().err
    assert review.stored(RUN_V1) == {}


def test_review_needs_a_report_and_a_known_run(project, capsys):
    make_run(RUN_V1, created="2026-10-23T11:00:00+00:00", report=False)
    for argv in ([RUN_V1, "--review"], [RUN_V1, "--review", "verdict=4"]):
        assert status_cli.main(argv) == 1
        assert "has no 05_report.md to review yet" in capsys.readouterr().err
    assert status_cli.main(["20261023-120000-missing", "--review", "verdict=4"]) == 1
    assert "unknown run" in capsys.readouterr().err
    assert status_cli.main(["not a run id", "--review"]) == 1
    assert "not a valid run id" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv", [["--review"], ["--review", "verdict=4"], [RUN_V1, "--reviews"], [RUN_V1, "--diff", RUN_V1, RUN_V2],
             ["--reviews", "--diff", RUN_V1, RUN_V2]]
)
def test_bad_mode_combinations(project, argv):
    with pytest.raises(SystemExit) as e:
        status_cli.main(argv)
    assert e.value.code == 2


def test_no_reviews(project, capsys):
    assert status_cli.main(["--reviews"]) == 0
    assert capsys.readouterr().out == "no reviews yet; score a report with /status <run_id> --review\n"


def test_reviews_trend_golden(version_pair, capsys):
    """Two runs on version A, one on B (prompt change + downgrade), one without meta.json."""
    make_run(RUN_A2 := "20261023-120000-berry-drying", created="2026-10-23T12:00:00+00:00", idea_id="berry-drying")
    make_run(RUN_X := "20261022-090000-pizza", created="2026-10-25T09:00:00+00:00", idea_id="pizza", write_meta=False)
    review.store(RUN_V1, ["verdict=4", "score_table=4", "risks=2"])
    review.store(RUN_A2, ["verdict=5", "score_table=3", "risks=3", "sources=4"])
    review.store(RUN_V2, ["verdict=3", "score_table=4", "risks=2:generic"])
    review.store(RUN_X, ["verdict=1"])
    assert status_cli.main(["--reviews"]) == 0
    out = capsys.readouterr().out
    assert out == GOLDEN_TREND.read_text(encoding="utf-8")


def test_trend_groups_by_config_and_models(project):
    make_run(RUN_V1, created="2026-10-23T11:00:00+00:00")
    make_run(RUN_V2, created="2026-10-24T11:00:00+00:00", config_dirty=True, version=2, parent=RUN_V1)
    make_run("20261025-110000-same-config", created="2026-10-25T11:00:00+00:00", models={**OPUS, "debate_judge": "haiku"})
    for run_id in (RUN_V1, RUN_V2, "20261025-110000-same-config"):
        review.store(run_id, ["verdict=3"])
    vs = review.versions()
    assert [(v.label, v.config, review.models_text(v.models), v.run_ids) for v in vs] == [
        ("A", "aaaaaaa", "opus (all roles)", [RUN_V1]),
        ("B", "aaaaaaa+dirty", "opus (all roles)", [RUN_V2]),
        ("C", "aaaaaaa", "opus except debate_judge=haiku", ["20261025-110000-same-config"]),
    ]


def test_diff_golden(version_pair, capsys):
    assert status_cli.main(["--diff", RUN_V1, RUN_V2]) == 0
    assert capsys.readouterr().out == GOLDEN_DIFF.read_text(encoding="utf-8")


def test_diff_same_sheet(version_pair):
    out = status.diff_runs(RUN_V1, RUN_V1)
    assert "config: same (aaaaaaa)" in out and "models: same" in out
    assert "verdict: NO_GO (same)" in out and "weighted total: 2.65 → 2.65 (0)" in out
    assert "in both: free_good_enough_substitute" in out and "only in" not in out


def test_diff_without_meta_or_with_missing_dimensions(project):
    make_run(RUN_V1, created="2026-10-23T11:00:00+00:00", scores="scores_v1.synthetic.json", write_meta=False)
    sheet = json.loads((STATUS_FIXTURES / "scores_v2.synthetic.json").read_text(encoding="utf-8"))
    sheet["scores"] = [s for s in sheet["scores"] if s["dimension"] != "market"]
    sheet["scores"][0]["final_score"] = None
    sheet["kill_triggers_fired"] = []
    run_dir = make_run(RUN_V2, created="2026-10-24T11:00:00+00:00", version=2, parent=RUN_V1)
    (run_dir / "04_scores.json").write_text(json.dumps(sheet), encoding="utf-8")
    lines = status.diff_runs(RUN_V1, RUN_V2).splitlines()
    assert f"A: {RUN_V1} · meta.json missing or invalid · config unknown · models unknown" in lines
    assert "models: unknown (meta.json missing)" in lines
    assert [line.split() for line in lines if line.startswith(("customer", "market"))] == [
        ["customer", "3", "n/a", "-"],
        ["market", "2", "capped", "-", "-"],
    ]
    assert "only in A: free_good_enough_substitute" in lines


def test_diff_needs_two_score_sheets(version_pair, capsys):
    make_run(RUN_X := "20261025-090000-no-scores", created="2026-10-25T09:00:00+00:00")
    assert status_cli.main(["--diff", RUN_V1, RUN_X]) == 1
    assert f"run {RUN_X} has no valid 04_scores.json" in capsys.readouterr().err
    (runs.run_dir(RUN_X) / "04_scores.json").write_text('{"scores": []}', encoding="utf-8")
    assert status_cli.main(["--diff", RUN_X, RUN_V1]) == 1
    assert "is not valid" in capsys.readouterr().err
    assert status_cli.main(["--diff", RUN_V1, "20261025-090000-missing"]) == 1
    assert "unknown run" in capsys.readouterr().err
