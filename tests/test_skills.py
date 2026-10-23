"""Static consistency of the pipeline skills (IF-206) with the agent registry and the scripts.

The skills are prompts, so nothing here runs them. The tests check that every agent, stage,
script and module they name exists, that every command they cite is allowed by the pipeline
guard and their own allowed-tools, and that each stage is wrapped in run_stage.py.
"""

import importlib.util
import re
from pathlib import Path

import pytest
import yaml

from ideaforge import agents, config, guard, runs, validate_file

ROOT = config.ROOT  # captured before the project fixture repoints config.ROOT
SKILLS_DIR = ROOT / ".claude" / "skills"
SKILLS = sorted(p.parent.name for p in SKILLS_DIR.glob("*/SKILL.md"))
RESEARCH_AGENTS = [a for a in agents.AGENTS.values() if a.kind == "research"]

# Placeholders the skills use in commands → a value the guard and the stage table accept.
PLACEHOLDERS = {
    "<run_id>": "20261023-120000-sauna-cabins",
    "<dim>": "market",
    "<stage>": "plan",
    "<idea text>": "sauna cabins by the lake",
    "<name>": "economy",
}
STAGE_SECTIONS = {  # validate skill heading → the stage(s) it must wrap
    "Stage 0 — Intake": "intake",
    "Stage 1 — Research plan": "plan",
    "Stage 2 — Parallel research": "research:<dim>",
    "Stage 3 — Claim verification": "verify",
}
CODE_SPAN_RE = re.compile(r"`([^`\n]+)`")
RUN_STAGE_RE = re.compile(r"run_stage\.py <run_id> (\S+) --(begin|finish|insufficient-data)")


def read(skill: str) -> str:
    return (SKILLS_DIR / skill / "SKILL.md").read_text(encoding="utf-8")


def split(skill: str) -> tuple[dict, str]:
    text = read(skill)
    assert text.startswith("---\n"), f"{skill}: no frontmatter"
    front, body = text[4:].split("\n---\n", 1)
    return yaml.safe_load(front), body


def sections(body: str) -> dict[str, str]:
    parts = re.split(r"^## (.+)$", body, flags=re.MULTILINE)
    return {title.strip(): text for title, text in zip(parts[1::2], parts[2::2], strict=True)}


def commands(text: str) -> list[str]:
    """The shell commands a skill cites: code spans that start with `uv run`."""
    return [c for c in CODE_SPAN_RE.findall(text) if c.startswith("uv run")]


def fill(command: str) -> str:
    for k, v in PLACEHOLDERS.items():
        command = command.replace(k, v)
    return command


def test_pipeline_skills_exist():
    assert {"validate", "research", "status", "synthesize"} <= set(SKILLS)


@pytest.mark.parametrize("skill", SKILLS)
def test_frontmatter(skill):
    front, _ = split(skill)
    assert front["name"] == skill
    assert front["description"].strip()
    assert isinstance(front.get("allowed-tools"), str)


def test_validate_names_every_research_agent():
    text = read("validate")
    assert len(RESEARCH_AGENTS) == 11
    for spec in RESEARCH_AGENTS:
        assert f"`{spec.name}`" in text, spec.name
        assert f"`research:{spec.dimension}`" in text, spec.dimension
        assert f"02_research/{spec.dimension}.md" in text, spec.dimension


def test_validate_agent_table_matches_registry():
    rows = re.findall(r"^\| `(\w+)`\s*\| `([\w-]+)`\s*\| `([\w:]+)`\s*\|", read("validate"), re.MULTILINE)
    assert len(rows) == len(RESEARCH_AGENTS)
    for dim, name, stage in rows:
        spec = agents.research_agent(dim)
        assert spec is not None and spec.name == name, dim
        assert stage == f"research:{dim}" and stage in runs.STAGES


@pytest.mark.parametrize("skill", SKILLS)
def test_cited_scripts_and_modules_exist(skill):
    text = read(skill)
    for script in set(re.findall(r"scripts/([\w-]+\.py)", text)):
        assert (ROOT / "scripts" / script).is_file(), f"{skill} cites missing scripts/{script}"
    for module in set(re.findall(r"python -m (ideaforge(?:\.\w+)*)", text)):
        assert importlib.util.find_spec(module) is not None, f"{skill} cites missing module {module}"
    for path in set(re.findall(r"`((?:config|prompts|src/ideaforge|\.claude/skills)/[\w./-]+)`", text)):
        assert (ROOT / path).exists(), f"{skill} cites missing {path}"


