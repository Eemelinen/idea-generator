"""Debate anonymization, rebuttal validation and the /debate skill's helpers (plan §6 stage 7,
IF-402 / IF-403 / IF-407).

    uv run python -m ideaforge.debate anonymize <run_id> <round> [--seed N]
    uv run python -m ideaforge.debate evidence <run_id> [--seed N]
    uv run python -m ideaforge.debate reprompt <run_id> <round>
    uv run python -m ideaforge.debate skip-interim <run_id> <round>
    uv run python -m ideaforge.debate status <run_id>

`anonymize` maps the five persona roles to P1…P5 with a seeded shuffle. The seed is stored in
the run's `debates` row and, with the mapping, in `debate/.mapping.json`, which no persona or
the judge is ever given. The round's files (round 0: `Position`, later rounds: `Rebuttal`) are
written to `debate/round<N>/positions_anon.json` in P-id order, without `role`, without
`mini_research.requested_by` and with self-labels such as "the accountant persona" replaced by
"[persona]". The mapping is fixed for the whole debate, so `target_position_id` in a rebuttal
always names the same persona.

`validate_round` (scripts/debate_validate.py) applies the rebuttal rules of §6 stage 7 to
`debate/round<N>/<role>.json` for every persona, writes `debate/round<N>/REJECTED_<role>` with
one reason per line for each rejected role (removed once the role passes) and records every
turn in `debate_turns`. Rule choices: TICKETS.md plan note 25.

`check_convergence` (scripts/debate_converged.py), `conformity_flag` and `finalize_verdict`
(render_report.py --debate) read only the turns that entered the debate: a file's latest
`debate_turns` row must hold its current text and be accepted. Rule choices: plan note 26.

`evidence` writes each persona's evidence subset (`agents.PERSONA_EVIDENCE`) to
`debate/evidence/<role>.json`, with its own P-id and every verified mini-research claim; a
turn may cite only those ids (`allowed_claim_ids`, checked for rebuttals and round-0 positions);
`reprompt` lists the rejected personas of a round that were not yet sent back (each once); and
`status` prints the debate's next step, so /debate resumes per round. A mini-research request
counts against the run preset's `max_mini_research_tasks` here and in `ideaforge.mini_research`.
Rule choices: plan note 27.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, TypeAdapter, ValidationError

from ideaforge import agents, config, db, runs
from ideaforge.schemas import PERSONAS, RESEARCH_DIMENSIONS, Basis, Claim, InterimScores, Position, Rebuttal, ScoreSheet, Verdict
from ideaforge.validate_file import candidate_claims

MAPPING_NAME = ".mapping.json"
ANON_NAME = "positions_anon.json"
REJECTED_PREFIX = "REJECTED_"
INTERIM_NAME = "interim_scores.json"
VERDICT_NAME = "verdict.json"
EVIDENCE_DIR = "evidence"  # debate/evidence/<role>.json: each persona's evidence subset
REPROMPTED_NAME = ".reprompted"  # round<N>/.reprompted: the roles already sent back once
INTERIM_SKIPPED_NAME = "interim_scores.skipped"  # round<N>/: the judge's projection, set aside

# Claim ids inside free text (a `basis.computation`); schemas.CLAIM_ID_RE without anchors.
CLAIM_ID_IN_TEXT_RE = re.compile(r"\b[a-z_]+-\d{3,}\b")
_NUMBER_RE = re.compile(r"\d")
_ROLE = "|".join(PERSONAS)
# Self-labels that would tell the reader which persona wrote a position. Persona names as plain
# words stay: "customer", "founder" and "operator" are also ordinary words in a business plan
# (and "customer" is a dimension), so only labelling phrases are replaced: "debate-<role>",
# "<role> persona / lens / here", "as (the|a|an) <role>", "from the <role>'s perspective",
# "I am / I'm / I, the <role>", an article-less "as <role>" only before a comma or at the start
# of a sentence, line, bracket or quote ("such as customer reviews" stays), and the Finnish
# "minä (olen / oon) <role>", "<role>n näkökulmasta / silmin" and essive self-labels
# ("sijoittajana", "kirjanpitäjänä": the ending follows vowel harmony).
# "yrittäjänä" and "asiakkaana" stay: Finnish plans use them for the real founder and customers.
_A = r"(?:the\s+|an?\s+|my\s+|our\s+|this\s+|your\s+)"
_FI_ROLE = r"(?:perustaja|sijoittaja|kirjanpitäjä|tilintarkastaja|operaattori)"
# A pattern with a `keep` group keeps that prefix (the punctuation before a sentence-initial
# "as <role>") and replaces the rest; Python lookbehinds cannot take variable-width whitespace.
_SELF_LABEL_RES = (
    re.compile(rf"\bdebate-(?:{_ROLE})\b", re.IGNORECASE),
    re.compile(rf"\b{_A}?(?:{_ROLE})(?:'s)?\s+(?:persona|lens)\b", re.IGNORECASE),
    re.compile(rf"\b(?:I\s+am|I'm|I,|speaking\s+as)\s+{_A}?(?:{_ROLE})\b(?:'s)?", re.IGNORECASE),
    re.compile(rf"\bas\s+{_A}(?:{_ROLE})\b(?:'s)?", re.IGNORECASE),
    re.compile(rf"\bas\s+(?:{_ROLE})\b(?:'s)?(?=\s*,)", re.IGNORECASE),
    re.compile(
        rf"(?P<keep>(?:^|[.!?:;(\"“*•-])\s*)as\s+(?:{_ROLE})\b(?:'s)?", re.IGNORECASE | re.MULTILINE
    ),
    re.compile(
        rf"\bfrom\s+{_A}?(?:{_ROLE})(?:'s|s')?\s+"
        r"(?:perspective|point\s+of\s+view|view|side|standpoint|angle)\b",
        re.IGNORECASE,
    ),
    re.compile(rf"\b(?:{_ROLE})\s+here\b", re.IGNORECASE),
    re.compile(rf"\b(?:minä|mä)\s+(?:(?:olen|oon)\s+)?(?:{_FI_ROLE}(?:n[aä])?|yrittäjä|asiakas)\b", re.IGNORECASE),
    re.compile(rf"\b{_FI_ROLE}n[aä]\b", re.IGNORECASE),
    re.compile(rf"\b{_FI_ROLE}n\s+(?:näkökulmasta|silmin)\b", re.IGNORECASE),
)
REDACTED = "[persona]"


class DebateError(Exception):
    """A debate input is missing or invalid, or the stored seed and mapping disagree."""


# ---------------------------------------------------------------- paths and loading


def debate_dir(run_id: str) -> Path:
    return runs.run_dir(run_id) / "debate"


def round_dir(run_id: str, round_no: int) -> Path:
    return debate_dir(run_id) / f"round{round_no}"


def _check_run(run_id: str) -> Path:
    try:
        run_dir = runs.run_dir(run_id)
    except ValueError as e:
        raise DebateError(str(e)) from None
    if not run_dir.is_dir():
        raise DebateError(f"{run_dir} does not exist")
    db.init()
    with db.session() as conn:
        if conn.execute("SELECT 1 FROM runs WHERE run_id=?", (run_id,)).fetchone() is None:
            raise DebateError(f"run {run_id!r} is not in the database; create it with scripts/new_run.py")
    return run_dir


def _load_model(path: Path, model: type[BaseModel]) -> Any:
    try:
        return model.model_validate_json(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise DebateError(f"{path} does not exist") from None
    except ValidationError as e:
        raise DebateError(f"{path} is not a valid {model.__name__}: {e.errors()[0]['msg']}") from None


def _write_json(path: Path, data: Any) -> None:
    """Write via a temp file and rename, so a crash never leaves half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def load_ledger(run_dir: Path) -> dict[str, Claim]:
    """The run's claim ledger (03_claims/verified.json, every verification state), by id."""
    path = run_dir / "03_claims" / "verified.json"
    try:
        claims = TypeAdapter(list[Claim]).validate_json(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise DebateError(f"{path} does not exist; run scripts/verify_claims.py first") from None
    except ValidationError as e:
        raise DebateError(f"{path} is not valid: {e.errors()[0]['msg']}") from None
    return {c.claim_id: c for c in claims}


# ---------------------------------------------------------------- seed and mapping


def mapping_for(seed: int) -> dict[str, str]:
    """role → P-id: the personas shuffled with `random.Random(seed)`, numbered in shuffled order."""
    order = list(PERSONAS)
    random.Random(seed).shuffle(order)
    return {role: f"P{i}" for i, role in enumerate(order, start=1)}


def _stored_seed(run_id: str) -> int | None:
    with db.session() as conn:
        row = conn.execute("SELECT seed FROM debates WHERE run_id=?", (run_id,)).fetchone()
    return None if row is None else int(row["seed"])


def ensure_mapping(run_id: str, seed: int | None = None) -> dict[str, str]:
    """The debate's role → P-id mapping, creating the seed, the `debates` row and
    `debate/.mapping.json` on first use. A given `seed` must match a stored one."""
    path = debate_dir(run_id) / MAPPING_NAME
    file_seed = None
    if path.exists():
        try:
            stored_file = json.loads(path.read_text(encoding="utf-8"))
            file_seed = int(stored_file["seed"])
        except (ValueError, KeyError, TypeError) as e:
            raise DebateError(f"{path} is not valid: {e}") from None
        if stored_file.get("mapping") != mapping_for(file_seed):
            raise DebateError(f"the mapping in {path} does not match its seed {file_seed}")
    db_seed = _stored_seed(run_id)
    if file_seed is not None and db_seed is not None and file_seed != db_seed:
        raise DebateError(f"seed in {path} ({file_seed}) differs from the debates row ({db_seed})")
    stored = db_seed if db_seed is not None else file_seed
    if seed is not None and stored is not None and seed != stored:
        raise DebateError(f"the debate already has seed {stored}; --seed {seed} would change the mapping")
    final = stored if stored is not None else seed if seed is not None else random.SystemRandom().randrange(2**31)
    if db_seed is None:
        with db.session() as conn:
            conn.execute(
                "INSERT INTO debates(run_id, seed, started_at) VALUES (?,?,?)", (run_id, final, db.now())
            )
    mapping = mapping_for(final)
    if file_seed is None:
        _write_json(path, {"seed": final, "mapping": mapping})
    return mapping


def load_mapping(run_id: str) -> dict[str, str]:
    """The stored mapping; a debate that was never anonymized has none."""
    if _stored_seed(run_id) is None and not (debate_dir(run_id) / MAPPING_NAME).exists():
        raise DebateError(f"run {run_id} has no debate seed yet; run `debate anonymize {run_id} 0` first")
    return ensure_mapping(run_id)


# ---------------------------------------------------------------- anonymization


def scrub(text: str) -> str:
    for pattern in _SELF_LABEL_RES:
        text = pattern.sub(lambda m: (m.groupdict().get("keep") or "") + REDACTED, text)
    return text


def _scrub_all(value: Any) -> Any:
    if isinstance(value, str):
        return scrub(value)
    if isinstance(value, list):
        return [_scrub_all(v) for v in value]
    if isinstance(value, dict):
        return {k: _scrub_all(v) for k, v in value.items()}
    return value


def anonymous_entry(turn: Position | Rebuttal, position_id: str) -> dict[str, Any]:
    data = turn.model_dump(mode="json", exclude={"role"})
    if isinstance(data.get("mini_research"), dict):
        data["mini_research"].pop("requested_by", None)
    return {"position_id": position_id, **_scrub_all(data)}


def rejected_roles(run_id: str, round_no: int) -> list[str]:
    d = round_dir(run_id, round_no)
    return [r for r in PERSONAS if (d / f"{REJECTED_PREFIX}{r}").exists()]


@dataclass
class AnonResult:
    path: Path
    position_ids: list[str]
    missing: list[str] = field(default_factory=list)  # roles without a file
    excluded: list[str] = field(default_factory=list)  # roles left out after a rejection


def anonymize(run_id: str, round_no: int, *, seed: int | None = None) -> AnonResult:
    """Write `debate/round<N>/positions_anon.json`. Round 0 also records the positions in
    `debate_turns`; later rounds leave roles with a `REJECTED_<role>` marker out."""
    if round_no < 0:
        raise DebateError("round must be 0 or more")
    run_dir = _check_run(run_id)
    d = round_dir(run_id, round_no)
    if not d.is_dir():
        raise DebateError(f"{d} does not exist")
    mapping = ensure_mapping(run_id, seed)
    model = Position if round_no == 0 else Rebuttal
    excluded = [r for r in rejected_roles(run_id, round_no) if (d / f"{r}.json").exists()] if round_no > 0 else []
    ledger = load_ledger(run_dir) if round_no == 0 else {}
    turns: dict[str, Position | Rebuttal] = {}
    raws: dict[str, str] = {}
    missing = []
    for role in PERSONAS:
        path = d / f"{role}.json"
        if not path.exists():
            missing.append(role)
            continue
        if role in excluded:
            continue
        turn = _load_model(path, model)
        raws[role] = path.read_text(encoding="utf-8")
        if turn.role != role:
            raise DebateError(f"{path} has role {turn.role!r}, expected {role!r}")
        if isinstance(turn, Rebuttal) and turn.round != round_no:
            raise DebateError(f"{path} has round {turn.round}, expected {round_no}")
        if isinstance(turn, Position) and (
            problems := check_position(
                turn, role=role, ledger=ledger, allowed=allowed_claim_ids(run_dir, role, ledger)
            )
        ):
            raise DebateError(f"{path} is not a valid position: {'; '.join(problems)}")
        turns[role] = turn
    if not turns:
        raise DebateError(f"no usable persona files in {d}")
    entries = sorted(
        (anonymous_entry(t, mapping[r]) for r, t in turns.items()), key=lambda e: int(e["position_id"][1:])
    )
    out = d / ANON_NAME
    _write_json(out, {"round": round_no, "positions": entries})
    if round_no == 0:
        for role in turns:
            record_turn(run_id, 0, role, mapping[role], raws[role], [])
    return AnonResult(out, [e["position_id"] for e in entries], missing, excluded)


# ---------------------------------------------------------------- turns


def record_turn(run_id: str, round_no: int, role: str, anon_id: str, payload: str, reasons: list[str]) -> int:
    """Insert a `debate_turns` row; re-validating an unchanged file updates its last attempt
    instead of counting a new one. Returns the attempt number."""
    accepted = 0 if reasons else 1
    reason = "\n".join(reasons) or None
    with db.session() as conn:
        last = conn.execute(
            "SELECT attempt, payload FROM debate_turns WHERE run_id=? AND round=? AND role=?"
            " ORDER BY attempt DESC LIMIT 1",
            (run_id, round_no, role),
        ).fetchone()
        if last is not None and last["payload"] == payload:
            conn.execute(
                "UPDATE debate_turns SET anon_id=?, accepted=?, reject_reason=?"
                " WHERE run_id=? AND round=? AND role=? AND attempt=?",
                (anon_id, accepted, reason, run_id, round_no, role, last["attempt"]),
            )
            return int(last["attempt"])
        attempt = 1 if last is None else int(last["attempt"]) + 1
        conn.execute(
            "INSERT INTO debate_turns(run_id, round, role, anon_id, attempt, accepted, reject_reason, payload)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (run_id, round_no, role, anon_id, attempt, accepted, reason, payload),
        )
        return attempt


# ---------------------------------------------------------------- rebuttal validation


def turn_claim_ids(turn: Position | Rebuttal) -> set[str]:
    """Every claim id a turn cites, including ids written into a computation."""
    if isinstance(turn, Position):
        return {cid for o in turn.objections for cid in o.claim_ids}
    ids: set[str] = set()
    bases = [r.basis for r in turn.responses] + ([turn.updated_change_basis] if turn.updated_change_basis else [])
    for r in turn.responses:
        ids.update(r.cited_claim_ids)
    for b in bases:
        ids.update(b.new_claim_ids)
        if b.computation:
            ids.update(CLAIM_ID_IN_TEXT_RE.findall(b.computation))
    return ids


@dataclass
class History:
    """What a role said before round N: the ids it cited and its current proposed change."""

    cited: set[str]
    proposal: str


def history(run_id: str, role: str, round_no: int) -> History:
    """From the role's files of rounds 0..N-1. A later round's turn counts only when it was not
    rejected (no `REJECTED_<role>` marker): a rejected turn never entered the debate."""
    path0 = round_dir(run_id, 0) / f"{role}.json"
    if not path0.exists():
        return History(set(), "")
    position = _load_model(path0, Position)
    cited = turn_claim_ids(position)
    proposal = position.proposed_change
    for n in range(1, round_no):
        path = round_dir(run_id, n) / f"{role}.json"
        if not path.exists() or role in rejected_roles(run_id, n):
            continue
        try:
            turn = Rebuttal.model_validate_json(path.read_text(encoding="utf-8"))
        except ValidationError:
            continue
        cited |= turn_claim_ids(turn)
        if turn.updated_change is not None:
            proposal = turn.updated_change
    return History(cited, proposal)


def _same_text(a: str, b: str) -> bool:
    return " ".join(a.split()).casefold() == " ".join(b.split()).casefold()


def _support_problems(basis: Basis | None, where: str, cited_before: set[str]) -> list[str]:
    """`agree` / `modify` / a changed proposal: new claim ids never cited before, or a computation."""
    if basis is None:
        return [f"{where}: needs a basis with new_claim_ids or a computation"]
    problems = []
    old = [cid for cid in basis.new_claim_ids if cid in cited_before]
    if old:
        problems.append(f"{where}: {', '.join(old)} already cited in an earlier turn, so not new evidence")
    if basis.computation is not None:
        comp = basis.computation
        if not (CLAIM_ID_IN_TEXT_RE.search(comp) and _NUMBER_RE.search(CLAIM_ID_IN_TEXT_RE.sub(" ", comp))):
            problems.append(f"{where}: the computation must show a number derived from at least one cited claim id")
    elif not basis.new_claim_ids:
        problems.append(
            f"{where}: needs basis.new_claim_ids (not cited before) or a basis.computation, not only an evidence_gap"
        )
    return problems


def _claim_problems(ids: set[str], ledger: dict[str, Claim], allowed: set[str]) -> list[str]:
    """Every cited id must be a verified ledger claim in the persona's evidence subset
    (`allowed_claim_ids`): persona briefs argue only from their own evidence (plan §6 stage 7)."""
    problems = []
    for cid in sorted(ids):
        claim = ledger.get(cid)
        if claim is None:
            problems.append(f"claim id {cid} does not exist in the ledger")
        elif claim.verification != "verified":
            problems.append(f"claim id {cid} is {claim.verification}, only verified claims may be cited")
        elif cid not in allowed:
            problems.append(
                f"claim id {cid} is not in your evidence file; cite only its claims or mini_research_claims"
            )
    return problems


def check_position(turn: Position, *, role: str, ledger: dict[str, Claim], allowed: set[str]) -> list[str]:
    """Rejection reasons for one round-0 position (empty: accepted)."""
    problems = []
    if turn.role != role:
        problems.append(f"role is {turn.role!r} but the file belongs to {role!r}")
    return problems + _claim_problems(turn_claim_ids(turn), ledger, allowed)


def position_problems(path: Path) -> list[str]:
    """`check_position` for `runs/<run_id>/debate/round0/<role>.json`, used by validate_file.
    A file outside a run with a claim ledger has nothing to check against and passes."""
    role, run_dir = path.stem, path.parents[2]
    if role not in PERSONAS or path.parent.name != "round0" or path.parents[1].name != "debate":
        return []
    if not (run_dir / "03_claims" / "verified.json").exists():
        return []
    ledger = load_ledger(run_dir)
    turn = _load_model(path, Position)
    return check_position(turn, role=role, ledger=ledger, allowed=allowed_claim_ids(run_dir, role, ledger))


def check_rebuttal(
    turn: Rebuttal,
    *,
    role: str,
    round_no: int,
    own_id: str,
    position_ids: set[str],
    past: History,
    ledger: dict[str, Claim],
    allowed: set[str],
) -> list[str]:
    """Rejection reasons for one rebuttal (empty: accepted). The mini-research limit is per round
    and checked by `validate_round`."""
    problems = []
    if turn.role != role:
        problems.append(f"role is {turn.role!r} but the file belongs to {role!r}")
    if turn.round != round_no:
        problems.append(f"round is {turn.round} but the file is in round{round_no}/")
    for i, r in enumerate(turn.responses, start=1):
        where = f"response {i} ({r.stance} {r.target_position_id})"
        if r.target_position_id == own_id:
            problems.append(f"{where}: targets your own position; change it through updated_change instead")
        elif r.target_position_id not in position_ids:
            problems.append(f"{where}: unknown position id (known: {', '.join(sorted(position_ids))})")
        if r.stance in ("agree", "modify"):
            problems += _support_problems(r.basis, where, past.cited)
        elif not (r.cited_claim_ids or r.basis.new_claim_ids or r.basis.evidence_gap):
            problems.append(f"{where}: a disagree needs a claim id in cited_claim_ids or a basis.evidence_gap")
    if turn.updated_change is not None and not _same_text(turn.updated_change, past.proposal):
        problems += _support_problems(turn.updated_change_basis, "updated_change", past.cited)
    if turn.mini_research is not None and turn.mini_research.requested_by != role:
        problems.append(f"mini_research.requested_by is {turn.mini_research.requested_by!r}, not {role!r}")
    problems += _claim_problems(turn_claim_ids(turn), ledger, allowed)
    return problems


@dataclass
class RoundResult:
    accepted: list[str] = field(default_factory=list)
    rejected: dict[str, list[str]] = field(default_factory=dict)  # role → reasons


def validate_round(run_id: str, round_no: int) -> RoundResult:
    """Check every persona's rebuttal of round N ≥ 1; write REJECTED_<role> markers and turns."""
    if round_no < 1:
        raise DebateError("rebuttal rounds start at 1; round-0 positions are checked by the SubagentStop hook")
    run_dir = _check_run(run_id)
    d = round_dir(run_id, round_no)
    if not d.is_dir():
        raise DebateError(f"{d} does not exist")
    mapping = load_mapping(run_id)
    anon0 = round_dir(run_id, 0) / ANON_NAME
    try:
        position_ids = {e["position_id"] for e in json.loads(anon0.read_text(encoding="utf-8"))["positions"]}
    except FileNotFoundError:
        raise DebateError(f"{anon0} does not exist; run `debate anonymize {run_id} 0` first") from None
    ledger = load_ledger(run_dir)

    result = RoundResult()
    turns: dict[str, Rebuttal] = {}
    raws: dict[str, str] = {}
    for role in PERSONAS:
        path = d / f"{role}.json"
        if not path.exists():
            result.rejected[role] = [f"no rebuttal file round{round_no}/{role}.json"]
            continue
        raw = path.read_text(encoding="utf-8")
        try:
            turn = Rebuttal.model_validate_json(raw)
        except ValidationError as e:
            err = e.errors()[0]
            loc = ".".join(str(p) for p in err["loc"]) or "file"
            result.rejected[role] = [f"not a valid Rebuttal: {loc}: {err['msg']}"]
            record_turn(run_id, round_no, role, mapping[role], raw, result.rejected[role])
            continue
        turns[role] = turn
        raws[role] = raw
        reasons = check_rebuttal(
            turn,
            role=role,
            round_no=round_no,
            own_id=mapping[role],
            position_ids=position_ids,
            past=history(run_id, role, round_no),
            ledger=ledger,
            allowed=allowed_claim_ids(run_dir, role, ledger),
        )
        if reasons:
            result.rejected[role] = reasons

    # At most one mini-research request per round: the lowest P-id keeps it, the others are
    # sent back to drop theirs. Once earlier rounds used the preset's `max_mini_research_tasks`,
    # every request is sent back (IF-404; mini_research.open_task refuses a fourth as well).
    requesting = sorted((r for r, t in turns.items() if t.mini_research), key=lambda r: int(mapping[r][1:]))
    cap = debate_budget(run_id).max_mini_research_tasks if requesting else 0
    used = sum(t["round"] < round_no for t in db.mini_research_tasks(run_id)) if requesting else 0
    if requesting and used >= cap:
        for role in requesting:
            result.rejected.setdefault(role, []).append(
                f"mini_research: this debate already ran {used} mini-research task(s), the limit of the run's "
                f"budget preset (max_mini_research_tasks: {cap}); drop it"
            )
        requesting = []
    for role in requesting[1:]:
        result.rejected.setdefault(role, []).append(
            f"mini_research: {mapping[requesting[0]]} already requested one this round (at most 1 per round); "
            "drop yours"
        )

    for role in PERSONAS:
        marker = d / f"{REJECTED_PREFIX}{role}"
        reasons = result.rejected.get(role)
        if role in turns:
            record_turn(run_id, round_no, role, mapping[role], raws[role], reasons or [])
        if reasons:
            marker.write_text("".join(f"{r}\n" for r in reasons), encoding="utf-8")
        else:
            marker.unlink(missing_ok=True)
            result.accepted.append(role)
    return result


# ---------------------------------------------------------------- rounds, convergence, conformity


def round_numbers(run_id: str) -> list[int]:
    """The debate's round directories, in order."""
    d = debate_dir(run_id)
    if not d.is_dir():
        return []
    return sorted(int(p.name[5:]) for p in d.glob("round*") if p.is_dir() and p.name[5:].isdigit())


def accepted_turns(run_id: str, round_no: int) -> dict[str, Position | Rebuttal]:
    """Round N's turns that entered the debate, by role: the file's latest `debate_turns` row must
    hold the file's current text and be accepted. A file never checked in its current form (round
    0: not anonymized, later rounds: not validated) is an error, not a silent skip."""
    d = round_dir(run_id, round_no)
    if not d.is_dir():
        raise DebateError(f"{d} does not exist")
    with db.session() as conn:
        rows = conn.execute(
            "SELECT role, accepted, payload FROM debate_turns WHERE run_id=? AND round=? ORDER BY attempt",
            (run_id, round_no),
        ).fetchall()
    latest = {r["role"]: r for r in rows}
    step = f"debate anonymize {run_id} 0" if round_no == 0 else f"scripts/debate_validate.py {run_id} {round_no}"
    model = Position if round_no == 0 else Rebuttal
    if not any((d / f"{role}.json").exists() for role in PERSONAS):
        raise DebateError(f"round{round_no}/ has no persona file")
    turns: dict[str, Position | Rebuttal] = {}
    for role in PERSONAS:
        path = d / f"{role}.json"
        if not path.exists():
            continue
        raw = path.read_text(encoding="utf-8")
        row = latest.get(role)
        if row is None or row["payload"] != raw:
            raise DebateError(f"round{round_no}/{role}.json was not checked in its current form; run {step} first")
        if row["accepted"]:
            turns[role] = _load_model(path, model)
    return turns


@dataclass
class RoundSummary:
    """What one round brought into the debate."""

    round: int
    turns: dict[str, Position | Rebuttal]
    new_claim_ids: set[str]  # cited for the first time in the whole debate
    moved: dict[str, str]  # role → its changed proposal
    mini_research: list[str]  # roles whose accepted turn requests mini-research


def summarize_rounds(run_id: str, upto: int) -> list[RoundSummary]:
    """Rounds 0..upto from the accepted turns. Round 0 has no new ids and no moves: it is the start."""
    summaries = []
    seen: set[str] = set()
    proposals: dict[str, str] = {}
    for n in range(upto + 1):
        turns = accepted_turns(run_id, n)
        ids = set().union(*(turn_claim_ids(t) for t in turns.values()))
        moved: dict[str, str] = {}
        if n == 0:
            proposals = {r: t.proposed_change for r, t in turns.items() if isinstance(t, Position)}
        else:
            for role, t in turns.items():
                if isinstance(t, Rebuttal) and t.updated_change is not None:
                    if not _same_text(t.updated_change, proposals.get(role, "")):
                        moved[role] = t.updated_change
                    proposals[role] = t.updated_change
        summaries.append(
            RoundSummary(
                round=n,
                turns=turns,
                new_claim_ids=set() if n == 0 else ids - seen,
                moved=moved,
                mini_research=sorted(r for r, t in turns.items() if isinstance(t, Rebuttal) and t.mini_research),
            )
        )
        seen |= ids
    return summaries


# Plan §6 stage 7 step 5: "≥ 4 of 5 personas agree on the same change".
CONFORMITY_MIN_AGREE = 4


def backers(turns: dict[str, Position | Rebuttal], mapping: dict[str, str]) -> dict[str, set[str]]:
    """Position id → the personas that back its change in this round: its author, who holds it
    (also when its own turn this round was rejected or missing, or it moved the change), plus
    every persona whose accepted turn has an `agree` response on it."""
    out = {pid: {role} for role, pid in mapping.items()}
    for role, turn in turns.items():
        if isinstance(turn, Rebuttal):
            for r in turn.responses:
                if r.stance == "agree" and r.target_position_id in out:
                    out[r.target_position_id].add(role)
    return out


def conformity_flag(
    turns: dict[str, Position | Rebuttal], mapping: dict[str, str], new_claim_ids: set[str]
) -> bool:
    """True when ≥ 4 of the 5 personas back the same change while zero new claim ids entered the
    debate: agreement without new evidence is a warning sign, not support (plan §0.7)."""
    if new_claim_ids:
        return False
    return any(len(b) >= CONFORMITY_MIN_AGREE for b in backers(turns, mapping).values())


def run_conformity_flag(run_id: str) -> bool:
    """The flag for the debate as it ended: the stances of its last rebuttal round, and the claim
    ids that entered in any round ≥ 1 (a debate without a rebuttal round has no stances: false)."""
    last = max(round_numbers(run_id), default=0)
    if last < 1:
        return False
    summaries = summarize_rounds(run_id, last)
    new_ids = set().union(*(s.new_claim_ids for s in summaries))
    return conformity_flag(summaries[-1].turns, load_mapping(run_id), new_ids)


def debate_budget(run_id: str) -> config.DebateBudget:
    """The `debate` budget of the run's preset (`runs.budget_preset`)."""
    with db.session() as conn:
        row = conn.execute("SELECT budget_preset FROM runs WHERE run_id=?", (run_id,)).fetchone()
    budget = config.budget()
    name = row["budget_preset"] if row else None
    if name not in budget.presets:
        raise DebateError(f"run {run_id} has budget preset {name!r}, which config/budget.yaml does not define")
    return budget.preset(name).debate


def load_interim(run_id: str, round_no: int) -> InterimScores | None:
    path = round_dir(run_id, round_no) / INTERIM_NAME
    if not path.exists():
        return None
    interim = _load_model(path, InterimScores)
    if interim.round != round_no:
        raise DebateError(f"{path} has round {interim.round}, expected {round_no}")
    return interim


def _report_scores(run_dir: Path) -> dict[str, float]:
    """The score sheet's final scores, the baseline for the first interim projection."""
    path = run_dir / "04_scores.json"
    sheet = _load_model(path, ScoreSheet)
    return {s.dimension: s.final_score for s in sheet.scores if s.final_score is not None}


@dataclass
class Convergence:
    round: int
    max_rounds: int
    met: list[str] = field(default_factory=list)  # the stop conditions that hold
    notes: list[str] = field(default_factory=list)  # why the others do not

    @property
    def stop(self) -> bool:
        return bool(self.met)


def check_convergence(run_id: str, round_no: int) -> Convergence:
    """Plan §6 stage 7 step 4, after round N ≥ 1 is validated: stop when (a) no new claim id entered
    and no proposed change moved, (b) the judge's interim projected scores moved less than
    `convergence_score_delta` on every dimension, or (c) round N is the preset's `max_rounds`."""
    if round_no < 1:
        raise DebateError("convergence is checked after a rebuttal round (1 or more)")
    run_dir = _check_run(run_id)
    if not round_dir(run_id, round_no).is_dir():
        raise DebateError(f"{round_dir(run_id, round_no)} does not exist")
    load_mapping(run_id)
    budget = debate_budget(run_id)
    result = Convergence(round_no, budget.max_rounds)
    current = summarize_rounds(run_id, round_no)[-1]

    # (a) A mini-research request brings new claim ids into the next round, so it counts as new evidence.
    blockers = []
    if current.new_claim_ids:
        blockers.append(f"new claim ids {', '.join(sorted(current.new_claim_ids))}")
    if current.moved:
        blockers.append(f"proposed change moved for {len(current.moved)} position(s)")
    if current.mini_research:
        blockers.append("a mini-research request brings new claims next round")
    if blockers:
        result.notes.append("(a) not met: " + "; ".join(blockers))
    else:
        result.met.append(f"(a) round {round_no} introduced no new claim ids and moved no proposed change")

    # (b) Interim projected scores against the previous interim (or, before the first, the score sheet).
    delta = budget.convergence_score_delta
    interim = load_interim(run_id, round_no)
    if interim is None:
        result.notes.append(f"(b) not met: no round{round_no}/{INTERIM_NAME}")
    else:
        prev = next((p for n in range(round_no - 1, -1, -1) if (p := load_interim(run_id, n))), None)
        baseline = prev.projected_scores if prev else _report_scores(run_dir)
        source = f"round {prev.round}" if prev else "04_scores.json"
        dims = sorted(set(interim.projected_scores) | set(baseline))
        moved = [
            d for d in dims
            if d not in interim.projected_scores or d not in baseline
            or round(abs(interim.projected_scores[d] - baseline[d]), 6) >= delta
        ]  # fmt: skip
        if not dims:
            result.notes.append("(b) not met: no projected scores to compare")
        elif moved:
            result.notes.append(f"(b) not met: moved ≥ {delta:g} against {source} on {', '.join(moved)}")
        else:
            result.met.append(f"(b) projected scores moved < {delta:g} against {source} on every dimension")

    if round_no >= budget.max_rounds:
        result.met.append(f"(c) round {round_no} reached max_rounds {budget.max_rounds}")
    else:
        result.notes.append(f"(c) not met: round {round_no} of max_rounds {budget.max_rounds}")

    with db.session() as conn:
        conn.execute("UPDATE debates SET rounds=? WHERE run_id=?", (round_no, run_id))
    return result


# ---------------------------------------------------------------- verdict


@dataclass
class FinalVerdict:
    verdict: Verdict
    judge_flag: bool  # what the judge wrote, kept so the revised plan can show a disagreement
    rounds: int


def finalize_verdict(run_id: str) -> FinalVerdict:
    """Check `debate/verdict.json` and return it with the computed `conformity_flag` (the file is
    not written here; see `write_verdict`).

    Every claim id of an accepted change must be in the ledger and verified; otherwise DebateError
    lists them all."""
    run_dir = _check_run(run_id)
    path = debate_dir(run_id) / VERDICT_NAME
    verdict = _load_model(path, Verdict)
    ledger = load_ledger(run_dir)
    problems = []
    for i, change in enumerate(verdict.accepted_changes, start=1):
        for cid in change.claim_ids:
            claim = ledger.get(cid)
            if claim is None:
                problems.append(f"accepted change {i} cites {cid}, which is not in the ledger")
            elif claim.verification != "verified":
                problems.append(f"accepted change {i} cites {cid}, which is {claim.verification}")
    if problems:
        raise DebateError(f"{path.name} is not accepted:\n" + "\n".join(f"  - {p}" for p in problems))
    flag = run_conformity_flag(run_id)
    judge_flag = verdict.conformity_flag
    if flag != judge_flag:
        verdict = verdict.model_copy(update={"conformity_flag": flag})
    return FinalVerdict(verdict, judge_flag, max(round_numbers(run_id), default=0))


def write_verdict(run_id: str, final: FinalVerdict) -> None:
    """Store the computed `conformity_flag` in `debate/verdict.json` (no write when the judge's
    value was right). Called only once the revised plan is committed, so a failed render leaves
    the judge's file, and the judge's disagreement, as they were. If this write itself fails, the
    plan and the `debates` row already hold the computed flag and only verdict.json keeps the judge's."""
    if final.verdict.conformity_flag != final.judge_flag:
        _write_json(debate_dir(run_id) / VERDICT_NAME, final.verdict.model_dump(mode="json"))


# ---------------------------------------------------------------- persona evidence subsets (IF-401)


def mini_claim_ids(run_dir: Path) -> set[str]:
    """Ids of the claims the debate's mini-research brought in (03_claims/mini-<n>-<dim>.json)."""
    ids: set[str] = set()
    for path in (run_dir / "03_claims").glob("mini-*.json"):
        if agents.parse_mini_stem(path.stem):
            ids |= {c.claim_id for c in TypeAdapter(list[Claim]).validate_json(path.read_bytes())}
    return ids


def _ledger_digest(run_dir: Path) -> str:
    return hashlib.sha256((run_dir / "03_claims" / "verified.json").read_bytes()).hexdigest()


def evidence_path(run_id: str, role: str) -> Path:
    return debate_dir(run_id) / EVIDENCE_DIR / f"{role}.json"


def _subset(run_dir: Path, role: str, ledger: dict[str, Claim]) -> tuple[list[Claim], list[Claim]]:
    """(the verified claims of the role's dimensions, every verified mini-research claim)."""
    dims = agents.PERSONA_EVIDENCE[role] or RESEARCH_DIMENSIONS
    mini = mini_claim_ids(run_dir)
    verified = [c for c in ledger.values() if c.verification == "verified"]
    return (
        [c for c in verified if c.claim_id not in mini and c.dimension in dims],
        [c for c in verified if c.claim_id in mini],
    )


def allowed_claim_ids(run_dir: Path, role: str, ledger: dict[str, Claim] | None = None) -> set[str]:
    """The claim ids a persona may cite: exactly the ids of its evidence file, from the current
    ledger (the file itself is rewritten whenever the ledger changes, see `stale_evidence`)."""
    own, mini = _subset(run_dir, role, load_ledger(run_dir) if ledger is None else ledger)
    return {c.claim_id for c in own + mini}


def evidence_subset(run_dir: Path, role: str, position_id: str) -> dict[str, Any]:
    """A persona's evidence file: the verified claims of its dimensions (`agents.PERSONA_EVIDENCE`,
    plan §6 stage 7) and every verified mini-research claim, which entered the debate for all."""
    own, mini = _subset(run_dir, role, load_ledger(run_dir))
    return {
        "role": role,
        "position_id": position_id,
        "dimensions": list(agents.PERSONA_EVIDENCE[role] or RESEARCH_DIMENSIONS),
        "ledger_sha256": _ledger_digest(run_dir),
        "claims": [c.model_dump(mode="json") for c in own],
        "mini_research_claims": [c.model_dump(mode="json") for c in mini],
    }


def write_evidence(run_id: str, *, seed: int | None = None) -> list[Path]:
    """Write `debate/evidence/<role>.json` for every persona from the current ledger. Creates the
    debate's seed and mapping on first use (the file names the persona's own P-id)."""
    run_dir = _check_run(run_id)
    mapping = ensure_mapping(run_id, seed)
    paths = []
    for role in PERSONAS:
        path = evidence_path(run_id, role)
        _write_json(path, evidence_subset(run_dir, role, mapping[role]))
        paths.append(path)
    return paths


def stale_evidence(run_id: str) -> list[str]:
    """Personas whose evidence file is missing or was built from another ledger."""
    digest = _ledger_digest(runs.run_dir(run_id))
    stale = []
    for role in PERSONAS:
        try:
            ok = json.loads(evidence_path(run_id, role).read_text(encoding="utf-8")).get("ledger_sha256") == digest
        except (FileNotFoundError, json.JSONDecodeError, AttributeError):
            ok = False
        if not ok:
            stale.append(role)
    return stale


# ---------------------------------------------------------------- re-prompts


def reprompted(run_id: str, round_no: int) -> set[str]:
    path = round_dir(run_id, round_no) / REPROMPTED_NAME
    return set(path.read_text(encoding="utf-8").split()) if path.exists() else set()


def reprompt(run_id: str, round_no: int) -> tuple[list[str], list[str]]:
    """(roles to re-prompt now, roles whose rejection is final): each rejected persona is sent
    back once per round. The roles are recorded in `round<N>/.reprompted` before they are
    returned, so a resumed session never re-prompts one twice."""
    if round_no < 1:
        raise DebateError("re-prompts are for rebuttal rounds (1 or more)")
    _check_run(run_id)
    done = reprompted(run_id, round_no)
    rejected = rejected_roles(run_id, round_no)
    now = [r for r in rejected if r not in done]
    if now:
        path = round_dir(run_id, round_no) / REPROMPTED_NAME
        path.write_text("".join(f"{r}\n" for r in PERSONAS if r in done or r in now), encoding="utf-8")
    return now, [r for r in rejected if r in done]


# ---------------------------------------------------------------- resume


# The steps `progress` names, in debate order; the /debate skill's Start section maps each one.
STEPS = (
    "report", "evidence", "positions", "anonymize", "rebuttals", "validate", "reprompt",
    "mini-research", "verify", "interim", "judge", "render", "done",
)  # fmt: skip


@dataclass
class Progress:
    """The debate's next step for the /debate skill (resumable per round)."""

    step: str  # one of STEPS
    round: int | None = None
    roles: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def line(self) -> str:
        parts = [f"next: {self.step}"]
        if self.round is not None:
            parts.append(f"round {self.round}")
        if self.roles:
            parts.append(", ".join(self.roles))
        return " ".join(parts)


def _unchecked(run_id: str, round_no: int) -> list[str]:
    """Roles whose round-N file was not anonymized (round 0) or validated in its current form."""
    d = round_dir(run_id, round_no)
    with db.session() as conn:
        rows = conn.execute(
            "SELECT role, payload FROM debate_turns WHERE run_id=? AND round=? ORDER BY attempt",
            (run_id, round_no),
        ).fetchall()
    latest = {r["role"]: r["payload"] for r in rows}
    return [
        role for role in PERSONAS
        if (d / f"{role}.json").exists() and latest.get(role) != (d / f"{role}.json").read_text(encoding="utf-8")
    ]  # fmt: skip


def progress(run_id: str) -> Progress:
    """Where a debate stands, from its files and rows. Every step it names is idempotent, so a
    crashed session resumes at the step it was in."""
    run_dir = _check_run(run_id)
    d = debate_dir(run_id)
    if (d / "revised_plan.md").exists():
        return Progress("done")
    if not (run_dir / "05_report.md").exists():
        return Progress("report", notes=["no 05_report.md: run /synthesize first"])
    if (d / VERDICT_NAME).exists():
        return Progress("render")
    tasks = db.mini_research_tasks(run_id)
    ledger_ids = set(load_ledger(run_dir))
    done_unverified = [
        t for t in tasks
        if t["status"] == "done" and not _mini_claim_ids(run_dir, t["n"], t["dimension"]) <= ledger_ids
    ]  # fmt: skip
    if done_unverified:
        t = done_unverified[0]
        return Progress("verify", t["round"], notes=[f"mini-{t['n']}-{t['dimension']}"])
    if stale := stale_evidence(run_id):
        return Progress("evidence", roles=stale)

    r0 = round_dir(run_id, 0)
    if not (r0 / ANON_NAME).exists():
        missing = [r for r in PERSONAS if not (r0 / f"{r}.json").exists()]
        return Progress("positions", 0, missing) if missing else Progress("anonymize", 0)
    if unchecked := _unchecked(run_id, 0):
        return Progress("anonymize", 0, unchecked)

    rounds = [n for n in round_numbers(run_id) if n >= 1]
    if not rounds:
        return Progress("rebuttals", 1, list(PERSONAS))
    n = rounds[-1]
    rd = round_dir(run_id, n)
    rejected = rejected_roles(run_id, n)
    missing = [r for r in PERSONAS if not (rd / f"{r}.json").exists() and r not in rejected]
    if missing:
        return Progress("rebuttals", n, missing)
    if (unchecked := _unchecked(run_id, n)) or not any((rd / f"{r}.json").exists() for r in PERSONAS):
        return Progress("validate", n, unchecked)
    if again := [r for r in rejected if r not in reprompted(run_id, n)]:
        return Progress("reprompt", n, again)

    task = next((t for t in tasks if t["round"] == n), None)
    requested = any(t.mini_research for t in accepted_turns(run_id, n).values())
    room = len(tasks) < debate_budget(run_id).max_mini_research_tasks
    if (task is None and requested and room) or (task is not None and task["status"] == "running"):
        return Progress("mini-research", n, notes=[] if task is None else [f"task {task['n']} is running"])
    if not (rd / ANON_NAME).exists() or _anon_stale(run_id, n):
        return Progress("anonymize", n)
    if load_interim(run_id, n) is None and not (rd / INTERIM_SKIPPED_NAME).exists():
        return Progress("interim", n)
    convergence = check_convergence(run_id, n)
    if convergence.stop:
        return Progress("judge", n, notes=convergence.met)
    return Progress("rebuttals", n + 1, list(PERSONAS), notes=convergence.notes)


def _mini_claim_ids(run_dir: Path, n: int, dimension: str) -> set[str]:
    """The candidate claim ids of a mini-research file. `verify_claims.py --only` writes its
    03_claims/<stem>.json before fetching, so only the ledger shows that verification finished."""
    md = agents.mini_output(run_dir, n, dimension)
    return {c.claim_id for c in candidate_claims(md.read_text(encoding="utf-8"))[0]} if md.exists() else set()


def skip_interim(run_id: str, round_no: int) -> Path:
    """Set round N's interim projection aside after the judge failed it twice: an invalid file is
    renamed (kept for reading), a missing one is recorded. (b) then does not hold for the round,
    and later rounds compare with the latest valid interim file or the score sheet."""
    _check_run(run_id)
    d = round_dir(run_id, round_no)
    if not d.is_dir():
        raise DebateError(f"{d} does not exist")
    path, skipped = d / INTERIM_NAME, d / INTERIM_SKIPPED_NAME
    if path.exists():
        path.replace(skipped)
    else:
        skipped.write_text("the judge wrote no interim_scores.json\n", encoding="utf-8")
    return skipped


def _anon_stale(run_id: str, round_no: int) -> bool:
    """positions_anon.json of a rebuttal round lists other P-ids than the round's accepted turns."""
    path = round_dir(run_id, round_no) / ANON_NAME
    listed = {e["position_id"] for e in json.loads(path.read_text(encoding="utf-8"))["positions"]}
    mapping = load_mapping(run_id)
    return listed != {mapping[r] for r in accepted_turns(run_id, round_no)}


# ---------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ideaforge.debate", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    anon = sub.add_parser("anonymize", help="write debate/round<N>/positions_anon.json")
    anon.add_argument("run_id")
    anon.add_argument("round", type=int)
    anon.add_argument("--seed", type=int, default=None, help="seed for a new debate (must match a stored one)")
    evidence = sub.add_parser("evidence", help="write debate/evidence/<role>.json from the current ledger")
    evidence.add_argument("run_id")
    evidence.add_argument("--seed", type=int, default=None, help="seed for a new debate (must match a stored one)")
    again = sub.add_parser("reprompt", help="list the rejected personas of round N to send back once")
    again.add_argument("run_id")
    again.add_argument("round", type=int)
    skip = sub.add_parser("skip-interim", help="set round N's interim projection aside after two failures")
    skip.add_argument("run_id")
    skip.add_argument("round", type=int)
    status = sub.add_parser("status", help="print the debate's next step")
    status.add_argument("run_id")
    args = parser.parse_args(argv)

    try:
        if args.command == "evidence":
            for path in write_evidence(args.run_id, seed=args.seed):
                data = json.loads(path.read_text(encoding="utf-8"))
                print(f"{data['role']}: {len(data['claims'])} claims, {len(data['mini_research_claims'])} mini-research"
                      f" ({', '.join(data['dimensions'])})")
            return 0
        if args.command == "reprompt":
            now, final = reprompt(args.run_id, args.round)
            for role in now:
                print(f"reprompt: {role} (round{args.round}/{REJECTED_PREFIX}{role})")
            for role in final:
                print(f"final: {role} was already sent back once; it stays out of round {args.round}")
            if not now and not final:
                print("nothing to re-prompt")
            return 0
        if args.command == "skip-interim":
            path = skip_interim(args.run_id, args.round)
            print(f"set aside: {path.relative_to(runs.run_dir(args.run_id)).as_posix()}; (b) does not hold for round {args.round}")
            return 0
        if args.command == "status":
            result = progress(args.run_id)
            for note in result.notes:
                print(note)
            print(result.line())
            return 0
        result = anonymize(args.run_id, args.round, seed=args.seed)
    except DebateError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if result.missing:
        print(f"warning: no file for {', '.join(result.missing)}", file=sys.stderr)
    if result.excluded:
        print(f"warning: rejected rebuttals left out: {', '.join(result.excluded)}", file=sys.stderr)
    print(f"wrote {result.path.relative_to(runs.run_dir(args.run_id)).as_posix()}: {', '.join(result.position_ids)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
