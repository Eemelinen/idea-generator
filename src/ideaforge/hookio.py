"""Shared plumbing for Claude Code hook entry points (JSON on stdin, exit codes)."""

from __future__ import annotations

import json
import sys
from typing import Any, NoReturn

# Claude Code hook exit codes: 0 = proceed, 2 = block and show stderr to the model.
OK = 0
BLOCK = 2


def read_input() -> dict[str, Any]:
    raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def agent_name(data: dict[str, Any]) -> str | None:
    """The subagent's type when the hook fired inside a subagent, else None (main session)."""
    return data.get("agent_type") or None


def is_subagent(data: dict[str, Any]) -> bool:
    return bool(data.get("agent_type") or data.get("agent_id"))


def block(message: str) -> NoReturn:
    print(message, file=sys.stderr)
    sys.exit(BLOCK)
