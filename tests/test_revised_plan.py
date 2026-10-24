"""Revised plan (IF-405, IF-406): `render_report.py --debate` → debate/revised_plan.md.

The run is test_report's `scored` run (score_run fixtures plus synthetic report claims), rendered
to 05_report.md, with a synthetic debate on top: five round-0 positions citing market-001, one
validated rebuttal round and tests/fixtures/debate/verdict.synthetic.json. All synthetic
(TICKETS.md plan note 14).

The snapshot is tests/golden/revised_plan.synthetic.md. After a deliberate change, regenerate it
with `IDEAFORGE_UPDATE_GOLDEN=1 uv run pytest tests/test_revised_plan.py` and review the diff.
"""

import json
import os
import re
import shutil
from datetime import UTC, datetime

import pytest
import render_report
from conftest import FIXTURES, REPO, debate_position
from test_report import RUN, edit_json, render, scored  # noqa: F401  (scored is a fixture)

from ideaforge import db, debate, report, revised_plan
from ideaforge.schemas import PERSONAS

NOW = datetime(2026, 10, 24, 9, 0, tzinfo=UTC)
SEED = 7
MAP = debate.mapping_for(SEED)
VERDICT = FIXTURES / "debate" / "verdict.synthetic.json"
GOLDEN = REPO / "tests" / "golden" / "revised_plan.synthetic.md"
GAP = {"evidence_gap": "Synthetic gap."}
COMPUTATION = {"computation": "market-001 gives 1200 nights x 0.3 = 360"}


def other(role):
    return next(pid for r, pid in MAP.items() if r != role)


def write_turn(run_dir, round_no, role, data):
    d = run_dir / "debate" / f"round{round_no}"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{role}.json").write_text(json.dumps(data), encoding="utf-8")


def debate_round(run_dir, agreeing=()):
    """Validated round 1. Without `agreeing`, the founder brings in pricing-001 (a new claim id,
    so no conformity) and the others disagree with a gap; with it, those roles agree with the
    founder's position by a computation over market-001 (no new claim id) and the rest disagree."""
    for role in PERSONAS:
        if role in agreeing:
            response = {"target_position_id": MAP["founder"], "stance": "agree", "basis": COMPUTATION}
        elif role == "founder" and not agreeing:
            response = {"target_position_id": MAP["investor"], "stance": "agree", "basis": {"new_claim_ids": ["pricing-001"]}}
        else:
            response = {"target_position_id": other(role), "stance": "disagree", "basis": GAP}
        write_turn(run_dir, 1, role, {"role": role, "round": 1, "responses": [response]})
    result = debate.validate_round(RUN, 1)
    assert not result.rejected, result.rejected


@pytest.fixture
def debated(scored):  # noqa: F811
    """The scored run after its report, a one-round debate and the judge's verdict."""
    render(scored)
    for role in PERSONAS:
        write_turn(scored, 0, role, debate_position(role))
    debate.anonymize(RUN, 0, seed=SEED)
    shutil.copy(VERDICT, scored / "debate" / "verdict.json")
    return scored


def plan(run_dir):
    return revised_plan.render(RUN, now=NOW).path.read_text(encoding="utf-8")


def section(text, heading):
    m = re.search(rf"^##+ {re.escape(heading)}\n(.*?)(?=^##+ |\Z)", text, re.M | re.S)
    assert m, f"no section {heading!r}"
    return m.group(1)


def table_rows(body):
    return [line for line in body.splitlines() if re.match(r"\| \d+ \|", line)]


# ---------------------------------------------------------------- output


def test_revised_plan_matches_the_snapshot(debated):
    debate_round(debated)
    text = plan(debated)
    if os.environ.get("IDEAFORGE_UPDATE_GOLDEN") == "1":
        GOLDEN.write_text(text, encoding="utf-8", newline="\n")
    assert GOLDEN.is_file(), f"missing {GOLDEN}; see this module's docstring"
    assert text == GOLDEN.read_text(encoding="utf-8")


