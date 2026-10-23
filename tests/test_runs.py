"""Stage state machine and resume (IF-214, Python side of IF-507).

Research files here are synthetic (TICKETS.md plan note 14): they only have to pass the
research validator, and their example.fi URLs are not real sources.
"""

import json
import shutil
from pathlib import Path

import pytest

import run_stage
from conftest import FIXTURES
from ideaforge import agents, db, runs
from ideaforge import validate_file as vf
from ideaforge.schemas import RESEARCH_DIMENSIONS

RUN = "20261023-120000-stage-test"
RESEARCH = [f"research:{d}" for d in RESEARCH_DIMENSIONS]

# Fixture file per JSON output; research and the report are written by the helpers below.
JSON_FIXTURES = {
    "00_spec.json": "spec.json",
    "01_plan.json": "plan.json",
    "03_claims/verified.json": "claims.json",
    "04_scores_proposed.json": "scores_proposed.json",
    "04_risks.json": "risks.json",
    "04_scores.json": "scores.json",
}


@pytest.fixture
def run(project):
    db.init()
    d = runs.create_run_dir(RUN, "stage test")
    db.create_run(RUN, "stage test", idea_id="stage-test", stages=runs.STAGES)
    return d


def synthetic_research(run_dir, dim, *, complete=True):
    url = f"https://example.fi/synthetic-{dim.replace('_', '-')}"
    claim = {
        "claim_id": f"{dim}-001",
        "dimension": dim,
        "statement": "Lake cabins are common near Rääkkylä.",
        "value": None,
        "unit": None,
        "source_url": url,
        "source_title": "Synthetic",
        "quote": "Lake cabins are common.",
        "published_date": None,
        "source_type": "news",
        "confidence": 0.5,
        "flags": [],
    }
    md = (
        f"# {dim}\n\nSynthetic file for the stage state-machine tests.\n\n## Findings\n\n"
        f"Lake cabins are common near Rääkkylä [src: {url}].\n\n## Candidate claims\n\n"
    )
    if complete:
        md += f"```json\n{json.dumps([claim], indent=2)}\n```\n\n## Gaps\n\n- None.\n"
    else:
        md += '```json\n[\n  {\n    "claim_id": "'  # the agent was killed mid-write
    (run_dir / "02_research" / f"{dim}.md").write_text(md, encoding="utf-8")
    with open(run_dir / ".seen_urls.txt", "a", encoding="utf-8") as f:
        f.write(f"{agents.research_agent(dim).name}\t{url}\n")


