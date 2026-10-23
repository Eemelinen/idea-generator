import math

import pytest
from pydantic import ValidationError

from ideaforge import config
from ideaforge.schemas import RUBRIC_DIMENSIONS


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


def test_official_domains_include_core_sources():
    official = set(config.domains().official)
    assert {"vero.fi", "prh.fi", "finlex.fi", "stat.fi", "raakkyla.fi"} <= official
