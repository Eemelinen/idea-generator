---
name: debate
description: Run the Ideaforge multi-agent debate (stage 7) on a run whose report exists. Five persona subagents take independent positions from their own evidence subsets, positions are anonymized, rebuttal rounds are validated in Python (stance changes need a new claim id or a computation), rejected personas are re-prompted once, at most one mini-research task per round (and a per-debate limit) brings in new verified claims, the judge projects scores after each round until the convergence check stops, then writes the verdict, and scripts/render_report.py writes the revised plan. Resumable per round. Use when the user types /debate <run_id>.
argument-hint: '<run_id>'
allowed-tools: Read Agent Bash(uv run python -m ideaforge.debate*) Bash(uv run python -m ideaforge.mini_research*) Bash(uv run python -m ideaforge.validate_file*) Bash(uv run python scripts/run_stage.py*) Bash(uv run python scripts/research_brief.py*) Bash(uv run python scripts/debate_validate.py*) Bash(uv run python scripts/debate_converged.py*) Bash(uv run python scripts/verify_claims.py*) Bash(uv run python scripts/render_report.py*) Bash(uv run python scripts/usage_report.py*) Bash(uv run python scripts/status.py*) Bash(ls*)
---

You are the orchestrator of an Ideaforge debate on an existing run. The personas, the judge and
the research subagents do the thinking; Python validates, anonymizes, counts and decides when to
stop. You never write or repair a debate, claim or research file, never read
`runs/<run_id>/debate/.mapping.json` or pass a persona's identity to the judge, and never add an
opinion of your own to a brief. All rules of CLAUDE.md → Pipeline sessions apply.

Arguments: `$ARGUMENTS` (one run id, `YYYYMMDD-HHMMSS-slug`, optionally `-vN`). Replace
`<run_id>` in every command with it literally, `<N>` with the round number, `<n>` with the
mini-research task number, `<role>` with a persona and `<dim>` with a dimension; never use
`$(…)` or shell variables.

| Persona      | Subagent            | Evidence file                                   | Round file                                      |
| ------------ | ------------------- | ----------------------------------------------- | ----------------------------------------------- |
| `founder`    | `debate-founder`    | `runs/<run_id>/debate/evidence/founder.json`    | `runs/<run_id>/debate/round<N>/founder.json`    |
| `investor`   | `debate-investor`   | `runs/<run_id>/debate/evidence/investor.json`   | `runs/<run_id>/debate/round<N>/investor.json`   |
| `customer`   | `debate-customer`   | `runs/<run_id>/debate/evidence/customer.json`   | `runs/<run_id>/debate/round<N>/customer.json`   |
| `accountant` | `debate-accountant` | `runs/<run_id>/debate/evidence/accountant.json` | `runs/<run_id>/debate/round<N>/accountant.json` |
| `operator`   | `debate-operator`   | `runs/<run_id>/debate/evidence/operator.json`   | `runs/<run_id>/debate/round<N>/operator.json`   |

## Start

1. If there is no argument, run `uv run python scripts/status.py` to list the recent runs, ask
   which one to use, and stop.
