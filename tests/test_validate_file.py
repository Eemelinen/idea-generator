import shutil

import pytest

from conftest import FIXTURES
from ideaforge import validate_file as vf

RESEARCH_FIXTURE = FIXTURES / "02_research" / "pricing.md"


def research_file(tmp_path, text=None):
    path = tmp_path / "02_research" / "pricing.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text is not None else RESEARCH_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def test_research_fixture_is_valid():
    claims = vf.validate_research(RESEARCH_FIXTURE)
    assert [c.claim_id for c in claims] == ["pricing-001"]


def test_research_missing_sections(tmp_path):
    text = RESEARCH_FIXTURE.read_text(encoding="utf-8").replace("## Gaps", "## Other")
    with pytest.raises(vf.Invalid, match="Gaps"):
        vf.validate_research(research_file(tmp_path, text))


def test_research_bad_json(tmp_path):
    text = RESEARCH_FIXTURE.read_text(encoding="utf-8").replace('"flags": []', '"flags": [],')
    with pytest.raises(vf.Invalid, match="does not parse"):
        vf.validate_research(research_file(tmp_path, text))


def test_research_wrong_dimension(tmp_path):
    text = RESEARCH_FIXTURE.read_text(encoding="utf-8").replace('"dimension": "pricing"', '"dimension": "market"')
    with pytest.raises(vf.Invalid):
        vf.validate_research(research_file(tmp_path, text))


def test_research_word_limit(tmp_path):
    with pytest.raises(vf.Invalid, match="words"):
        vf.validate_research(research_file(tmp_path), max_words=20)


def test_research_requires_claim_blocks(tmp_path):
    text = "# pricing\n\n## Candidate claims\n\nnone\n\n## Gaps\n\n- everything\n"
    with pytest.raises(vf.Invalid, match="no ```json"):
        vf.validate_research(research_file(tmp_path, text))


@pytest.mark.parametrize("rel,kind", [
    ("runs/r/00_spec.json", "spec"),
    ("runs/r/01_plan.json", "plan"),
    ("runs/r/02_research/gtm.md", "research"),
    ("runs/r/03_claims/gtm.json", "claims"),
    ("runs/r/03_claims/verified.json", "claims"),
    ("runs/r/04_scores_proposed.json", "scores_proposed"),
    ("runs/r/debate/round0/investor.json", "position"),
    ("runs/r/debate/round2/investor.json", "rebuttal"),
    ("runs/r/debate/verdict.json", "verdict"),
])
def test_infer_kind(rel, kind, tmp_path):
    assert vf.infer_kind(tmp_path / rel) == kind


def test_cli_validates_json(tmp_path):
    target = tmp_path / "runs" / "r" / "00_spec.json"
    target.parent.mkdir(parents=True)
    shutil.copy(FIXTURES / "spec.json", target)
    assert vf.main([str(target)]) == 0
    target.write_text('{"title": "x"}', encoding="utf-8")
    assert vf.main([str(target)]) == 1


# ---------------------------------------------------------------- hook mode


def test_auto_without_active_run_is_noop(project):
    assert vf.auto({"agent_type": "research-pricing"}, stop=False) == 0


def test_auto_ignores_unknown_agents(active_run):
    assert vf.auto({"agent_type": "general-purpose"}, stop=False) == 0


def test_auto_ignores_the_harness_evaluator(active_run):
    assert vf.auto({"agent_id": "e", "agent_type": "evaluator"}, stop=False) == 0
    assert not list(active_run.glob("VALIDATION_FAILED_*"))


def test_auto_blocks_once_then_records_failure(active_run):
    hook = {"agent_id": "a", "agent_type": "research-pricing"}
    with pytest.raises(SystemExit) as exc:
        vf.auto(hook, stop=False)
    assert exc.value.code == 2

    assert vf.auto(hook | {"stop_hook_active": True}, stop=False) == 0
    marker = active_run / "VALIDATION_FAILED_research-pricing"
    assert "does not exist" in marker.read_text(encoding="utf-8")

    shutil.copy(RESEARCH_FIXTURE, active_run / "02_research" / "pricing.md")
    assert vf.auto(hook, stop=False) == 0
    assert not marker.exists()


def test_auto_debate_agent_validates_latest_round(active_run):
    hook = {"agent_id": "a", "agent_type": "debate-investor"}
    with pytest.raises(SystemExit):
        vf.auto(hook, stop=False)  # nothing written yet
    (active_run / "debate" / "round0").mkdir()
    shutil.copy(FIXTURES / "position.json", active_run / "debate" / "round0" / "investor.json")
    assert vf.auto(hook, stop=False) == 0
    (active_run / "debate" / "round1").mkdir()
    (active_run / "debate" / "round1" / "investor.json").write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit):
        vf.auto(hook, stop=False)


def test_auto_stop_validates_existing_stage_files(active_run):
    assert vf.auto({}, stop=True) == 0
    (active_run / "00_spec.json").write_text('{"title": "only"}', encoding="utf-8")
    with pytest.raises(SystemExit):
        vf.auto({}, stop=True)
    shutil.copy(FIXTURES / "spec.json", active_run / "00_spec.json")
    assert vf.auto({}, stop=True) == 0
