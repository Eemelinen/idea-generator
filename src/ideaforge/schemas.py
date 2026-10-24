"""Pydantic models for every structured file the pipeline reads or writes.

All models forbid extra fields: a model that invents a key fails validation loudly.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

RUBRIC_DIMENSIONS = (
    "customer",
    "market",
    "competition",
    "pricing",
    "unit_economics",
    "gtm",
    "regulation",
    "financing",
    "location",
    "founder_risk",
)
# Scored rubric dimensions plus the unscored kill-cause research task.
RESEARCH_DIMENSIONS = (*RUBRIC_DIMENSIONS, "killcause")

KILL_TRIGGERS = (
    "free_good_enough_substitute",
    "permit_impossible",
    "negative_contribution_margin",
    "beachhead_below_founder_income",
    "no_evidence_anyone_pays",
)
# Non-trigger flags set by verification.
SYSTEM_FLAGS = ("unfetchable", "robots_disallowed", "after_as_of", "api_mismatch")

PERSONAS = ("founder", "investor", "customer", "accountant", "operator")

RubricDimension = Literal[
    "customer", "market", "competition", "pricing", "unit_economics",
    "gtm", "regulation", "financing", "location", "founder_risk",
]
Dimension = Literal[
    "customer", "market", "competition", "pricing", "unit_economics",
    "gtm", "regulation", "financing", "location", "founder_risk", "killcause",
]
KillTrigger = Literal[
    "free_good_enough_substitute", "permit_impossible", "negative_contribution_margin",
    "beachhead_below_founder_income", "no_evidence_anyone_pays",
]
ClaimFlag = Literal[
    "free_good_enough_substitute", "permit_impossible", "negative_contribution_margin",
    "beachhead_below_founder_income", "no_evidence_anyone_pays",
    "unfetchable", "robots_disallowed", "after_as_of", "api_mismatch",
]
SourceType = Literal["official", "industry", "news", "forum", "vendor", "api"]
VerificationState = Literal["pending", "verified", "unverified", "conflict"]
Persona = Literal["founder", "investor", "customer", "accountant", "operator"]
Goal = Literal["side_income", "full_time", "starttiraha"]
VerdictLabel = Literal["GO", "PIVOT", "NO_GO", "INSUFFICIENT_DATA"]
# Input roles of economics.py (economics.ROLES); the synthesizer assigns claim ids to them.
EconomicsRole = Literal[
    "price", "variable_cost", "variable_cost_pct", "fixed_costs", "cac", "volume",
    "purchases_per_customer", "vat_rate",
]
# Roles whose claims are summed (economics.ADDITIVE_ROLES); every other role takes one claim.
ADDITIVE_ECONOMICS_ROLES = ("variable_cost", "variable_cost_pct", "fixed_costs")

Score = Annotated[float, Field(ge=0, le=5)]
Unit01 = Annotated[float, Field(ge=0, le=1)]

CLAIM_ID_RE = re.compile(r"^[a-z_]+-\d{3,}$")
QUOTE_MAX_WORDS = 60


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- stage 0: intake


class FounderConstraints(Strict):
    hours_per_week: Annotated[float, Field(ge=0, le=100)]
    capital_eur: Annotated[float, Field(ge=0)]
    skills: list[str] = []
    goal: Goal


class Clarification(Strict):
    question: str
    answer: str


class IdeaSpec(Strict):
    idea_id: str
    title: str
    one_liner: str
    customer: str
    problem: str
    solution: str
    revenue_model: str
    # The ladder from config/finland.yaml (IF-150; tests/test_config.py keeps them equal).
    geography: list[str] = ["Rääkkylä", "North Karelia", "Finland", "online/EU"]
    founder_constraints: FounderConstraints
    clarifications: list[Clarification] = Field(default_factory=list, max_length=5)
    # Kill triggers the user has explicitly accepted the risk of; score_run.py will not
    # force NO_GO for these.
    kill_trigger_overrides: list[KillTrigger] = []
    # Whether the business charges VAT (economics.py: net amounts if registered; the price as
    # quoted and costs grossed up if not). The founder's choice, not research, so it lives here.
    vat_registered: bool = True
    version: Annotated[int, Field(ge=1)] = 1


# ---------------------------------------------------------------- stage 1: plan


class DimensionPlan(Strict):
    dimension: Dimension
    questions: Annotated[list[str], Field(min_length=1)]
    search_strategy: str
    preferred_domains: list[str] = []
    evidence_needed: str


class ResearchPlan(Strict):
    run_id: str
    dimensions: Annotated[list[DimensionPlan], Field(min_length=1)]

    @model_validator(mode="after")
    def _unique_dimensions(self) -> ResearchPlan:
        seen = [d.dimension for d in self.dimensions]
        if len(seen) != len(set(seen)):
            raise ValueError("each dimension may appear only once in the plan")
        if "killcause" not in seen:
            raise ValueError("the plan must always include the killcause task")
        return self


# ---------------------------------------------------------------- stage 2–3: claims


class Claim(Strict):
    claim_id: str
    dimension: Dimension
    statement: str
    value: float | None = None
    unit: str | None = None
    source_url: str
    source_title: str
    quote: str
    published_date: date | None = None
    retrieved_at: datetime
    source_type: SourceType
    confidence: Unit01
    flags: list[ClaimFlag] = []
    verification: VerificationState = "pending"

    @field_validator("claim_id")
    @classmethod
    def _claim_id_format(cls, v: str) -> str:
        if not CLAIM_ID_RE.match(v):
            raise ValueError("claim_id must look like '<dimension>-NNN', e.g. 'competition-007'")
        return v

    @field_validator("quote")
    @classmethod
    def _quote_length(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("quote must not be empty")
        if len(v.split()) > QUOTE_MAX_WORDS:
            raise ValueError(f"quote must be at most {QUOTE_MAX_WORDS} words")
        return v

    @field_validator("source_url")
    @classmethod
    def _url_scheme(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("source_url must be an http(s) URL")
        return v

    @model_validator(mode="after")
    def _id_matches_dimension(self) -> Claim:
        if not self.claim_id.startswith(f"{self.dimension}-"):
            raise ValueError("claim_id prefix must equal the claim's dimension")
        return self


class ConflictGroup(Strict):
    """One entry of 03_claims/conflicts.json: claims of one dimension whose statements are similar
    but whose values differ by more than 25 % (verify.detect_conflicts, IF-210). `claim_ids` is in
    preference order, the claim to prefer first: official > api > industry > news > forum >
    vendor, then the newest."""

    dimension: Dimension
    claim_ids: Annotated[list[str], Field(min_length=2)]


class CandidateClaim(Claim):
    """A claim as written by a research subagent: verify_claims.py fills retrieved_at and verification."""

    retrieved_at: datetime | None = None
    verification: Literal["pending"] = "pending"


# ---------------------------------------------------------------- stage 5: scoring


class DimensionScore(Strict):
    dimension: RubricDimension
    proposed_score: Score
    justification: str
    supporting_claim_ids: list[str] = []
    final_score: Score | None = None
    cap_reason: str | None = None
    status: Literal["scored", "insufficient_data"] = "scored"


class ProposedScores(Strict):
    """04_scores_proposed.json, written by the synthesizer."""

    scores: list[DimensionScore]
    # Unit-economics input role → the claim ids that supply it (economics.unit_economics
    # `assignments`). Empty: economics.py picks automatically, and score_run.py then lets no
    # computed kill trigger force NO_GO (TICKETS.md plan notes 21–22).
    unit_economics_inputs: dict[EconomicsRole, list[str]] = {}

    @model_validator(mode="after")
    def _one_score_per_dimension_and_claim_per_role(self) -> ProposedScores:
        seen = [s.dimension for s in self.scores]
        if len(seen) != len(set(seen)):
            raise ValueError("each dimension may be scored only once")
        for role, ids in self.unit_economics_inputs.items():
            if role not in ADDITIVE_ECONOMICS_ROLES and len(ids) > 1:
                raise ValueError(f"unit_economics_inputs.{role} takes at most one claim id, got {len(ids)}")
        return self


class RiskItem(Strict):
    risk: str
    dimension: Dimension
    likelihood: Annotated[int, Field(ge=1, le=5)]
    impact: Annotated[int, Field(ge=1, le=5)]
    mitigation: str
    claim_ids: list[str] = []


class RiskRegister(Strict):
    """04_risks.json, written by the synthesizer."""

    risks: list[RiskItem]


class SensitivityRow(Strict):
    price_change_pct: float
    volume_change_pct: float
    monthly_profit_eur: float


class UnitEconomics(Strict):
    """Output of `economics.py`. Prices and costs are per unit sold unless the field says per month,
    after the VAT treatment `vat_registered` names (net if registered, else gross)."""

    price_eur: float | None = None
    variable_cost_eur: float | None = None
    contribution_margin_eur: float | None = None
    contribution_margin_pct: float | None = None
    fixed_costs_month_eur: float | None = None
    cac_eur: float | None = None
    volume_month: float | None = None
    purchases_per_customer_month: float | None = None
    monthly_profit_eur: float | None = None
    break_even_units_month: float | None = None
    payback_months: float | None = None
    sensitivity: list[SensitivityRow] = []
    vat_registered: bool | None = None
    vat_rate_pct: float | None = None
    missing_inputs: list[str] = []
    input_claim_ids: list[str] = []
    # The claim ids each input role used (economics.ROLES order), so every figure traces to its
    # claims (the starttiraha calculation, IF-307). Empty in score sheets written before it.
    input_claims: dict[str, list[str]] = {}
    notes: list[str] = []


class ScoreSheet(Strict):
    scores: list[DimensionScore]
    weighted_total: Score
    kill_triggers_fired: list[KillTrigger] = []
    verdict: VerdictLabel
    unit_economics: UnitEconomics


# ---------------------------------------------------------------- stage 7: debate


class Objection(Strict):
    text: str
    claim_ids: list[str] = []


class Position(Strict):
    role: Persona
    objections: list[Objection]
    proposed_change: str
    expected_score_impact: dict[RubricDimension, Annotated[float, Field(ge=-5, le=5)]] = {}
    confidence: Unit01


class Basis(Strict):
    new_claim_ids: list[str] = []
    computation: str | None = None
    evidence_gap: str | None = None

    @model_validator(mode="after")
    def _not_empty(self) -> Basis:
        if not (self.new_claim_ids or self.computation or self.evidence_gap):
            raise ValueError("basis needs new_claim_ids, a computation or an evidence_gap")
        return self


class Response(Strict):
    target_position_id: str
    stance: Literal["agree", "disagree", "modify"]
    basis: Basis
    # Claim ids from the existing ledger that back a `disagree` (no novelty required).
    cited_claim_ids: list[str] = []


class MiniResearchRequest(Strict):
    question: str
    dimension: Dimension
    requested_by: Persona


class Rebuttal(Strict):
    role: Persona
    round: Annotated[int, Field(ge=1)]
    responses: list[Response]
    updated_change: str | None = None
    updated_change_basis: Basis | None = None
    mini_research: MiniResearchRequest | None = None


class ChangeDecision(Strict):
    change: str
    claim_ids: list[str] = []
    reason: str


class Assumption(Strict):
    assumption: str
    evidence_state: Literal["supported", "contested", "untested"]
    risk_if_wrong: str


class Experiment(Strict):
    name: str
    cost_eur: Annotated[float, Field(ge=0)]
    days: Annotated[float, Field(gt=0)]
    success_threshold: Annotated[str, Field(pattern=r"\S")]
    info_value: Annotated[int, Field(ge=1, le=5)]


# Plan §11: the revised plan lists at least this many experiments.
MIN_EXPERIMENTS = 5


class Verdict(Strict):
    accepted_changes: list[ChangeDecision]
    rejected_changes: list[ChangeDecision]
    assumption_register: list[Assumption]
    experiments: Annotated[list[Experiment], Field(min_length=MIN_EXPERIMENTS)]
    projected_scores: dict[RubricDimension, Score]
    # The judge's value; `debate.finalize_verdict` computes the real one and `debate.write_verdict`
    # stores it here once the revised plan is committed.
    conformity_flag: bool = False

    @model_validator(mode="after")
    def _accepted_cite_claims(self) -> Verdict:
        for c in self.accepted_changes:
            if not c.claim_ids:
                raise ValueError(f"accepted change {c.change!r} must cite at least one claim id")
        return self


class InterimScores(Strict):
    """`debate/round<N>/interim_scores.json`: the judge's projected scores after round N, which
    the convergence check compares with the previous round's (IF-405)."""

    round: Annotated[int, Field(ge=0)]
    projected_scores: dict[RubricDimension, Score]