@pytest.mark.parametrize("skill", SKILLS)
def test_commands_pass_the_guard_and_allowed_tools(skill, project):
    front, body = split(skill)
    allowed = re.findall(r"Bash\(([^)]*)\)", front["allowed-tools"])
    for pattern in allowed:
        for script in re.findall(r"scripts/([\w-]+\.py)", pattern):
            assert (ROOT / "scripts" / script).is_file(), pattern
    cited = commands(body)
    if skill in ("validate", "research", "synthesize"):
        assert cited
    for command in cited:
        filled = fill(command)
        assert "<" not in filled and ">" not in filled, f"unknown placeholder in {command!r}"
        # Strict mode for the main session: the project fixture removes the dev marker.
        assert guard.check_bash({"tool_input": {"command": filled}}) is None, command
        assert any(filled.startswith(p.rstrip("*")) for p in allowed), f"{command!r} not in allowed-tools"


@pytest.mark.parametrize("skill", SKILLS)
def test_cited_flags_and_kinds_exist(skill):
    """A renamed flag or validator kind would leave the skill calling something that is gone."""
    for command in commands(read(skill)):
        script = re.search(r"scripts/([\w-]+\.py)", command)
        module = re.search(r"python -m (ideaforge(?:\.\w+)*)", command)
        if script:
            source = (ROOT / "scripts" / script.group(1)).read_text(encoding="utf-8")
        else:
            assert module, command
            source = Path(importlib.util.find_spec(module.group(1)).origin).read_text(encoding="utf-8")
        for flag in re.findall(r"(?<!\S)(--[a-z][\w-]*)", command):
            assert f'"{flag}"' in source or f"'{flag}'" in source, (
                f"{skill}: {command!r} uses {flag}, which the script does not define"
            )
        for kind in re.findall(r"--kind (\w+)", command):
            assert kind in validate_file.KINDS, f"{skill}: unknown validator kind {kind}"


@pytest.mark.parametrize("skill", SKILLS)
def test_run_stage_calls_name_real_stages(skill):
    for stage, _ in RUN_STAGE_RE.findall(read(skill)):
        assert fill(stage) in runs.STAGES, f"{skill}: unknown stage {stage}"


def test_each_validate_stage_is_wrapped_in_run_stage():
    _, body = split("validate")
    by_title = sections(body)
    assert set(STAGE_SECTIONS) <= set(by_title)
    for title, stage in STAGE_SECTIONS.items():
        text = by_title[title]
        begin = text.find(f"run_stage.py <run_id> {stage} --begin")
        finish = text.find(f"run_stage.py <run_id> {stage} --finish")
        assert 0 <= begin < finish, f"{title}: {stage} not wrapped in --begin/--finish"
        assert "usage_report.py <run_id>" in text[finish:], f"{title}: no usage report after the stage"
    # Each stage's file is validated with validate_file before the stage is finished.
    for title, kind in (
        ("Stage 0 — Intake", "spec"),
        ("Stage 1 — Research plan", "plan"),
        ("Stage 3 — Claim verification", "claims"),
    ):
        text = by_title[title]
        check, finish = text.find(f"validate_file --kind {kind}"), text.find("--finish")
        assert 0 <= check < finish, f"{title}: no validate_file --kind {kind} before --finish"


def test_validate_stage0_intake_rules():
    text = sections(split("validate")[1])["Stage 0 — Intake"]
    assert "AskUserQuestion" in text and "at most 5" in text
    assert "config/founder.yaml" in text
    assert "00_spec.json" in text


def test_validate_stage1_plan_has_killcause_and_local_questions():
    text = sections(split("validate")[1])["Stage 1 — Research plan"]
    assert "01_plan.json" in text and "config/rubric.yaml" in text
    assert "killcause" in text and "Finland/Rääkkylä" in text
    assert "just run it" in text


def test_validate_stage2_launch_retry_and_markers():
    text = sections(split("validate")[1])["Stage 2 — Parallel research"]
    assert "in one message" in text
    assert "Re-launch it once" in text
    assert "research:<dim> --insufficient-data" in text
    for marker in ("VALIDATION_FAILED_", "VALIDATION_WARNINGS_", "BUDGET_EXCEEDED_"):
        assert marker in text, marker
    assert "Skip every dimension" in text and "--next" in text
    for item in ("run_id", "00_spec.json", "01_plan.json", "budget", "preferred domains", "output path"):
        assert item in text, item


def test_validate_stage3_runs_the_verifier():
    text = sections(split("validate")[1])["Stage 3 — Claim verification"]
    assert "verify_claims.py <run_id>" in text
    assert text.find("verify --begin") < text.find("verify_claims.py") < text.find("verify --finish")


def test_validate_resumes_an_existing_run():
    text = read("validate")
    assert "new_run.py" in text
    assert "run_stage.py <run_id> --resume" in text


