#!/usr/bin/env bash
# PostToolUse hook: run Prettier on the edited file (honours .prettierignore). Never blocks.
set -uo pipefail
input="$(cat)"
root="${CLAUDE_PROJECT_DIR:-$PWD}"
file="$(printf '%s' "$input" | node -e '
  let s = ""
  process.stdin.on("data", (d) => (s += d)).on("end", () => {
    try { process.stdout.write(String((JSON.parse(s).tool_input || {}).file_path || "")) } catch {}
  })
')"
[ -n "$file" ] || exit 0
case "$file" in /*) ;; *) file="$root/$file" ;; esac
[ -f "$file" ] || exit 0
case "$file" in "$root"/*) ;; *) exit 0 ;; esac
(cd "$root" && pnpm exec prettier --write --log-level warn --ignore-unknown "$file" >/dev/null 2>&1) || true
exit 0
