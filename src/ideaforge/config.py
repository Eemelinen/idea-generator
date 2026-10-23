"""Project paths and validated access to config/*.yaml."""

from __future__ import annotations

import math
import os
from functools import cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ideaforge.schemas import RUBRIC_DIMENSIONS, Goal


def _find_root() -> Path:
    env = os.environ.get("IDEAFORGE_ROOT")
    if env:
        return Path(env).resolve()
    # src/ideaforge/config.py → repo root
    return Path(__file__).resolve().parents[2]


ROOT = _find_root()
CONFIG_DIR = ROOT / "config"
RUNS_DIR = ROOT / "runs"
CACHE_DIR = ROOT / "cache"
AGENT_TEMPLATES_DIR = ROOT / "agent_templates"
PROMPTS_DIR = ROOT / "prompts"
AGENTS_DIR = ROOT / ".claude" / "agents"
DEV_MARKER = ROOT / ".ideaforge-dev"

ModelAlias = Literal["opus", "sonnet", "haiku"]


class _Cfg(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModelsConfig(_Cfg):
    roles: dict[
        Literal[
            "orchestrator", "research_subagent", "killcause_scout", "claim_extractor",
            "synthesizer", "debate_persona", "debate_judge",
        ],
        ModelAlias,
    ]
    notes: str = ""


class ResearchBudget(_Cfg):
    max_web_searches: int = Field(gt=0)
    max_web_fetches: int = Field(gt=0)
    max_output_words: int = Field(default=1200, gt=0)


class DebateBudget(_Cfg):
    max_rounds: int = Field(ge=1, le=3)
    max_mini_research_tasks: int = Field(ge=0)
    convergence_score_delta: float = Field(gt=0)


class BudgetPreset(_Cfg):
    research_subagent: ResearchBudget
    killcause_scout: ResearchBudget
    debate: DebateBudget


class BudgetConfig(_Cfg):
    default_preset: str
    presets: dict[str, BudgetPreset]

    @model_validator(mode="after")
    def _default_exists(self) -> BudgetConfig:
        if self.default_preset not in self.presets:
            raise ValueError(f"default_preset {self.default_preset!r} is not defined")
        return self

    def preset(self, name: str | None = None) -> BudgetPreset:
        return self.presets[name or self.default_preset]


class EvidenceRule(BaseModel):
    model_config = ConfigDict(extra="allow")
    rule: Literal["min_sources", "has_official_source", "has_numeric"]


class RubricDimensionCfg(_Cfg):
    id: Literal[
        "customer", "market", "competition", "pricing", "unit_economics",
        "gtm", "regulation", "financing", "location", "founder_risk",
    ]
    name: str
    weight: float = Field(gt=0, le=1)
    research_questions: list[str] = Field(min_length=3, max_length=6)
    min_evidence_for_3: str
    evidence_rule: list[EvidenceRule]
    kill_triggers: list[str] = []
    preferred_domains: list[str] = []


class VerdictThresholds(_Cfg):
    go: float
    pivot: float
    max_insufficient_dimensions: int


class KillcauseCfg(_Cfg):
    research_questions: list[str]
    kill_triggers: list[str]


class RubricConfig(_Cfg):
    verdict_thresholds: VerdictThresholds
    dimensions: list[RubricDimensionCfg]
    killcause: KillcauseCfg

    @model_validator(mode="after")
    def _check(self) -> RubricConfig:
        ids = [d.id for d in self.dimensions]
        if sorted(ids) != sorted(RUBRIC_DIMENSIONS):
            raise ValueError(f"rubric must define exactly the dimensions {RUBRIC_DIMENSIONS}")
        total = sum(d.weight for d in self.dimensions)
        if not math.isclose(total, 1.0, abs_tol=1e-9):
            raise ValueError(f"rubric weights must sum to 1.0, got {total}")
        if not self.verdict_thresholds.pivot < self.verdict_thresholds.go:
            raise ValueError("verdict_thresholds.pivot must be below go")
        return self

    def dimension(self, dim_id: str) -> RubricDimensionCfg:
        return next(d for d in self.dimensions if d.id == dim_id)


class DomainsConfig(_Cfg):
    official: list[str]
    preferred: dict[str, list[str]]


class FounderConfig(_Cfg):
    confirmed: bool
    hours_per_week: float
    capital_eur: float
    skills: list[str]
    goal: Goal


def load_yaml(name: str) -> Any:
    with open(CONFIG_DIR / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


@cache
def models() -> ModelsConfig:
    return ModelsConfig.model_validate(load_yaml("models.yaml"))


@cache
def budget() -> BudgetConfig:
    return BudgetConfig.model_validate(load_yaml("budget.yaml"))


@cache
def rubric() -> RubricConfig:
    return RubricConfig.model_validate(load_yaml("rubric.yaml"))


@cache
def domains() -> DomainsConfig:
    return DomainsConfig.model_validate(load_yaml("domains.yaml"))


@cache
def founder() -> FounderConfig:
    return FounderConfig.model_validate(load_yaml("founder.yaml"))


@cache
def finland() -> dict[str, Any]:
    # Free-form hints; only the verify flags are enforced (see tests/test_config.py).
    return load_yaml("finland.yaml")


def load_all() -> None:
    """Validate every config file; raises on the first invalid one."""
    models(), budget(), rubric(), domains(), founder(), finland()
