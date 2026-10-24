"""Debate mini-research tasks (plan §6 stage 7 step 3, IF-404).

    uv run python -m ideaforge.mini_research open <run_id> <round>
    uv run python -m ideaforge.mini_research finish <run_id> <n>

`open` turns round N's accepted `MiniResearchRequest` (scripts/debate_validate.py keeps at most
one per round) into task n of the debate: a `mini_research` row, the output file
`02_research/mini-<n>-<dimension>.md` and the first claim number for its ids. It prints the brief
the /debate skill passes to the dimension's research subagent. At most the run preset's
`max_mini_research_tasks` tasks per debate (config/budget.yaml): a request beyond that is refused
(exit 3). Opening a round's task again prints the same task.

While a task is running, the pipeline guard lets the dimension's research agent write only the
task's file and the SubagentStop hook validates that file (`agents.research_target`).

`finish` validates the file against the research output contract (validate_file, which also
refuses claim ids the run already has). Valid → `done` (exit 0); then
`scripts/verify_claims.py <run_id> --only mini-<n>-<dimension>` verifies its claims and
`python -m ideaforge.debate evidence <run_id>` gives them to every persona for the next round.
Invalid on the first launch → exit 2 with the errors (re-launch the agent once). Invalid on the
second → `failed` (exit 3): the file is renamed to `.md.failed`, so its claims never reach the
ledger, and the task still counts against the limit. Exit 1: bad input. Rule choices: TICKETS.md
plan note 27.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from ideaforge import agents, config, db, debate, runs
from ideaforge.validate_file import Invalid, claim_ids_elsewhere, validate_research

MAX_LAUNCHES = 2  # the first launch plus one re-launch, as for stage-2 research


class Refused(Exception):
    """The debate already ran its preset's `max_mini_research_tasks` tasks."""


@dataclass(frozen=True)
class Task:
    n: int
    round: int
    role: str
    anon_id: str
    dimension: str
    question: str
    claim_start: int
    status: str  # running | done | failed
    attempts: int
    reason: str | None

    @property
    def stem(self) -> str:
        return f"mini-{self.n}-{self.dimension}"

    def output(self, run_id: str) -> Path:
        return agents.mini_output(runs.run_dir(run_id), self.n, self.dimension)

    @property
    def agent(self) -> str:
        spec = agents.research_agent(self.dimension)
        assert spec is not None  # MiniResearchRequest.dimension is a research dimension
        return spec.name


def _task(row) -> Task:
    return Task(
        row["n"], row["round"], row["role"], row["anon_id"], row["dimension"], row["question"],
        row["claim_start"], row["status"], row["attempts"], row["reason"],
    )  # fmt: skip


def tasks(run_id: str) -> list[Task]:
    return [_task(r) for r in db.mini_research_tasks(run_id)]


def get(run_id: str, n: int) -> Task:
    task = next((t for t in tasks(run_id) if t.n == n), None)
    if task is None:
        raise debate.DebateError(f"run {run_id} has no mini-research task {n}")
    return task


