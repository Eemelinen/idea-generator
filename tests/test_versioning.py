"""Versioning (IF-308): meta.json provenance, `new_run.py --from` and an immutable parent run.

The scored runs reuse the synthetic score_run / report fixtures (TICKETS.md plan note 14):
invented URLs and values that exercise the logic only.
"""

import hashlib
import json
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import new_run
import pytest
import render_report
import score_run
from conftest import FIXTURES

from ideaforge import config, db, meta, runs, validate_file
from ideaforge.schemas import RunMeta

SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def create(capsys, *argv) -> str:
    assert new_run.main(list(argv)) == 0
    return capsys.readouterr().out.strip().splitlines()[-1]  # earlier script output may precede it


def read_meta(run_id) -> dict:
    return json.loads((config.RUNS_DIR / run_id / "meta.json").read_text(encoding="utf-8"))


def score_and_render(run_id):
    """Put a run through stages 5b and 5c on the synthetic fixtures."""
    d = config.RUNS_DIR / run_id
    shutil.copy(FIXTURES / "spec.json", d / "00_spec.json")
    shutil.copy(FIXTURES / "score_run" / "verified.synthetic.json", d / "03_claims" / "verified.json")
    shutil.copy(FIXTURES / "score_run" / "04_scores_proposed.synthetic.json", d / "04_scores_proposed.json")
    shutil.copy(FIXTURES / "score_run" / "04_risks.synthetic.json", d / "04_risks.json")
    assert score_run.main([run_id]) == 0
    assert render_report.main([run_id]) == 0


def snapshot(run_id) -> dict[str, str]:
    """Every file of a run directory → its sha256."""
    d = config.RUNS_DIR / run_id
    return {
        p.relative_to(d).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(d.rglob("*")) if p.is_file()
    }


def db_rows(run_id) -> dict[str, list[tuple]]:
    with db.session() as conn:
        return {
            table: [tuple(r) for r in conn.execute(f"SELECT * FROM {table} WHERE run_id=? ORDER BY 1, 2", (run_id,))]
            for table in ("runs", "idea_versions", "stages", "scores", "reports")
        }


@pytest.fixture
def claude_version(monkeypatch):
    monkeypatch.setenv("IDEAFORGE_CLAUDE_CODE_VERSION", "2.1.309")


# ---------------------------------------------------------------- meta.json


def test_meta_records_provenance(project, capsys, claude_version):
    before = datetime.now(UTC)
    run_id = create(capsys, "Sauna-and-lake cabins for remote workers")
    data = read_meta(run_id)
    m = RunMeta.model_validate(data)

    assert (m.run_id, m.idea_id, m.version, m.parent_run_id) == (run_id, "sauna-and-lake-cabins-for", 1, None)
    assert before <= m.created_at <= datetime.now(UTC) and m.updated_at == m.created_at
    # The repository this test runs in: HEAD and the last commit touching prompts/config.
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=config.CONFIG_DIR.parent,
                          capture_output=True, text=True, check=True).stdout.strip()
    assert m.git_commit == head
    assert SHA_RE.match(m.config_commit)
    assert isinstance(m.config_dirty, bool)
    assert m.claude_code_version == "2.1.309"
    assert m.models == dict(config.models().roles) and m.models["synthesizer"] == "opus"
    assert m.budget_preset == "standard"
    validate_file.validate_path(config.RUNS_DIR / run_id / "meta.json")  # kind inferred from the name


def test_config_commit_is_the_last_change_to_prompts_or_config(project):
    # The sources of every prompt and agent file; a path missing here would go unrecorded.
    assert meta.PROVENANCE_PATHS == ("config", "prompts", "agent_templates")
    assert all((config.CONFIG_DIR.parent / p).is_dir() for p in meta.PROVENANCE_PATHS)
    paths = subprocess.run(
        ["git", "log", "-1", "--format=%H", "--", "config", "prompts", "agent_templates"],
        cwd=config.CONFIG_DIR.parent, capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert meta.config_commit() == paths


def test_probes_fail_soft_without_git_or_claude(project, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(meta, "_repo", lambda: tmp_path)  # not a git repository
    monkeypatch.delenv("IDEAFORGE_CLAUDE_CODE_VERSION", raising=False)
    monkeypatch.setattr(meta.shutil, "which", lambda name: None)
    run_id = create(capsys, "vegan bakery")
    m = RunMeta.model_validate(read_meta(run_id))
    assert (m.git_commit, m.config_commit, m.config_dirty, m.claude_code_version) == (None, None, None, None)


@pytest.mark.parametrize(
    ("returncode", "stdout", "expected"),
    [(0, "2.1.309 (Claude Code)\n", "2.1.309"), (0, "garbage\n", None), (1, "2.1.309\n", None)],
)
def test_claude_code_version_parses_the_cli(monkeypatch, returncode, stdout, expected):
    monkeypatch.delenv("IDEAFORGE_CLAUDE_CODE_VERSION", raising=False)
    monkeypatch.setattr(meta.shutil, "which", lambda name: "/usr/bin/claude")
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr="")

    monkeypatch.setattr(meta.subprocess, "run", fake_run)
    assert meta.claude_code_version() == expected
    assert calls == [["/usr/bin/claude", "--version"]]


def test_claude_code_version_survives_a_hanging_cli(monkeypatch):
    monkeypatch.delenv("IDEAFORGE_CLAUDE_CODE_VERSION", raising=False)
    monkeypatch.setattr(meta.shutil, "which", lambda name: "/usr/bin/claude")

    def hang(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))

    monkeypatch.setattr(meta.subprocess, "run", hang)
    assert meta.claude_code_version() is None


