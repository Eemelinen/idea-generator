"""Stage 3, before verify_claims.py: decide whether the claim-extractor pass is needed (IF-211).

    uv run python scripts/extract_claims.py <run_id>

Finds the `[src: …]` sentences of every runs/<run_id>/02_research/*.md that none of the file's
candidate claims covers (same URL and, for a sentence with a `> quote` block, the same quote) and
writes them to 03_claims/extracted/request.json. Prints one `extract:` line per file the
`claim-extractor` agent still has to read, or `nothing to extract`; notes (an extraction removed
because its research file changed) go to stderr. A file already extracted for its current
version is not listed again. Exit 0 once the request is written, 1 for an unknown run or a run
without 02_research/.
"""

from __future__ import annotations

import argparse
import sys

from ideaforge import agents, config, extract, runs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_id")
    args = parser.parse_args(argv)

    try:
        run_dir = runs.run_dir(args.run_id)
        request, notes = extract.write_request(args.run_id)
    except (ValueError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    for note in notes:
        print(f"note: {note}", file=sys.stderr)
    todo = extract.pending(run_dir, request)
    for f in todo:
        print(
            f"extract: {f.research_file}: {len(f.sentences)} sentence(s) without a candidate claim"
            f" → {f.output_file} (ids from {f.first_claim_id})"
        )
    if todo:
        print(f"request: {agents.extract_request(run_dir).relative_to(config.ROOT).as_posix()}")
    else:
        print("nothing to extract")
    return 0


if __name__ == "__main__":
    sys.exit(main())
