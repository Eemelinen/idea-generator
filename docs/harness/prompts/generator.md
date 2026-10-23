You are running unattended inside the Ideaforge loop driver (`docs/harness/README.md`).
Nobody can answer questions and `HARNESS_LOOP=1` is set. Work only on feature
**{{FEATURE_ID}} — {{FEATURE_TITLE}}** (attempt {{ATTEMPT}} of {{MAX_ATTEMPTS}}) on this branch.

Follow the session loop exactly:

1. `/clock-in {{FEATURE_ID}}` — the driver already ran `FAST=1 ./init.sh`; do not re-run the baseline.
2. Implement the `user_visible_behavior`. First run `pnpm harness:feature show {{FEATURE_ID}}` and read the
   `spec` section it links in `docs/TICKETS.md` and the `IMPLEMENTATION_PLAN.md` sections that ticket cites.
   Obey every constraint in AGENTS.md, including the pipeline non-negotiables, and stay inside the
   feature's scope; a narrow supporting fix is fine, a second feature is not.
3. `/verify-feature {{FEATURE_ID}}` — never pass `--allow-manual`; if the feature has a manual step it is not
   yours to finish (block it, see below).
4. Clock out by following AGENTS.md → Clock-out and `.claude/skills/clock-out/SKILL.md` step by step yourself.
   The `/clock-out` skill is user-only (`disable-model-invocation`), so do not call it through the Skill tool;
   this prompt is the user's explicit request to run its steps. Commit on this branch with a conventional
   subject and a body that explains why. Do not push: the driver pushes and opens the pull request.

Rules for unattended runs:

- Never run `git push`, `git checkout main` or `git worktree …`; the driver owns the branch and the guard hook
  blocks these anyway. Never fetch live data (no live API calls, no recording fixtures): tests use the
  committed fixtures, and a feature that needs the network has a `manual:` step and is not yours.
- Never change the host outside this worktree (no files in the home directory, no PATH or shell-profile
  edits, no global installs). If the machine itself is broken (a tool missing from PATH, wrong Node
  version, `uv` not found), describe it in `PROGRESS.md` and block the feature; a human fixes the host.
- Never ask a question. Pick the simplest interpretation that satisfies the spec, implement it, and record the
  choice in `PROGRESS.md` and, when it deviates from the plan, under "Plan notes and deviations" in
  `docs/TICKETS.md`.
- If you cannot finish (missing network or credentials, spec conflict you cannot resolve, a layer that fails for reasons outside
  the feature), run `pnpm harness:feature block {{FEATURE_ID}} --reason "…"` with a precise reason, write what
  you learned into `PROGRESS.md`, commit, and clock out. A blocked feature with a clear reason is a good
  outcome; an unverified "passing" is not.
- Stop when the feature is `passing` or `blocked` and the tree is committed. The Stop hook will refuse to end
  the session in any other state.
  {{CONTEXT}}