def claim_start(run_dir: Path, dimension: str) -> int:
    """The first claim number for a new task's ids: past every `<dimension>-NNN` id the run has,
    rounded up to the next hundred plus one (pricing-001…012 → pricing-101)."""
    pattern = re.compile(rf"^{re.escape(dimension)}-(\d+)$")
    numbers = [int(m.group(1)) for i in claim_ids_elsewhere(run_dir, "") if (m := pattern.match(i or ""))]
    return (max(numbers, default=0) // 100 + 1) * 100 + 1


def open_task(run_id: str, round_no: int) -> Task | None:
    """Task n for round N's accepted request (None: the round requested nothing)."""
    if round_no < 1:
        raise debate.DebateError("mini-research is requested in rebuttal rounds (1 or more)")
    run_dir = debate._check_run(run_id)
    existing = tasks(run_id)
    for t in existing:
        if t.round == round_no:
            return t
    running = [t for t in existing if t.status == "running"]
    if running:
        raise debate.DebateError(f"task {running[0].n} (round {running[0].round}) is still running; finish it first")
    turns = debate.accepted_turns(run_id, round_no)
    requests = [(role, t.mini_research) for role, t in turns.items() if t.mini_research is not None]
    if not requests:
        return None
    mapping = debate.load_mapping(run_id)
    role, request = min(requests, key=lambda r: int(mapping[r[0]][1:]))  # validation leaves one
    cap = debate.debate_budget(run_id).max_mini_research_tasks
    if len(existing) >= cap:
        raise Refused(
            f"this debate already ran {len(existing)} mini-research task(s), the limit of the run's budget preset"
            f" (max_mini_research_tasks: {cap}); round {round_no}'s request is refused"
        )
    n = max((t.n for t in existing), default=0) + 1
    with db.session() as conn:
        conn.execute(
            "INSERT INTO mini_research(run_id, n, round, role, anon_id, dimension, question, claim_start, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (run_id, n, round_no, role, mapping[role], request.dimension, request.question,
             claim_start(run_dir, request.dimension), db.now()),
        )  # fmt: skip
    return get(run_id, n)


@dataclass
class Finish:
    task: Task
    problems: str | None  # the validator's message, when the file failed


def finish_task(run_id: str, n: int) -> Finish:
    """Validate task n's file; mark it `done`, keep it `running` for one re-launch, or `failed`."""
    debate._check_run(run_id)
    task = get(run_id, n)
    if task.status != "running":
        return Finish(task, task.reason if task.status == "failed" else None)
    path = task.output(run_id)
    try:
        validate_research(path)
        problems = None
    except Invalid as e:
        problems = str(e)
    attempts = task.attempts + 1
    status = "done" if problems is None else "failed" if attempts >= MAX_LAUNCHES else "running"
    if status == "failed" and path.exists():
        # Out of verify_claims.py's *.md glob: an invalid file's claims never reach the ledger.
        path.replace(path.with_name(path.name + ".failed"))
    with db.session() as conn:
        conn.execute(
            "UPDATE mini_research SET status=?, attempts=?, reason=?, finished_at=? WHERE run_id=? AND n=?",
            (status, attempts, problems, db.now() if status != "running" else None, run_id, n),
        )
    return Finish(get(run_id, n), problems)


def brief(run_id: str, task: Task) -> list[str]:
    """What the /debate skill passes to the research subagent (plus the spec path it names)."""
    rel = task.output(run_id).relative_to(config.ROOT).as_posix()
    return [
        f"task: {task.n}",
        f"subagent_type: {task.agent}",
        f"run_id: {run_id}",
        f"question: {task.question}",
        f"dimension: {task.dimension}",
        f"output: {rel}",
        f"first claim id: {task.dimension}-{task.claim_start:03d}",
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ideaforge.mini_research", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    opener = sub.add_parser("open", help="open the mini-research task of round N's accepted request")
    opener.add_argument("run_id")
    opener.add_argument("round", type=int)
    finisher = sub.add_parser("finish", help="validate task n's file and record the result")
    finisher.add_argument("run_id")
    finisher.add_argument("n", type=int)
    args = parser.parse_args(argv)

    try:
        if args.command == "open":
            task = open_task(args.run_id, args.round)
            if task is None:
                print(f"round {args.round} requested no mini-research")
                return 0
            print("\n".join(brief(args.run_id, task)))
            print(f"status: {task.status}")
            if task.status == "running" and task.reason:
                print(f"last errors (append them to the re-launch brief):\n{task.reason}")
            return 0
        result = finish_task(args.run_id, args.n)
    except Refused as e:
        print(f"refused: {e}", file=sys.stderr)
        return 3
    except debate.DebateError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    task = result.task
    print(f"task {task.n} ({task.stem}): {task.status} after {task.attempts} launch(es)")
    if result.problems:
        print(result.problems)
    if task.status == "done":
        return 0
    return 2 if task.status == "running" else 3


if __name__ == "__main__":
    sys.exit(main())
