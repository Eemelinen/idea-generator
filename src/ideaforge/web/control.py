"""Pipeline control from the UI (IF-607, TICKETS.md plan notes 36 and 41): the new-idea and
new-version forms, the run actions a run's state allows, the eval action, the job log tail and
the background worker the server runs.

Every action goes through the job queue (`ideaforge.jobs`): a new idea or version is created by
`jobs.enqueue_idea` (so `new_run.py --intake` validates it), a run action by `jobs.enqueue`, and
the jobs run `claude -p` under the strict pipeline guard. Nothing here writes a run's files.
"""

from __future__ import annotations

import json
import math
import sqlite3
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import get_args

from pydantic import ValidationError

from ideaforge import config, db, jobs, runs
from ideaforge.schemas import KILL_TRIGGERS, Goal, Intake
from ideaforge.synthesis import InputError, load_spec

GOALS = get_args(Goal)
DEFAULT_GEOGRAPHY = Intake.model_fields["geography"].default
MAX_ANSWERS = Intake.model_fields["answers"].metadata[0].max_length
# How far a new idea runs: (key, label, the jobs chained after validate).
RUN_TO = (
    ("validate", "validate (stages 0–3)", ()),
    ("synthesize", "validate + synthesize (score and report)", ("synthesize",)),
    ("debate", "validate + synthesize + debate", ("synthesize", "debate")),
)
VALIDATE_STAGES = [s for group in runs.STAGE_GROUPS[:4] for s in group]  # intake … verify
SYNTHESIZE_STAGES = [s for group in runs.STAGE_GROUPS[4:] for s in group]  # synthesize, score, report
# (key, button label) of the run actions, in the order the run page offers them.
RUN_ACTIONS = (
    ("validate", "Resume validate"),
    ("synthesize", "Synthesize"),
    ("debate", "Debate"),
    ("version", "New version"),
)
OPEN = ("queued", "running")
TAIL_BYTES = 64_000  # the log shown when the job page loads
CHUNK_BYTES = 256_000  # at most this much per poll


class FormError(Exception):
    """Form input that queues nothing; `errors` are the messages shown with the form."""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


# ---------------------------------------------------------------- new idea and new version


@dataclass
class IdeaForm:
    """The new-idea form (and the new-version form) as typed, so a refused form is shown again."""

    idea: str = ""
    goal: str = ""
    capital_eur: str = ""
    hours_per_week: str = ""
    skills: str = ""  # one per line
    geography: str = ""  # one per line, nearest first
    preset: str = ""
    as_of: str = ""
    kill_trigger_overrides: list[str] = field(default_factory=list)
    answers: list[tuple[str, str]] = field(default_factory=list)  # (question, answer), MAX_ANSWERS rows
    run_to: str = "validate"

    def __post_init__(self) -> None:
        self.answers = (list(self.answers) + [("", "")] * MAX_ANSWERS)[:MAX_ANSWERS]

    @classmethod
    def defaults(cls) -> IdeaForm:
        """Founder constraints from `config/founder.yaml`, the default geography and preset."""
        founder = config.founder()
        return cls(
            goal=founder.goal,
            capital_eur=_number_text(founder.capital_eur),
            hours_per_week=_number_text(founder.hours_per_week),
            skills="\n".join(founder.skills),
            geography="\n".join(DEFAULT_GEOGRAPHY),
            preset=config.budget().default_preset,
        )

    @classmethod
    def for_version(cls, parent: str) -> IdeaForm:
        """A new version of `parent`: its idea text, preset and as-of date, and the answers of its
        `00_spec.json` when that validates (the founder defaults otherwise)."""
        form = cls.defaults()
        with db.session() as conn:
            row = conn.execute("SELECT idea_text, budget_preset, as_of FROM runs WHERE run_id=?", (parent,)).fetchone()
        if row is not None:
            form.idea, form.preset, form.as_of = row["idea_text"], row["budget_preset"] or form.preset, row["as_of"] or ""
        try:
            spec = load_spec(runs.run_dir(parent))
        except (InputError, ValueError):
            return form
        fc = spec.founder_constraints
        form.goal, form.capital_eur, form.hours_per_week = fc.goal, _number_text(fc.capital_eur), _number_text(fc.hours_per_week)
        if fc.skills:
            form.skills = "\n".join(fc.skills)
        form.geography = "\n".join(spec.geography)
        form.kill_trigger_overrides = list(spec.kill_trigger_overrides)
        form.answers = [(c.question, c.answer) for c in spec.clarifications]
        form.__post_init__()
        return form

    @classmethod
    def from_fields(cls, fields: Mapping[str, str], kill_triggers: list[str]) -> IdeaForm:
        return cls(
            idea=fields.get("idea", ""),
            goal=fields.get("goal", ""),
            capital_eur=fields.get("capital_eur", ""),
            hours_per_week=fields.get("hours_per_week", ""),
            skills=fields.get("skills", ""),
            geography=fields.get("geography", ""),
            preset=fields.get("preset", ""),
            as_of=fields.get("as_of", ""),
            kill_trigger_overrides=kill_triggers,
            answers=[
                (fields.get(f"question_{i}", ""), fields.get(f"answer_{i}", "")) for i in range(1, MAX_ANSWERS + 1)
            ],
            run_to=fields.get("run_to", ""),
        )


