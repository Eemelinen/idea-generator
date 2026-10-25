"""Stage 5 scoring: evidence rules, caps, kill triggers, weighted total and verdict.

The synthesizer only proposes scores (`04_scores_proposed.json`); everything that decides the
outcome happens here, driven by `config/rubric.yaml`:

- A dimension's evidence is the verified claims its score cites (`supporting_claim_ids`); cited ids
  that are unknown or not `verified` are dropped first.
- Every `evidence_rule` of the dimension must pass for `final_score` to exceed 2. Otherwise
  `final_score = min(proposed_score, 2)`, `cap_reason` names the failed rules and the status is
  `insufficient_data`. A rubric dimension the synthesizer did not score gets 0, capped.
- A kill trigger fires when any verified claim of the run carries it as a flag (or the caller
  passes it as computed evidence, e.g. a negative contribution margin from `economics.py`),
  unless the spec overrides it. A fired trigger forces `NO_GO`.
- Verdict precedence: fired trigger → NO_GO; more insufficient dimensions than
  `max_insufficient_dimensions` → INSUFFICIENT_DATA; else the `go` / `pivot` thresholds on the
  weighted total.

Rules chosen unattended are TICKETS.md plan note 20.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from urllib.parse import urlsplit

from ideaforge import config
from ideaforge.config import EvidenceRule, RubricConfig
from ideaforge.schemas import (
    KILL_TRIGGERS,
    RUBRIC_DIMENSIONS,
    Claim,
    DimensionScore,
    ScoreSheet,
    UnitEconomics,
    VerdictLabel,
)
from ideaforge.verify import is_official

CAP = 2.0
NUMERIC_FIELDS = ("price", "cost", "unit_count")

# Second-level labels under which the registrable domain has three labels (example.co.uk).
_SECOND_LEVEL = {"co", "com", "net", "org", "gov", "ac", "edu"}
_CURRENCY_RE = re.compile(r"^(eur(o|os|oa)?\b|€)", re.IGNORECASE)
_PRICE_RE = re.compile(r"\bpric(e|es|ed|ing)\b|\bhin(ta|na|no)", re.IGNORECASE)
_COST_RE = re.compile(
    r"\bcosts?\b|\bexpens|\bfees?\b|\bcommission|\brent\b|\bwages?\b|\bsalar|\binsuranc"
    r"|\bkustannu|\bkulu|\bvuokra|\bpalk|\bvakuutu|\bmaksu",
    re.IGNORECASE,
)
_COUNT_UNITS = {
    "count", "person", "people", "resident", "inhabitant", "household", "customer", "company",
    "business", "enterprise", "firm", "establishment", "visitor", "tourist", "guest",
    "overnight stay", "night", "unit", "item", "piece", "pc", "henkilö", "asukas", "yritys",
    "kotitalous", "asiakas", "matkailija", "yöpyminen", "kpl",
    # Finnish partitive plurals as written after a number ("1 900 asukasta")
    "henkilöä", "asukasta", "yritystä", "kotitaloutta", "asiakasta", "matkailijaa", "yöpymistä",
}  # fmt: skip
# A count may be per period ("visitors/year"), never per area or per other unit.
_PERIODS = {"year", "yr", "month", "week", "day", "night", "season", "vuosi", "v", "kk", "kuukausi", "vrk"}


# ---------------------------------------------------------------- claim helpers


def domain(url: str) -> str:
    """The registrable domain of a URL: `pxdata.stat.fi` → `stat.fi`, `www.bbc.co.uk` → `bbc.co.uk`."""
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    labels = host.split(".")
    keep = 3 if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in _SECOND_LEVEL else 2
    return ".".join(labels[-keep:])


def _count_unit(unit: str) -> bool:
    word, _, per = (part.strip() for part in unit.lower().partition("/"))
    if per and per not in _PERIODS:
        return False
    singular = {word, word.removesuffix("s"), word.removesuffix("ies") + "y"}
    return bool(singular & _COUNT_UNITS)


def numeric_field(claim: Claim) -> str | None:
    """The `has_numeric` field a claim's value supplies: `price`, `cost`, `unit_count` or None.

    A currency value (unit `EUR…`, `euro…` or `€…`) is a price when the statement names a price
    (price/hinta) or the claim belongs to `pricing`, and a cost when it names a cost
    (cost, fee, rent, kustannus, vuokra, …) or belongs to `unit_economics`. A value with a count
    unit (`persons`, `companies`, `visitors/year`, `asukasta`, …) is a `unit_count`. Keyword
    matching is crude: "a sauna evening costs 25 EUR" outside `pricing` reads as a cost (note 20).
    """
    if claim.value is None or not claim.unit:
        return None
    unit = claim.unit.strip()
    if _CURRENCY_RE.match(unit):
        if _PRICE_RE.search(claim.statement) or claim.dimension == "pricing":
            return "price"
        if _COST_RE.search(claim.statement) or claim.dimension == "unit_economics":
            return "cost"
        return None
    return "unit_count" if _count_unit(unit) else None


def verified_citations(score: DimensionScore, claims: dict[str, Claim]) -> tuple[list[str], list[str]]:
    """Split a score's cited ids into (kept, dropped): kept ids exist and are `verified`."""
    kept, dropped = [], []
    for cid in dict.fromkeys(score.supporting_claim_ids):
        claim = claims.get(cid)
        (kept if claim is not None and claim.verification == "verified" else dropped).append(cid)
    return kept, dropped