# ---------------------------------------------------------------- run metadata


class RunMeta(Strict):
    """`runs/<run_id>/meta.json`, written by `ideaforge.meta` (plan §6 stage 6)."""

    run_id: str
    idea_id: str | None = None
    version: Annotated[int, Field(ge=1)] = 1
    parent_run_id: str | None = None
    created_at: datetime
    updated_at: datetime | None = None  # last stage transition
    git_commit: str | None = None  # repository HEAD
    config_commit: str | None = None  # last commit touching config/, prompts/, agent_templates/
    config_dirty: bool | None = None  # uncommitted changes there at creation
    claude_code_version: str | None = None
    models: dict[str, str]  # config/models.yaml roles at creation
    budget_preset: str
    as_of: date | None = None

    @model_validator(mode="after")
    def _version_has_parent(self) -> RunMeta:
        # A parent with version 1 is allowed: child runs made before IF-308 have no `version`.
        if self.version > 1 and self.parent_run_id is None:
            raise ValueError("version > 1 needs a parent_run_id")
        return self


# ---------------------------------------------------------------- evaluation


# What the validate skill leaves out of an idea text it passes to `new_run.py '<idea text>'`
# (quotes, backticks, dollar signs, `#`, backslashes), plus line breaks. `golden.load` also
# runs that command through the guard, which refuses more (`<<`, `<(`, `curl`, …).
UNQUOTABLE_RE = re.compile(r"['\"`$#\\\n\r]")


