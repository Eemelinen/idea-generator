"""PreToolUse guard for file writes and shell commands.

    uv run python -m ideaforge.guard write   < hook-json   (Write|Edit|MultiEdit|NotebookEdit)
    uv run python -m ideaforge.guard bash    < hook-json   (Bash|PowerShell)

Policy (exit 2 = deny, reason on stderr):
- Writes outside the project root, or into .git/, are always denied.
- Subagents are always strict: a research agent may write only its own
  runs/<run_id>/02_research/<dimension>.md, a debate agent only under
  runs/<run_id>/debate/, any other subagent only under runs/ or cache/.
- The main session is strict (runs/ and cache/ only) unless it is a development
  session: the dev marker file .ideaforge-dev exists at the project root, or the
  harness loop driver started it (HARNESS_LOOP=1, docs/DECISIONS.md D-005). A
  development session may write anywhere inside the project.
- Shell commands in strict mode must match an allow-list (uv run python -m
  ideaforge…, uv run python scripts/…, uv run pytest, git, ls, cat) and may not
  fetch from the network, substitute commands or redirect output to files.
  Research agents may only run the ideaforge.fi data tools (plus ls/cat); the
  harness evaluator may also run the read-only harness checks, pnpm test:py and
  grep/head/tail/wc. Text inside quotes is not read as `>` or `|`.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any

from ideaforge import agents, config, hookio, runs

NETWORK_RE = re.compile(
    r"(?i)(^|[\s;&|(])(curl|wget|invoke-webrequest|iwr|invoke-restmethod|irm|start-bitstransfer)(\.exe)?\b"
)
SEGMENT_SPLIT_RE = re.compile(r"&&|\|\||[;|&\n]")
SAFE_REDIRECTS_RE = re.compile(r"\d?>&\d|2>\s*(/dev/null|\$null|nul)\b", re.IGNORECASE)
# A complete '…' or "…" string; an unterminated quote is left alone, so nothing after it hides.
QUOTED_RE = re.compile(r"'[^']*'|\"(?:[^\"\\]|\\.)*\"")
# Shell syntax QUOTED_RE cannot read the way the shell does: an escaped quote outside a string
# (`cat \'; rm -rf src; cat \'`), ANSI-C `$'…'`, a comment, a heredoc. With any of it, quotes are
# not stripped and the command is checked as written.
UNQUOTE_UNSAFE_RE = re.compile(r"\\['\"]|\$'|#|<<")

GENERAL_ALLOW = (
    re.compile(r"^uv\s+run\s+(--quiet\s+|-q\s+)?python\s+-m\s+ideaforge(\.|\s|$)"),
    re.compile(r"^uv\s+run\s+(--quiet\s+|-q\s+)?python\s+scripts/[\w./-]+\.py(\s|$)"),
    re.compile(r"^uv\s+run\s+(--quiet\s+|-q\s+)?pytest(\s|$)"),
    re.compile(r"^python\s+-m\s+ideaforge(\.|\s|$)"),
    re.compile(r"^git(\s|$)"),
    re.compile(r"^(ls|cat)(\s|$)"),
)
HARNESS_ALLOW = GENERAL_ALLOW + (
    re.compile(r"^pnpm\s+(--silent\s+)?(check|test:py|harness:check|harness:feature\s+(show|list|next))(\s|$)"),
    # Read-only filters, mostly the tail of a pipeline (`pnpm check 2>&1 | tail -5`).
    re.compile(r"^(grep|head|tail|wc)(\s|$)"),
)
RESEARCH_ALLOW = (
    re.compile(r"^uv\s+run\s+(--quiet\s+|-q\s+)?python\s+-m\s+ideaforge\.fi\.\w+(\s|$)"),
    re.compile(r"^python\s+-m\s+ideaforge\.fi\.\w+(\s|$)"),
    re.compile(r"^(ls|cat)(\s|$)"),
)


def dev_mode() -> bool:
    return config.DEV_MARKER.exists() or os.environ.get("HARNESS_LOOP") == "1"


def _within(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


MSYS_DRIVE_RE = re.compile(r"^/([a-zA-Z])(/|$)")


def _native(raw: str) -> Path:
    """Path from hook input; Git Bash style '/c/Users/…' becomes 'C:/Users/…' on Windows."""
    if sys.platform == "win32":
        raw = MSYS_DRIVE_RE.sub(lambda m: f"{m.group(1).upper()}:/", raw)
    return Path(raw)


def _target_path(data: dict[str, Any]) -> Path | None:
    ti = data.get("tool_input") or {}
    raw = ti.get("file_path") or ti.get("notebook_path") or ti.get("path")
    if not raw:
        return None
    p = _native(raw)
    if not p.is_absolute():
        p = _native(data.get("cwd") or str(config.ROOT)) / p
    return p.resolve()


def check_write(data: dict[str, Any]) -> str | None:
    """Return a denial reason, or None when the write is allowed."""
    target = _target_path(data)
    if target is None:
        return None
    root = config.ROOT
    if not _within(target, root):
        return f"write denied: {target} is outside the project ({root})"
    if _within(target, root / ".git"):
        return "write denied: .git/ is never written by tools"

    runs_dir, cache_dir = config.RUNS_DIR, config.CACHE_DIR
    if hookio.is_subagent(data):
        spec = agents.get(hookio.agent_name(data))
        run_id = runs.active_run_id()
        if spec is not None and spec.kind == "research":
            if run_id is None:
                return "write denied: no active run (runs/.active) for this research agent"
            allowed = agents.research_output(runs_dir / run_id, spec)
            if target != allowed.resolve():
                return f"write denied: {spec.name} may only write {allowed.relative_to(root).as_posix()}"
            return None
        if spec is not None and spec.kind in ("debate", "judge"):
            if run_id is None:
                return "write denied: no active run (runs/.active) for this debate agent"
            if not _within(target, (runs_dir / run_id / "debate").resolve()):
                return f"write denied: {spec.name} may only write under runs/{run_id}/debate/"
            return None
        if _within(target, runs_dir) or _within(target, cache_dir):
            return None
        return "write denied: subagents may only write under runs/ or cache/"

    if dev_mode():
        return None
    if _within(target, runs_dir) or _within(target, cache_dir):
        return None
    return (
        "write denied: outside a development session only runs/ and cache/ are writable "
        "(create .ideaforge-dev at the project root to develop)"
    )


def check_bash(data: dict[str, Any]) -> str | None:
    """Return a denial reason, or None when the command is allowed."""
    command = ((data.get("tool_input") or {}).get("command") or "").strip()
    if not command:
        return None
    subagent = hookio.is_subagent(data)
    if not subagent and dev_mode():
        return None

    if NETWORK_RE.search(command):
        return "command denied: fetch pages with WebFetch or the ideaforge.fi tools so they are logged and cached"
    if any(token in command for token in ("$(", "`", "<(", ">(")):
        return "command denied: command substitution is not allowed"
    # `>` and `|` inside quotes are pattern text (`git grep -e "a|b"`), not shell operators.
    unquoted = (
        command
        if UNQUOTE_UNSAFE_RE.search(command)
        else QUOTED_RE.sub(lambda m: m.group(0)[0] * 2, command)
    )
    # `2>&1` is allowed and must not split the command at its `&`.
    unquoted = SAFE_REDIRECTS_RE.sub("", unquoted)
    if ">" in unquoted:
        return "command denied: redirecting output to files is not allowed; write files with the Write tool"

    spec = agents.get(hookio.agent_name(data)) if subagent else None
    kind = spec.kind if spec is not None else None
    allow = {"research": RESEARCH_ALLOW, "harness": HARNESS_ALLOW}.get(kind, GENERAL_ALLOW)
    for segment in SEGMENT_SPLIT_RE.split(unquoted):
        seg = segment.strip().replace("\\", "/")
        if seg and not any(p.match(seg) for p in allow):
            return f"command denied: {seg!r} is not on the allow-list"
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ideaforge.guard")
    parser.add_argument("kind", choices=["write", "bash"])
    args = parser.parse_args(argv)
    data = hookio.read_input()
    reason = check_write(data) if args.kind == "write" else check_bash(data)
    if reason:
        hookio.block(reason)
    return hookio.OK


if __name__ == "__main__":
    sys.exit(main())
