"""Command line entry point."""

from __future__ import annotations

import argparse
from pathlib import Path

from . import __version__
from .briefing import MAX_CHARS, build_briefing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="claude-handoff",
        description="Briefings for a new Claude Code session, derived from ground truth.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    brief = sub.add_parser("brief", help="print the briefing for a directory")
    brief.add_argument("--cwd", type=Path, default=Path.cwd(), help="directory to describe")
    brief.add_argument("--max-chars", type=int, default=MAX_CHARS, help="size ceiling")

    args = parser.parse_args(argv)
    if args.command == "brief":
        print(build_briefing(args.cwd.resolve(), args.max_chars))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