def write_output(run_dir, stage):
    if stage.startswith("research:"):
        synthetic_research(run_dir, stage.split(":", 1)[1])
    elif stage == "report":
        (run_dir / "05_report.md").write_text("# Report\n\nSynthetic.\n", encoding="utf-8")
    else:
        for rel, _kind in runs.STAGE_OUTPUTS[stage]:
            (run_dir / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(FIXTURES / JSON_FIXTURES[rel], run_dir / rel)


def complete(run_dir, *stages):
    for stage in stages:
        runs.begin(RUN, stage)
        write_output(run_dir, stage)
        runs.finish(RUN, stage)


def row(stage):
    return next(r for r in db.stages(RUN) if r["stage"] == stage)


def test_every_stage_has_outputs_and_a_group():
    assert set(runs.STAGE_OUTPUTS) == set(runs.STAGES)
    assert [s for group in runs.STAGE_GROUPS for s in group] == runs.STAGES


def test_stage_outputs_agree_with_the_validator_file_map():
    for stage, outputs in runs.STAGE_OUTPUTS.items():
        for rel, kind in outputs:
            if kind == "research":
                assert vf.infer_kind(Path("runs/x") / rel) == "research", stage
            elif kind != "markdown":
                assert vf.STAGE_FILES[rel] == kind, stage


def test_bad_run_id_is_a_stage_error(project):
    with pytest.raises(runs.StageError, match="not a valid run id"):
        runs.is_complete("../etc", "intake", "done")


def test_new_run_starts_at_intake(run):
    assert set(runs.statuses(RUN).values()) == {"pending"}
    assert runs.next_stages(RUN) == ["intake"]


def test_transitions(run):
    runs.begin(RUN, "intake")
    assert runs.statuses(RUN)["intake"] == "running"
    assert runs.next_stages(RUN) == []  # wait for the running stage
    with pytest.raises(runs.StageError, match="already running"):
        runs.begin(RUN, "intake")

    with pytest.raises(runs.StageError, match="does not exist"):
        runs.finish(RUN, "intake")
    assert runs.statuses(RUN)["intake"] == "failed"
    assert runs.next_stages(RUN) == ["intake"]  # a failed stage is re-queued
    with pytest.raises(runs.StageError, match="not running"):
        runs.finish(RUN, "intake")

    runs.begin(RUN, "intake")
    write_output(run, "intake")
    runs.finish(RUN, "intake")
    r = row("intake")
    assert (r["status"], r["attempts"]) == ("done", 2)
    assert r["finished_at"] >= r["started_at"]
    with pytest.raises(runs.StageError, match="already done"):
        runs.begin(RUN, "intake")
    assert runs.next_stages(RUN) == ["plan"]


def test_begin_needs_earlier_groups_complete(run):
    with pytest.raises(runs.StageError, match="before intake complete"):
        runs.begin(RUN, "plan")
    complete(run, "intake", "plan")
    assert runs.next_stages(RUN) == RESEARCH  # the whole research group at once
    complete(run, *RESEARCH[:-1])
    with pytest.raises(runs.StageError, match=f"before {RESEARCH[-1]} complete"):
        runs.begin(RUN, "verify")
    assert runs.statuses(RUN)["verify"] == "pending"


def test_full_run_walks_every_stage(run):
    complete(run, *runs.STAGES)
    assert set(runs.statuses(RUN).values()) == {"done"}
    assert runs.next_stages(RUN) == []
    assert runs.resume(RUN) == []


def test_done_needs_a_valid_file(run):
    runs.begin(RUN, "intake")
    (run / "00_spec.json").write_text('{"idea_id": "x"}', encoding="utf-8")
    with pytest.raises(runs.StageError, match="not a valid spec"):
        runs.finish(RUN, "intake")
    assert runs.statuses(RUN)["intake"] == "failed"

    runs.begin(RUN, "intake")
    write_output(run, "intake")
    runs.finish(RUN, "intake")
    # The table says done, but the file went bad afterwards: the stage no longer counts.
    (run / "00_spec.json").write_text("{", encoding="utf-8")
    assert not runs.is_complete(RUN, "intake")
    assert runs.next_stages(RUN) == ["intake"]
    with pytest.raises(runs.StageError, match="before intake complete"):
        runs.begin(RUN, "plan")


def test_synthesize_needs_both_files(run):
    complete(run, "intake", "plan", *RESEARCH, "verify")
    runs.begin(RUN, "synthesize")
    shutil.copy(FIXTURES / "scores_proposed.json", run / "04_scores_proposed.json")
    with pytest.raises(runs.StageError, match="04_risks.json does not exist"):
        runs.finish(RUN, "synthesize")


def test_blank_report_is_not_done(run):
    complete(run, *runs.STAGES[:-1])
    runs.begin(RUN, "report")
    (run / "05_report.md").write_text("  \n", encoding="utf-8")
    with pytest.raises(runs.StageError, match="is empty"):
        runs.finish(RUN, "report")


def test_insufficient_data_completes_a_research_stage_without_a_file(run):
    complete(run, "intake", "plan", *RESEARCH[1:])
    runs.begin(RUN, RESEARCH[0])
    runs.mark_insufficient(RUN, RESEARCH[0])
    assert runs.next_stages(RUN) == ["verify"]
    with pytest.raises(runs.StageError, match="already insufficient_data"):
        runs.begin(RUN, RESEARCH[0])
    with pytest.raises(runs.StageError, match="only a research stage"):
        runs.mark_insufficient(RUN, "verify")
    assert runs.resume(RUN) == []  # insufficient_data needs no file and is never reset


def test_resume_resets_crashed_and_broken_stages(run):
    complete(run, "intake", "plan")
    runs.begin(RUN, "research:market")  # crashed before writing anything
    runs.begin(RUN, "research:pricing")  # the agent wrote a valid file; --finish never ran
    write_output(run, "research:pricing")
    runs.begin(RUN, "research:gtm")
    with pytest.raises(runs.StageError):
        runs.finish(RUN, "research:gtm")
    (run / "01_plan.json").unlink()  # a done stage whose output disappeared

    changes = runs.resume(RUN)
    assert changes == [
        ("plan", "done", "pending"),
        ("research:market", "running", "pending"),
        ("research:pricing", "running", "done"),
    ]
    assert runs.statuses(RUN)["research:gtm"] == "failed"  # failed stays failed
    assert row("research:market")["attempts"] == 1
    assert runs.next_stages(RUN) == ["plan"]
    assert runs.resume(RUN) == []  # idempotent


def test_mid_stage2_crash_resume_requeues_only_unfinished_dimensions(run):
    """IF-507: the session died during stage 2. Some dimensions finished, one was half-written,
    several were still running without output, one had been marked insufficient_data."""
    complete(run, "intake", "plan")
    finished = RESEARCH[:5]
    complete(run, *finished)
    half_written, *unstarted = RESEARCH[5:9]
    agent_done_bookkeeping_lost = RESEARCH[9]
    gave_up = RESEARCH[10]
    for stage in RESEARCH[5:10]:
        runs.begin(RUN, stage)
    synthetic_research(run, half_written.split(":", 1)[1], complete=False)
    write_output(run, agent_done_bookkeeping_lost)
    runs.mark_insufficient(RUN, gave_up)
    assert runs.next_stages(RUN) == []  # mid-crash, everything looks busy

    runs.resume(RUN)
    status = runs.statuses(RUN)
    assert all(status[s] == "done" for s in [*finished, agent_done_bookkeeping_lost])
    assert status[gave_up] == "insufficient_data"
    assert runs.next_stages(RUN) == [half_written, *unstarted]

    complete(run, half_written, *unstarted)
    assert runs.next_stages(RUN) == ["verify"]


# ---------------------------------------------------------------- CLI


def test_cli_begin_finish_next(run, capsys):
    assert run_stage.main([RUN, "--next"]) == 0
    assert capsys.readouterr().out == "intake\n"
    assert run_stage.main([RUN, "intake", "--begin"]) == 0
    write_output(run, "intake")
    assert run_stage.main([RUN, "intake", "--finish"]) == 0
    assert capsys.readouterr().out == "intake: running\nintake: done\n"

    assert run_stage.main([RUN, "plan", "--begin"]) == 0
    assert run_stage.main([RUN, "plan", "--finish"]) == 1
    err = capsys.readouterr().err
    assert err.startswith("error: plan failed") and "01_plan.json does not exist" in err

    assert run_stage.main([RUN, "verify", "--begin"]) == 1
    assert "cannot begin before plan" in capsys.readouterr().err


def test_cli_resume_and_insufficient_data(run, capsys):
    complete(run, "intake", "plan")
    runs.begin(RUN, "research:market")
    assert run_stage.main([RUN, "--resume"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "reset: research:market: running -> pending"
    assert out[1:] == RESEARCH
    assert run_stage.main([RUN, "research:market", "--insufficient-data"]) == 0
    assert capsys.readouterr().out == "research:market: insufficient_data\n"


def test_cli_rejects_bad_input(run, capsys):
    assert run_stage.main([RUN, "research:nope", "--begin"]) == 1
    assert "unknown stage" in capsys.readouterr().err
    assert run_stage.main(["20261023-120000-missing", "--next"]) == 1
    assert "unknown run" in capsys.readouterr().err
    assert run_stage.main(["not a run id", "--next"]) == 1
    with pytest.raises(SystemExit):
        run_stage.main([RUN, "--begin"])
    with pytest.raises(SystemExit):
        run_stage.main([RUN, "intake", "--next"])
    with pytest.raises(SystemExit):
        run_stage.main([RUN, "intake"])
