"""The job queue and headless runner (IF-604) with a fake `claude` binary (IDEAFORGE_CLAUDE_BIN).

The fake records each invocation (argv, cwd, the environment the worker gave it, start and end
times) and prints synthetic stream-json events; what it does is chosen per prompt through
FAKE_CLAUDE_MODES. Nothing here starts the real Claude Code.
"""

import json
import os
import signal
import subprocess
import sys
import threading
import time

import pytest

from ideaforge import config, db, jobs, runs
from ideaforge.schemas import Intake


FAKE = """
import json, os, signal, sys, time

prompt = sys.argv[sys.argv.index("-p") + 1]
mode = json.loads(os.environ.get("FAKE_CLAUDE_MODES", "{}")).get(prompt, "ok")
if mode == "ignore_term":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)


def record(event, **fields):
    with open(os.environ["FAKE_CLAUDE_RECORD"], "a", encoding="utf-8") as f:
        f.write(json.dumps({"event": event, "prompt": prompt, "t": time.time(), **fields}) + "\\n")


record(
    "start",
    argv=sys.argv[1:],
    cwd=os.getcwd(),
    harness_loop=os.environ.get("HARNESS_LOOP"),
    run_id=os.environ.get("IDEAFORGE_RUN_ID"),
    pid=os.getpid(),
)
print(json.dumps({"type": "system", "subtype": "init", "synthetic": True}), flush=True)
time.sleep(float(os.environ.get("FAKE_CLAUDE_SECONDS", "0")))
if mode in ("sleep", "ignore_term"):
    time.sleep(60)
code = 0
if mode == "ok":
    print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "synthetic done"}))
elif mode == "fail":
    print(json.dumps({"type": "result", "subtype": "error_during_execution", "is_error": True, "result": "boom"}))
    code = 1
elif mode == "usage_limit":
    print(json.dumps({"type": "result", "subtype": "success", "is_error": True,
                      "result": "Claude AI usage limit reached|1761300000"}))
    code = 1
elif mode == "usage_limit_exit0":
    print(json.dumps({"type": "result", "subtype": "success", "is_error": True,
                      "result": "Claude AI usage limit reached|1761300000"}))
elif mode == "stderr_limit":
    print("API Error: 429 rate_limit_error", file=sys.stderr)
    code = 1
elif mode == "page_mentions_limit":
    # a fetched page that talks about rate limits is tool output, not the session's own limit
    print(json.dumps({"type": "user", "message": {"content": [
        {"type": "tool_result", "content": "The API has a rate limit of 10 requests; usage limit reached."}]}}))
    print(json.dumps({"type": "result", "subtype": "error_during_execution", "is_error": True, "result": "boom"}))
    code = 1
record("end", code=code)
sys.exit(code)
"""

INTAKE = {
    "goal": "side_income",
    "capital_eur": 3000,
    "hours_per_week": 15,
    "geography": ["Rääkkylä", "North Karelia"],
    "answers": [{"question": "Who pays?", "answer": "Remote workers from Helsinki (synthetic)"}],
}


