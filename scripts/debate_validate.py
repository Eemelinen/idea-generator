"""Debate rebuttal validation (plan §6 stage 7, IF-403).

    uv run python scripts/debate_validate.py <run_id> <round>

Checks runs/<run_id>/debate/round<N>/<role>.json of every persona against the rebuttal rules:
`agree` / `modify`, or a changed proposal, needs `basis.new_claim_ids` the role has not cited in
an earlier turn or a `basis.computation` that derives a number from a cited claim id; `disagree`
needs a claim id or a `basis.evidence_gap`; every claim id must exist in 03_claims/verified.json
and be verified; at most one mini-research request per round (the lowest P-id keeps it).
Needs `python -m ideaforge.debate anonymize <run_id> 0` first.

Writes debate/round<N>/REJECTED_<role> (one reason per line) for each rejected role and removes
it once the role passes, records each turn in `debate_turns`, and prints one line per role.
Exit 0 when every role is accepted, 2 when any is rejected (re-prompt those personas once with
their REJECTED_<role> file), 1 when the run or an input file is missing or invalid.
"""

from __future__ import annotations

import argparse
import sys

from ideaforge import debate
from ideaforge.schemas import PERSONAS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_id")
    parser.add_argument("round", type=int)
    args = parser.parse_args(argv)

    try:
        result = debate.validate_round(args.run_id, args.round)
    except debate.DebateError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    for role in PERSONAS:
        if role in result.accepted:
            print(f"{role}: accepted")
        else:
            print(f"{role}: rejected")
            for reason in result.rejected[role]:
                print(f"  - {reason}")
    return 2 if result.rejected else 0


if __name__ == "__main__":
    sys.exit(main())
