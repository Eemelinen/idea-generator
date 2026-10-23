---
name: synthesize
description: Run Ideaforge stage 5 for a run whose claims are verified. The synthesizer subagent proposes scores, unit-economics inputs and a risk register from the spec, the verified and conflict claims and the rubric only; scripts/score_run.py then drops unverified citations, applies the caps, kill triggers and unit economics and writes the final score sheet and verdict, and scripts/render_report.py writes the immutable report. Resumable. Use when the user types /synthesize <run_id>.
argument-hint: '<run_id>'
allowed-tools: Read Agent Bash(uv run python scripts/run_stage.py*) Bash(uv run python scripts/synthesis_input.py*) Bash(uv run python scripts/score_run.py*) Bash(uv run python scripts/render_report.py*) Bash(uv run python scripts/usage_report.py*) Bash(uv run python scripts/status.py*) Bash(uv run python -m ideaforge.validate_file*) Bash(ls*)
---

You are the orchestrator of an existing Ideaforge run. This skill runs stage 5 only:
`synthesize` (the `synthesizer` subagent proposes), `score` (Python decides) and `report`
(Python renders `05_report.md`). You never
write a score, a risk or a claim file yourself, never read the research or claim files and
never compute anything: all rules of CLAUDE.md → Pipeline sessions apply.

Arguments: `$ARGUMENTS` (one run id, `YYYYMMDD-HHMMSS-slug`, optionally `-vN`). Replace
`<run_id>` in every command with it literally; never use `$(…)` or shell variables.

## Start

1. If there is no argument, run `uv run python scripts/status.py` to list the recent runs, ask
   which one to use, and stop.
2. `uv run python scripts/run_stage.py <run_id> --resume`: it makes the run active (the hooks
   validate the synthesizer's files for the active run), resets stages a crash left `running`
   (`reset:` lines; show them) and lists the stages to run now. Exit 1 → unknown run; say so
   and stop.
3. If it lists `intake`, `plan`, a `research:` stage or `verify`, stages 0–3 are incomplete:
   tell the user to run `/validate <run_id>` first, and stop. If it lists `score`, skip to
   **Stage 5b — Scoring**. If it lists `report`, skip to **Stage 5c — Report**. If it lists
   nothing, stage 5 is complete: go to **End**.

## Stage 5a — Synthesis

1. `uv run python scripts/run_stage.py <run_id> synthesize --begin`
2. `uv run python scripts/synthesis_input.py <run_id>`: it writes
   `runs/<run_id>/04_synthesis_input.json`, the synthesizer's **only** input (the spec, the
   verified and conflict claims, the rubric; unverified claims are left out) and prints the
   claims per dimension. Exit 1 → report the error and stop.
3. Launch one `Agent` with `subagent_type: synthesizer`. The brief contains exactly:
   - `run_id: <run_id>`
   - the input: `runs/<run_id>/04_synthesis_input.json`, and "read no other file"
   - the outputs: `runs/<run_id>/04_scores_proposed.json` and `runs/<run_id>/04_risks.json`,
     and "write no other file"

   Pass nothing else: no research prose, no claim text, no opinion of your own about the idea.

4. `uv run python -m ideaforge.validate_file --kind scores_proposed runs/<run_id>/04_scores_proposed.json`
   and `uv run python -m ideaforge.validate_file --kind risks runs/<run_id>/04_risks.json`.
5. `uv run python scripts/run_stage.py <run_id> synthesize --finish`, also when step 4 failed
   (it then exits 1 and the stage becomes `failed`, which step 6 can begin again). Exit 0 → `done`.
6. If step 4 or 5 failed, read `runs/<run_id>/VALIDATION_FAILED_synthesizer` if it exists.
   **Re-launch it once**: `uv run python scripts/run_stage.py <run_id> synthesize --begin`,
   then the same brief with the validator's messages appended and the instruction to fix its
   files so they pass; then steps 4–5 again. If it fails a second time (`status.py <run_id>`
   shows the `attempts`), report the errors and stop: never write or repair the files yourself.
7. `uv run python scripts/usage_report.py <run_id>`: report it to the user.

## Stage 5b — Scoring

1. `uv run python scripts/run_stage.py <run_id> score --begin`
2. `uv run python scripts/score_run.py <run_id>`: it drops cited claim ids that are unknown or
   not verified, sets a proposal with no verified citation to 0, applies the evidence rules,
   caps, kill triggers and unit economics, and writes `runs/<run_id>/04_scores.json` and the
   `scores` rows. Exit 1 → report the error and stop. Show its `warning:` lines.
3. `uv run python -m ideaforge.validate_file --kind scores runs/<run_id>/04_scores.json`
4. `uv run python scripts/run_stage.py <run_id> score --finish`
5. `uv run python scripts/usage_report.py <run_id>`: report it to the user.

## Stage 5c — Report

1. `uv run python scripts/run_stage.py <run_id> report --begin`
2. `uv run python scripts/render_report.py <run_id>`: it writes `runs/<run_id>/05_report.md`
   (verdict, score table with cap labels, kill triggers, unit economics and sensitivity,
   dimension sections, Finland funding fit, Rääkkylä notes, risk register, sources, usage) and
   its `reports` row. Reports are immutable: if it says the report already exists, do not
   delete or edit it; a new version is a new run. Any other exit 1 → report the error and stop.
3. `uv run python scripts/run_stage.py <run_id> report --finish`
4. `uv run python scripts/usage_report.py <run_id>`: report it to the user.

## End

1. Show the `score_run.py` output verbatim in a code block: the score table with cap reasons,
   the dropped citations, the kill triggers fired, the verdict and the unit economics with
   their missing inputs and notes. If stage 5b ran in an earlier session, read
   `runs/<run_id>/04_scores.json` instead and summarise the same items from it.
2. Check `ls runs/<run_id>/` for `BUDGET_EXCEEDED_*` and `VALIDATION_FAILED_*` markers and
   report them.
3. Point the user at `runs/<run_id>/05_report.md`. Every Finland funding item there is backed
   by a verified official-source claim or marked "unverified – see gaps"; never fill a gap
   from your own knowledge or from the Finland hints in config.
4. Tell the user the verdict comes from Python (`config/rubric.yaml` thresholds, caps and
   kill triggers), not from the synthesizer. A kill trigger the founder explicitly accepts
   goes into `kill_trigger_overrides` of `00_spec.json`; `uv run python scripts/score_run.py <run_id>`
   then re-scores the run; the report of this run stays as it is (reports are immutable).
