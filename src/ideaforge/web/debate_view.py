"""The run page's debate tab (IF-606): the debate's next step, each round as the judge saw it,
the verdict, the revised plan, the assumption register and the experiments.

Reads only, through the debate's own functions (`debate.progress`, `round_numbers`,
`load_interim`, `reprompted`, `finalize_verdict`, `revised_plan.experiment_order`), so the tab
agrees with `python -m ideaforge.debate status` and `revised_plan.md`. A round is shown from its
`positions_anon.json` (P-ids, no roles); its turns, re-prompts and mini-research come from
`debate_turns`, `round<N>/.reprompted` and the `mini_research` table. Role names appear only once
`debate/verdict.json` exists (as the file browser withholds `debate/.mapping.json`): before that
every role a line would name is replaced by its P-id.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError

from ideaforge import db, debate, mini_research, revised_plan
from ideaforge.schemas import PERSONAS, Assumption, Claim, Experiment, InterimScores, Verdict
from ideaforge.web.run_detail import render_markdown

# A role as a word of its own: `customer-001` (a claim id) and `founder_risk` (a dimension) stay.
_ROLE_WORD_RE = re.compile(rf"(?<![\w-])({'|'.join(PERSONAS)})(?![\w-])")


@dataclass
class Turn:
    """One `debate_turns` row: an attempt at a round's turn and whether it entered the debate."""

    who: str  # the P-id, with the role after the verdict
    attempt: int
    accepted: bool
    reasons: list[str]


@dataclass
class MiniTask:
    n: int
    who: str
    dimension: str
    question: str
    status: str
    attempts: int
    reason: str | None
    claims: list[tuple[str, str]]  # (claim id, its ledger state or "not verified yet")


@dataclass
class Round:
    number: int
    positions: list[dict[str, Any]] | None = None  # positions_anon.json entries, as the judge saw them
    positions_error: str | None = None
    persona_files: int = 0  # round<N>/<role>.json files written so far
    turns: list[Turn] = field(default_factory=list)
    reprompted: list[str] = field(default_factory=list)
    mini: list[MiniTask] = field(default_factory=list)
    interim: InterimScores | None = None
    interim_error: str | None = None
    interim_skipped: bool = False


@dataclass
class VerdictView:
    verdict: Verdict
    conformity_flag: bool  # computed by `debate.finalize_verdict` when it accepts the file
    judge_flag: bool
    error: str | None = None  # why the file was not accepted; the flag is then the judge's
    experiments: list[tuple[Experiment, str]] = field(default_factory=list)  # (experiment, info per 100 EUR)

    @property
    def assumptions(self) -> list[Assumption]:
        return self.verdict.assumption_register


@dataclass
class DebateView:
    started: bool
    next_step: str | None = None  # `Progress.line()`
    notes: list[str] = field(default_factory=list)
    error: str | None = None
    mapping: dict[str, str] | None = None  # role → P-id; None when the debate has none yet
    roles_shown: bool = False  # the verdict exists
    role_of: dict[str, str] = field(default_factory=dict)  # P-id → role, filled only once roles are shown
    rounds: list[Round] = field(default_factory=list)
    verdict: VerdictView | None = None
    verdict_error: str | None = None
    plan_html: Any = None


def _rel(text: str, run_dir: Path) -> str:
    return text.replace(str(run_dir) + os.sep, "")


def _mapping(run_dir: Path) -> dict[str, str] | None:
    """debate/.mapping.json when it matches its seed, read without creating anything."""
    try:
        stored = json.loads((run_dir / "debate" / debate.MAPPING_NAME).read_text(encoding="utf-8"))
        mapping = debate.mapping_for(int(stored["seed"]))
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return mapping if stored.get("mapping") == mapping else None


class _Names:
    """Who a role is on the page: `P3` before the verdict, `P3 (investor)` after it."""

    def __init__(self, mapping: dict[str, str] | None, roles_shown: bool) -> None:
        self.mapping = mapping or {}
        self.roles_shown = roles_shown

    def who(self, role: str, anon_id: str | None = None) -> str:
        pid = anon_id or self.mapping.get(role)
        if self.roles_shown:
            return f"{pid} ({role})" if pid else role
        return pid or "P?"

    def text(self, text: str) -> str:
        return text if self.roles_shown else _ROLE_WORD_RE.sub(lambda m: self.who(m.group()), text)


