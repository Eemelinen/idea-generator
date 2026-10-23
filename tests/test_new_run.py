import json

import pytest

import new_run
from ideaforge import db, runs


def test_new_run_creates_dir_db_rows_and_marker(project, capsys):
    assert new_run.main(["Sauna-and-lake cabin rentals for remote workers in Rääkkylä"]) == 0
    run_id = capsys.readouterr().out.strip()
    assert runs.RUN_ID_RE.match(run_id)
    assert run_id.endswith("sauna-and-lake-cabin-rentals")

    d = project / "runs" / run_id
    assert "Rääkkylä" in (d / "idea.md").read_text(encoding="utf-8")
    assert (d / "02_research").is_dir() and (d / "03_claims").is_dir()
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    assert meta["budget_preset"] == "standard"
    assert meta["models"]["synthesizer"] == "opus"

    assert runs.active_run_id() == run_id
    assert len(db.stages(run_id)) == len(runs.STAGES)


def test_new_version_links_parent(project, capsys):
    new_run.main(["vegan bakery"])
    parent = capsys.readouterr().out.strip()
    new_run.main(["vegan bakery, revised", "--from", parent, "--preset", "economy"])
    child = capsys.readouterr().out.strip()
    assert child == f"{parent}-v2"
    with db.session() as conn:
        row = conn.execute("SELECT * FROM idea_versions WHERE run_id=?", (child,)).fetchone()
    assert (row["parent"], row["version"]) == (parent, 2)


def test_rejects_unknown_preset(project):
    with pytest.raises(SystemExit):
        new_run.main(["idea", "--preset", "turbo"])


def test_env_run_id_overrides_marker(active_run, monkeypatch):
    monkeypatch.setenv("IDEAFORGE_RUN_ID", "other")
    assert runs.active_run_id() == "other"