2. `uv run python scripts/run_stage.py <run_id> --resume`: it makes the run active (the hooks
   validate the subagents' files for the active run). Exit 1 → unknown run; say so and stop.
   If it lists any stage, the run is not complete up to its report: tell the user to finish it
   with `/validate <run_id>` or `/synthesize <run_id>` first, and stop.
3. `uv run python -m ideaforge.debate status <run_id>` prints the debate's next step as
   `next: <step> [round <N>] [roles]`. Every step is idempotent, so a crashed debate resumes
   where it stopped. After steps 4 and 5, go to the section for the step:
   - `report` → as step 2: the report is missing; stop.
   - `evidence` → run `uv run python -m ideaforge.debate evidence <run_id>` (the ledger changed since the
     evidence files were written), then `status` again.
   - `positions` or `anonymize round 0` → **Round 0 — Independent positions** from step 2 or 4.
   - `rebuttals`, `validate` or `reprompt` (round N) → **Rounds 1..N — Rebuttals** for round N, from step 1, 2 or 3; launch only the roles it lists.
   - `mini-research` (round N) → **Mini-research** for round N from step 1 (`open` prints a running task
     again), `verify` (round N, it prints the file stem) → **Mini-research** from step 4; then continue
     the round at step 5.
   - `anonymize` or `interim` (round N) → **Rounds 1..N — Rebuttals**, round N from step 5 or 6 (`status` lists `interim` again until the file validates or is set aside with `skip-interim`).
   - `judge` → **Judge**. `render` → **Render**. `done` → **End**.
4. Read `runs/<run_id>/meta.json` (`budget_preset`) and that preset's `debate` entry in
   `config/budget.yaml` (`max_rounds`, `max_mini_research_tasks`) and its `research_subagent`
   and `killcause_scout` entries (the mini-research budget). Tell the user the limits.
5. `uv run python scripts/research_brief.py <run_id> --scope` prints the run's scope lines
   from `00_spec.json` (the business mode, the base location, the target markets and the mode's
   guidance). Every persona brief carries them verbatim, so the personas judge the plan for the
   run's own base and markets. Exit 1 → report the error and stop.

## Round 0 — Independent positions

1. `uv run python -m ideaforge.debate evidence <run_id>`: it writes each persona's evidence
   subset (`agents.PERSONA_EVIDENCE`: the verified claims of its dimensions, every verified
   mini-research claim and its own P-id) to `runs/<run_id>/debate/evidence/<role>.json` and
   creates the debate's seed. Exit 1 → report the error and stop.
2. Launch the five personas **in one message** (one `Agent` call each, `subagent_type` from the
   table; after a resume only the roles `status` listed). Each brief contains exactly:
   - `run_id: <run_id>` and `round: 0`
   - the scope lines from Start step 5, verbatim
   - the inputs: `runs/<run_id>/05_report.md` and the persona's evidence file from the table, and "read no other file"
   - the output: the persona's round file with `<N>` = 0, and "write no other file"
3. `uv run python -m ideaforge.validate_file --kind position runs/<run_id>/debate/round0/<role>.json`
   for each persona (the schema, and every claim id verified and in the persona's evidence file).
   A persona whose file is missing or invalid is **re-launched once** with the
   validator's message appended (all re-launches in one message). A persona that still wrote no
   file is left out of the debate (step 4 warns); one whose file is still invalid stops the
   debate: report the errors and stop. Never write, repair or delete a position yourself.
4. `uv run python -m ideaforge.debate anonymize <run_id> 0`: it writes
   `runs/<run_id>/debate/round0/positions_anon.json` (P1…P5, no roles, self-labels redacted) and
   records the positions. Show its `warning:` lines. Exit 1 → report the error and stop.
5. `uv run python scripts/usage_report.py <run_id>`: report it to the user.

## Rounds 1..N — Rebuttals

Run round N = 1, 2, … until step 7 says stop.

1. Launch the five personas **in one message** (after a resume only the roles `status`
   listed). Each brief contains exactly:
   - `run_id: <run_id>` and `round: <N>`
   - the scope lines from Start step 5, verbatim
   - the inputs: `runs/<run_id>/05_report.md`, the persona's evidence file, and
     `runs/<run_id>/debate/round<k>/positions_anon.json` for every k from 0 to N − 1, and "read no other file"
   - the output: the persona's round file, and "write no other file"
2. `uv run python scripts/debate_validate.py <run_id> <N>`: it checks every rebuttal (stance
   changes need a claim id never cited before or a computation, every id verified, one
   mini-research request per round, the debate's limit) and prints `accepted` / `rejected` with
   reasons per role. Exit 0 → step 4. Exit 2 → step 3. Exit 1 → report the error and stop.
3. `uv run python -m ideaforge.debate reprompt <run_id> <N>`: it lists each rejected persona to
   send back (`reprompt:`) and records it, so no persona is re-prompted twice in a round.
   **Re-launch each listed persona once** (all in one message) with the step-1 brief plus the
   text of `runs/<run_id>/debate/round<N>/REJECTED_<role>` and the instruction to fix exactly
   those points (dropping a change that has no new evidence is a valid fix). Then
   `uv run python scripts/debate_validate.py <run_id> <N>` again. A persona still rejected (or
   listed as `final:`) stays out of round N and keeps its last accepted position; never
   re-launch it again and never edit its file.
4. Mini-research for round N: follow **Mini-research**.
5. `uv run python -m ideaforge.debate anonymize <run_id> <N>`: the round's accepted rebuttals,
   anonymized for the judge (rejected roles left out).
6. Launch one `Agent` with `subagent_type: debate-judge` in **interim** mode. The brief contains exactly:
   - `run_id: <run_id>`, `mode: interim` and `round: <N>`
   - the inputs: `runs/<run_id>/debate/round<k>/positions_anon.json` for every k from 0 to N,
     `runs/<run_id>/03_claims/verified.json`, `runs/<run_id>/04_scores.json` and the judge's
     earlier `interim_scores.json` files, and "read no other file"
   - the output: `runs/<run_id>/debate/round<N>/interim_scores.json`, projecting every rubric
     dimension, and "write no other file"

   Then `uv run python -m ideaforge.validate_file --kind interim_scores runs/<run_id>/debate/round<N>/interim_scores.json`;
   on exit 1 (or no file) re-launch the judge once with the message. A second failure:
   `uv run python -m ideaforge.debate skip-interim <run_id> <N>` sets the file aside (convergence
   condition (b) then does not hold for this round), and go on.

7. `uv run python scripts/debate_converged.py <run_id> <N>`: it prints which stop conditions
   hold ((a) nothing new, (b) projected scores moved less than `convergence_score_delta`,
   (c) `max_rounds`). Exit 0 → **Judge**. Exit 2 → the next round, N + 1, from step 1. Exit 1 →
   report the error and stop.
8. `uv run python scripts/usage_report.py <run_id>`: report it to the user, with the round's
   accepted and rejected personas.

## Mini-research

The only way new facts enter the debate. At most one task per round (the lowest P-id's
request; validation sends the others back) and at most the preset's `max_mini_research_tasks`
per debate, enforced in Python.

1. `uv run python -m ideaforge.mini_research open <run_id> <N>`. "requested no mini-research" →
   this section is done. Exit 3 (`refused:`, the debate's limit is used up) → tell the user and
   this section is done. Exit 1 → report the error and stop. Otherwise it prints the task's
   brief: `task`, `subagent_type`, `question`, `dimension`, `output` and `first claim id`. After a
   resume it may print a running task's `last errors`: append them to the brief as in step 3.
2. Launch one `Agent` with that `subagent_type` (the dimension's `research-*` agent). The brief
   contains exactly:
   - `run_id: <run_id>`, the spec path `runs/<run_id>/00_spec.json` and "This is a debate mini-research task."
   - the printed `question`, `dimension`, `output` and `first claim id`
   - the lines `uv run python scripts/research_brief.py <run_id> <dim>` prints for the task's
     dimension, verbatim: the run's scope lines, the budget line of the run's preset and, in a
     back-test run, the header that forbids sources published after the as-of date
   - "write no other file"
3. `uv run python -m ideaforge.mini_research finish <run_id> <n>`: it validates the file
   against the research output contract. Exit 0 → step 4. Exit 2 → **re-launch it once** with
   the printed errors appended and the instruction to rewrite its file so it passes, then run
   `finish` again. Exit 3 → the task failed twice: its file is set aside and still counts
   against the limit; tell the user and this section is done. Never write or repair the file.
4. `uv run python scripts/verify_claims.py <run_id> --only mini-<n>-<dim>`: it verifies only the
   task's claims and adds them to `03_claims/verified.json`; every earlier claim keeps its state.
   Show its summary and `warning:` lines.
5. `uv run python -m ideaforge.debate evidence <run_id>`: the new verified claims go into every
   persona's `mini_research_claims` for round N + 1.
6. Check `ls runs/<run_id>/` for `VALIDATION_FAILED_research-*` and `BUDGET_EXCEEDED_research-*`
   markers (a task's budget marker is `BUDGET_EXCEEDED_<agent>.mini-<n>`) and report them.

## Judge

1. Launch one `Agent` with `subagent_type: debate-judge` in **verdict** mode. The brief contains exactly:
   - `run_id: <run_id>`, `mode: verdict` and the last round N
   - the inputs of interim mode (every round's `positions_anon.json`, `runs/<run_id>/03_claims/verified.json`,
     `runs/<run_id>/04_scores.json`, the interim files), and "read no other file"
   - the output: `runs/<run_id>/debate/verdict.json`, and "write no other file"
2. `uv run python -m ideaforge.validate_file --kind verdict runs/<run_id>/debate/verdict.json`;
   on exit 1 re-launch the judge once with the message. A second failure: report the errors and
   stop.

## Render

1. `uv run python scripts/render_report.py <run_id> --debate`: it checks that every accepted
   change cites verified claim ids, recomputes `conformity_flag`, and writes the immutable
   `runs/<run_id>/debate/revised_plan.md` (diff against `05_report.md`, accepted and rejected
   changes, assumption register, experiments by information value per euro) and its rows. If it
   refuses accepted changes citing unknown or unverified ids, re-launch the judge once in
   verdict mode with the error and the instruction to fix those changes, validate, and render
   again; a second refusal: report it and stop. If the plan already exists, do not delete or
   edit it.
2. `uv run python scripts/usage_report.py <run_id>`: report it to the user.

## End

1. Read `runs/<run_id>/debate/revised_plan.md` and show the user: the `conformity_flag` first
   and prominently (true means the personas converged without new evidence: treat the
   accepted changes with suspicion), the projected total against the report's, the accepted
   changes with their claim ids, and the top five experiments.
2. Check `ls runs/<run_id>/` for `BUDGET_EXCEEDED_*` and `VALIDATION_FAILED_*` markers and
   report them.
3. Offer to re-submit the revised plan as the idea's next version: `/validate --from <run_id>`
   creates `<run_id>-vN` with this run, its report and its debate unchanged.
