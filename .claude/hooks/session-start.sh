#!/usr/bin/env bash
# SessionStart hook: print a compact, read-only state summary into Claude's context.
# Must stay fast (< 1 s). It never fails the session.
set -uo pipefail
cd "${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}" || exit 0

echo "## Ideaforge session state ($(date +%F))"
echo "repo: $PWD · branch: $(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
echo
echo "recent commits:"
git log --oneline -5 2>/dev/null | sed 's/^/  /'

dirty="$(git status --short 2>/dev/null || true)"
if [ -n "$dirty" ]; then
  echo
  echo "uncommitted changes:"
  printf '%s\n' "$dirty" | head -15 | sed 's/^/  /'
  if printf '%s\n' "$dirty" | grep -qE '^.. (src|scripts|prompts|agent_templates)/' && ! printf '%s\n' "$dirty" | grep -qE '^.. (PROGRESS\.md|feature_list\.json)$'; then
    echo
    echo "WARNING: source files have uncommitted changes but PROGRESS.md / feature_list.json are untouched."
    echo "A previous session may have stopped without clock-out. Read the diff before continuing."
  fi
fi

if [ -f PROGRESS.md ]; then
  echo
  awk '/^## Current Verified State/{f=1; print; next} /^## /{if (f) exit} f' PROGRESS.md
fi

if [ -f feature_list.json ]; then
  node -e '
    const fs = require("fs")
    try {
      const list = JSON.parse(fs.readFileSync("feature_list.json", "utf8"))
      const by = (s) => list.features.filter((f) => f.status === s)
      const active = by("in_progress")[0]
      const next = by("not_started").sort((a, b) => a.priority - b.priority)[0]
      console.log("")
      console.log(active ? `active feature: ${active.id} — ${active.title}` : "active feature: none (WIP=1 slot is free)")
      if (next) console.log(`next not_started: ${next.id} — ${next.title}`)
      console.log(`features: ${list.features.length} total · ${by("passing").length} passing · ${by("in_progress").length} in_progress · ${by("blocked").length} blocked`)
    } catch (e) {
      console.log("feature_list.json: " + e.message)
    }
  '
fi

echo
command -v uv >/dev/null 2>&1 && echo "uv: on PATH (pipeline hooks active)" || echo "uv: NOT on PATH — the pipeline hooks (ideaforge.guard, usage, validate_file) fail open; add ~/.local/bin to PATH"
if [ -f .ideaforge-dev ]; then
  echo "dev marker: .ideaforge-dev present (main session may edit project files)"
elif [ "${HARNESS_LOOP:-0}" = "1" ]; then
  echo "dev marker: HARNESS_LOOP=1 (driver-run development session)"
else
  echo "dev marker: absent — pipeline mode; main-session writes are limited to runs/ and cache/"
fi
[ -f runs/.active ] && echo "active run: $(cat runs/.active)"
echo
echo "Clock-in: AGENTS.md → Clock-in (or /clock-in). Layer: pnpm check (L1). Pipeline runs: CLAUDE.md → Pipeline sessions."
exit 0
