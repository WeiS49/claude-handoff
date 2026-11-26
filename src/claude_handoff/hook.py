"""Claude Code hook entry points. A hook must never fail the session or print an error."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from .briefing import MAX_CHARS, build_briefing
from .gitstate import read_git_state
from .store import project_root, write_state

# Every way reading the input or building the briefing can fail:
# ValueError covers bad JSON, bad UTF-8 (stdin or git output) and NUL bytes in a path;
# OSError covers I/O and path resolution; RuntimeError covers symlink loops and
# RecursionError from deeply nested JSON.
HOOK_ERRORS = (ValueError, OSError, RuntimeError)
# The Stop hook also writes a file, so it widens the net: TypeError and LookupError cover
# JSON serialisation and unexpected shapes of data on the way to the state file.
STOP_ERRORS = (*HOOK_ERRORS, TypeError, LookupError)
# Set by Claude Code for hook processes: "1" in an interactive session, "0" in an unattended
# one such as `claude -p`. Undocumented, so only the exact value "0" counts as unattended.
ATTENDED_VARIABLE = "CLAUDE_CODE_SESSION_ATTENDED"
# Set by Claude Code for hook processes: the project directory the session started in. Unlike
# the input's ``cwd``, it does not follow the session when it changes directory.
PROJECT_DIR_VARIABLE = "CLAUDE_PROJECT_DIR"


def session_unattended() -> bool:
    """True only when ``$CLAUDE_CODE_SESSION_ATTENDED`` is exactly ``0``.

    Any other value, an empty one or none at all counts as attended.
    """
    return os.environ.get(ATTENDED_VARIABLE) == "0"


def _load_object(raw: bytes) -> dict[str, Any] | None:
    """The hook input as a JSON object, or None if it is valid JSON of another type.

    Bad UTF-8 or bad JSON raises ``ValueError``.
    """
    data = json.loads(raw.decode("utf-8"))
    return data if isinstance(data, dict) else None


def _cwd_from_data(data: dict[str, Any]) -> Path | None:
    """The existing directory named by ``cwd``, resolved, or None.

    A relative ``cwd`` resolves against the current working directory, as ``brief --cwd``
    does. ``build_briefing`` would describe a missing directory as "not a git repository",
    so existence is checked here.
    """
    cwd = data.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        return None
    path = Path(cwd).resolve()
    return path if path.is_dir() else None


def session_directory(cwd: Path) -> Path:
    """The directory the session started in: ``$CLAUDE_PROJECT_DIR`` if usable, else ``cwd``.

    Usable means not empty, absolute, and naming an existing directory; it is resolved. A
    relative value is refused because it would depend on where the hook process runs.
    """
    value = os.environ.get(PROJECT_DIR_VARIABLE)
    if not value:
        return cwd
    try:
        path = Path(value)
        if not path.is_absolute():
            return cwd
        resolved = path.resolve()
        return resolved if resolved.is_dir() else cwd
    except HOOK_ERRORS:
        return cwd


def session_start_text(raw: bytes, max_chars: int = MAX_CHARS) -> str:
    """What the SessionStart hook prints for ``raw`` stdin: the briefing plus a newline, or "".

    Bad input of any kind yields "": the hook must neither fail session start nor put error
    text into the new session's context. A string ``session_id`` in the input leaves that
    session's own record out of the briefing: a resumed or compacted session does not need it.
    The briefing describes the session directory (see ``session_directory``), not ``cwd``; the
    input still needs an existing ``cwd``.
    """
    try:
        data = _load_object(raw)
        cwd = None if data is None else _cwd_from_data(data)
        if data is None or cwd is None:
            return ""
        session_id = data.get("session_id")
        session = session_id if isinstance(session_id, str) else None
        return build_briefing(session_directory(cwd), max_chars, session_id=session) + "\n"
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


def record_stop(raw: bytes) -> Path | None:
    """Save the last reply named in Stop hook input ``raw``; return the state file, or None.

    The reply goes to the file of this session (by ``session_id``) in the project's state
    directory, so parallel sessions in one project keep separate files; a missing or
    non-string ``session_id`` uses ``unknown.json``. Only the newest few sessions of a project
    are kept (see ``store.MAX_SESSIONS``).

    Nothing is written, and existing state files are left alone, unless the input is a JSON
    object with an existing directory as ``cwd`` and a ``last_assistant_message`` string that
    is not blank. The message is saved as given (not stripped). Fields other than ``cwd``,
    ``session_id`` and ``last_assistant_message`` are ignored. A session run unattended (see
    ``session_unattended``) is saved with ``"attended": false``.

    The record belongs to the project of the session directory (see ``session_directory``),
    so a session that moved into a subfolder or a nested repository is still found from where
    it started. Branch and HEAD come from ``cwd`` when it is in the same project (another work
    tree of the same repository), else from the session directory.
    """
    data = _load_object(raw)
    if data is None:
        return None
    cwd = _cwd_from_data(data)
    message = data.get("last_assistant_message")
    if cwd is None or not isinstance(message, str) or not message.strip():
        return None
    session_id = data.get("session_id")
    start = session_directory(cwd)
    project = project_root(start)
    # The branch and HEAD of the work tree the session ran in, not of the main checkout.
    git = read_git_state(cwd if project_root(cwd) == project else start)
    return write_state(
        project=project,
        session_id=session_id if isinstance(session_id, str) else None,
        branch=git.branch,
        head=git.head_sha,
        message=message,
        attended=False if session_unattended() else None,
    )


def run_stop() -> int:
    """Read the Stop hook JSON from stdin and record the last reply. Prints nothing; returns 0.

    A Stop hook runs after every reply, so a failure, including a full disk or a state
    directory without write permission, is swallowed rather than shown to the session.
    """
    try:
        record_stop(sys.stdin.buffer.read())
    except STOP_ERRORS:
        return 0
    return 0
