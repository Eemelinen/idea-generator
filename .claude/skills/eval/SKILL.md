---
name: eval
description: Run the Ideaforge golden set (tests/golden/*.yaml). Each golden idea goes through stages 0–5 (/validate in "just run it" mode, then /synthesize), strictly one idea at a time to respect usage limits; finished runs are reused and unfinished ones resumed unless --fresh is given. Then scripts/eval_check.py checks each run (verdict in the expected range, must-find facts among the verified claims, no unverified claim cited in the score sheet) and prints a summary table. Use when the user types /eval [--limit N] [--fresh].
argument-hint: '[--limit N] [--fresh]'
allowed-tools: Read Write Agent Bash(uv run python scripts/eval_check.py*) Bash(uv run python scripts/new_run.py*) Bash(uv run python scripts/run_stage.py*) Bash(uv run python scripts/research_brief.py*) Bash(uv run python scripts/verify_claims.py*) Bash(uv run python scripts/synthesis_input.py*) Bash(uv run python scripts/score_run.py*) Bash(uv run python scripts/render_report.py*) Bash(uv run python scripts/usage_report.py*) Bash(uv run python scripts/status.py*) Bash(uv run python -m ideaforge.validate_file*) Bash(ls*) Bash(cat*)
---

You are the orchestrator of an Ideaforge eval. You run the normal pipeline on each golden idea
and let `scripts/eval_check.py` judge the result. All rules of CLAUDE.md → Pipeline sessions
apply: never research in this context, never write claim, score or report files, never compute
anything.

Arguments: `$ARGUMENTS`. `--limit N` (a whole number ≥ 1) runs and checks only the first N
golden ideas, for spot checks such as a model downgrade; `--fresh` starts a new run for every
golden idea even when one exists. In the commands below, replace `<N>` with the limit and
leave out `--limit <N>` when there is none; replace `<run_id>` and `<idea text>` literally,
never with `$(…)` or shell variables.

The answer key stays hidden: never read `tests/golden/` and never put an expected verdict or a
must-find fact into a spec, plan, brief or question. The idea text is all a golden idea gives
the pipeline, exactly as for a user's idea.

## Start

1. `uv run python scripts/eval_check.py --plan --limit <N>`: one tab-separated line per golden
   idea, in order: golden id, state (`none` | `incomplete` | `complete`), the newest run with
   that idea text (or `-`) and the idea text. Exit 1 → a golden file is invalid: show the error
   and stop. If it prints `no golden ideas`, say so (the golden set is IF-501) and stop.
2. Tell the user how many ideas will run, that they run one at a time through stages 0–5
   (each a full `/validate` + `/synthesize` run, so check `/usage` first), and which existing
   runs will be reused or resumed.

## Golden ideas, one at a time

Take the lines **sequentially**: finish one idea completely (or give up on it) before you
start the next; never launch the research agents of two ideas together. For each line:

1. Choose the run:
   - `complete` without `--fresh`: nothing to run; its run is checked as it is. Next line.
   - `incomplete` without `--fresh`: resume the listed run id.
   - `none`, or any state with `--fresh`: `uv run python scripts/new_run.py '<idea text>'`
     with the idea text exactly as the plan line shows it (golden ideas contain no character
     the guard refuses). It prints only the new run id; use it from here on.
2. Stages 0–3: read `.claude/skills/validate/SKILL.md` and follow it for this run id, in its
   **"Just run it"** mode: ask no clarifying questions and do not ask for approval of the plan;
   the spec comes from the idea text and `config/founder.yaml` only. For a resumed run start at
   its **Start** resume steps; for a new run continue with its **Stage 0 — Intake**. Then its
   stages up to and including **End**, exactly as written there.
3. Stage 5: read `.claude/skills/synthesize/SKILL.md` and follow it for the same run id, from
   its **Start** through **End**. Do not offer or run `/debate`: the eval covers stages 0–5.
4. If either skill tells you to stop (an error, a second validation failure of the
   synthesizer), note the golden id, the run id and the reason, and go on with the next line.
   Never repair or write a pipeline file yourself to get a run through.
5. `uv run python scripts/usage_report.py <run_id>`: report it to the user before the next idea.

## Check

1. `uv run python scripts/eval_check.py --limit <N>` (the same limit as in Start). It finds each
   golden idea's newest run and checks that the verdict of `04_scores.json` is in the expected
   range, that every must-find fact is among the verified claims and that the score sheet cites
   no claim that is not verified. Exit 0 → every idea passed, 2 → at least one failed, 1 → a
   golden file is invalid.
2. Show its output verbatim in a code block: the summary table, the failures and the
   `passed: X of N` line.

## End

1. List the ideas whose pipeline stopped early (from step 4 above) with their reasons.
2. Tell the user the result comes from `eval_check.py`, not from you: do not recount, reinterpret
   or excuse a failure. Phase 5 accepts the eval when at least 8 of the 10 golden ideas pass
   (IMPLEMENTATION_PLAN.md §11).
3. To compare score sheets after a model or prompt change, point the user at
   `uv run python scripts/status.py <run_id>` for each run.
