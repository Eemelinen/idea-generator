# Quality document

A quality snapshot per product domain and architectural layer. Read it at clock-in to see
where the codebase is weakest; update it at clock-out when the session changed a grade.

**Update cadence:** after each significant session, and during the periodic (monthly) sweep.

**Grades:** **A** all verification passing, clean boundaries, agent-legible, stable tests ·
**B** verification passing, minor gaps in legibility or coverage · **C** partially working,
known gaps, hard for an agent to follow · **D** not working or major structural issues.

## Product domains

| Domain                                            | Grade | Verification                                            | Agent legibility                             | Test stability | Key gaps                                                                   | Last updated |
| ------------------------------------------------- | ----- | ------------------------------------------------------- | -------------------------------------------- | -------------- | -------------------------------------------------------------------------- | ------------ |
| Schemas & validation (`schemas`, `validate_file`) | B     | Unit: every fixture validates, extras rejected          | One registry (`SCHEMAS`); plan §5 maps 1:1   | Stable         | Research validator lacks bare-number and URL-provenance rules (F-006)      | 2026-10-23   |
| Run store (`db`, `runs`, `new_run.py`)            | B     | Unit                                                    | Plan §5 tables; stage list in `runs.STAGES`  | Stable         | No stage state machine or resume yet (F-010)                               | 2026-10-23   |
| Hooks (`guard`, `usage`, `validate_file --auto`)  | B     | Unit (`test_guard`, `test_usage`, `test_validate_file`) | Module docstrings state the policy           | Stable         | Fail open when `uv` is missing from `PATH`                                 | 2026-10-23   |
| Agents & prompts (`agent_templates`, `prompts`)   | C     | `gen_agents --check` + content assertions               | Templates + includes; generated files marked | Stable         | Briefs untuned against real runs (F-012); synthesizer/debate prompts draft | 2026-10-23   |
| Finnish data tools (`fi/`)                        | D     | None                                                    | Stubs with planned API in docstrings         | —              | Not implemented; no recorded fixtures (F-003–F-005)                        | 2026-10-23   |
| Verification of claims (`verify`)                 | D     | None                                                    | Plan §6 stage 3                              | —              | Not implemented (F-007, F-008)                                             | 2026-10-23   |
| Scoring, economics, report                        | D     | None                                                    | Plan §6 stage 5                              | —              | Not implemented (F-014–F-019)                                              | 2026-10-23   |
| Debate                                            | D     | Schemas only                                            | Plan §6 stage 7                              | —              | Not implemented (F-021–F-023)                                              | 2026-10-23   |
| Evaluation (golden set, `/eval`)                  | D     | None                                                    | Plan §9                                      | —              | Not implemented (F-025, F-026)                                             | 2026-10-23   |

## Architectural layers

| Layer                              | Grade | Boundary enforcement                                               | Agent legibility                    | Key gaps                                                   | Last updated |
| ---------------------------------- | ----- | ------------------------------------------------------------------ | ----------------------------------- | ---------------------------------------------------------- | ------------ |
| Python package (`src/ideaforge`)   | B     | Pydantic `extra="forbid"`; config validated on load                | Module docstrings; plan §1 layout   | No type checker or linter on Python yet                    | 2026-10-23   |
| Claude Code layer (skills, agents) | C     | Pipeline guard + generated agents (`gen_agents --check` in pytest) | Plan §6–7                           | No pipeline skills yet (`/validate`, `/research`, …)       | 2026-10-23   |
| Development harness                | B     | Scripts with exit codes; hooks; CI job `L1 (pnpm check)`           | `docs/harness/README.md`, AGENTS.md | Driver not yet run for real; rubric not yet calibrated     | 2026-10-23   |
| Tests & environments               | B     | Offline tests; `project` fixture isolates root, DB and env         | `tests/conftest.py`                 | Only L1 exists; live pipeline behaviour is checked by hand | 2026-10-23   |

## Change history

### 2026-10-23

- Changes: initial snapshot at harness bootstrap (Phase 1 skeleton done).
- Domains promoted: —
- Demoted: —
- New gaps identified: see Key gaps; all tracked as features in `feature_list.json`.
- Gaps closed: —