def test_research_skill_reuses_validate_stages_1_to_3():
    _, body = split("research")
    assert "new_run.py" not in body and "intake --begin" not in body
    assert "run_stage.py <run_id> --resume" in body
    assert ".claude/skills/validate/SKILL.md" in body
    referenced = re.findall(r"\*\*((?:Stage \d — [^*]+)|End)\*\*", body)
    stages = [r for r in referenced if r != "End"]
    assert stages == ["Stage 1 — Research plan", "Stage 2 — Parallel research", "Stage 3 — Claim verification"]
    assert "End" in referenced
    assert set(referenced) <= set(sections(split("validate")[1]))
    for marker in ("VALIDATION_FAILED_", "BUDGET_EXCEEDED_", "usage_report.py"):
        assert marker in body, marker


# ---------------------------------------------------------------- synthesize (IF-304)

SYNTHESIZE_SECTIONS = {  # synthesize skill heading → (stage, validator kinds checked before --finish)
    "Stage 5a — Synthesis": ("synthesize", ("scores_proposed", "risks")),
    "Stage 5b — Scoring": ("score", ("scores",)),
}
# What the synthesizer may see: the input file synthesis_input.py writes (spec, verified and
# conflict claims, rubric) and the two files it writes. Anything else is a leak.
SYNTHESIZER_PATHS = {
    f"runs/<run_id>/{agents.SYNTHESIS_INPUT}",
    *(f"runs/<run_id>/{name}" for name in agents.SYNTHESIS_OUTPUTS),
}
FORBIDDEN_INPUTS = ("02_research", "03_claims", "verified.json", "idea.md", "01_plan.json", "usage.jsonl")


def test_synthesize_stages_are_wrapped_in_run_stage():
    by_title = sections(split("synthesize")[1])
    assert set(SYNTHESIZE_SECTIONS) <= set(by_title)
    for title, (stage, kinds) in SYNTHESIZE_SECTIONS.items():
        text = by_title[title]
        begin = text.find(f"run_stage.py <run_id> {stage} --begin")
        finish = text.find(f"run_stage.py <run_id> {stage} --finish")
        assert 0 <= begin < finish, f"{title}: {stage} not wrapped in --begin/--finish"
        assert "usage_report.py <run_id>" in text[finish:], f"{title}: no usage report after the stage"
        for kind in kinds:
            check = text.find(f"validate_file --kind {kind}")
            assert begin < check < finish, f"{title}: no validate_file --kind {kind} before --finish"
    scoring = by_title["Stage 5b — Scoring"]
    assert scoring.find("score --begin") < scoring.find("score_run.py <run_id>") < scoring.find("score --finish")


def test_synthesize_launches_the_registered_synthesizer_with_only_the_allowed_input():
    text = sections(split("synthesize")[1])["Stage 5a — Synthesis"]
    spec = agents.get("synthesizer")
    assert spec is not None and spec.kind == "synthesizer" and spec.role == "synthesizer"
    assert "subagent_type: synthesizer" in text
    # the input file is written before the launch, and is the only input the brief names
    assert text.find("synthesis_input.py <run_id>") < text.find("subagent_type: synthesizer")
    brief = text[text.find("The brief contains exactly") : text.find("validate_file")]
    assert set(re.findall(r"runs/<run_id>/[\w./-]+", brief)) == SYNTHESIZER_PATHS
    assert "read no other file" in brief and "write no other file" in brief


@pytest.mark.parametrize("path", [SKILLS_DIR / "synthesize" / "SKILL.md", config.PROMPTS_DIR / "synthesizer.md"])
def test_synthesizer_never_sees_research_or_unfiltered_claims(path):
    text = path.read_text(encoding="utf-8")
    for forbidden in FORBIDDEN_INPUTS:
        assert forbidden not in text, f"{path.name} names {forbidden}"


def test_synthesizer_prompt_reads_one_file_and_writes_two():
    text = (config.PROMPTS_DIR / "synthesizer.md").read_text(encoding="utf-8")
    assert set(re.findall(r"runs/<run_id>/[\w./-]+", text)) == SYNTHESIZER_PATHS
    assert "Read **only** `runs/<run_id>/04_synthesis_input.json`" in text
    for rule in ("cites at least one claim id", "no verified evidence", "Never introduce facts"):
        assert rule in text, rule
    agent = (config.AGENTS_DIR / "synthesizer.md").read_text(encoding="utf-8")
    front = yaml.safe_load(agent.split("---\n")[1])
    assert front["tools"] == "Read, Write"
    assert front["model"] == config.models().roles["synthesizer"]


def test_validate_points_to_synthesize():
    end = sections(split("validate")[1])["End"]
    assert "/synthesize <run_id>" in end
