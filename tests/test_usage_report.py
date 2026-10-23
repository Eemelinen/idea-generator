import json

import pytest
import usage_report
from conftest import FIXTURES, SYNTHETIC_RUN

from ideaforge import db, usage

GOLDEN = FIXTURES / "status" / "usage_report.golden.txt"


def test_golden_output(synthetic_run, capsys):
    assert usage_report.main([SYNTHETIC_RUN]) == 0
    assert capsys.readouterr().out == GOLDEN.read_text(encoding="utf-8")


def test_stage_attribution(synthetic_run):
    s = usage.summarize(SYNTHETIC_RUN, synthetic_run, db.stages(SYNTHETIC_RUN))
    calls = {stage: t.calls for stage, t in s.by_stage.items()}
    assert calls == {
        "(no stage)": 1,          # before intake started
        "intake": 1,
        "plan": 1,
        "research:market": 3,     # by agent, incl. a write after its window closed
        "research:pricing": 3,    # by agent, incl. a first-attempt search before the retry's started_at
        "research:killcause": 2,  # its own search + main's read (latest-started open window)
        "verify": 1,              # the row's own stage field
    }
    assert (s.total.calls, s.total.searches, s.total.fetches, s.skipped_lines) == (12, 4, 2, 1)
    assert s.by_agent["research-market"].tokens == 2400 + 5000 + 900


def test_finished_window_is_closed():
    windows = usage.stage_windows([
        {"stage": "plan", "status": "done", "started_at": "2026-10-23T10:00:00+00:00",
         "finished_at": "2026-10-23T10:05:00+00:00"},
        {"stage": "verify", "status": "pending", "started_at": None, "finished_at": None},
    ])
    assert [w.stage for w in windows] == ["plan"]
    assert usage.attribute_stage({"ts": "2026-10-23T10:05:00+00:00", "agent": "main"}, windows) == "plan"
    assert usage.attribute_stage({"ts": "2026-10-23T10:05:01+00:00", "agent": "main"}, windows) == "(no stage)"
    assert usage.attribute_stage({"ts": "garbage", "agent": "main"}, windows) == "(no stage)"


def test_run_without_usage_log(project, capsys):
    from ideaforge import runs

    run_id = "20261023-120000-empty"
    runs.create_run_dir(run_id, "empty")
    assert usage_report.main([run_id]) == 0
    assert capsys.readouterr().out == (
        f"usage for {run_id}: 0 tool calls, 0 searches, 0 fetches, ~0 tokens\n\nbudget markers\nnone\n"
    )


def test_marker_text_joined(project):
    from ideaforge import runs

    d = runs.create_run_dir("20261023-120000-m", "m")
    (d / "BUDGET_EXCEEDED_research-gtm").write_text("WebSearch: 7 > 6\nWebFetch: 9 > 8\n", encoding="utf-8")
    assert usage.budget_markers(d) == {"BUDGET_EXCEEDED_research-gtm": "WebSearch: 7 > 6; WebFetch: 9 > 8"}


@pytest.mark.parametrize("run_id", ["not a run id", "20261023-120000-missing"])
def test_bad_or_missing_run(project, capsys, run_id):
    assert usage_report.main([run_id]) == 1
    assert capsys.readouterr().err.startswith("error: ")


def test_logged_rows_feed_the_report(active_run):
    usage.log({"tool_name": "WebSearch", "tool_input": {"query": "q"}, "tool_response": "",
               "agent_id": "x", "agent_type": "research-market"})
    rows, skipped = usage.read_log(active_run)
    assert skipped == 0 and json.loads(json.dumps(rows))[0]["tool"] == "WebSearch"
    s = usage.summarize(active_run.name, active_run)
    assert (s.total.calls, s.total.searches, list(s.by_stage)) == (1, 1, ["research:market"])


def test_invalid_utf8_is_not_fatal(project):
    from ideaforge import runs

    d = runs.create_run_dir("20261023-120000-bytes", "bytes")
    good = json.dumps({"ts": "2026-10-23T10:00:00+00:00", "agent": "main", "tool": "Read", "approx_tokens": 4})
    (d / "usage.jsonl").write_bytes(good.encode() + b"\n\xff\xfe broken\n")
    (d / "BUDGET_EXCEEDED_research-gtm").write_bytes(b"WebSearch: 7 > 6 \xff\n")
    (d / "BUDGET_EXCEEDED_dir").mkdir()  # not a marker file
    s = usage.summarize(d.name, d)
    assert (s.total.calls, s.skipped_lines) == (1, 1)
    assert list(s.budget_markers) == ["BUDGET_EXCEEDED_research-gtm"]
