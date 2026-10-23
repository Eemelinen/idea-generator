---
name: status
description: Show Ideaforge runs. With no argument, the recent runs and their stages; with a run id, that run's stages, claims per dimension (verified / unverified / conflict / pending), kill flags fired, validation and budget markers and its usage summary. Use when the user asks for the status of a run or what runs exist.
argument-hint: '[run_id]'
allowed-tools: Bash(uv run python scripts/status.py*) Bash(uv run python scripts/usage_report.py*)
---

Run `uv run python scripts/status.py $ARGUMENTS` and show its output to the user verbatim in a
code block. Do not recompute, reinterpret or add to the numbers: they come from SQLite and
`runs/<run_id>/`, which the pipeline scripts wrote.

- Exit code 1 means the run id is invalid or unknown; say so and run
  `uv run python scripts/status.py` to list the recent runs instead.
- For the full per-agent usage of a run, also run `uv run python scripts/usage_report.py <run_id>`.
- If the output lists `VALIDATION_FAILED_*` or `BUDGET_EXCEEDED_*` markers, point them out: the
  orchestrator marks a dimension `INSUFFICIENT_DATA` after a second validation failure.