def test_cli_writes_the_plan(debated, capsys):
    debate_round(debated)
    assert render_report.main([RUN, "--debate"]) == 0
    out = capsys.readouterr().out
    assert "accepted 2 change(s), rejected 2; 6 experiment(s); conformity flag not raised" in out
    assert f"wrote runs/{RUN}/debate/revised_plan.md" in out
    assert (debated / "debate" / "revised_plan.md").is_file()


def test_at_least_five_experiments_each_with_cost_days_and_threshold(debated):
    debate_round(debated)
    rows = table_rows(section(plan(debated), "Experiments"))
    assert len(rows) >= 5
    for row in rows:
        cells = [c.strip() for c in row.strip("|").split(" | ")]
        _, name, cost, days, threshold, info, _ = cells
        assert name and threshold
        assert re.fullmatch(r"\d[\d ]*\.\d\d", cost) and re.fullmatch(r"\d+(\.\d+)?", days)
        assert info in "12345"


def test_experiments_are_ordered_by_info_value_per_cost(debated):
    debate_round(debated)
    rows = table_rows(section(plan(debated), "Experiments"))
    names = [row.split(" | ")[1] for row in rows]
    assert names == [
        "Remote-work forum post",  # free, info 3
        "Cleaning quote from two providers",  # free, info 2
        "Price test at two nightly rates",  # 4 / 40
        "Winter landing page with deposit",  # 5 / 60
        "Sauna-equipment rental quote",  # 2 / 60
        "Weekend pilot stay",  # 4 / 150
    ]
    assert rows[0].endswith("| free |") and "| 10.00 |" in rows[2]


def test_diff_against_the_report(debated):
    debate_round(debated)
    sheet = json.loads((debated / "04_scores.json").read_text(encoding="utf-8"))
    finals = {s["dimension"]: s["final_score"] for s in sheet["scores"]}
    diff = re.search(r"```diff\n(.*?)```", plan(debated), re.S).group(1).splitlines()
    assert diff[0].startswith("@@ dimension scores: 05_report.md")
    assert f"- market          {report.score_fmt(finals['market'])}" in diff
    assert "+ market          3.5" in diff
    assert any(line.startswith("  customer") and line.endswith("(not projected)") for line in diff)
    i = diff.index("@@ weighted total: report → projection @@")
    assert diff[i + 1] == f"- {report.num(sheet['weighted_total'])}" and diff[i + 2].startswith("+ ")
    assert "+ Size the beachhead from remote-worker stays, not total nights. [market-001, market-002]" in diff


def test_projected_total_is_computed_in_python(debated):
    from ideaforge import config, scoring
    from ideaforge.schemas import ScoreSheet, Verdict

    sheet = ScoreSheet.model_validate_json((debated / "04_scores.json").read_text(encoding="utf-8"))
    verdict = Verdict.model_validate_json(VERDICT.read_text(encoding="utf-8"))
    weights = {d.id: d.weight for d in config.rubric().dimensions}
    expected = sheet.weighted_total + sum(
        weights[d] * (v - next(s.final_score for s in sheet.scores if s.dimension == d))
        for d, v in verdict.projected_scores.items()
    )
    assert revised_plan.projected_total(debated, verdict) == pytest.approx(expected)
    assert scoring.weighted_total(sheet.scores, config.rubric()) == pytest.approx(sheet.weighted_total)


def test_accepted_changes_show_their_claims_and_rejected_their_reasons(debated):
    debate_round(debated)
    text = plan(debated)
    accepted = section(text, "Accepted changes")
    assert "`market-001`:" in accepted and "`pricing-001`:" in accepted and "Source: [" in accepted
    rejected = section(text, "Rejected changes")
    assert "Add a third cabin in year one. Reason: Synthetic reason: no verified demand" in rejected
    assert "Not in the ledger: market-999." in rejected