@pytest.fixture
def fake_claude(project, tmp_path, monkeypatch):
    """A fake `claude` executable; returns a function that reads its invocation records."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    script = bindir / "fake_claude.py"
    script.write_text(FAKE, encoding="utf-8")
    if os.name == "nt":
        binary = bindir / "fake_claude.cmd"
        binary.write_text(f'@"{sys.executable}" "{script}" %*\n', encoding="utf-8")
    else:
        binary = bindir / "fake_claude"
        binary.write_text(f"#!{sys.executable}\n" + FAKE, encoding="utf-8")
        binary.chmod(0o755)
    record = tmp_path / "record.jsonl"
    monkeypatch.setenv(jobs.CLAUDE_BIN_ENV, str(binary))
    monkeypatch.setenv("FAKE_CLAUDE_RECORD", str(record))
    db.init()

    def records(event: str | None = None) -> list[dict]:
        if not record.exists():
            return []
        rows = [json.loads(line) for line in record.read_text(encoding="utf-8").splitlines()]
        return [r for r in rows if event is None or r["event"] == event]

    return records


def modes(monkeypatch, **by_prompt):
    monkeypatch.setenv("FAKE_CLAUDE_MODES", json.dumps({k.replace("_", " ", 1): v for k, v in by_prompt.items()}))


def make_run(slug: str) -> str:
    run_id = f"20261024-100000-{slug}"
    runs.create_run_dir(run_id, f"synthetic idea {slug}")
    return run_id


def row(job_id: int):
    return jobs.get(job_id)


def wait_for(predicate, timeout: float = 10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("timed out")


def worker_thread(**kwargs):
    stop = threading.Event()
    result = {}

    def target():
        try:
            result["code"] = jobs.run_worker(poll=0.02, stop=stop, **kwargs)
        except BaseException as e:  # noqa: BLE001 — surfaced by the test
            result["error"] = e

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread, stop, result


# ---------------------------------------------------------------- schema and enqueue


def test_migration_adds_the_jobs_table(project):
    db.init()
    with db.session() as conn:
        assert db.schema_version(conn) == len(db.MIGRATIONS) >= 2
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(jobs)")}
    assert cols == {
        "job_id", "kind", "args", "run_id", "status", "reason", "pid", "created_at", "started_at",
        "finished_at", "exit_code", "log_path", "next_job_id",
    }


@pytest.mark.parametrize(
    "kind,run,args,then,message",
    [
        ("synthesize", None, None, [], "needs --run"),
        ("synthesize", "20261024-100000-missing", None, [], "unknown run"),
        ("synthesize", "../etc", None, [], "not a valid run id"),
        ("eval", "RUN", None, [], "eval takes no --run"),
        ("debate", "RUN", {"limit": 2}, [], "takes no --args"),
        ("eval", None, {"limit": 0}, [], "whole number"),
        ("eval", None, {"limit": True}, [], "whole number"),
        ("eval", None, {"fresh": "yes"}, [], "true or false"),
        ("eval", None, {"rounds": 2}, [], "unknown eval argument"),
        ("eval", None, None, ["synthesize"], "needs --run"),
        ("validate", "RUN", None, ["deploy"], "unknown job kind"),
    ],
)
def test_enqueue_refuses_bad_requests_and_queues_nothing(fake_claude, kind, run, args, then, message):
    run_id = make_run("sauna")
    with pytest.raises(jobs.JobError, match=message):
        jobs.enqueue(kind, run_id if run == "RUN" else run, args, then)
    assert jobs.all_jobs() == []


def test_cli_enqueue_list_and_show(fake_claude, capsys):
    run_id = make_run("sauna")
    assert jobs.main(["enqueue", "synthesize", "--run", run_id, "--then", "debate"]) == 0
    assert capsys.readouterr().out.splitlines() == [f"queued job 1: synthesize {run_id}", f"queued job 2: debate {run_id}"]
    assert jobs.main(["enqueue", "eval", "--args", '{"limit": 2, "fresh": true}']) == 0
    capsys.readouterr()
    assert jobs.main(["list"]) == 0
    lines = [line.split("\t") for line in capsys.readouterr().out.splitlines()]
    assert lines[0] == ["job", "kind", "run", "status", "reason", "created", "duration", "next"]
    assert [(r[0], r[1], r[2], r[3], r[4], r[7]) for r in lines[1:]] == [
        ("1", "synthesize", run_id, "queued", "-", "2"),
        ("2", "debate", run_id, "queued", "after job 1", "-"),
        ("3", "eval", "-", "queued", "-", "-"),
    ]
    assert jobs.main(["show", "3"]) == 0
    out = capsys.readouterr().out
    assert "command: /eval --limit 2 --fresh" in out and "status: queued" in out
    assert jobs.main(["show", "9"]) == 1
    assert "no job 9" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        jobs.main(["enqueue", "eval", "--args", "{not json"])
    with pytest.raises(SystemExit):
        jobs.main(["enqueue", "synthesize", "--run", run_id, "--intake", "{}"])


# ---------------------------------------------------------------- worker


def test_worker_runs_claude_headless_with_the_strict_guard(fake_claude, project, monkeypatch, capsys):
    monkeypatch.setenv("HARNESS_LOOP", "1")  # set when the worker itself was started by the loop driver
    monkeypatch.setenv("IDEAFORGE_RUN_ID", "20261024-090000-stale")
    run_id = make_run("sauna")
    (job_id,) = jobs.enqueue("synthesize", run_id)
    assert jobs.main(["worker", "--once"]) == 0
    assert capsys.readouterr().out.splitlines() == [f"job 1: /synthesize {run_id}", "job 1: done"]

    (start,) = fake_claude("start")
    assert start["argv"] == [
        "-p", f"/synthesize {run_id}", "--model", config.models().roles["orchestrator"],
        "--output-format", "stream-json", "--verbose",
    ]
    assert os.path.samefile(start["cwd"], project)
    assert start["harness_loop"] is None
    assert start["run_id"] == run_id
    job = row(job_id)
    assert (job["status"], job["reason"], job["exit_code"], job["pid"]) == ("done", None, 0, start["pid"])
    assert job["log_path"] == f"runs/.jobs/{job_id}.log"
    log = (project / job["log_path"]).read_text(encoding="utf-8")
    assert '"synthetic done"' in log and '"subtype": "init"' in log
    assert job["started_at"] <= job["finished_at"]
    assert not jobs.lock_file().exists()


def test_eval_job_command_and_no_run_pin(fake_claude, monkeypatch):
    monkeypatch.setenv("IDEAFORGE_RUN_ID", "20261024-090000-stale")
    jobs.enqueue("eval", args={"limit": 3})
    jobs.run_worker(once=True)
    (start,) = fake_claude("start")
    assert start["prompt"] == "/eval --limit 3" and start["run_id"] is None
    assert jobs.command("eval", None, {}) == "/eval"
    assert jobs.command("eval", None, {"fresh": True}) == "/eval --fresh"


def test_queue_order_one_job_at_a_time_and_a_single_worker(fake_claude, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_CLAUDE_SECONDS", "0.3")
    a, b, c = make_run("aaa"), make_run("bbb"), make_run("ccc")
    jobs.enqueue("research", b)
    jobs.enqueue("synthesize", a)
    jobs.enqueue("debate", c)
    thread, stop, result = worker_thread()
    wait_for(lambda: fake_claude("start"))
    # A second worker is refused while the first holds the lock.
    assert jobs.main(["worker", "--once"]) == 1
    assert "a worker is already running" in capsys.readouterr().err
    wait_for(lambda: all(r["status"] == "done" for r in jobs.all_jobs()))
    stop.set()
    thread.join(5)
    assert result == {"code": 0}
    starts, ends = fake_claude("start"), fake_claude("end")
    assert [s["prompt"] for s in starts] == [f"/research {b}", f"/synthesize {a}", f"/debate {c}"]
    for end, nxt in zip(ends, starts[1:], strict=False):
        assert end["t"] <= nxt["t"], "a job started before the previous one ended"
    assert not jobs.lock_file().exists()


def test_chained_jobs_wait_for_their_predecessor_and_follow_it(fake_claude, monkeypatch):
    run_id, other = make_run("sauna"), make_run("berry")
    ids = jobs.enqueue("validate", run_id, then=["synthesize", "debate"])
    later = jobs.enqueue("research", other)[0]
    assert [row(i)["next_job_id"] for i in ids] == [ids[1], ids[2], None]
    for _ in range(4):
        jobs.run_worker(once=True)
    # The chain runs before the later job: each follower is the oldest runnable one once its
    # predecessor is done.
    assert [s["prompt"] for s in fake_claude("start")] == [
        f"/validate {run_id}", f"/synthesize {run_id}", f"/debate {run_id}", f"/research {other}",
    ]
    assert [row(i)["status"] for i in [*ids, later]] == ["done"] * 4


def test_a_failed_job_cancels_its_chain(fake_claude, monkeypatch, capsys):
    run_id = make_run("sauna")
    modes(monkeypatch, **{f"/validate_{run_id}": "fail"})
    ids = jobs.enqueue("validate", run_id, then=["synthesize", "debate"])
    jobs.run_worker(once=True)
    assert [(row(i)["status"], row(i)["reason"]) for i in ids] == [
        ("failed", "exit 1"), ("cancelled", f"job {ids[0]} failed"), ("cancelled", f"job {ids[0]} failed"),
    ]
    assert row(ids[0])["exit_code"] == 1
    capsys.readouterr()
    assert jobs.run_worker(once=True) == 0
    assert capsys.readouterr().out == "no queued job\n"
    assert len(fake_claude("start")) == 1


@pytest.mark.parametrize(
    "mode,reason",
    [
        ("usage_limit", "usage_limit"),
        ("usage_limit_exit0", "usage_limit"),
        ("stderr_limit", "usage_limit"),
        ("page_mentions_limit", "exit 1"),
        ("fail", "exit 1"),
    ],
)
def test_failure_reason(fake_claude, monkeypatch, mode, reason):
    run_id = make_run("sauna")
    modes(monkeypatch, **{f"/research_{run_id}": mode})
    (job_id,) = jobs.enqueue("research", run_id)
    jobs.run_worker(once=True)
    assert (row(job_id)["status"], row(job_id)["reason"]) == ("failed", reason)


def test_missing_claude_binary_fails_the_job(fake_claude, project, monkeypatch):
    monkeypatch.setenv(jobs.CLAUDE_BIN_ENV, str(project / "no-such-claude"))
    run_id = make_run("sauna")
    ids = jobs.enqueue("synthesize", run_id, then=["debate"])
    jobs.run_worker(once=True)
    assert row(ids[0])["status"] == "failed" and row(ids[0])["reason"].startswith("cannot start")
    assert row(ids[1])["status"] == "cancelled"


def test_worker_refuses_while_the_dev_marker_exists(fake_claude, project, capsys):
    run_id = make_run("sauna")
    (job_id,) = jobs.enqueue("synthesize", run_id)
    config.DEV_MARKER.write_text("", encoding="utf-8")
    assert jobs.main(["worker", "--once"]) == 1
    err = capsys.readouterr().err
    assert ".ideaforge-dev exists" in err and "strict pipeline guard" in err
    assert row(job_id)["status"] == "queued"
    assert fake_claude() == []
    assert not jobs.lock_file().exists()


# ---------------------------------------------------------------- cancel and retry


def test_cancel_a_queued_job_and_its_chain(fake_claude, capsys):
    run_id = make_run("sauna")
    ids = jobs.enqueue("validate", run_id, then=["synthesize"])
    assert jobs.main(["cancel", str(ids[0])]) == 0
    assert capsys.readouterr().out.splitlines() == [f"cancelled job {ids[0]}", f"cancelled job {ids[1]}"]
    assert [(row(i)["status"], row(i)["reason"]) for i in ids] == [
        ("cancelled", "cancelled"), ("cancelled", f"job {ids[0]} cancelled"),
    ]
    assert jobs.main(["cancel", str(ids[0])]) == 1
    assert "already cancelled" in capsys.readouterr().err
    jobs.run_worker(once=True)
    assert fake_claude() == []


# POSIX: the exit code is minus the signal; Windows terminates with the signal number as exit code
# and cannot ignore it.
@pytest.mark.parametrize("mode,signal_code", [("sleep", -15), ("ignore_term", -9)])
def test_cancel_a_running_job_terminates_it(fake_claude, monkeypatch, mode, signal_code):
    run_id = make_run("sauna")
    modes(monkeypatch, **{f"/debate_{run_id}": mode})
    ids = jobs.enqueue("debate", run_id, then=["synthesize"])
    thread, stop, result = worker_thread()
    wait_for(lambda: fake_claude("start") and row(ids[0])["pid"])
    pid = fake_claude("start")[0]["pid"]
    started = time.monotonic()
    assert jobs.cancel(ids[0], grace=0.5) == ids
    wait_for(lambda: row(ids[0])["exit_code"] is not None)
    stop.set()
    thread.join(5)
    assert time.monotonic() - started < 10
    assert result == {"code": 0}
    job = row(ids[0])
    expected = int(signal.SIGTERM) if os.name == "nt" else signal_code
    assert (job["status"], job["reason"], job["exit_code"]) == ("cancelled", "cancelled", expected)
    assert not jobs.pid_alive(pid)
    assert row(ids[1])["status"] == "cancelled"
    assert fake_claude("end") == []
    assert len(fake_claude("start")) == 1  # the cancelled chain never ran


def test_retry_queues_the_job_and_its_cancelled_chain_again(fake_claude, monkeypatch, capsys):
    run_id = make_run("sauna")
    modes(monkeypatch, **{f"/validate_{run_id}": "usage_limit"})
    ids = jobs.enqueue("validate", run_id, then=["synthesize", "debate"])
    with pytest.raises(jobs.JobError, match="still queued"):
        jobs.retry(ids[0])
    jobs.run_worker(once=True)
    monkeypatch.delenv("FAKE_CLAUDE_MODES")
    capsys.readouterr()
    assert jobs.main(["retry", str(ids[0])]) == 0
    assert capsys.readouterr().out.splitlines() == [
        f"queued job 4: validate {run_id}", f"queued job 5: synthesize {run_id}", f"queued job 6: debate {run_id}",
    ]
    for _ in range(3):
        jobs.run_worker(once=True)
    assert [row(i)["status"] for i in (4, 5, 6)] == ["done"] * 3
    assert [row(i)["status"] for i in ids] == ["failed", "cancelled", "cancelled"]
    eval_id = jobs.enqueue("eval", args={"limit": 1})[0]
    jobs.cancel(eval_id)
    (again,) = jobs.retry(eval_id)
    assert json.loads(row(again)["args"]) == {"limit": 1}


# ---------------------------------------------------------------- restart safety


def dead_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def insert_running(run_id: str, pid: int | None) -> int:
    with db.session() as conn:
        cur = conn.execute(
            "INSERT INTO jobs(kind, args, run_id, status, pid, created_at, started_at)"
            " VALUES ('research', '{}', ?, 'running', ?, ?, ?)",
            (run_id, pid, db.now(), db.now()),
        )
        return cur.lastrowid


def test_restart_marks_a_running_job_without_a_process_interrupted(fake_claude, capsys):
    run_id = make_run("sauna")
    gone = insert_running(run_id, dead_pid())
    never_started = insert_running(run_id, None)
    follower = jobs.enqueue("synthesize", run_id)[0]
    with db.session() as conn:
        conn.execute("UPDATE jobs SET next_job_id=? WHERE job_id=?", (follower, gone))
    assert jobs.main(["worker", "--once"]) == 0
    out = capsys.readouterr().out
    assert f"job {gone}: interrupted" in out and f"job {never_started}: interrupted" in out
    for job_id in (gone, never_started):
        assert (row(job_id)["status"], row(job_id)["reason"]) == ("failed", "interrupted")
    assert row(follower)["status"] == "cancelled"
    assert fake_claude() == []  # nothing else was queued
    (retried, again) = jobs.retry(gone)
    jobs.run_worker(once=True)
    jobs.run_worker(once=True)
    assert [s["prompt"] for s in fake_claude("start")] == [f"/research {run_id}", f"/synthesize {run_id}"]
    assert row(retried)["status"] == row(again)["status"] == "done"


def test_worker_refuses_while_a_running_job_still_has_a_process(fake_claude, capsys):
    run_id = make_run("sauna")
    job_id = insert_running(run_id, os.getpid())
    queued = jobs.enqueue("synthesize", run_id)[0]
    assert jobs.main(["worker", "--once"]) == 1
    assert f"job {job_id} is still running as pid {os.getpid()}" in capsys.readouterr().err
    assert row(job_id)["status"] == "running" and row(queued)["status"] == "queued"


def test_a_stale_pid_file_does_not_block_the_worker(fake_claude):
    jobs.lock_file().parent.mkdir(parents=True, exist_ok=True)
    jobs.lock_file().write_text(f"{dead_pid()}\n", encoding="utf-8")
    assert jobs.run_worker(once=True) == 0
    assert not jobs.lock_file().exists()


# ---------------------------------------------------------------- new ideas


def test_enqueue_a_new_idea_creates_the_run_with_its_intake(fake_claude, project, capsys):
    code = jobs.main([
        "enqueue", "validate", "--idea", "Sauna cabins by the lake (synthetic)", "--intake", json.dumps(INTAKE),
        "--preset", "economy", "--then", "synthesize",
    ])
    assert code == 0
    lines = capsys.readouterr().out.splitlines()
    run_id = lines[0].split()[-1]
    assert runs.RUN_ID_RE.match(run_id)
    assert lines == [f"queued job 1: validate {run_id}", f"queued job 2: synthesize {run_id}"]
    run_dir = project / "runs" / run_id
    intake = Intake.model_validate_json((run_dir / "intake.json").read_text(encoding="utf-8"))
    assert intake.goal == "side_income" and intake.skills is None and len(intake.answers) == 1
    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["budget_preset"] == "economy"
    jobs.run_worker(once=True)
    assert fake_claude("start")[0]["prompt"] == f"/validate {run_id}"


@pytest.mark.parametrize(
    "intake",
    [json.dumps(INTAKE | {"goal": "rich"}), json.dumps(INTAKE | {"extra": 1}), "{not json", json.dumps({})],
)
def test_an_invalid_intake_creates_no_run_and_no_job(fake_claude, project, capsys, intake):
    assert jobs.main(["enqueue", "validate", "--idea", "Sauna cabins", "--intake", intake]) == 1
    err = capsys.readouterr().err
    assert "invalid --intake" in err and "new_run.py refused" in err
    assert [p.name for p in (project / "runs").iterdir() if runs.RUN_ID_RE.match(p.name)] == []
    assert jobs.all_jobs() == []


def test_new_idea_flags_go_together(fake_claude):
    with pytest.raises(SystemExit):
        jobs.main(["enqueue", "validate", "--idea", "Sauna cabins"])  # no --intake
    with pytest.raises(SystemExit):
        jobs.main(["enqueue", "research", "--idea", "Sauna cabins", "--intake", json.dumps(INTAKE)])
    with pytest.raises(SystemExit):
        jobs.main(["enqueue", "validate", "--preset", "economy", "--run", make_run("x")])
    assert jobs.all_jobs() == []
