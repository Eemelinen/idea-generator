"""Persistent job queue and headless runner (IF-604, TICKETS.md plan notes 36 and 40).

    uv run python -m ideaforge.jobs enqueue <kind> [--run <run_id>] [--args '<json>'] [--then <kind> …]
    uv run python -m ideaforge.jobs enqueue validate --idea '<text>' --intake '<json>'
                                    [--preset <name>] [--as-of YYYY-MM-DD] [--then <kind> …]
    uv run python -m ideaforge.jobs list | show <job_id> | cancel <job_id> | retry <job_id>
    uv run python -m ideaforge.jobs worker [--once]

A job is one pipeline skill (validate, research, synthesize, debate, eval) kept in the `jobs`
table. `--then` chains follow-up jobs on the same run: each waits until its predecessor (the job
whose `next_job_id` points at it) is `done`, and is cancelled when that one fails or is cancelled.

The worker runs one job at a time (§10), oldest first, as
`claude -p "/<kind> <run_id>" --model <roles.orchestrator> --output-format stream-json --verbose`
in the project root, with output in `runs/.jobs/<job_id>.log`. It refuses to start while
`.ideaforge-dev` exists and drops `HARNESS_LOOP` from the child environment, so the child always
runs under the strict pipeline guard (§7, D-005). A pid file plus `BEGIN IMMEDIATE` keeps a second
worker out; at start, a `running` job whose process is gone becomes `failed` (`interrupted`).
The binary is `IDEAFORGE_CLAUDE_BIN` or `claude`.

A new idea (`--idea`) is created by `scripts/new_run.py --intake` before the job is queued, so the
job knows its run id and `/validate` takes its clarifications from `intake.json`.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

from ideaforge import config, db, runs

KINDS = ("validate", "research", "synthesize", "debate", "eval")
RUN_KINDS = ("validate", "research", "synthesize", "debate")  # the skill takes a run id
FINISHED = ("done", "failed", "cancelled")
CLAUDE_BIN_ENV = "IDEAFORGE_CLAUDE_BIN"
GRACE_SECONDS = 10.0  # SIGTERM → SIGKILL on cancel
POLL_SECONDS = 2.0  # idle worker
# What Claude Code prints when a subscription usage limit or an API rate limit stops a session.
USAGE_LIMIT_RE = re.compile(r"usage limit|rate[ _-]?limit|limit reached|hit your limit|out of extra usage", re.I)
NEW_RUN_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "new_run.py"


class JobError(Exception):
    """A request the queue refuses; the message says why."""


def jobs_dir() -> Path:
    return config.RUNS_DIR / ".jobs"


def log_file(job_id: int) -> Path:
    return jobs_dir() / f"{job_id}.log"


def lock_file() -> Path:
    return jobs_dir() / "worker.pid"


def get(job_id: int) -> sqlite3.Row:
    with db.session() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
    if row is None:
        raise JobError(f"no job {job_id}")
    return row


def all_jobs() -> list[sqlite3.Row]:
    """Every job, oldest first, with `after`: the predecessor's id while it is not done yet."""
    with db.session() as conn:
        return conn.execute(
            "SELECT j.*, (SELECT p.job_id FROM jobs p WHERE p.next_job_id = j.job_id AND p.status != 'done')"
            " AS after FROM jobs j ORDER BY j.job_id"
        ).fetchall()


# ---------------------------------------------------------------- enqueue


def check_args(kind: str, args: dict) -> dict:
    """Only /eval takes arguments: `limit` (a whole number ≥ 1) and `fresh` (bool)."""
    if not isinstance(args, dict):
        raise JobError("--args must be a JSON object")
    if kind != "eval":
        if args:
            raise JobError(f"{kind} takes no --args (its argument is the run id)")
        return {}
    unknown = set(args) - {"limit", "fresh"}
    if unknown:
        raise JobError(f"unknown eval argument(s): {', '.join(sorted(unknown))}; use limit, fresh")
    limit = args.get("limit")
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 1):
        raise JobError("eval limit must be a whole number ≥ 1")
    if not isinstance(args.get("fresh", False), bool):
        raise JobError("eval fresh must be true or false")
    return args


