#!/usr/bin/env bash
# Standard startup and verification path (course: learn-harness-engineering).
#   ./init.sh                 install + tooling checks + L1 baseline (`pnpm check`)
#   FAST=1 ./init.sh          skip the baseline (tooling checks only)
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$1"; }
step() { printf '\n\033[1;36m==> %s\033[0m\n' "$1"; }

step "Working directory: $PWD"

step "Tooling"
WANT_NODE="$(tr -d 'v[:space:]' < .nvmrc)"
HAVE_NODE="$(node -v 2>/dev/null | tr -d 'v' || true)"
if [ -z "$HAVE_NODE" ]; then
  echo "Node.js is not installed; install Node ${WANT_NODE} (see .nvmrc)." >&2
  exit 1
fi
if [ "${HAVE_NODE%%.*}" != "${WANT_NODE%%.*}" ]; then
  warn "Node ${HAVE_NODE} found, .nvmrc wants ${WANT_NODE} (try: nvm use)"
fi
if ! command -v pnpm >/dev/null 2>&1; then
  echo "pnpm is missing; run: corepack enable" >&2
  exit 1
fi
# The pipeline hooks in .claude/settings.json run through uv; without it they fail open.
if ! command -v uv >/dev/null 2>&1; then
  echo "uv is missing from PATH; install it (https://docs.astral.sh/uv/) or add ~/.local/bin to PATH" >&2
  exit 1
fi
echo "node ${HAVE_NODE} · pnpm $(pnpm -v) · $(uv --version) · python $(tr -d '[:space:]' < .python-version)"

if [ -f .ideaforge-dev ]; then
  echo "dev marker: .ideaforge-dev present (main session may write project files)"
elif [ "${HARNESS_LOOP:-0}" = "1" ]; then
  echo "dev marker: not needed in a driver-run session (HARNESS_LOOP=1)"
else
  warn ".ideaforge-dev is missing — the pipeline guard limits writes to runs/ and cache/; touch .ideaforge-dev to develop"
fi

step "Installing dependencies"
pnpm install --frozen-lockfile

step "Harness wiring (@eemelinen/harness package + plugin pin)"
pnpm harness:doctor
uv sync --frozen

if [ "${FAST:-0}" = "1" ]; then
  step "FAST=1 — skipping baseline verification"
else
  step "Baseline verification (L1): pnpm check"
  pnpm check
fi

step "Start commands"
echo "  uv run python scripts/gen_agents.py   # after editing config/models.yaml, agent_templates/ or prompts/"
echo "  /validate <idea text>                 # in Claude Code: run the pipeline (Phase 2+)"
echo "  pnpm check                            # L1"

cat <<'MSG'

Next steps:
  1. Read PROGRESS.md and feature_list.json.
  2. Pick ONE unfinished feature (highest priority, not blocked) and set it in_progress.
  3. Implement only that feature; run its verification layers in order.
  4. Record evidence, update PROGRESS.md, commit (see AGENTS.md → Clock-out).
MSG