class MustFindFact(Strict):
    """A fact the pipeline must find for a golden idea (eval_check.py, IF-502).

    A verified claim finds it when its source URL is one of `source_urls` (scheme, `www.`,
    trailing slash and fragment ignored) or its statement or quote contains every keyword
    (case-insensitive substrings, so a Finnish stem matches its inflections). `dimensions`, when
    given, limits the claims that count.
    """

    fact: Annotated[str, Field(pattern=r"\S")]
    source_urls: Annotated[list[str], Field(min_length=1)]
    keywords: list[Annotated[str, Field(pattern=r"\S")]] = []
    dimensions: list[Dimension] = []

    @field_validator("source_urls")
    @classmethod
    def _url_schemes(cls, v: list[str]) -> list[str]:
        for url in v:
            if not url.startswith(("http://", "https://")):
                raise ValueError(f"source url {url!r} must be an http(s) URL")
        return v


class GoldenIdea(Strict):
    """`tests/golden/<golden_id>.yaml`: one idea of the eval golden set (plan §9)."""

    idea: str
    expected_verdicts: Annotated[list[VerdictLabel], Field(min_length=1)]
    must_find: Annotated[list[MustFindFact], Field(min_length=2, max_length=3)]
    notes: str | None = None

    @field_validator("idea")
    @classmethod
    def _idea_is_one_quotable_line(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("idea must not be empty")
        if v != v.strip():
            raise ValueError("idea must not start or end with whitespace")
        bad = sorted(set(UNQUOTABLE_RE.findall(v)))
        if bad:
            raise ValueError(f"idea is passed to new_run.py in single quotes and may not contain {bad!r}")
        return v

    @field_validator("expected_verdicts")
    @classmethod
    def _unique_verdicts(cls, v: list[str]) -> list[str]:
        if len(v) != len(set(v)):
            raise ValueError("expected_verdicts must not repeat a verdict")
        return v


# Kind name → model, used by validate_file.py and tests.
SCHEMAS: dict[str, type[BaseModel]] = {
    "spec": IdeaSpec,
    "plan": ResearchPlan,
    "claim": Claim,
    "candidate_claim": CandidateClaim,
    "scores_proposed": ProposedScores,
    "risks": RiskRegister,
    "scores": ScoreSheet,
    "position": Position,
    "rebuttal": Rebuttal,
    "mini_research": MiniResearchRequest,
    "verdict": Verdict,
    "interim_scores": InterimScores,
    "meta": RunMeta,
}
# Kinds whose file holds a JSON list of the model rather than a single object.
LIST_KINDS: dict[str, type[BaseModel]] = {
    "claims": Claim,
    "candidate_claims": CandidateClaim,
    "conflicts": ConflictGroup,
}
