---
name: research
description: Run Ideaforge stages 1–3 (research plan, the 11 parallel research subagents, claim verification) for an existing run whose intake is done. Resumable; completed stages and dimensions are skipped. Use when the user types /research <run_id>.
argument-hint: '<run_id>'
allowed-tools: Read Write Agent Bash(uv run python scripts/run_stage.py*) Bash(uv run python scripts/verify_claims.py*) Bash(uv run python scripts/usage_report.py*) Bash(uv run python scripts/status.py*) Bash(uv run python -m ideaforge.validate_file*) Bash(ls*) Bash(cat*)
---

You are the orchestrator of an existing Ideaforge run. This skill runs stages 1–3 only; it
never creates a run and never writes `00_spec.json`.

Arguments: `$ARGUMENTS` (one run id, `YYYYMMDD-HHMMSS-slug`, optionally `-vN`). Replace
`<run_id>` in every command with it literally; never use `$(…)` or shell variables.

1. If there is no argument, run `uv run python scripts/status.py` to list the recent runs, ask
   which one to use, and stop.
2. `uv run python scripts/run_stage.py <run_id> --resume`: it makes the run active (the hooks
   log usage and validate files for the active run), resets stages a crash left `running`
   (`reset:` lines; show them) and lists the stages to run now. Exit 1 → unknown run; say so
   and list the runs with `uv run python scripts/status.py`.
3. If it lists `intake`, the spec is missing or invalid: tell the user to run
   `/validate <run_id>`, which does intake first, and stop. If it lists `synthesize` or
   nothing, stages 1–3 are complete: run only the validate skill's **End** section.
4. Read `.claude/skills/validate/SKILL.md` and follow its sections **Stage 1 — Research plan**,
   **Stage 2 — Parallel research**, **Stage 3 — Claim verification** and **End**, in order,
   exactly as written there. Those sections wrap every stage in
   `uv run python scripts/run_stage.py <run_id> <stage> --begin` / `--finish`, skip what
   `--next` does not list (a completed plan, research dimensions that are `done` or
   `insufficient_data`, a completed verification), re-launch a failed research agent once and
   mark a second failure with `--insufficient-data`, check the `VALIDATION_FAILED_*`,
   `VALIDATION_WARNINGS_*` and `BUDGET_EXCEEDED_*` markers and print
   `uv run python scripts/usage_report.py <run_id>` after each stage.
5. Never research in this context, never write claim or research files yourself.
