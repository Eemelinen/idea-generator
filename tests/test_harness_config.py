"""The loop driver's models (harness.config.json) must match config/models.yaml (non-negotiable 2)."""

import json

from conftest import REPO
from ideaforge import config


def test_driver_models_match_models_yaml():
    harness = json.loads((REPO / "harness.config.json").read_text(encoding="utf-8"))
    roles = config.models().roles
    assert harness["generator"]["model"] == roles["harness_generator"]
    assert harness["evaluator"]["model"] == roles["harness_evaluator"]
