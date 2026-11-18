"""Claude Code hook entry points. A hook must never fail the session or print an error."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .briefing import MAX_CHARS, build_briefing

# Every way reading the input or building the briefing can fail:
# ValueError covers bad JSON, bad UTF-8 (stdin or git output) and NUL bytes in a path;
# OSError covers I/O and path resolution; RuntimeError covers symlink loops and
# RecursionError from deeply nested JSON.
HOOK_ERRORS = (ValueError, OSError, RuntimeError)


def _cwd_from_input(raw: bytes) -> Path | None:
    """The directory named by the hook input's ``cwd``, or None if the input is unusable.

    Fields other than ``cwd`` are ignored. A relative ``cwd`` resolves against the current
    working directory, as ``brief --cwd`` does. ``build_briefing`` would describe a missing
    directory as "not a git repository", so existence is checked here.
    """
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        return None
    cwd = data.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        return None
    path = Path(cwd).resolve()
    return path if path.is_dir() else None


def session_start_text(raw: bytes, max_chars: int = MAX_CHARS) -> str:
    """What the SessionStart hook prints for ``raw`` stdin: the briefing plus a newline, or "".

    Bad input of any kind yields "": the hook must neither fail session start nor put error
    text into the new session's context.
    """
    try:
        cwd = _cwd_from_input(raw)
        if cwd is None:
            return ""
        return build_briefing(cwd, max_chars) + "\n"
    except HOOK_ERRORS:
        return ""


def run_session_start() -> int:
    """Read the SessionStart hook JSON from stdin and print the briefing. Always returns 0."""
    try:
        text = session_start_text(sys.stdin.buffer.read())
        if text:
            sys.stdout.write(text)
            sys.stdout.flush()
    except HOOK_ERRORS:
        return 0
    return 0
