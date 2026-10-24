import json

import pytest

import new_run
from ideaforge import db, runs, validate_file
from ideaforge.schemas import IdeaSpec, Intake


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


INTAKE = {
    "goal": "starttiraha",
    "capital_eur": 2000,
    "hours_per_week": 30,
    "skills": ["carpentry (synthetic)"],
    "geography": ["Rääkkylä", "Finland"],
    "answers": [{"question": "Who pays?", "answer": "Summer cottage owners (synthetic)"}],
    "kill_trigger_overrides": ["permit_impossible"],
}


def test_intake_writes_a_valid_intake_json(project, capsys):
    assert new_run.main(["Lakeside sauna rentals", "--intake", json.dumps(INTAKE)]) == 0
    run_id = capsys.readouterr().out.strip()
    path = project / "runs" / run_id / "intake.json"
    validate_file.validate_path(path)  # the kind is inferred from the file name
    assert validate_file.main(["--kind", "intake", str(path)]) == 0
    assert Intake.model_validate_json(path.read_text(encoding="utf-8")).model_dump() == INTAKE


def test_intake_defaults(project, capsys):
    minimal = {"goal": "side_income", "capital_eur": 0, "hours_per_week": 10}
    new_run.main(["Lakeside sauna rentals", "--intake", json.dumps(minimal)])
    run_id = capsys.readouterr().out.strip()
    intake = Intake.model_validate_json((project / "runs" / run_id / "intake.json").read_text(encoding="utf-8"))
    assert intake.skills is None and intake.answers == [] and intake.kill_trigger_overrides == []
    assert intake.geography == IdeaSpec.model_fields["geography"].default


@pytest.mark.parametrize(
    "intake",
    [
        INTAKE | {"goal": "get_rich"},
        INTAKE | {"hours_per_week": 120},
        INTAKE | {"capital_eur": -1},
        INTAKE | {"geography": []},
        INTAKE | {"answers": [{"question": "q", "answer": "a"}] * 6},
        INTAKE | {"kill_trigger_overrides": ["bad_weather"]},
        INTAKE | {"unexpected": 1},
        {k: v for k, v in INTAKE.items() if k != "goal"},
        "not json",
    ],
)
def test_invalid_intake_is_rejected_and_creates_nothing(project, capsys, intake):
    with pytest.raises(SystemExit) as e:
        new_run.main(["Lakeside sauna rentals", "--intake", intake if isinstance(intake, str) else json.dumps(intake)])
    assert e.value.code == 2
    assert "invalid --intake" in capsys.readouterr().err
    assert list((project / "runs").iterdir()) == []
    assert not db.db_path().exists()  # refused before the database is touched
