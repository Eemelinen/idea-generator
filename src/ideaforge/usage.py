"""Tool-call usage log, driven by the PostToolUse hook.

    uv run python -m ideaforge.usage log   < hook-json

Appends one line per tool call to runs/<run_id>/usage.jsonl, keeps per-agent
search/fetch counters, records every URL an agent has seen (for the
no-invented-URL check), and writes runs/<run_id>/BUDGET_EXCEEDED_<agent> when a
counter passes its budget. Does nothing when no run is active. Never blocks.

`summarize` / `render_summary` turn a run's usage.jsonl into the per-stage and per-agent
report printed by scripts/usage_report.py (and the usage section of scripts/status.py).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ideaforge import agents, config, db, hookio, runs

URL_RE = re.compile(r"https?://[^\s\"'<>()\[\]{}\\]+")
COUNTED_TOOLS = {"WebSearch": "max_web_searches", "WebFetch": "max_web_fetches"}


def approx_tokens(data: dict[str, Any]) -> int:
    payload = json.dumps(
        {"in": data.get("tool_input"), "out": data.get("tool_response")}, ensure_ascii=False, default=str
    )
    return len(payload) // 4


def seen_urls(data: dict[str, Any]) -> list[str]:
    tool = data.get("tool_name")
    if tool == "WebFetch":
        url = (data.get("tool_input") or {}).get("url")
        return [url] if url else []
    if tool == "WebSearch":
        text = json.dumps(data.get("tool_response"), ensure_ascii=False, default=str)
        return sorted({u.rstrip(".,;:") for u in URL_RE.findall(text)})
    return []


def run_preset(run_dir: Path) -> str | None:
    try:
        return json.loads((run_dir / "meta.json").read_text(encoding="utf-8")).get("budget_preset")
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def update_counters(run_dir: Path, agent: str, tool: str) -> dict[str, int]:
    path = run_dir / ".counters.json"
    try:
        counters = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        counters = {}
    per_agent = counters.setdefault(agent, {})
    per_agent[tool] = per_agent.get(tool, 0) + 1
    path.write_text(json.dumps(counters, indent=2), encoding="utf-8")
    return per_agent


def check_budget(run_dir: Path, agent: str, per_agent: dict[str, int]) -> str | None:
    spec = agents.get(agent)
    if spec is None or spec.budget_key is None:
        return None
    limits = getattr(config.budget().preset(run_preset(run_dir)), spec.budget_key)
    over = [
        f"{tool}: {n} > {getattr(limits, key)}"
        for tool, key in COUNTED_TOOLS.items()
        if (n := per_agent.get(tool, 0)) > getattr(limits, key)
    ]
    if not over:
        return None
    (run_dir / f"BUDGET_EXCEEDED_{agent}").write_text("\n".join(over) + "\n", encoding="utf-8")
    return "; ".join(over)


def log(data: dict[str, Any]) -> None:
    run_id = runs.active_run_id()
    if not run_id:
        return
    run_dir = config.RUNS_DIR / run_id
    agent = hookio.agent_name(data) or "main"
    tool = data.get("tool_name") or "?"
    spec = agents.get(agent)
    row = {
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
        "run_id": run_id,
        "stage": None,
        "agent": agent,
        "tool": tool,
        "model": config.models().roles.get(spec.role if spec else "orchestrator"),
        "approx_tokens": approx_tokens(data),
    }
    with open(run_dir / "usage.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")

    urls = seen_urls(data)
    if urls:
        with open(run_dir / ".seen_urls.txt", "a", encoding="utf-8") as f:
            f.write("".join(f"{agent}\t{u}\n" for u in urls))

    if tool in COUNTED_TOOLS:
        check_budget(run_dir, agent, update_counters(run_dir, agent, tool))

    try:
        db.log_usage(row)
    except Exception:  # the JSONL file is the source of truth; the DB copy is best effort
        pass


# ------------------------------------------------------------------ per-run report

NO_STAGE = "(no stage)"


@dataclass
class Tally:
    calls: int = 0
    searches: int = 0
    fetches: int = 0
    tokens: int = 0

    def add(self, row: Mapping[str, Any]) -> None:
        self.calls += 1
        self.searches += row.get("tool") == "WebSearch"
        self.fetches += row.get("tool") == "WebFetch"
        tokens = row.get("approx_tokens")
        self.tokens += tokens if isinstance(tokens, int) else 0


@dataclass
class UsageSummary:
    run_id: str
    total: Tally = field(default_factory=Tally)
    by_stage: dict[str, Tally] = field(default_factory=dict)
    by_agent: dict[str, Tally] = field(default_factory=dict)
    skipped_lines: int = 0
    budget_markers: dict[str, str] = field(default_factory=dict)  # file name → its text, one line


def read_log(run_dir: Path) -> tuple[list[dict[str, Any]], int]:
    """The usage.jsonl rows of a run and the number of lines that were not a JSON object."""
    try:
        lines = (run_dir / "usage.jsonl").read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return [], 0
    rows, skipped = [], 0
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            row = None
        if isinstance(row, dict):
            rows.append(row)
        else:
            skipped += 1
    return rows, skipped


def parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        ts = datetime.fromisoformat(value)
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)


@dataclass(frozen=True)
class StageWindow:
    stage: str
    start: datetime
    end: datetime | None  # None = still open

    def contains(self, ts: datetime) -> bool:
        return self.start <= ts and (self.end is None or ts <= self.end)


def stage_windows(stage_rows: Iterable[Mapping[str, Any]]) -> list[StageWindow]:
    """Time windows of the stages that have started. A running stage, or one restarted after it
    last finished (stage_set keeps the old finished_at), is open-ended."""
    windows = []
    for r in stage_rows:
        start = parse_ts(r["started_at"])
        if start is None:
            continue
        end = parse_ts(r["finished_at"])
        if r["status"] == "running" or (end is not None and end < start):
            end = None
        windows.append(StageWindow(r["stage"], start, end))
    return windows


def attribute_stage(row: Mapping[str, Any], windows: Sequence[StageWindow]) -> str:
    """The row's own `stage`; else, for a research agent, its dimension's stage (research stages
    run in parallel, and a retry moves `started_at` past the first attempt's calls); else the
    latest-started stage whose window holds the timestamp."""
    if row.get("stage"):
        return str(row["stage"])
    spec = agents.get(row.get("agent"))
    if spec is not None and spec.kind == "research":
        return f"research:{spec.dimension}"
    ts = parse_ts(row.get("ts"))
    holding = [w for w in windows if ts is not None and w.contains(ts)]
    return max(holding, key=lambda w: w.start).stage if holding else NO_STAGE


def marker_text(path: Path) -> list[str]:
    """The non-blank lines of a marker file (BUDGET_EXCEEDED_*, VALIDATION_*)."""
    text = path.read_text(encoding="utf-8", errors="replace")
    return [line.strip() for line in text.splitlines() if line.strip()]


def budget_markers(run_dir: Path) -> dict[str, str]:
    return {
        p.name: "; ".join(marker_text(p)) for p in sorted(run_dir.glob("BUDGET_EXCEEDED_*")) if p.is_file()
    }


def summarize(run_id: str, run_dir: Path, stage_rows: Iterable[Mapping[str, Any]] = ()) -> UsageSummary:
    rows, skipped = read_log(run_dir)
    windows = stage_windows(stage_rows)
    summary = UsageSummary(run_id, skipped_lines=skipped, budget_markers=budget_markers(run_dir))
    for row in rows:
        summary.total.add(row)
        summary.by_stage.setdefault(attribute_stage(row, windows), Tally()).add(row)
        summary.by_agent.setdefault(str(row.get("agent") or "?"), Tally()).add(row)
    return summary


def table(headers: Sequence[str], rows: Iterable[Sequence[Any]], align: str = "") -> list[str]:
    """Plain-text columns. `align` has one `l` or `r` per column; the default left-aligns the
    first column and right-aligns the rest."""
    cells = [[str(c) for c in headers], *([str(c) for c in r] for r in rows)]
    align = align or "l" + "r" * (len(headers) - 1)
    widths = [max(len(r[i]) for r in cells) for i in range(len(headers))]
    return [
        "  ".join(c.ljust(widths[i]) if align[i] == "l" else c.rjust(widths[i]) for i, c in enumerate(r)).rstrip()
        for r in cells
    ]


def _stage_order(stage: str) -> tuple[int, str]:
    if stage in runs.STAGES:
        return runs.STAGES.index(stage), ""
    return (len(runs.STAGES) + (stage == NO_STAGE), stage)


def usage_table(key: str, tallies: Mapping[str, Tally], total: Tally) -> list[str]:
    if key == "stage":
        names = sorted(tallies, key=_stage_order)
    else:
        names = sorted(tallies, key=lambda a: (a != "main", a))
    rows = [(n, t.calls, t.searches, t.fetches, t.tokens) for n, t in ((n, tallies[n]) for n in names)]
    rows.append(("total", total.calls, total.searches, total.fetches, total.tokens))
    return table((key, "calls", "searches", "fetches", "~tokens"), rows)


def render_summary(summary: UsageSummary) -> str:
    t = summary.total
    lines = [
        f"usage for {summary.run_id}: {t.calls} tool calls, {t.searches} searches, "
        f"{t.fetches} fetches, ~{t.tokens} tokens"
    ]
    if summary.skipped_lines:
        lines.append(f"warning: skipped {summary.skipped_lines} malformed line(s) in usage.jsonl")
    if t.calls:
        lines += ["", "per stage", *usage_table("stage", summary.by_stage, t)]
        lines += ["", "per agent", *usage_table("agent", summary.by_agent, t)]
    lines += ["", "budget markers"]
    lines += [f"{name}: {text}" for name, text in summary.budget_markers.items()] or ["none"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ideaforge.usage")
    parser.add_argument("command", choices=["log"])
    parser.parse_args(argv)
    try:
        log(hookio.read_input())
    except Exception as e:  # a logging hook must never break the session
        print(f"ideaforge.usage: {e}", file=sys.stderr)
    return hookio.OK


if __name__ == "__main__":
    sys.exit(main())
