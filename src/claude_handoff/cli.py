"""Command line entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, store
from .briefing import MAX_CHARS, NO_SAVED, build_briefing, render_saved
from .gitstate import read_git_state
from .hook import run_session_start, run_stop


def run_show(cwd: Path, index: int | None) -> int:
    """Print the saved replies of the project of ``cwd`` in full; return the exit code.

    A directory that does not exist has no records. An ``index`` outside 1..K, where K is the
    number of records, prints an error to stderr and returns 1.
    """
    cwd = cwd.resolve()
    records = store.read_states(store.project_root(cwd)) if cwd.is_dir() else []
    if not records:
        print(NO_SAVED)
        return 0
    if index is not None and not 1 <= index <= len(records):
        print(f"No saved session {index}; this project has {len(records)}.", file=sys.stderr)
        return 1
    lines = render_saved(records, read_git_state(cwd), cwd, store._now(), index)
    print("\n".join(lines))
    return 0


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

    show = sub.add_parser("show", help="print the saved final replies of a project in full")
    show.add_argument("--cwd", type=Path, default=Path.cwd(), help="directory of the project")
    show.add_argument("--index", type=int, help="print only saved session N (1 is the newest)")

    hook = sub.add_parser("hook", help="entry points for Claude Code hooks")
    hook_sub = hook.add_subparsers(dest="hook_event", required=True)
    hook_sub.add_parser(
        "session-start",
        help="read SessionStart hook JSON from stdin and print the briefing for its cwd",
    )
    hook_sub.add_parser(
        "stop",
        help="read Stop hook JSON from stdin and save its last reply to this machine's state",
    )

    args = parser.parse_args(argv)
    if args.command == "brief":
        print(build_briefing(args.cwd.resolve(), args.max_chars))
    elif args.command == "show":
        return run_show(args.cwd, args.index)
    elif args.command == "hook" and args.hook_event == "session-start":
        return run_session_start()
    elif args.command == "hook" and args.hook_event == "stop":
        return run_stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