@dataclass
class NewRun:
    """A checked form: what `jobs.enqueue_idea` gets."""

    idea: str
    intake: Intake
    preset: str
    as_of: date | None
    then: tuple[str, ...]


def _number_text(value: float) -> str:
    return f"{value:g}"


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _number(text: str, label: str, errors: list[str]) -> float | None:
    cleaned = text.strip().replace(" ", "").replace(" ", "").replace(",", ".")
    if not cleaned:
        errors.append(f"{label} is required")
        return None
    try:
        value = float(cleaned)
    except ValueError:
        errors.append(f"{label} must be a number, not {text.strip()!r}")
        return None
    if not math.isfinite(value):
        errors.append(f"{label} must be a finite number")
        return None
    return value


def _pydantic_errors(e: ValidationError) -> list[str]:
    out = []
    for err in e.errors():
        where = ".".join(str(p) for p in err["loc"])
        out.append(f"{where}: {err['msg']}" if where else err["msg"])
    return out


def check_idea(form: IdeaForm) -> NewRun:
    """The form as a new run, or FormError with every problem found. The intake is validated by
    the `Intake` schema (as `new_run.py --intake` does); nothing is created here."""
    errors: list[str] = []
    idea = form.idea.strip()
    if not idea:
        errors.append("the idea text must not be empty")
    if form.goal not in GOALS:
        errors.append(f"goal must be one of {', '.join(GOALS)}")
    capital = _number(form.capital_eur, "capital (EUR)", errors)
    hours = _number(form.hours_per_week, "hours per week", errors)
    geography = _lines(form.geography)
    if not geography:
        errors.append("geography needs at least one place")
    skills = _lines(form.skills)
    unknown = sorted(set(form.kill_trigger_overrides) - set(KILL_TRIGGERS))
    if unknown:
        errors.append(f"unknown kill trigger(s): {', '.join(unknown)}")
    answers = []
    for i, (question, answer) in enumerate(form.answers, 1):
        question, answer = question.strip(), answer.strip()
        if question and not answer:
            errors.append(f"question {i} has no answer")
        elif answer and not question:
            errors.append(f"answer {i} has no question")
        elif question:
            answers.append({"question": question, "answer": answer})
    presets = config.budget().presets
    if form.preset not in presets:
        errors.append(f"preset must be one of {', '.join(sorted(presets))}")
    as_of = None
    if form.as_of.strip():
        try:
            as_of = date.fromisoformat(form.as_of.strip())
        except ValueError:
            errors.append(f"as-of date must be YYYY-MM-DD, not {form.as_of.strip()!r}")
        else:
            if as_of > date.today():
                errors.append("as-of date must not be in the future")
    then = next((chain for key, _, chain in RUN_TO if key == form.run_to), None)
    if then is None:
        errors.append(f"how far to run must be one of {', '.join(key for key, _, _ in RUN_TO)}")
    intake = None
    if not errors:
        try:
            intake = Intake.model_validate({
                "goal": form.goal,
                "capital_eur": capital,
                "hours_per_week": hours,
                # unchanged founder skills stay null, so the spec takes config/founder.yaml's
                "skills": None if skills == config.founder().skills else skills,
                "geography": geography,
                "answers": answers,
                "kill_trigger_overrides": sorted(set(form.kill_trigger_overrides), key=KILL_TRIGGERS.index),
            })
        except ValidationError as e:
            errors += _pydantic_errors(e)
    if errors:
        raise FormError(errors)
    return NewRun(idea, intake, form.preset, as_of, then)


