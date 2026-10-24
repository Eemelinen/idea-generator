"""`uv run python -m ideaforge.web [--port 8765]`: serve the web UI on 127.0.0.1 only."""

from __future__ import annotations

import argparse
import sys

import uvicorn

from ideaforge.web import DEFAULT_PORT, HOST, create_app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ideaforge.web",
        description=f"Serve the Ideaforge web UI on http://{HOST}:<port>/ (local only, no login). Ctrl+C stops it.",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"port (default {DEFAULT_PORT})")
    args = parser.parse_args(argv)
    # The host is fixed: the UI has no login and must never listen on a network interface.
    uvicorn.run(create_app(), host=HOST, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