# ---------------------------------------------------------------- evidence rules
# Each rule takes the dimension's verified evidence and the rule's parameters and returns None
# when it passes, else the reason it failed.


def min_sources(evidence: list[Claim], n: int, independent: bool = True) -> str | None:
    """≥ n verified claims; with `independent`, from n distinct registrable domains."""
    if independent:
        have = len({domain(c.source_url) for c in evidence})
        what = "independent source domains"
    else:
        have = len(evidence)
        what = "verified claims"
    return None if have >= n else f"min_sources: {have} of {n} {what}"


def has_official_source(evidence: list[Claim], official: list[str] | None = None) -> str | None:
    """≥ 1 verified claim on an allow-listed domain (by URL, not the declared `source_type`).
    `official` is the run's allow-list (`verify.official_domains`), the global one by default."""
    if any(is_official(c.source_url, official) for c in evidence):
        return None
    return "has_official_source: no verified claim on an allow-listed official domain"


def has_numeric(evidence: list[Claim], field: str) -> str | None:
    """≥ 1 verified claim whose value supplies `field` (see `numeric_field`)."""
    if field not in NUMERIC_FIELDS:
        raise ValueError(f"has_numeric: unknown field {field!r} (known: {', '.join(NUMERIC_FIELDS)})")
    if any(numeric_field(c) == field for c in evidence):
        return None
    return f"has_numeric({field}): no verified claim with a {field} value"


RULES: dict[str, Callable[..., str | None]] = {
    "min_sources": min_sources,
    "has_official_source": has_official_source,
    "has_numeric": has_numeric,
}


def check_rule(rule: EvidenceRule, evidence: list[Claim], official: list[str] | None = None) -> str | None:
    """Apply one rubric `evidence_rule` entry; a malformed entry raises ValueError."""
    params = dict(rule.model_extra or {})
    if rule.rule == "min_sources":
        n, independent = params.pop("n", None), params.pop("independent", True)
        if not isinstance(n, int) or isinstance(n, bool) or n < 1:
            raise ValueError(f"min_sources needs an integer n >= 1, got {n!r}")
        if not isinstance(independent, bool):
            raise ValueError(f"min_sources: independent must be true or false, got {independent!r}")
        args: dict[str, object] = {"n": n, "independent": independent}
    elif rule.rule == "has_numeric":
        args = {"field": params.pop("field", None)}
    else:
        args = {"official": official}
    if params:
        raise ValueError(f"{rule.rule}: unknown parameters {sorted(params)}")
    return RULES[rule.rule](evidence, **args)


def check_rubric(rubric: RubricConfig) -> None:
    """Raise ValueError if any `evidence_rule` entry of the rubric cannot be applied.

    `score` raises on a bad rule anyway, but only when it reaches it; this checks the rubric up front
    (the test suite runs it on `config/rubric.yaml`; `score_run.py` may call it before scoring).
    """
    for dim in rubric.dimensions:
        for rule in dim.evidence_rule:
            try:
                check_rule(rule, [])
            except ValueError as e:
                raise ValueError(f"rubric dimension {dim.id}: {e}") from e


# ---------------------------------------------------------------- scoring