def _check_run(kind: str, run_id: str | None) -> str | None:
    if kind not in RUN_KINDS:
        return None
    if not run_id:
        raise JobError(f"{kind} needs --run <run_id>")
    try:
        exists = runs.run_dir(run_id).is_dir()
    except ValueError as e:
        raise JobError(str(e)) from None
    if not exists:
        raise JobError(f"unknown run {run_id} (no runs/{run_id}/)")
    return run_id


def _insert_chain(chain: list[tuple[str, str | None, dict]]) -> list[int]:
    """Insert (kind, run_id, args) jobs in one transaction, each the previous one's next_job_id."""
    ids: list[int] = []
    with db.session() as conn:
        for kind, run_id, args in chain:
            cur = conn.execute(
                "INSERT INTO jobs(kind, args, run_id, status, created_at) VALUES (?,?,?, 'queued', ?)",
                (kind, json.dumps(args, ensure_ascii=False), run_id, db.now()),
            )
            if ids:
                conn.execute("UPDATE jobs SET next_job_id=? WHERE job_id=?", (cur.lastrowid, ids[-1]))
            ids.append(cur.lastrowid)
    return ids


def enqueue(kind: str, run_id: str | None = None, args: dict | None = None, then: list[str] = ()) -> list[int]:
    """Queue `kind` and its `then` chain (follow-ups on the same run, no arguments); the job ids."""
    chain = []
    for i, k in enumerate([kind, *then]):
        if k not in KINDS:
            raise JobError(f"unknown job kind {k!r}; choose from {', '.join(KINDS)}")
        if k == "eval" and run_id and i == 0:
            raise JobError("eval takes no --run (it makes its own runs)")
        chain.append((k, _check_run(k, run_id), check_args(k, args or {}) if i == 0 else {}))
    return _insert_chain(chain)


_NEW_RUN_LOCK = threading.Lock()  # redirect_stdout is process-wide: one new run at a time


