#!/usr/bin/env bash
# Opt-in Stop hook for driver-run sessions (docs/DECISIONS.md D-008). Inert unless the loop
# driver sets HARNESS_STOP_GUARD=1. Blocks the session from ending while the machine-checkable
# clean-state checks fail or the active feature is still in_progress, at most 3 times per
# session (Claude Code also caps consecutive Stop-hook blocks).
#   stdout {"decision":"block","reason":"…"} → Claude keeps working; plain exit 0 → may stop
set -uo pipefail
[ "${HARNESS_STOP_GUARD:-0}" = "1" ] || exit 0
input="$(cat)"
root="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"

field() {
  printf '%s' "$input" | node -e '
    let s = ""
    process.stdin.on("data", (d) => (s += d)).on("end", () => {
      try { const v = JSON.parse(s)[process.argv[1]]; process.stdout.write(v == null ? "" : String(v)) } catch {}
    })
  ' "$1"
}

# A previous block already put Claude back to work in this turn; never loop.
[ "$(field stop_hook_active)" = "true" ] && exit 0

session="$(field session_id)"
counter="$root/.harness/stop-blocks-${session:-unknown}"
mkdir -p "$root/.harness"
count="$(cat "$counter" 2>/dev/null || echo 0)"
if [ "$count" -ge 3 ]; then
  echo "stop-guard: block cap reached for this session; letting it stop" >&2
  exit 0
fi

report="$(cd "$root" && scripts/clean-state-check.sh --quick --require-terminal 2>&1)"
status=$?
if [ "$status" = "0" ]; then
  exit 0
fi

echo $((count + 1)) > "$counter"
first="$(printf '%s\n' "$report" | grep -m1 '\[FAIL\]' | sed 's/.*\[FAIL\][^m]*m //; s/\x1b\[[0-9;]*m//g')"
reason="Not clean yet: ${first:-clean-state check failed}. Finish the loop: /verify-feature the active feature (or pnpm harness:feature block <id> --reason \"…\"), then /clock-out so the tree is committed. Block $((count + 1))/3."
node -e 'console.log(JSON.stringify({ decision: "block", reason: process.argv[1] }))' "$reason"
exit 0
