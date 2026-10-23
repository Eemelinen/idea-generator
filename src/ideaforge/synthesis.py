"""Stage 5: the synthesizer's input file and the score run.

    synthesis_input(run_id)   → the only thing the synthesizer reads (04_synthesis_input.json):
                                 00_spec.json, the verified and conflict claims, the rubric
    score_run(run_id)         → 04_scores.json + the `scores` rows, from 04_scores_proposed.json

The synthesizer only proposes. `score_run` drops cited claim ids that are unknown or not
verified, sets a proposal with no verified citation left to 0 ("no verified evidence"), runs
`economics.unit_economics` on the synthesizer's `unit_economics_inputs` and `scoring.score` on
the result. A negative margin fires `negative_contribution_margin` only when the synthesizer
assigned the inputs and every assigned per-unit cost reads as per unit sold: the automatic pick
and a model's odd unit are too crude to force NO_GO (TICKETS.md notes 21–22).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError

from ideaforge import agents, config, db, economics, runs, scoring
from ideaforge.schemas import (
    Claim,
    DimensionScore,
    IdeaSpec,
    ProposedScores,
    RiskRegister,
    ScoreSheet,
)

INPUT_STATES = ("verified", "conflict")
NO_EVIDENCE = "no verified evidence"
AUTOMATIC_PICK_NOTE = (
    "no unit_economics_inputs from the synthesizer: inputs were picked automatically, so a "
    "negative margin is reported but fires no kill trigger"
)

UNCHECKED_UNIT_NOTE = (
    "assigned {role} claim {cid} has unit {unit!r}, which does not read as per unit sold: "
    "a negative margin is reported but fires no kill trigger"
)

# What each economics role means, for the synthesizer's assignments (economics.ROLES).
ECONOMICS_ROLES: dict[str, str] = {
    "price": "price of one unit sold (EUR; per person, night, visit, … or per month for a subscription)",
    "variable_cost": "cost of one unit sold (EUR per unit sold, never per month or per hour); claims are summed",
    "variable_cost_pct": "commission or fee as % of the price (unit %); claims are summed",
    "fixed_costs": "running costs per period (EUR/month, EUR/year, …); claims are summed",
    "cac": "cost of acquiring one customer (EUR per customer)",
    "volume": "units sold per period (count per month, year, …), the business's own expected volume",
    "purchases_per_customer": "purchases by one customer per period",
    "vat_rate": "the VAT rate that applies (unit %)",
}


class InputError(Exception):
    """A run file score_run or synthesis_input needs is missing or invalid."""


# ---------------------------------------------------------------- loading


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise InputError(f"{path} does not exist") from None


def _load(path: Path, adapter: Any) -> Any:
    try:
        return adapter.validate_json(_read(path))
    except ValidationError as e:
        raise InputError(f"{path} is not valid: {e.error_count()} error(s), first: {e.errors()[0]['msg']}") from None


def load_spec(run_dir: Path) -> IdeaSpec:
    return _load(run_dir / "00_spec.json", TypeAdapter(IdeaSpec))


def load_claims(run_dir: Path) -> list[Claim]:
    return _load(run_dir / "03_claims" / "verified.json", TypeAdapter(list[Claim]))


def load_proposed(run_dir: Path) -> ProposedScores:
    return _load(run_dir / "04_scores_proposed.json", TypeAdapter(ProposedScores))


def load_risks(run_dir: Path) -> RiskRegister:
    return _load(run_dir / "04_risks.json", TypeAdapter(RiskRegister))


def load_scores(run_dir: Path) -> ScoreSheet:
    return _load(run_dir / "04_scores.json", TypeAdapter(ScoreSheet))


def _write_json(path: Path, data: Any) -> None:
    """Write via a temp file and rename, so a crash never leaves half a stage file."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------- synthesizer input


def synthesis_input(run_id: str) -> dict[str, Any]:
    """The synthesizer's whole input: the spec, the verified + conflict claims and the rubric.

    Unverified and pending claims are left out, so the synthesizer cannot lean on them.
    """
    run_dir = runs.run_dir(run_id)
    spec = load_spec(run_dir)
    claims = [c for c in load_claims(run_dir) if c.verification in INPUT_STATES]
    rubric = config.rubric()
    return {
        "run_id": run_id,
        "spec": spec.model_dump(mode="json"),
        "claims": [c.model_dump(mode="json") for c in sorted(claims, key=lambda c: c.claim_id)],
        "rubric": {
            "verdict_thresholds": rubric.verdict_thresholds.model_dump(),
            "dimensions": [
                {
                    "id": d.id,
                    "name": d.name,
                    "weight": d.weight,
                    "min_evidence_for_3": d.min_evidence_for_3,
                    "evidence_rule": [r.model_dump() for r in d.evidence_rule],
                    "kill_triggers": d.kill_triggers,
                }
                for d in rubric.dimensions
            ],
            "killcause_kill_triggers": rubric.killcause.kill_triggers,
        },
        "economics_roles": ECONOMICS_ROLES,
    }


def write_synthesis_input(run_id: str) -> tuple[Path, dict[str, Any]]:
    data = synthesis_input(run_id)
    path = runs.run_dir(run_id) / agents.SYNTHESIS_INPUT
    _write_json(path, data)
    return path, data


# ---------------------------------------------------------------- score run


@dataclass
class ScoreRunResult:
    run_id: str
    sheet: ScoreSheet
    path: Path
    dropped: dict[str, list[str]] = field(default_factory=dict)
    zeroed: list[str] = field(default_factory=list)
    assigned: bool = False
    warnings: list[str] = field(default_factory=list)


