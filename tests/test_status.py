import pytest
import status as status_cli
from conftest import FIXTURES, SYNTHETIC_RUN

from ideaforge import db, runs, status

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
