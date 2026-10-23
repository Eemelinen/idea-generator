"""Tool-call usage log, driven by the PostToolUse hook.

    uv run python -m ideaforge.usage log   < hook-json

Appends one line per tool call to runs/<run_id>/usage.jsonl, keeps per-agent
search/fetch counters, records every URL an agent has seen (for the
no-invented-URL check), and writes runs/<run_id>/BUDGET_EXCEEDED_<agent> when a
counter passes its budget. Does nothing when no run is active. Never blocks.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
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