def start_idea(new: NewRun, parent: str | None = None) -> tuple[str, list[int]]:
    """Create the run (a version of `parent` when given) and queue its job chain."""
    try:
        return jobs.enqueue_idea(
            new.idea, new.intake.model_dump_json(), preset=new.preset, as_of=new.as_of, then=list(new.then),
            parent=parent,
        )
    except jobs.JobError as e:
        raise FormError([str(e)]) from None


# ---------------------------------------------------------------- run actions


def open_jobs(run_id: str | None = None, kind: str | None = None) -> list[sqlite3.Row]:
    """Queued and running jobs, of one run and/or one kind."""
    sql, params = "SELECT * FROM jobs WHERE status IN ('queued','running')", []
    if run_id is not None:
        sql, params = sql + " AND run_id=?", [*params, run_id]
    if kind is not None:
        sql, params = sql + " AND kind=?", [*params, kind]
    with db.session() as conn:
        return conn.execute(sql + " ORDER BY job_id", params).fetchall()


def run_actions(run_id: str, in_db: bool, has_dir: bool) -> dict[str, str | None]:
    """Action → None when the run's state allows it, else why not. The run page offers only the
    allowed ones, and the server refuses the others with this reason."""
    if not (in_db and has_dir):
        why = "the run needs both its directory and its database row"
        return {key: why for key, _ in RUN_ACTIONS}
    complete = {s: runs.is_complete(run_id, s, status) for s, status in runs.statuses(run_id).items()}
    pending = open_jobs(run_id)
    busy = f"job {pending[0]['job_id']} ({pending[0]['kind']}) is {pending[0]['status']} for this run" if pending else None
    validated = all(complete[s] for s in VALIDATE_STAGES)
    reported = all(complete[s] for s in SYNTHESIZE_STAGES)
    debated = (runs.run_dir(run_id) / "debate" / "revised_plan.md").exists()
    return {
        "validate": busy or ("stages 0–3 are complete" if validated else None),
        "synthesize": busy
        or ("stages 0–3 are not complete; resume validate first" if not validated else None)
        or ("synthesis, scoring and the report are complete" if reported else None),
        "debate": busy
        or ("the debate needs the report; synthesize first" if not reported else None)
        or ("the debate is finished (debate/revised_plan.md exists)" if debated else None),
        # a version is a new run; the parent is only read
        "version": None,
    }


def eval_refusal() -> str | None:
    pending = open_jobs(kind="eval")
    return f"eval job {pending[0]['job_id']} is {pending[0]['status']}" if pending else None


def check_eval(limit: str, fresh: str) -> dict:
    """The eval form as `jobs.enqueue` arguments; FormError for a bad limit."""
    args: dict = {}
    if limit.strip():
        try:
            args["limit"] = int(limit.strip())
        except ValueError:
            raise FormError([f"limit must be a whole number ≥ 1, not {limit.strip()!r}"]) from None
    if fresh:
        args["fresh"] = True
    try:
        return jobs.check_args("eval", args)
    except jobs.JobError as e:
        raise FormError([str(e)]) from None


# ---------------------------------------------------------------- jobs page and log tail


@dataclass
class JobRow:
    job_id: int
    kind: str
    run_id: str | None
    status: str
    reason: str
    created_at: str
    duration: str
    next_job_id: int | None
    command: str


def job_row(r: sqlite3.Row, after: int | None = None) -> JobRow:
    reason = r["reason"] or (f"after job {after}" if r["status"] == "queued" and after else "")
    return JobRow(
        r["job_id"], r["kind"], r["run_id"], r["status"], reason, r["created_at"], jobs.duration(r),
        r["next_job_id"], jobs.command(r["kind"], r["run_id"], json.loads(r["args"])),
    )


def job_rows() -> list[JobRow]:
    """Every job, newest first (the queue order is by job id), as `jobs list` shows them."""
    return [job_row(r, r["after"]) for r in reversed(jobs.all_jobs())]


