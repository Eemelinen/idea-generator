#!/usr/bin/env bash
# Machine-checkable part of docs/harness/clean-state-checklist.md (AGENTS.md → Clock-out).
# Exit 0 only when every check passes. Idempotent and read-only.
#
#   scripts/clean-state-check.sh                     full run (includes FAST=1 ./init.sh)
#   scripts/clean-state-check.sh --quick             skip init.sh (used by the Stop hook)
#   scripts/clean-state-check.sh --allow-state-dirty tolerate uncommitted state files
#                                                    (feature_list.json, PROGRESS.md, docs/harness/**)
#   scripts/clean-state-check.sh --require-terminal  fail if any feature is still in_progress
#                                                    (driver-run sessions must end passing or blocked)
#   scripts/clean-state-check.sh --base <ref>        diff base for the branch checks
#                                                    (default: origin/main, then main)
set -uo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)" || exit 1

quick=0
allow_state_dirty=0
require_terminal=0
base=""
while [ $# -gt 0 ]; do
  case "$1" in
    --quick) quick=1 ;;
    --allow-state-dirty) allow_state_dirty=1 ;;
    --require-terminal) require_terminal=1 ;;
    --base) shift; base="${1:-}" ;;
    -h | --help) sed -n '2,14p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 1 ;;
  esac
  shift
done

if [ -z "$base" ]; then
  if git rev-parse --verify --quiet origin/main >/dev/null; then base="origin/main"; else base="main"; fi
fi

failures=0
ok() { printf '  \033[32m[ok]\033[0m   %s\n' "$1"; }
fail() { printf '  \033[31m[FAIL]\033[0m %s\n' "$1"; failures=$((failures + 1)); }
skip() { printf '  \033[33m[skip]\033[0m %s\n' "$1"; }

echo "clean-state check (base: $base, branch: $(git rev-parse --abbrev-ref HEAD))"

# 1. Working tree ---------------------------------------------------------------
dirty="$(git status --porcelain)"
if [ -z "$dirty" ]; then
  ok "working tree is clean"
elif [ "$allow_state_dirty" = "1" ]; then
  other="$(printf '%s\n' "$dirty" | grep -vE '^.. (feature_list\.json|PROGRESS\.md|docs/harness/)' || true)"
  if [ -z "$other" ]; then
    ok "only state files are uncommitted (allowed)"
  else
    fail "uncommitted changes outside the state files:"
    printf '%s\n' "$other" | sed 's/^/         /'
  fi
else
  fail "working tree is dirty (commit, or pass --allow-state-dirty when only state files changed):"
  printf '%s\n' "$dirty" | head -10 | sed 's/^/         /'
fi

# 2. Feature list ----------------------------------------------------------------
if out="$(pnpm --silent harness:check 2>&1)"; then
  ok "$out"
else
  fail "pnpm harness:check: $out"
fi

active="$(node -e '
  const l = JSON.parse(require("fs").readFileSync("feature_list.json", "utf8"))
  const a = l.features.filter((f) => f.status === "in_progress").map((f) => f.id)
  process.stdout.write(a.join(","))
' 2>/dev/null || true)"
if [ "$require_terminal" = "1" ]; then
  if [ -z "$active" ]; then
    ok "no feature left in_progress (session ended passing or blocked)"
  else
    fail "$active is still in_progress; run /verify-feature or mark it blocked before stopping"
  fi
fi

# 3. Branch diff checks (committed + uncommitted, relative to base) ---------------
# Added lines relative to base: committed + uncommitted diff plus whole untracked files.
diff_added() {
  git diff "$base" -- "$@" 2>/dev/null | grep -E '^\+' | grep -vE '^\+\+\+' || true
  git ls-files --others --exclude-standard -- "$@" 2>/dev/null | while IFS= read -r f; do
    [ -f "$f" ] && cat "$f"
  done
}
diff_removed() { git diff "$base" -- "$@" 2>/dev/null | grep -E '^-' | grep -vE '^---' || true; }

if ! git rev-parse --verify --quiet "$base" >/dev/null; then
  skip "base $base does not exist; diff checks skipped"
else
  if diff_added tests | grep -qE '\.(only|skip)\(|\b(it|test|describe)\.(only|skip)\b|pytest\.mark\.(skip|skipif|xfail)\b|pytest\.(skip|xfail)\('; then
    fail "a skip/only/xfail was added under tests/ (AGENTS.md: never skip tests to get green)"
  else
    ok "no skip/only/xfail added under tests/"
  fi
  if diff_removed pyproject.toml vitest.config.ts | grep -qE 'fail_under|--cov-fail-under|(lines|functions|branches|statements):\s*[0-9]+'; then
    fail "a coverage threshold in pyproject.toml or vitest.config.ts was removed or changed; keep or raise thresholds"
  else
    ok "coverage thresholds untouched"
  fi
  # print() is not checked: the src/ and scripts/ CLIs print their results by design.
  if diff_added 'src/*.py' 'scripts/*.py' | grep -qE '\bbreakpoint\(\)|pdb\.set_trace\(|^\+?\s*import i?pdb\b'; then
    fail "a Python debugger call (breakpoint or pdb) was added under src/ or scripts/"
  else
    ok "no Python debugger calls added under src/ or scripts/"
  fi
  branch_files="$(git diff --name-only "$base" 2>/dev/null || true)"
  if [ -n "$branch_files" ] && ! printf '%s\n' "$branch_files" | grep -qx 'PROGRESS.md'; then
    fail "PROGRESS.md was not updated on this branch (Current Verified State, session entry, Next Steps)"
  elif [ -n "$branch_files" ]; then
    ok "PROGRESS.md updated on this branch"
  else
    skip "no diff against $base; PROGRESS.md check not applicable"
  fi
fi

# 4. Secrets and generated files -------------------------------------------------
if git ls-files --error-unmatch .env >/dev/null 2>&1 || git diff --cached --name-only | grep -qx '.env'; then
  fail ".env is tracked or staged"
else
  ok ".env is not tracked or staged"
fi

# 5. Restart path ------------------------------------------------------------------
if [ "$quick" = "1" ]; then
  skip "FAST=1 ./init.sh (--quick)"
elif FAST=1 ./init.sh >/dev/null 2>&1; then
  ok "FAST=1 ./init.sh exits 0"
else
  fail "FAST=1 ./init.sh failed; the next session cannot start cleanly"
fi

echo
if [ "$failures" = "0" ]; then
  echo "clean-state: all checks passed"
  exit 0
fi
echo "clean-state: $failures check(s) failed"
exit 1