def test_stage_transitions_refresh_updated_at_only(project, capsys, claude_version, monkeypatch):
    run_id = create(capsys, "vegan bakery")
    created = read_meta(run_id)
    later = datetime(2030, 1, 1, tzinfo=UTC)
    monkeypatch.setattr(meta, "datetime", type("FixedNow", (), {"now": staticmethod(lambda tz=None: later)}))

    runs.begin(run_id, "intake")
    data = read_meta(run_id)
    assert datetime.fromisoformat(data["updated_at"]) == later
    assert {k: v for k, v in data.items() if k != "updated_at"} == {
        k: v for k, v in created.items() if k != "updated_at"
    }
    shutil.copy(FIXTURES / "spec.json", config.RUNS_DIR / run_id / "00_spec.json")
    (config.RUNS_DIR / run_id / "meta.json").write_text(json.dumps(created), encoding="utf-8")
    runs.finish(run_id, "intake")
    assert datetime.fromisoformat(read_meta(run_id)["updated_at"]) == later


def test_touch_fails_soft_when_the_write_fails(project, capsys, monkeypatch):
    run_id = create(capsys, "vegan bakery")
    d = config.RUNS_DIR / run_id
    before = (d / "meta.json").read_bytes()

    def locked(src, dst):  # e.g. a reader holding meta.json open on Windows
        raise PermissionError(13, "in use", str(dst))

    monkeypatch.setattr(meta.os, "replace", locked)
    assert meta.touch(d) is False
    runs.begin(run_id, "intake")  # the stage transition still succeeds
    assert runs.statuses(run_id)["intake"] == "running"
    assert (d / "meta.json").read_bytes() == before
    assert sorted(p.name for p in d.iterdir() if p.name.endswith(".tmp")) == []


def test_write_uses_a_unique_temp_file(project, capsys, monkeypatch):
    run_id = create(capsys, "vegan bakery")
    d = config.RUNS_DIR / run_id
    seen = []
    real = meta.os.replace
    monkeypatch.setattr(meta.os, "replace", lambda src, dst: (seen.append(Path(src).name), real(src, dst)))
    meta.touch(d)
    meta.touch(d)
    assert len(seen) == 2 and seen[0] != seen[1] and all(n.startswith(".meta.") for n in seen)
    RunMeta.model_validate(read_meta(run_id))


def test_touch_leaves_a_foreign_meta_alone(tmp_path):
    (tmp_path / "meta.json").write_text('{"budget_preset": "economy"}', encoding="utf-8")
    assert meta.touch(tmp_path) is False
    assert (tmp_path / "meta.json").read_text(encoding="utf-8") == '{"budget_preset": "economy"}'
    assert meta.touch(tmp_path / "missing") is False


def test_meta_schema_ties_version_to_parent():
    base = {"run_id": "r", "created_at": "2026-10-23T12:00:00Z", "models": {}, "budget_preset": "standard"}
    RunMeta.model_validate(base)
    RunMeta.model_validate({**base, "version": 2, "parent_run_id": "p"})
    RunMeta.model_validate({**base, "parent_run_id": "p"})  # a child run made before IF-308
    with pytest.raises(ValueError):
        RunMeta.model_validate({**base, "version": 2})


# ---------------------------------------------------------------- validate --from


def test_v2_has_its_own_directory_and_parent_link(project, capsys, claude_version):
    parent = create(capsys, "Sauna-and-lake cabins for remote workers")
    child = create(capsys, "--from", parent)
    assert child == f"{parent}-v2" and runs.RUN_ID_RE.match(child)

    d = config.RUNS_DIR / child
    assert d.is_dir() and d != config.RUNS_DIR / parent
    assert (d / "02_research").is_dir() and (d / "03_claims").is_dir()
    assert "Sauna-and-lake cabins" in (d / "idea.md").read_text(encoding="utf-8")  # the parent's text
    assert runs.active_run_id() == child
    assert len(db.stages(child)) == len(runs.STAGES)

    with db.session() as conn:
        rows = {r["run_id"]: r for r in conn.execute("SELECT * FROM idea_versions")}
    assert (rows[child]["parent"], rows[child]["version"]) == (parent, 2)
    assert rows[child]["idea_id"] == rows[parent]["idea_id"]
    m = RunMeta.model_validate(read_meta(child))
    assert (m.parent_run_id, m.version, m.idea_id) == (parent, 2, rows[parent]["idea_id"])