def chain(job_id: int) -> list[JobRow]:
    """The job's chain: its predecessors, itself and its followers, in order."""
    rows = {r["job_id"]: r for r in jobs.all_jobs()}
    if job_id not in rows:
        raise jobs.JobError(f"no job {job_id}")
    before = {r["next_job_id"]: jid for jid, r in rows.items() if r["next_job_id"]}
    first = job_id
    while first in before:
        first = before[first]
    out, nxt = [], first
    while nxt is not None and nxt in rows:
        out.append(job_row(rows[nxt], rows[nxt]["after"]))
        nxt = rows[nxt]["next_job_id"]
    return out


@dataclass
class LogChunk:
    text: str
    offset: int  # the byte offset to ask for next
    size: int
    done: bool  # the job has finished and everything up to the end has been sent


def log_chunk(job_id: int, offset: int | None = None) -> LogChunk:
    """The log bytes from `offset` (None: the last TAIL_BYTES, from a line start) up to the last
    complete line, so a poll never splits a line or a UTF-8 character; once the job has finished
    the rest is sent too. Raises JobError for an unknown job."""
    finished = jobs.get(job_id)["status"] in jobs.FINISHED
    path = jobs.log_file(job_id)
    try:
        with open(path, "rb") as f:
            size = f.seek(0, 2)
            if offset is None:
                offset = max(0, size - TAIL_BYTES)
                if offset:  # start after the first line break, not inside a line
                    f.seek(offset)
                    newline = f.read(size - offset).find(b"\n")
                    offset = offset + newline + 1 if newline >= 0 else size
            offset = min(max(offset, 0), size)
            f.seek(offset)
            data = f.read(min(size - offset, CHUNK_BYTES))
    except FileNotFoundError:
        return LogChunk("", 0, 0, finished)
    end = offset + len(data)
    if end < size or not finished:
        cut = data.rfind(b"\n")
        if cut >= 0:
            data = data[: cut + 1]
        elif len(data) < CHUNK_BYTES:
            data = b""  # an unfinished line: wait for the rest
    end = offset + len(data)
    return LogChunk(data.decode("utf-8", errors="replace"), end, size, finished and end >= size)


# ---------------------------------------------------------------- the server's worker


class Worker:
    """The one background worker the web server runs (`jobs.run_worker` in a thread). `start`
    at server start, `ensure` after a job is queued (it starts the worker again once the reason
    it stopped is gone), `stop` at shutdown: the running job is stopped and marked interrupted,
    as Ctrl+C on the CLI worker does."""

    def __init__(self, poll: float = jobs.POLL_SECONDS):
        self.poll = poll
        self.enabled = False
        self.error: str | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()

    @property
    def alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        self.enabled = True
        self.ensure()

    def ensure(self) -> None:
        if not self.enabled:
            return
        with self._lock:
            if self.alive:
                return
            refusal = jobs.dev_marker_refusal()
            if refusal:
                self.error = refusal
                return
            self.error = None
            self._stop = threading.Event()
            self._thread = threading.Thread(target=self._run, args=(self._stop,), name="ideaforge-worker", daemon=True)
            self._thread.start()

    def _run(self, stop: threading.Event) -> None:
        try:
            jobs.run_worker(poll=self.poll, stop=stop)
        except jobs.JobError as e:
            self.error = str(e)
        except Exception as e:  # noqa: BLE001 — shown on the jobs page instead of dying silently
            self.error = f"the worker stopped: {type(e).__name__}: {e}"

    def stop(self, timeout: float = jobs.GRACE_SECONDS + 5) -> None:
        self.enabled = False
        self._stop.set()
        thread = self._thread
        if thread is None:
            return
        deadline = time.monotonic() + timeout
        while thread.is_alive() and time.monotonic() < deadline:
            # This worker holds the lock, so a running job is its own; one claimed just as the
            # stop was set is caught on the next pass.
            for row in open_jobs():
                if row["status"] == "running":
                    jobs.interrupt(row["job_id"], grace=max(0.0, deadline - time.monotonic()))
            thread.join(0.1)

    def state(self) -> tuple[str, str]:
        """(running | stopped | off, what the jobs page says about it)."""
        if self.alive:
            return "running", "The worker is running; queued jobs start one at a time."
        refusal = jobs.dev_marker_refusal()
        if refusal:
            return "stopped", f"The worker cannot start: {refusal} Queued jobs wait until then."
        if self.error:
            return "stopped", f"The worker is not running: {self.error}"
        if not self.enabled:
            return "off", "This server runs no worker; start one with `uv run python -m ideaforge.jobs worker`."
        return "stopped", "The worker is not running."