def test_assumption_register_is_a_table(debated):
    debate_round(debated)
    rows = table_rows(section(plan(debated), "Assumption register"))
    assert len(rows) == 3
    assert "| contested |" in rows[1] and "a \\| in" in rows[1]


def test_tables_are_persisted(debated):
    debate_round(debated)
    plan(debated)
    with db.session() as conn:
        assumptions = conn.execute("SELECT * FROM assumptions WHERE run_id=? ORDER BY idx", (RUN,)).fetchall()
        experiments = conn.execute("SELECT * FROM experiments WHERE run_id=? ORDER BY idx", (RUN,)).fetchall()
        row = conn.execute("SELECT * FROM reports WHERE run_id=? AND kind='revised_plan'", (RUN,)).fetchone()
        deb = conn.execute("SELECT * FROM debates WHERE run_id=?", (RUN,)).fetchone()
    assert [a["evidence_state"] for a in assumptions] == ["untested", "contested", "supported"]
    assert [e["name"] for e in experiments][:2] == ["Remote-work forum post", "Cleaning quote from two providers"]
    assert [e["idx"] for e in experiments] == [1, 2, 3, 4, 5, 6]
    assert all(e["cost_eur"] is not None and e["days"] > 0 and e["success_threshold"] for e in experiments)
    assert row["path"] == f"runs/{RUN}/debate/revised_plan.md" and row["created_at"] == NOW.isoformat()
    assert (deb["status"], deb["rounds"], deb["conformity_flag"], deb["finished_at"]) == ("done", 1, 0, NOW.isoformat())


# ---------------------------------------------------------------- conformity flag


def test_conformity_flag_is_recomputed_and_shown_prominently(debated, capsys):
    debate_round(debated, agreeing=("investor", "customer", "accountant"))
    assert render_report.main([RUN, "--debate"]) == 0
    assert "conformity flag RAISED" in capsys.readouterr().out
    text = (debated / "debate" / "revised_plan.md").read_text(encoding="utf-8")
    head = text.split("## Changes against the report")[0]
    assert "> **⚠ Conformity flag.**" in head
    assert "The judge wrote `conformity_flag: false`; Python recomputed it as `true`" in head
    assert json.loads((debated / "debate" / "verdict.json").read_text(encoding="utf-8"))["conformity_flag"] is True
    with db.session() as conn:
        assert conn.execute("SELECT conformity_flag FROM debates WHERE run_id=?", (RUN,)).fetchone()[0] == 1


def test_judge_flag_without_conformity_is_corrected(debated):
    debate_round(debated)
    edit_json(debated / "debate" / "verdict.json", lambda v: v.update(conformity_flag=True))
    text = plan(debated)
    assert "Conformity flag: not raised" in text
    assert "Python recomputed it as `false`" in text
    assert json.loads((debated / "debate" / "verdict.json").read_text(encoding="utf-8"))["conformity_flag"] is False


# ---------------------------------------------------------------- refusals


@pytest.mark.parametrize(
    ("claim_id", "message"),
    [("market-999", "market-999, which is not in the ledger"), ("market-004", "market-004, which is conflict")],
)
def test_accepted_change_with_unknown_or_unverified_claim_is_refused(debated, capsys, claim_id, message):
    debate_round(debated)
    edit_json(debated / "debate" / "verdict.json", lambda v: v["accepted_changes"][1].update(claim_ids=[claim_id]))
    before = (debated / "debate" / "verdict.json").read_text(encoding="utf-8")
    assert render_report.main([RUN, "--debate"]) == 1
    assert f"accepted change 2 cites {message}" in capsys.readouterr().err
    assert not (debated / "debate" / "revised_plan.md").exists()
    assert (debated / "debate" / "verdict.json").read_text(encoding="utf-8") == before
    with db.session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM experiments WHERE run_id=?", (RUN,)).fetchone()[0] == 0
        assert db.get_report(RUN, "revised_plan") is None


