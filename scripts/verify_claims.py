"""Stage 3: extract and verify a run's candidate claims.

    uv run python scripts/verify_claims.py <run_id>
    uv run python scripts/verify_claims.py <run_id> --only mini-<n>-<dim>

Parses the '## Candidate claims' blocks of runs/<run_id>/02_research/*.md into
03_claims/<dimension>.json, fetches every source (robots.txt respected, 10 s timeout, cached in
cache/), marks each claim verified or unverified by fuzzy quote match, and writes
03_claims/verified.json plus the claims and sources rows in SQLite.

Prints one summary line per dimension on stdout and warnings (unparseable claim blocks,
unfetchable or robots-disallowed sources) on stderr. Exit 0 once verified.json is written,
1 when the run is unknown (bad id, no directory, no DB row) or has no 02_research/.

--only <stem> (repeatable; a debate's mini-research file) parses and verifies just that file and
adds its claims to the existing verified.json; every other claim keeps its state and retrieval
time. Exit 1 also when that file or verified.json is missing.
"""

from __future__ import annotations

import argparse
import sys

from ideaforge import db, runs, verify


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_id")
    parser.add_argument("--only", action="append", metavar="STEM", help="verify only 02_research/<STEM>.md")
    args = parser.parse_args(argv)

    try:
        run_dir = runs.run_dir(args.run_id)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if not run_dir.is_dir():
        print(f"error: {run_dir} does not exist", file=sys.stderr)
        return 1
    db.init()
    with db.session() as conn:
        known = conn.execute("SELECT 1 FROM runs WHERE run_id=?", (args.run_id,)).fetchone()
    if known is None:
        print(f"error: run {args.run_id!r} is not in the database; create it with scripts/new_run.py", file=sys.stderr)
        return 1

    try:
        result = verify.verify_run(args.run_id, only=args.only)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    for w in result.warnings:
        print(f"warning: {w}", file=sys.stderr)
    print(verify.summary(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