def _positions(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data.get("positions") if isinstance(data, dict) else None
    if not isinstance(entries, list) or not all(isinstance(e, dict) and "position_id" in e for e in entries):
        raise ValueError("expected {\"round\": N, \"positions\": [{\"position_id\": …}, …]}")
    return entries


def _mini_claims(run_dir: Path, stem: str, ledger: dict[str, Claim]) -> list[tuple[str, str]]:
    path = run_dir / "03_claims" / f"{stem}.json"
    try:
        claims = TypeAdapter(list[Claim]).validate_json(path.read_bytes())
    except (OSError, ValidationError):
        return []
    return [
        (c.claim_id, ledger[c.claim_id].verification if c.claim_id in ledger else "not verified yet")
        for c in claims
    ]


def _round(run_id: str, run_dir: Path, n: int, names: _Names, ledger: dict[str, Claim],
           tasks: list[mini_research.Task]) -> Round:  # fmt: skip
    d = debate.round_dir(run_id, n)
    r = Round(n, persona_files=sum((d / f"{role}.json").is_file() for role in PERSONAS))
    if (d / debate.ANON_NAME).is_file():
        try:
            r.positions = _positions(d / debate.ANON_NAME)
        except (OSError, ValueError) as e:
            r.positions_error = f"round{n}/{debate.ANON_NAME} is not valid: {e}"
    with db.session() as conn:
        rows = conn.execute(
            "SELECT role, anon_id, attempt, accepted, reject_reason FROM debate_turns"
            " WHERE run_id=? AND round=? ORDER BY anon_id, attempt",
            (run_id, n),
        ).fetchall()
    r.turns = [
        Turn(names.who(row["role"], row["anon_id"]), row["attempt"], bool(row["accepted"]),
             [names.text(line) for line in (row["reject_reason"] or "").splitlines() if line])
        for row in rows
    ]  # fmt: skip
    r.reprompted = sorted(names.who(role) for role in debate.reprompted(run_id, n))
    r.mini = [
        MiniTask(t.n, names.who(t.role, t.anon_id), t.dimension, names.text(t.question), t.status, t.attempts,
                 names.text(t.reason) if t.reason else None, _mini_claims(run_dir, t.stem, ledger))
        for t in tasks if t.round == n
    ]  # fmt: skip
    try:
        r.interim = debate.load_interim(run_id, n)
    except debate.DebateError as e:
        r.interim_error = _rel(str(e), run_dir)
    r.interim_skipped = (d / debate.INTERIM_SKIPPED_NAME).exists()
    return r


def _verdict(run_id: str, run_dir: Path) -> VerdictView:
    """The verdict with the conformity flag `finalize_verdict` computes; when it refuses the file
    (an accepted change cites an unverified claim, a round was not validated), the judge's file
    and flag with the reason. Raises DebateError when verdict.json itself is not valid."""
    try:
        final = debate.finalize_verdict(run_id)
        view = VerdictView(final.verdict, final.verdict.conformity_flag, final.judge_flag)
    except debate.DebateError as e:
        path = run_dir / "debate" / debate.VERDICT_NAME
        try:
            raw = Verdict.model_validate_json(path.read_bytes())
        except (OSError, ValidationError) as invalid:
            raise debate.DebateError(f"debate/{debate.VERDICT_NAME} is not valid: {invalid}") from None
        view = VerdictView(raw, raw.conformity_flag, raw.conformity_flag, error=_rel(str(e), run_dir))
    order = revised_plan.experiment_order(view.verdict.experiments)
    view.experiments = [(e, revised_plan.per_100_eur(e)) for e in order]
    return view


def debate_view(run_id: str, run_dir: Path, in_db: bool, ledger: dict[str, Claim]) -> DebateView:
    d = run_dir / "debate"
    view = DebateView(started=(d / "round0").is_dir() or (d / debate.EVIDENCE_DIR).is_dir())
    view.roles_shown = (d / debate.VERDICT_NAME).is_file()
    view.mapping = _mapping(run_dir)
    names = _Names(view.mapping, view.roles_shown)
    if view.roles_shown and view.mapping:
        view.role_of = {pid: role for role, pid in view.mapping.items()}
    if in_db and run_dir.is_dir():
        try:
            p = debate.progress(run_id)
            view.next_step = debate.Progress(p.step, p.round, [names.who(r) for r in p.roles]).line()
            view.notes = [names.text(n) for n in p.notes]
        except (debate.DebateError, OSError, ValueError, KeyError) as e:
            view.error = names.text(_rel(str(e), run_dir))
    tasks = mini_research.tasks(run_id) if in_db else []
    view.rounds = [_round(run_id, run_dir, n, names, ledger, tasks) for n in debate.round_numbers(run_id)]
    if view.roles_shown:
        try:
            view.verdict = _verdict(run_id, run_dir)
        except debate.DebateError as e:
            view.verdict_error = _rel(str(e), run_dir)
    plan = d / revised_plan.REVISED_PLAN
    if plan.is_file() and not plan.is_symlink():
        view.plan_html = render_markdown(plan.read_text(encoding="utf-8", errors="replace"))
    return view
