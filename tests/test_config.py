import math
import re

import pytest
from pydantic import ValidationError

from ideaforge import config
from ideaforge.schemas import RUBRIC_DIMENSIONS, BaseLocation, IdeaSpec, Intake


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


def test_founder_scope_is_the_schema_default():
    """IF-701: the founder's scope is what a spec or intake without one (every run made before
    D-009) loads as, so the default behaviour is the same whichever path a run takes."""
    founder = config.founder()
    for model in (IdeaSpec, Intake):
        fields = model.model_fields
        assert founder.geography == fields["geography"].default
        assert founder.business_mode == fields["business_mode"].default == "local"
        assert founder.base_location == fields["base_location"].get_default(call_default_factory=True)
    assert "geography_ladder" not in config.finland()


def test_base_location_rejects_bad_codes_and_domains():
    base = config.founder().base_location.model_dump()
    for bad in ({"municipality_code": "707"}, {"region_code": "Pohjois-Karjala"},
                {"official_domains": ["https://raakkyla.fi/"]}, {"leader_group": {"name": "", "domain": "jetina.fi"}}):
        with pytest.raises(ValidationError):
            BaseLocation.model_validate(base | bad)
    # a Leader group left blank (as the settings form posts it) is none
    assert BaseLocation.model_validate(base | {"leader_group": {"name": " ", "domain": ""}}).leader_group is None


def test_official_domains_include_core_sources():
    official = set(config.domains().official)
    assert {"vero.fi", "prh.fi", "finlex.fi", "stat.fi"} <= official


def _default_place_terms() -> list[str]:
    """The founder default's place names, codes and domains, plus the sub-region and the Finnish
    region name the rubric used to name."""
    base = config.founder().base_location
    leader = [base.leader_group.name] if base.leader_group else []
    codes = [c for c in (base.municipality_code, base.region_code) if c]
    return [base.municipality, base.region, *base.nearby, *codes, *leader, *base.official_sources(),
            "Keski-Karjala", "Pohjois-Karjala", "Rääkkylä", "raakkyla", "jetina", "luotsi"]  # fmt: skip


def test_place_domains_are_run_level_not_global():
    """IF-703: the base's own sites are official for its runs only (the founder default lists
    them), never on the global allow-list or a preferred list."""
    domains = config.domains()
    run_level = config.founder().base_location.official_sources()
    assert run_level == ["raakkyla.fi", "luotsipohjoiskarjala.fi", "jetina.fi"]
    listed = [*domains.official, *(d for ds in domains.preferred.values() for d in ds)]
    assert not set(run_level) & set(listed)
    assert "pohjois-karjala.fi" not in listed


def test_rubric_names_no_place():
    """IF-703: the rubric refers to the spec's base and target markets, never to a fixed place."""
    text = (config.CONFIG_DIR / "rubric.yaml").read_text(encoding="utf-8")
    rubric = config.rubric()
    names = [d.name for d in rubric.dimensions]
    for term in _default_place_terms():
        assert term.casefold() not in text.casefold(), term
    assert rubric.dimension("location").name == "Location fit"
    assert len(set(names)) == len(names)


def test_rubric_mode_questions():
    """IF-703: mode-specific questions carry a "Local or hybrid:" / "Online or hybrid:" prefix;
    location has both kinds, and regulation, gtm and unit economics get online questions."""
    rubric = config.rubric()
    prefixes = ("Local or hybrid: ", "Online or hybrid: ")
    for dim in rubric.dimensions:
        for q in dim.research_questions:
            if q.startswith(("Local", "Online")):
                assert q.startswith(prefixes), q
    location = rubric.dimension("location").research_questions
    assert all(q.startswith(prefixes) for q in location)
    assert {q.split(":")[0] for q in location} == {"Local or hybrid", "Online or hybrid"}
    for dim_id in ("regulation", "gtm", "unit_economics"):
        assert any(q.startswith(prefixes[1]) for q in rubric.dimension(dim_id).research_questions), dim_id
    regulation = " ".join(rubric.dimension("regulation").research_questions)
    assert "distance-selling" in regulation and "OSS" in regulation


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