def require_evidence(proposed: list[DimensionScore], claims: list[Claim]) -> tuple[list[DimensionScore], list[str]]:
    """A proposal with no verified citation left is set to 0 with "no verified evidence".

    The synthesizer's rule (every justification cites a claim; a dimension without verified
    evidence is proposed 0) applied mechanically, so an uncited score cannot reach the cap of 2.
    Returns the proposals and the dimensions changed.
    """
    by_id = {c.claim_id: c for c in claims}
    out, zeroed = [], []
    for p in proposed:
        kept, dropped = scoring.verified_citations(p, by_id)
        if kept or p.proposed_score == 0:
            out.append(p)
            continue
        why = f"proposed {p.proposed_score:g}"
        if dropped:
            why += f"; dropped citations: {', '.join(dropped)}"
        out.append(p.model_copy(update={"proposed_score": 0, "justification": f"{NO_EVIDENCE} ({why}). {p.justification}"}))
        zeroed.append(p.dimension)
    return out, zeroed


def unchecked_per_unit(assignments: dict[str, list[str]], claims: list[Claim]) -> list[str]:
    """Notes for assigned `variable_cost` / `cac` claims whose unit is not plainly per unit sold.

    economics.py trusts an assignment (an `EUR/h` wage is used per unit, note 21), so a
    misassigned claim could produce a false negative margin; such a margin must not force NO_GO.
    """
    by_id = {c.claim_id: c for c in claims}
    notes = []
    for role in economics.PER_UNIT_ROLES:
        for cid in assignments.get(role, []):
            claim = by_id.get(cid)
            if claim is not None and not economics.per_unit(claim.unit or ""):
                notes.append(UNCHECKED_UNIT_NOTE.format(role=role, cid=cid, unit=claim.unit))
    return notes


def score_run(run_id: str) -> ScoreRunResult:
    """Score a run from its files, write 04_scores.json and replace its `scores` rows."""
    run_dir = runs.run_dir(run_id)
    spec = load_spec(run_dir)
    claims = load_claims(run_dir)
    proposed = load_proposed(run_dir)
    rubric = config.rubric()
    scoring.check_rubric(rubric)

    dropped = scoring.dropped_citations(proposed.scores, claims)
    scores, zeroed = require_evidence(proposed.scores, claims)
    assignments = {role: ids for role, ids in proposed.unit_economics_inputs.items() if ids}
    ue = economics.unit_economics(claims, assignments or None, vat_registered=spec.vat_registered)
    guard_notes = unchecked_per_unit(assignments, claims) if assignments else [AUTOMATIC_PICK_NOTE]
    triggers = [] if guard_notes else economics.computed_triggers(ue)
    if guard_notes:
        ue = ue.model_copy(update={"notes": [*ue.notes, *guard_notes]})
    sheet = scoring.score(
        scores, claims, spec.kill_trigger_overrides, unit_economics=ue, computed_triggers=triggers, rubric=rubric
    )

    warnings = []
    known = {c.claim_id for c in claims}
    try:
        risks = load_risks(run_dir).risks
    except InputError as e:  # the synthesize stage owns 04_risks.json; scoring does not need it
        risks = []
        warnings.append(f"risks not checked: {e}")
    for risk in risks:
        unknown = [cid for cid in risk.claim_ids if cid not in known]
        if unknown:
            warnings.append(f"risk {risk.risk[:60]!r} cites unknown claim ids: {', '.join(unknown)}")

    path = run_dir / "04_scores.json"
    _write_json(path, sheet.model_dump(mode="json"))
    db.replace_scores(run_id, sheet.scores)
    return ScoreRunResult(run_id, sheet, path, dropped, zeroed, bool(assignments), warnings)


def _fmt(x: float | None, unit: str = "") -> str:
    return "-" if x is None else f"{x:,.2f}{unit}".replace(",", " ")


def summary(result: ScoreRunResult) -> str:
    """The text score_run.py prints: per-dimension scores, total, triggers, verdict, economics."""
    sheet = result.sheet
    lines = [f"run {result.run_id}", f"{'dimension':<16} {'proposed':>8} {'final':>6}  status / cap reason"]
    for s in sheet.scores:
        note = s.status + (f": {s.cap_reason}" if s.cap_reason else "")
        lines.append(f"{s.dimension:<16} {s.proposed_score:>8g} {s.final_score:>6g}  {note}")
    lines.append(f"weighted total: {sheet.weighted_total:g}")
    lines.append(f"kill triggers fired: {', '.join(sheet.kill_triggers_fired) or 'none'}")
    lines.append(f"verdict: {sheet.verdict}")
    for dim, ids in result.dropped.items():
        lines.append(f"dropped citations ({dim}): {', '.join(ids)}")
    for dim in result.zeroed:
        lines.append(f"no verified citation, set to 0: {dim}")
    ue = sheet.unit_economics
    lines.append(
        "unit economics ({}): price {} · variable cost {} · margin {} ({}) · fixed/month {} · "
        "break-even units/month {} · monthly profit {} · payback months {}".format(
            "assigned" if result.assigned else "automatic pick",
            _fmt(ue.price_eur), _fmt(ue.variable_cost_eur), _fmt(ue.contribution_margin_eur),
            _fmt(ue.contribution_margin_pct, " %"), _fmt(ue.fixed_costs_month_eur),
            _fmt(ue.break_even_units_month), _fmt(ue.monthly_profit_eur), _fmt(ue.payback_months),
        )
    )  # fmt: skip
    if ue.missing_inputs:
        lines.append(f"missing inputs: {', '.join(ue.missing_inputs)}")
    lines.extend(f"note: {n}" for n in ue.notes)
    lines.append(f"wrote {result.path.as_posix()}")
    return "\n".join(lines)