def _new_run(argv: list[str]) -> str:
    """Run scripts/new_run.py in this process (so it sees this root and database); the run id.
    Its stdout and stderr are captured; stderr (argparse's reason) also goes into the error."""
    spec = importlib.util.spec_from_file_location("ideaforge_new_run", NEW_RUN_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    out, err = io.StringIO(), io.StringIO()
    with _NEW_RUN_LOCK:
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                module.main(argv)
        except SystemExit as e:
            text = err.getvalue()
            sys.stderr.write(text)
            reason = text.split(": error: ", 1)[-1].strip()
            raise JobError(f"new_run.py refused the idea (exit {e.code})" + (f": {reason}" if reason else "")) from None
    sys.stderr.write(err.getvalue())
    # A worker thread in the same process (the web server's) may print meanwhile: take the id line.
    ids = [line.strip() for line in out.getvalue().splitlines() if runs.RUN_ID_RE.match(line.strip())]
    if not ids:
        raise JobError(f"new_run.py printed no run id: {out.getvalue().strip()!r}")
    return ids[-1]


def enqueue_idea(
    idea: str,
    intake: str,
    *,
    preset: str | None = None,
    as_of: date | None = None,
    then: list[str] = (),
    parent: str | None = None,
) -> tuple[str, list[int]]:
    """Create the run with `new_run.py --intake` (with `parent`: its next version, `--from`),
    then queue `validate` on it and the `then` chain."""
    for k in then:
        if k not in KINDS:
            raise JobError(f"unknown job kind {k!r}; choose from {', '.join(KINDS)}")
    argv = ["--intake", intake]
    if parent:
        argv += ["--from", parent]
    if preset:
        argv += ["--preset", preset]
    if as_of:
        argv += ["--as-of", as_of.isoformat()]
    run_id = _new_run([*argv, "--", idea])  # "--": an idea text may start with a dash
    return run_id, enqueue("validate", run_id, then=list(then))


# ---------------------------------------------------------------- cancel and retry


def _cancel_followers(conn: sqlite3.Connection, job_id: int, why: str) -> list[int]:
    """Cancel the queued jobs chained after `job_id`."""
    cancelled = []
    row = conn.execute("SELECT next_job_id FROM jobs WHERE job_id=?", (job_id,)).fetchone()
    nxt = row["next_job_id"] if row else None
    while nxt is not None:
        cur = conn.execute(
            "UPDATE jobs SET status='cancelled', reason=?, finished_at=? WHERE job_id=? AND status='queued'",
            (why, db.now(), nxt),
        )
        if cur.rowcount:
            cancelled.append(nxt)
        nxt = conn.execute("SELECT next_job_id FROM jobs WHERE job_id=?", (nxt,)).fetchone()["next_job_id"]
    return cancelled


def pid_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    if os.name == "nt":  # os.kill(pid, 0) would terminate the process on Windows
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        try:
            kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        finally:
            kernel32.CloseHandle(handle)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _signal(pid: int, sig: int) -> None:
    """Signal the job's process group (the worker starts each job in its own session)."""
    try:
        if os.name == "nt":
            os.kill(pid, sig)
            return
        try:
            os.killpg(pid, sig)
        except (ProcessLookupError, PermissionError):
            os.kill(pid, sig)
    except (ProcessLookupError, OSError):
        pass


def terminate(pid: int, grace: float = GRACE_SECONDS) -> None:
    """SIGTERM, then SIGKILL when the process outlives the grace period."""
    _signal(pid, signal.SIGTERM)
    deadline = time.monotonic() + grace
    while pid_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    if pid_alive(pid):
        _signal(pid, getattr(signal, "SIGKILL", signal.SIGTERM))


def cancel(job_id: int, grace: float = GRACE_SECONDS) -> list[int]:
    """Drop a queued job or stop a running one; its chained jobs are cancelled too. The ids."""
    row = get(job_id)
    if row["status"] in FINISHED:
        raise JobError(f"job {job_id} is already {row['status']}")
    with db.session() as conn:
        cur = conn.execute(
            "UPDATE jobs SET status='cancelled', reason='cancelled', finished_at=?"
            " WHERE job_id=? AND status IN ('queued','running')",
            (db.now(), job_id),
        )
        if not cur.rowcount:
            raise JobError(f"job {job_id} finished meanwhile")
        cancelled = [job_id, *_cancel_followers(conn, job_id, f"job {job_id} cancelled")]
    if row["status"] == "running" and row["pid"]:
        terminate(row["pid"], grace)
    return cancelled


def interrupt(job_id: int, grace: float = GRACE_SECONDS) -> bool:
    """Stop a running job because its worker is stopping (the web server shuts down): `failed`
    / `interrupted`, as a Ctrl+C on the CLI worker, and its chained jobs are cancelled. False
    when the job is not running (any more)."""
    row = get(job_id)
    with db.session() as conn:
        cur = conn.execute(
            "UPDATE jobs SET status='failed', reason='interrupted', finished_at=? WHERE job_id=? AND status='running'",
            (db.now(), job_id),
        )
        if not cur.rowcount:
            return False
        _cancel_followers(conn, job_id, f"job {job_id} failed")
    if row["pid"]:  # without a pid yet, run_job sees the status and stops the process it starts
        terminate(row["pid"], grace)
    return True


def retry(job_id: int) -> list[int]:
    """A new job with the same kind, run and arguments, plus the chained jobs its end cancelled.
    The stages resume, so a retried run continues where it stopped."""
    row = get(job_id)
    if row["status"] not in FINISHED:
        raise JobError(f"job {job_id} is still {row['status']}; cancel it first")
    _check_run(row["kind"], row["run_id"])
    chain = [(row["kind"], row["run_id"], json.loads(row["args"]))]
    nxt = row["next_job_id"]
    while nxt is not None:
        follower = get(nxt)
        if follower["status"] != "cancelled":
            break
        chain.append((follower["kind"], follower["run_id"], json.loads(follower["args"])))
        nxt = follower["next_job_id"]
    return _insert_chain(chain)


# ---------------------------------------------------------------- worker


def command(kind: str, run_id: str | None, args: dict) -> str:
    """The skill invocation a job runs headless."""
    if kind == "eval":
        parts = ["/eval"]
        if args.get("limit"):
            parts.append(f"--limit {args['limit']}")
        if args.get("fresh"):
            parts.append("--fresh")
        return " ".join(parts)
    return f"/{kind} {run_id}"


def claude_argv(prompt: str) -> list[str]:
    binary = os.environ.get(CLAUDE_BIN_ENV) or "claude"
    model = config.models().roles["orchestrator"]
    return [shutil.which(binary) or binary, "-p", prompt, "--model", model, "--output-format", "stream-json", "--verbose"]


def child_env(run_id: str | None) -> dict[str, str]:
    """The worker's environment without HARNESS_LOOP (strict guard), pinned to the job's run."""
    env = dict(os.environ)
    env.pop("HARNESS_LOOP", None)
    env.pop("IDEAFORGE_RUN_ID", None)
    if run_id:
        env["IDEAFORGE_RUN_ID"] = run_id
    return env


def scan_log(path: Path) -> tuple[bool, bool]:
    """(a usage or rate limit is reported anywhere outside tool output, the final result is an
    error that reports one). Stream-json events are checked by their `result` and `error` fields
    only, so a fetched page that mentions rate limits does not count; other lines (stderr) whole."""
    anywhere = in_result = False
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False, False
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            event = None
        if not isinstance(event, dict):
            anywhere = anywhere or bool(USAGE_LIMIT_RE.search(line))
            continue
        fields = [event.get("error"), event.get("result") if event.get("type") == "result" else None]
        hit = any(isinstance(f, str | dict) and USAGE_LIMIT_RE.search(json.dumps(f)) for f in fields if f)
        anywhere = anywhere or hit
        if event.get("type") == "result" and event.get("is_error") and hit:
            in_result = True
    return anywhere, in_result


def _finish(job_id: int, status: str, reason: str | None, exit_code: int | None) -> str:
    """Record the end of a running job (a job cancelled meanwhile stays cancelled); final status."""
    with db.session() as conn:
        cur = conn.execute(
            "UPDATE jobs SET status=?, reason=?, exit_code=?, finished_at=? WHERE job_id=? AND status='running'",
            (status, reason, exit_code, db.now(), job_id),
        )
        if not cur.rowcount:
            conn.execute("UPDATE jobs SET exit_code=? WHERE job_id=?", (exit_code, job_id))
            status = conn.execute("SELECT status FROM jobs WHERE job_id=?", (job_id,)).fetchone()["status"]
        if status != "done":
            _cancel_followers(conn, job_id, f"job {job_id} {status}")
    return status


def run_job(job: sqlite3.Row) -> str:
    """Run a claimed job to its end; its final status."""
    job_id = job["job_id"]
    log = log_file(job_id)
    log.parent.mkdir(parents=True, exist_ok=True)
    try:
        rel = log.relative_to(config.ROOT).as_posix()
    except ValueError:
        rel = str(log)
    argv = claude_argv(command(job["kind"], job["run_id"], json.loads(job["args"])))
    with open(log, "wb") as out:
        try:
            proc = subprocess.Popen(
                argv,
                cwd=config.ROOT,
                env=child_env(job["run_id"]),
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=subprocess.STDOUT,
                start_new_session=os.name != "nt",
            )
        except OSError as e:
            out.write(f"cannot start {argv[0]}: {e}\n".encode())
            with db.session() as conn:
                conn.execute("UPDATE jobs SET log_path=? WHERE job_id=?", (rel, job_id))
            return _finish(job_id, "failed", f"cannot start {argv[0]}: {e.strerror or e}", None)
        with db.session() as conn:
            cur = conn.execute(
                "UPDATE jobs SET pid=?, log_path=? WHERE job_id=? AND status='running'", (proc.pid, rel, job_id)
            )
        if not cur.rowcount:  # cancelled between the claim and the start
            terminate(proc.pid, GRACE_SECONDS)
        try:
            code = proc.wait()
        except BaseException:  # worker stopped (Ctrl-C, SIGTERM): stop the job too
            terminate(proc.pid, GRACE_SECONDS)
            proc.wait()
            _finish(job_id, "failed", "interrupted", proc.returncode)
            raise
    limited, result_limited = scan_log(log)
    if code == 0 and not result_limited:
        return _finish(job_id, "done", None, code)
    return _finish(job_id, "failed", "usage_limit" if limited else f"exit {code}", code)


def claim_next() -> sqlite3.Row | None:
    """Mark the oldest runnable queued job running (a chained job waits for its predecessor)."""
    with db.session() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM jobs j WHERE status='queued' AND NOT EXISTS"
            " (SELECT 1 FROM jobs p WHERE p.next_job_id = j.job_id AND p.status != 'done')"
            " ORDER BY job_id LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        conn.execute("UPDATE jobs SET status='running', started_at=? WHERE job_id=?", (db.now(), row["job_id"]))
        return conn.execute("SELECT * FROM jobs WHERE job_id=?", (row["job_id"],)).fetchone()


def recover() -> tuple[list[int], list[sqlite3.Row]]:
    """At worker start: (jobs marked failed `interrupted` because their process is gone, running
    jobs whose process still lives)."""
    interrupted, alive = [], []
    with db.session() as conn:
        for row in conn.execute("SELECT * FROM jobs WHERE status='running' ORDER BY job_id").fetchall():
            if pid_alive(row["pid"]):
                alive.append(row)
                continue
            conn.execute(
                "UPDATE jobs SET status='failed', reason='interrupted', finished_at=? WHERE job_id=?",
                (db.now(), row["job_id"]),
            )
            _cancel_followers(conn, row["job_id"], f"job {row['job_id']} failed")
            interrupted.append(row["job_id"])
    return interrupted, alive


def _read_pid(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


@contextmanager
def worker_lock() -> Iterator[None]:
    """Hold `runs/.jobs/worker.pid`; checked and written inside BEGIN IMMEDIATE, so two workers
    starting together cannot both get it."""
    path = lock_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    with db.session() as conn:
        conn.execute("BEGIN IMMEDIATE")
        holder = _read_pid(path)
        if holder is not None and pid_alive(holder):
            raise JobError(f"a worker is already running (pid {holder}; {path})")
        path.write_text(f"{os.getpid()}\n", encoding="utf-8")
    try:
        yield
    finally:
        if _read_pid(path) == os.getpid():
            path.unlink(missing_ok=True)


def dev_marker_refusal() -> str | None:
    if config.DEV_MARKER.exists():
        return (
            f"{config.DEV_MARKER.name} exists, so Claude Code would run with the development policy; "
            "jobs run only under the strict pipeline guard. Delete the marker and start the worker again."
        )
    return None


def run_worker(once: bool = False, poll: float = POLL_SECONDS, stop: threading.Event | None = None) -> int:
    """Run queued jobs one at a time until stopped (`once`: at most one job, then return; `stop`:
    return when it is set, between jobs)."""
    refusal = dev_marker_refusal()
    if refusal:
        raise JobError(refusal)
    with worker_lock():
        interrupted, alive = recover()
        for job_id in interrupted:
            print(f"job {job_id}: interrupted (its process is gone) → failed")
        if alive:
            row = alive[0]
            raise JobError(f"job {row['job_id']} is still running as pid {row['pid']}; wait for it or cancel it")
        while stop is None or not stop.is_set():
            refusal = dev_marker_refusal()
            if refusal:
                raise JobError(refusal)
            job = claim_next()
            if job is None:
                if once:
                    print("no queued job")
                    return 0
                if stop is None:
                    time.sleep(poll)
                else:
                    stop.wait(poll)
                continue
            print(f"job {job['job_id']}: {command(job['kind'], job['run_id'], json.loads(job['args']))}", flush=True)
            status = run_job(job)
            row = get(job["job_id"])
            print(f"job {job['job_id']}: {status}" + (f" ({row['reason']})" if row["reason"] else ""), flush=True)
            if once:
                return 0
    return 0


# ---------------------------------------------------------------- CLI


def duration(row: sqlite3.Row) -> str:
    if not row["started_at"]:
        return "-"
    end = datetime.fromisoformat(row["finished_at"]) if row["finished_at"] else datetime.now().astimezone()
    seconds = int((end - datetime.fromisoformat(row["started_at"])).total_seconds())
    return f"{seconds // 3600}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"


def list_lines() -> list[str]:
    lines = ["job\tkind\trun\tstatus\treason\tcreated\tduration\tnext"]
    for r in all_jobs():
        reason = r["reason"] or (f"after job {r['after']}" if r["status"] == "queued" and r["after"] else "-")
        lines.append(
            "\t".join(
                str(v)
                for v in (
                    r["job_id"], r["kind"], r["run_id"] or "-", r["status"], reason, r["created_at"],
                    duration(r), r["next_job_id"] or "-",
                )
            )
        )
    return lines


def show_lines(job_id: int, tail: int = 20) -> list[str]:
    row = get(job_id)
    lines = [f"{key}: {row[key] if row[key] is not None else '-'}" for key in row.keys()]
    lines.append(f"command: {command(row['kind'], row['run_id'], json.loads(row['args']))}")
    if row["log_path"]:
        path = config.ROOT / row["log_path"]
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace").splitlines()
            lines.append(f"log (last {min(tail, len(text))} of {len(text)} lines):")
            lines += [f"  {line}" for line in text[-tail:]]
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ideaforge.jobs", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    enq = sub.add_parser("enqueue", help="queue a job (and its --then chain)")
    enq.add_argument("kind", choices=KINDS)
    enq.add_argument("--run", default=None, help="run id (validate, research, synthesize, debate)")
    enq.add_argument("--args", default=None, help='JSON object; eval only: {"limit": N, "fresh": true}')
    enq.add_argument("--then", action="append", default=[], choices=KINDS, help="follow-up job on the same run")
    enq.add_argument("--idea", default=None, help="validate a new idea: new_run.py creates the run first")
    enq.add_argument("--intake", default=None, help="with --idea: the clarifications as JSON (schema Intake)")
    enq.add_argument("--preset", default=None, help="with --idea: budget preset")
    enq.add_argument("--as-of", type=date.fromisoformat, default=None, help="with --idea: back-test date")
    sub.add_parser("list", help="every job, oldest first")
    for name, text in (("show", "one job and its log tail"), ("cancel", "drop or stop a job"), ("retry", "queue it again")):
        sub.add_parser(name, help=text).add_argument("job_id", type=int)
    wrk = sub.add_parser("worker", help="run queued jobs one at a time")
    wrk.add_argument("--once", action="store_true", help="run at most one job, then exit")
    args = parser.parse_args(argv)

    db.init()
    try:
        if args.command == "enqueue":
            if args.idea is not None:
                if args.kind != "validate" or args.run or args.args:
                    parser.error("--idea goes with validate only, without --run or --args")
                if args.intake is None:
                    parser.error("--idea needs --intake, so the headless run asks no questions")
                run_id, ids = enqueue_idea(args.idea, args.intake, preset=args.preset, as_of=args.as_of, then=args.then)
            else:
                if args.intake or args.preset or args.as_of:
                    parser.error("--intake, --preset and --as-of go with --idea")
                try:
                    extra = json.loads(args.args) if args.args else {}
                except ValueError as e:
                    parser.error(f"--args is not JSON: {e}")
                ids = enqueue(args.kind, args.run, extra, args.then)
            for row in map(get, ids):
                print(f"queued job {row['job_id']}: {row['kind']} {row['run_id'] or '-'}")
        elif args.command == "list":
            print("\n".join(list_lines()))
        elif args.command == "show":
            print("\n".join(show_lines(args.job_id)))
        elif args.command == "cancel":
            print("\n".join(f"cancelled job {i}" for i in cancel(args.job_id)))
        elif args.command == "retry":
            for row in map(get, retry(args.job_id)):
                print(f"queued job {row['job_id']}: {row['kind']} {row['run_id'] or '-'}")
        else:
            signal.signal(signal.SIGTERM, _interrupt)
            return run_worker(once=args.once)
    except JobError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("worker stopped", file=sys.stderr)
        return 130
    return 0


def _interrupt(signum, frame):  # SIGTERM → the same clean stop as Ctrl-C
    raise KeyboardInterrupt


if __name__ == "__main__":
    sys.exit(main())