def test_v2_takes_a_revised_idea_text(project, capsys):
    parent = create(capsys, "vegan bakery")
    child = create(capsys, "--from", parent, "vegan bakery with a lunch counter", "--preset", "economy")
    assert "lunch counter" in (config.RUNS_DIR / child / "idea.md").read_text(encoding="utf-8")
    assert read_meta(child)["budget_preset"] == "economy"


def test_v2_inherits_preset_and_as_of(project, capsys):
    parent = create(capsys, "vegan bakery", "--preset", "deep", "--as-of", "2025-06-01")
    child = create(capsys, "--from", parent)
    assert (read_meta(child)["budget_preset"], read_meta(child)["as_of"]) == ("deep", "2025-06-01")
    with db.session() as conn:
        row = conn.execute("SELECT budget_preset, as_of FROM runs WHERE run_id=?", (child,)).fetchone()
    assert tuple(row) == ("deep", "2025-06-01")
    other = create(capsys, "--from", parent, "--preset", "economy", "--as-of", "2026-01-01")
    assert (read_meta(other)["budget_preset"], read_meta(other)["as_of"]) == ("economy", "2026-01-01")


def test_versions_never_reuse_a_run_id(project, capsys):
    v1 = create(capsys, "vegan bakery")
    v2 = create(capsys, "--from", v1)
    v3 = create(capsys, "--from", v1)  # a second revision of v1
    v4 = create(capsys, "--from", v2)
    assert (v2, v3, v4) == (f"{v1}-v2", f"{v1}-v3", f"{v1}-v4")
    with db.session() as conn:
        rows = {r["run_id"]: (r["parent"], r["version"]) for r in conn.execute("SELECT * FROM idea_versions")}
    assert rows[v3] == (v1, 3) and rows[v4] == (v2, 4)


def test_a_v1_slug_ending_in_v2_is_not_a_version(project, capsys):
    v1 = create(capsys, "product v2")
    assert v1.endswith("-product-v2")
    assert create(capsys, "--from", v1) == f"{v1}-v2"


@pytest.mark.parametrize("parent", ["20261023-120000-nope", "not a run id"])
def test_unknown_parent_is_refused(project, capsys, parent):
    with pytest.raises(SystemExit) as e:
        new_run.main(["--from", parent])
    assert e.value.code == 2
    assert [p.name for p in config.RUNS_DIR.iterdir() if p.is_dir()] == []


def test_a_taken_directory_is_skipped(project, capsys):
    parent = create(capsys, "vegan bakery")
    (config.RUNS_DIR / f"{parent}-v2").mkdir()  # a stray directory without a db row
    assert create(capsys, "--from", parent) == f"{parent}-v3"


def test_new_run_refuses_an_existing_directory(project, capsys, monkeypatch):
    run_id = create(capsys, "vegan bakery")
    before = snapshot(run_id)
    monkeypatch.setattr(runs, "new_run_id", lambda idea: run_id)  # same second, same slug
    with pytest.raises(SystemExit):
        new_run.main(["vegan bakery"])
    assert snapshot(run_id) == before


def test_idea_text_is_required_without_from(project):
    with pytest.raises(SystemExit):
        new_run.main([])
    with pytest.raises(SystemExit):
        new_run.main(["   "])


def test_v1_report_unchanged_by_a_new_version(project, capsys, claude_version):
    v1 = create(capsys, "Sauna-and-lake cabins for remote workers")
    score_and_render(v1)
    report_v1 = (config.RUNS_DIR / v1 / "05_report.md").read_bytes()
    files, rows = snapshot(v1), db_rows(v1)
    assert rows["reports"]

    v2 = create(capsys, "--from", v1, "Sauna cabins with a winter package")
    runs.begin(v2, "intake")
    shutil.copy(FIXTURES / "spec.json", config.RUNS_DIR / v2 / "00_spec.json")
    runs.finish(v2, "intake")
    score_and_render(v2)

    assert snapshot(v1) == files
    assert db_rows(v1) == rows
    assert (config.RUNS_DIR / v1 / "05_report.md").read_bytes() == report_v1
    assert (config.RUNS_DIR / v2 / "05_report.md").is_file()
    assert db.get_report(v2) is not None and db.get_report(v1)["path"] != db.get_report(v2)["path"]
    assert render_report.main([v1]) == 1  # the v1 report still cannot be overwritten
