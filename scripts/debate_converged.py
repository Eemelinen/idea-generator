"""Debate convergence check (plan §6 stage 7 step 4, IF-405).

    uv run python scripts/debate_converged.py <run_id> <round>

Run after round N ≥ 1 is validated (scripts/debate_validate.py) and its mini-research is done.
The debate stops when any of these holds:

  (a) round N introduced no new claim ids (none cited for the first time in the debate, no
      mini-research request) and no persona's proposed change moved;
  (b) the judge's interim projected scores (debate/round<N>/interim_scores.json) moved less than
      `convergence_score_delta` on every dimension against the previous round's, or against
      04_scores.json before the first;
  (c) N is the run's preset's `max_rounds` (config/budget.yaml).

Prints which conditions hold and why the others do not, and records N in the `debates` row.
Exit 0 = stop (run the judge), 2 = run another round, 1 = the run or an input file is missing or
invalid, or the round was not validated in its current form.
"""

from __future__ import annotations

import argparse
import sys

from ideaforge import debate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_id")
    parser.add_argument("round", type=int)
    args = parser.parse_args(argv)

    try:
        result = debate.check_convergence(args.run_id, args.round)
    except debate.DebateError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    for line in result.met:
        print(f"met: {line}")
    for line in result.notes:
        print(f"  {line}")
    if result.stop:
        print(f"converged after round {result.round}: stop the debate and run the judge")
        return 0
    print(f"not converged after round {result.round}: run round {result.round + 1}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
