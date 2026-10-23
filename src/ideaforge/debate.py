"""Debate anonymization and rebuttal validation (plan §6 stage 7, IF-402 / IF-403).

    uv run python -m ideaforge.debate anonymize <run_id> <round> [--seed N]

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
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, TypeAdapter, ValidationError

from ideaforge import db, runs
from ideaforge.schemas import PERSONAS, Basis, Claim, Position, Rebuttal

MAPPING_NAME = ".mapping.json"
ANON_NAME = "positions_anon.json"
REJECTED_PREFIX = "REJECTED_"

# Claim ids inside free text (a `basis.computation`); schemas.CLAIM_ID_RE without anchors.
CLAIM_ID_IN_TEXT_RE = re.compile(r"\b[a-z_]+-\d{3,}\b")
_NUMBER_RE = re.compile(r"\d")
_ROLE = "|".join(PERSONAS)
# Self-labels that would tell the reader which persona wrote a position. Persona names as plain
# words stay: "customer", "founder" and "operator" are also ordinary words in a business plan
# (and "customer" is a dimension), so only labelling phrases are replaced: "debate-<role>",
# "<role> persona / lens / here", "as (the|a|an) <role>", "from the <role>'s perspective",
# "I am / I'm / I, the <role>", and the Finnish essive self-labels ("sijoittajana", …).
# "yrittäjänä" and "asiakkaana" stay: Finnish plans use them for the real founder and customers.
_A = r"(?:the\s+|an?\s+|my\s+|our\s+|this\s+|your\s+)"
_FI_ROLE = r"(?:perustaja|sijoittaja|kirjanpitäjä|tilintarkastaja|operaattori)"
_SELF_LABEL_RES = (
    re.compile(rf"\bdebate-(?:{_ROLE})\b", re.IGNORECASE),
    re.compile(rf"\b{_A}?(?:{_ROLE})(?:'s)?\s+(?:persona|lens)\b", re.IGNORECASE),
    re.compile(rf"\b(?:I\s+am|I'm|I,|speaking\s+as)\s+{_A}?(?:{_ROLE})\b(?:'s)?", re.IGNORECASE),
    re.compile(rf"\bas\s+{_A}(?:{_ROLE})\b(?:'s)?", re.IGNORECASE),
    re.compile(
        rf"\bfrom\s+{_A}?(?:{_ROLE})(?:'s|s')?\s+(?:perspective|point\s+of\s+view|view|side|standpoint|angle)\b",
        re.IGNORECASE,
    ),
    re.compile(rf"\b(?:{_ROLE})\s+here\b", re.IGNORECASE),
    re.compile(rf"\b(?:minä|mä)\s+(?:olen\s+)?(?:{_FI_ROLE}|yrittäjä|asiakas)\b", re.IGNORECASE),
    re.compile(rf"\b{_FI_ROLE}na\b", re.IGNORECASE),
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
        text = pattern.sub(REDACTED, text)
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
    _check_run(run_id)
    d = round_dir(run_id, round_no)
    if not d.is_dir():
        raise DebateError(f"{d} does not exist")
    mapping = ensure_mapping(run_id, seed)
    model = Position if round_no == 0 else Rebuttal
    excluded = [r for r in rejected_roles(run_id, round_no) if (d / f"{r}.json").exists()] if round_no > 0 else []
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
        problems.append(f"{where}: needs basis.new_claim_ids (not cited before) or a basis.computation, not only an evidence_gap")
    return problems


def _claim_problems(ids: set[str], ledger: dict[str, Claim]) -> list[str]:
    problems = []
    for cid in sorted(ids):
        claim = ledger.get(cid)
        if claim is None:
            problems.append(f"claim id {cid} does not exist in the ledger")
        elif claim.verification != "verified":
            problems.append(f"claim id {cid} is {claim.verification}, only verified claims may be cited")
    return problems


def check_rebuttal(
    turn: Rebuttal,
    *,
    role: str,
    round_no: int,
    own_id: str,
    position_ids: set[str],
    past: History,
    ledger: dict[str, Claim],
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
    problems += _claim_problems(turn_claim_ids(turn), ledger)
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
        )
        if reasons:
            result.rejected[role] = reasons

    # At most one mini-research request per round: the lowest P-id keeps it, the others are
    # sent back to drop theirs.
    requesting = sorted((r for r, t in turns.items() if t.mini_research), key=lambda r: int(mapping[r][1:]))
    for role in requesting[1:]:
        result.rejected.setdefault(role, []).append(
            f"mini_research: {mapping[requesting[0]]} already requested one this round (at most 1 per round); drop yours"
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


# ---------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ideaforge.debate", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    anon = sub.add_parser("anonymize", help="write debate/round<N>/positions_anon.json")
    anon.add_argument("run_id")
    anon.add_argument("round", type=int)
    anon.add_argument("--seed", type=int, default=None, help="seed for a new debate (must match a stored one)")
    args = parser.parse_args(argv)

    try:
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