def test_verdict_with_fewer_than_five_experiments_is_refused(debated, capsys):
    debate_round(debated)
    edit_json(debated / "debate" / "verdict.json", lambda v: v.update(experiments=v["experiments"][:4]))
    assert render_report.main([RUN, "--debate"]) == 1
    assert "not a valid Verdict" in capsys.readouterr().err


def test_missing_verdict_is_refused(debated, capsys):
    debate_round(debated)
    (debated / "debate" / "verdict.json").unlink()
    assert render_report.main([RUN, "--debate"]) == 1
    assert "verdict.json does not exist" in capsys.readouterr().err


def test_unvalidated_round_is_refused(debated, capsys):
    write_turn(debated, 1, "founder", {"role": "founder", "round": 1, "responses": []})
    assert render_report.main([RUN, "--debate"]) == 1
    assert "was not checked in its current form" in capsys.readouterr().err


def test_needs_the_report(scored, capsys):  # noqa: F811
    for role in PERSONAS:
        write_turn(scored, 0, role, debate_position(role))
    from score_run import main as score

    assert score([RUN]) == 0
    debate.anonymize(RUN, 0, seed=SEED)
    shutil.copy(VERDICT, scored / "debate" / "verdict.json")
    assert render_report.main([RUN, "--debate"]) == 1
    assert "05_report.md does not exist" in capsys.readouterr().err


def test_plan_is_immutable(debated, capsys):
    debate_round(debated)
    assert render_report.main([RUN, "--debate"]) == 0
    path = debated / "debate" / "revised_plan.md"
    first = path.read_text(encoding="utf-8")
    assert render_report.main([RUN, "--debate"]) == 1
    assert "immutable" in capsys.readouterr().err
    assert path.read_text(encoding="utf-8") == first
    path.unlink()
    assert render_report.main([RUN, "--debate"]) == 1  # the row still refuses
    assert "revised_plan row" in capsys.readouterr().err


def test_failed_write_leaves_no_row_and_no_tables(debated, monkeypatch):
    debate_round(debated)

    def boom(path, text):
        raise OSError("disk full")

    monkeypatch.setattr(report, "write_new", boom)
    with pytest.raises(OSError):
        revised_plan.render(RUN, now=NOW)
    with db.session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM assumptions WHERE run_id=?", (RUN,)).fetchone()[0] == 0
        assert conn.execute("SELECT status FROM debates WHERE run_id=?", (RUN,)).fetchone()[0] == "running"
    assert db.get_report(RUN, "revised_plan") is None


def test_failed_render_keeps_the_judges_flag_for_the_rerun(debated, monkeypatch):
    debate_round(debated)
    edit_json(debated / "debate" / "verdict.json", lambda v: v.update(conformity_flag=True))
    real = report.write_new

    def boom(path, text):
        raise OSError("disk full")

    monkeypatch.setattr(report, "write_new", boom)
    with pytest.raises(OSError):
        revised_plan.render(RUN, now=NOW)
    assert json.loads((debated / "debate" / "verdict.json").read_text(encoding="utf-8"))["conformity_flag"] is True
    monkeypatch.setattr(report, "write_new", real)
    assert "Python recomputed it as `false`" in plan(debated)
    assert json.loads((debated / "debate" / "verdict.json").read_text(encoding="utf-8"))["conformity_flag"] is False


def test_projection_above_the_cap_is_marked(debated):
    debate_round(debated)
    edit_json(debated / "debate" / "verdict.json", lambda v: v["projected_scores"].update(founder_risk=3.0))
    diff = re.search(r"```diff\n(.*?)```", plan(debated), re.S).group(1).splitlines()
    assert "+ founder_risk    3  (above the cap of 2: insufficient data)" in diff
    assert "+ market          3.5" in diff  # a scored dimension carries no mark
