---
name: status
description: Show Ideaforge runs. With no argument, the recent runs and their stages; with a run id, that run's stages, claims per dimension (verified / unverified / conflict / pending), kill flags fired, validation and budget markers and its usage summary. `<run_id> --review` scores the run's report sections 1–5 with the user, `--reviews` shows the review-score trend across prompt and model versions, `--diff <run_a> <run_b>` compares two score sheets. Use when the user asks for the status of a run, what runs exist, to review a report or to compare two runs.
argument-hint: '[run_id] [--review] | --reviews | --diff <run_a> <run_b>'
allowed-tools: Bash(uv run python scripts/status.py*) Bash(uv run python scripts/usage_report.py*)
---

Run `uv run python scripts/status.py $ARGUMENTS` and show its output to the user verbatim in a
code block. Do not recompute, reinterpret or add to the numbers: they come from SQLite and
`runs/<run_id>/`, which the pipeline scripts wrote.

- Exit code 1 means the run id is invalid or unknown (or, for `--review` / `--diff`, the run has
  no report or score sheet yet); say so and run `uv run python scripts/status.py` to list the
  recent runs instead.
- For the full per-agent usage of a run, also run `uv run python scripts/usage_report.py <run_id>`.
- If the output lists `VALIDATION_FAILED_*` or `BUDGET_EXCEEDED_*` markers, point them out: the
  orchestrator marks a dimension `INSUFFICIENT_DATA` after a second validation failure.

## Review (`/status <run_id> --review`)

1. `uv run python scripts/status.py <run_id> --review` lists the sections of the run's
   `05_report.md` with their ids and any scores stored earlier. Show the list.
2. Ask the user, in one message, to score each section from 1 (useless) to 5 (excellent), with an
   optional short note per section. They may skip sections; a skipped section keeps its earlier
   score. Never propose, guess or fill in a score yourself: the scores are the user's judgement.
3. Store exactly what they answered as `section=score` or `section=score:note` entries, each
   entry in single quotes when it has a note (no quotes, backticks or `$` inside a note):
   `uv run python scripts/status.py <run_id> --review <entries>`. Exit 1 names the bad entry;
   fix that entry with the user and run the command again.

## Trend and diff

- `uv run python scripts/status.py --reviews` shows the mean review score per section for each
  prompt/config and model version (from each run's `meta.json`), so a drop after a prompt or
  model change is visible.
- `uv run python scripts/status.py --diff <run_a> <run_b>` compares two runs' `04_scores.json`
  (versions of an idea, or the same idea under different models): the final score per dimension,
  the weighted total, the verdict and the kill triggers fired, plus the config and model changes
  between them. Use it after a model downgrade (README → Usage limits).
