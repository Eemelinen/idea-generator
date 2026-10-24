import math
import re

import pytest
from pydantic import ValidationError

from ideaforge import config
from ideaforge.schemas import RUBRIC_DIMENSIONS, IdeaSpec


def test_all_configs_load():
    config.load_all()


def test_models_default_to_opus():
    assert set(config.models().roles.values()) == {"opus"}


def test_rubric_weights_sum_to_one():
    dims = config.rubric().dimensions
    assert sorted(d.id for d in dims) == sorted(RUBRIC_DIMENSIONS)
    assert math.isclose(sum(d.weight for d in dims), 1.0)


def test_rubric_rejects_bad_weights():
    data = config.load_yaml("rubric.yaml")
    data["dimensions"][0]["weight"] += 0.05
    with pytest.raises(ValidationError, match="sum to 1.0"):
        config.RubricConfig.model_validate(data)


def test_budget_presets():
    budget = config.budget()
    assert set(budget.presets) == {"economy", "standard", "deep"}
    std = budget.preset()
    assert std.research_subagent.max_web_searches == 8
    assert std.debate.max_rounds == 3


def test_finland_hints_are_flagged_for_verification():
    hints = config.finland()["hints"]
    assert hints
    for name, hint in hints.items():
        assert hint.get("verify_at_runtime") is True, name
        assert str(hint.get("verify_url", "")).startswith("https://"), name


def test_founder_constraints_are_confirmed():
    """IF-150: the founder constraints are the user's answers, not placeholders."""
    founder = config.founder()
    assert founder.confirmed is True
    assert founder.skills


def test_report_language_is_set():
    """IF-150: the report and the business-plan draft each have a language."""
    report = config.report()
    assert report.language in {"en", "fi"}
    assert report.business_plan_language in {"en", "fi"}


def test_report_language_rejects_unknown():
    with pytest.raises(ValidationError):
        config.ReportConfig.model_validate({"language": "sv", "business_plan_language": "fi"})


def test_geography_ladder_is_the_same_everywhere():
    """IF-150: the user's ladder is the spec default and what the research agents and /validate use."""
    ladder = config.finland()["geography_ladder"]
    assert IdeaSpec.model_fields["geography"].default == ladder
    assert " → ".join(ladder) in (config.PROMPTS_DIR / "research_base.md").read_text(encoding="utf-8")
    skill = (config.ROOT / ".claude" / "skills" / "validate" / "SKILL.md").read_text(encoding="utf-8")
    assert "[" + ", ".join(f'"{step}"' for step in ladder) + "]" in skill


def test_official_domains_include_core_sources():
    official = set(config.domains().official)
    assert {"vero.fi", "prh.fi", "finlex.fi", "stat.fi", "raakkyla.fi"} <= official


def test_readme_usage_section_matches_config():
    """IF-508: the README's preset table and downgrade order are what config/ says."""
    readme = (config.ROOT / "README.md").read_text(encoding="utf-8")
    section = readme.split("## Usage limits, presets and model downgrades", 1)[1].split("\n## ", 1)[0]
    budget = config.budget()
    rows = re.findall(r"^\s*\| `(\w+)`\s*\|(.+)\|\s*$", section, re.MULTILINE)
    assert [name for name, _ in rows] == list(budget.presets)
    for name, cells in rows:
        p = budget.preset(name)
        r, k = p.research_subagent, p.killcause_scout
        expected = [
            f"{r.max_web_searches} / {r.max_web_fetches}", str(r.max_output_words),
            f"{k.max_web_searches} / {k.max_web_fetches}", str(p.debate.max_rounds), str(p.debate.max_mini_research_tasks),
        ]
        assert [c.strip() for c in cells.split("|")] == expected, name
    assert f"the default is `{budget.default_preset}`" in section
    order = re.search(r"Downgrade order[^:]*: ([\w →]+)\.", config.models().notes).group(1).split(" → ")
    positions = [section.find(f"`{role}`") for role in order]
    assert -1 not in positions and positions == sorted(positions), order
    for item in ("/usage", "gen_agents.py", "/eval --limit 3", "/status --diff", "Fable", "50 %", "/model"):
        assert item in section, item