def score_dimension(
    proposed: DimensionScore, claims: dict[str, Claim], rubric: RubricConfig, official: list[str] | None = None
) -> DimensionScore:
    """Drop unverified citations, apply the dimension's evidence rules and cap if any fails."""
    kept, _ = verified_citations(proposed, claims)
    evidence = [claims[cid] for cid in kept]
    failures = [
        reason
        for rule in rubric.dimension(proposed.dimension).evidence_rule
        if (reason := check_rule(rule, evidence, official)) is not None
    ]
    if failures:
        return proposed.model_copy(
            update={
                "supporting_claim_ids": kept,
                "final_score": min(proposed.proposed_score, CAP),
                "cap_reason": "; ".join(failures),
                "status": "insufficient_data",
            }
        )
    return proposed.model_copy(
        update={
            "supporting_claim_ids": kept,
            "final_score": proposed.proposed_score,
            "cap_reason": None,
            "status": "scored",
        }
    )


def fired_kill_triggers(
    claims: Iterable[Claim], overrides: Iterable[str] = (), computed: Iterable[str] = ()
) -> list[str]:
    """Kill triggers carried by verified claims or passed as computed evidence, minus overrides."""
    found = {f for c in claims if c.verification == "verified" for f in c.flags if f in KILL_TRIGGERS}
    for t in computed:
        if t not in KILL_TRIGGERS:
            raise ValueError(f"unknown kill trigger {t!r}")
        found.add(t)
    return sorted(found - set(overrides))


def weighted_total(scores: Iterable[DimensionScore], rubric: RubricConfig) -> float:
    """Σ weight × final_score over the rubric dimensions, rounded to 6 places against float noise."""
    total = 0.0
    for s in scores:
        if s.final_score is None:
            raise ValueError(f"dimension {s.dimension} has no final_score")
        total += rubric.dimension(s.dimension).weight * s.final_score
    return round(total, 6)


def verdict(
    total: float, insufficient: int, kill_triggers: Iterable[str], rubric: RubricConfig
) -> VerdictLabel:
    t = rubric.verdict_thresholds
    if list(kill_triggers):
        return "NO_GO"
    if insufficient > t.max_insufficient_dimensions:
        return "INSUFFICIENT_DATA"
    if total >= t.go:
        return "GO"
    if total >= t.pivot:
        return "PIVOT"
    return "NO_GO"


def _missing(dimension: str) -> DimensionScore:
    return DimensionScore(
        dimension=dimension,
        proposed_score=0,
        justification="no proposed score",
    )


def score(
    proposed: Iterable[DimensionScore],
    claims: Iterable[Claim],
    overrides: Iterable[str] = (),
    *,
    unit_economics: UnitEconomics | None = None,
    computed_triggers: Iterable[str] = (),
    rubric: RubricConfig | None = None,
    official: list[str] | None = None,
) -> ScoreSheet:
    """Score a run: proposed scores + all its claims (any state) + the spec's kill-trigger overrides.
    `official` is the run's official-domain list (`verify.official_domains` of the spec's base)."""
    rubric = rubric or config.rubric()
    claims = list(claims)
    by_id = {c.claim_id: c for c in claims}
    by_dim: dict[str, DimensionScore] = {}
    for p in proposed:
        if p.dimension in by_dim:
            raise ValueError(f"dimension {p.dimension} is scored more than once")
        by_dim[p.dimension] = p
    scores = [score_dimension(by_dim.get(d) or _missing(d), by_id, rubric, official) for d in RUBRIC_DIMENSIONS]
    total = weighted_total(scores, rubric)
    fired = fired_kill_triggers(claims, overrides, computed_triggers)
    insufficient = sum(s.status == "insufficient_data" for s in scores)
    return ScoreSheet(
        scores=scores,
        weighted_total=total,
        kill_triggers_fired=fired,
        verdict=verdict(total, insufficient, fired, rubric),
        unit_economics=unit_economics or UnitEconomics(),
    )


def dropped_citations(proposed: Iterable[DimensionScore], claims: Iterable[Claim]) -> dict[str, list[str]]:
    """Per dimension, the cited claim ids `score` drops (unknown or not verified)."""
    by_id = {c.claim_id: c for c in claims}
    out = {}
    for p in proposed:
        _, dropped = verified_citations(p, by_id)
        if dropped:
            out[p.dimension] = dropped
    return out
