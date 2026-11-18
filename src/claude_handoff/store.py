"""Per-session state kept on this machine, outside the project directory.

Each project has its own directory, and each session one JSON file in it, replaced as a whole
on every write. All work trees of one git repository are one project (see ``project_root``),
so a session in one work tree sees where sessions in the others stopped. Only the newest ``MAX_SESSIONS`` files of a project are kept, so parallel
sessions in one project do not overwrite each other. The state lives outside the project so
it never shows up in ``git status`` and cannot be committed by mistake: the saved reply may
contain anything the session saw.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .gitstate import git_common_root

STATE_VERSION = 1
MAX_MESSAGE_CHARS = 4000
ELLIPSIS = "…"
MAX_SESSIONS = 5
UNKNOWN_SESSION = "unknown"
TEMP_PREFIX = ".tmp-"
SUFFIX = ".json"
# Sorts before every real time: records whose time cannot be read count as the oldest.
_OLDEST = datetime.min.replace(tzinfo=UTC)


def _env(name: str) -> str | None:
    """An environment variable's value; an empty string counts as unset."""
    return os.environ.get(name) or None


def _now() -> datetime:
    """The current time in UTC. A function of its own so tests can control the clock."""
    return datetime.now(UTC)


def _digest(text: str) -> str:
    """The first 16 hex digits of the sha256 of ``text``."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def state_dir() -> Path:
    """Where state lives.

    ``$CLAUDE_HANDOFF_STATE_DIR`` if set, else ``$XDG_STATE_HOME/claude-handoff``, else
    ``~/.local/state/claude-handoff``.
    """
    explicit = _env("CLAUDE_HANDOFF_STATE_DIR")
    if explicit:
        return Path(explicit)
    xdg = _env("XDG_STATE_HOME")
    if xdg:
        return Path(xdg) / "claude-handoff"
    return Path.home() / ".local" / "state" / "claude-handoff"


def project_root(cwd: Path) -> Path:
    """The project ``cwd`` belongs to, or ``cwd`` itself outside git.

    Inside git this is the root of the main checkout, so every work tree of one repository
    (``git worktree add``) shares one project and sees the others' sessions. Where there is
    no main checkout (a work tree of a bare repository, a submodule) it is the root of the
    work tree that contains ``cwd``. ``cwd`` is resolved first, so a directory reached
    through a symlink maps to the same project.
    """
    resolved = cwd.resolve()
    return git_common_root(resolved) or resolved


def project_state_dir(project: Path) -> Path:
    """The directory holding the session files of ``project``, named by a hash of its path."""
    return state_dir() / _digest(str(project))


def state_path(project: Path, session_id: str | None) -> Path:
    """The state file for one session of ``project``.

    Named by a hash of ``session_id``; a missing or non-string id maps to ``unknown.json``.
    """
    name = _digest(session_id) if isinstance(session_id, str) else UNKNOWN_SESSION
    return project_state_dir(project) / f"{name}{SUFFIX}"


def clip_message(message: str) -> str:
    """``message`` unchanged, or cut to ``MAX_MESSAGE_CHARS`` characters ending in an ellipsis."""
    if len(message) <= MAX_MESSAGE_CHARS:
        return message
    return message[: MAX_MESSAGE_CHARS - 1] + ELLIPSIS


def _ensure_dir(directory: Path) -> None:
    """Create ``directory`` with mode 0700. An existing directory is left as it is."""
    try:
        directory.mkdir(mode=0o700, parents=True)
    except FileExistsError:
        return
    os.chmod(directory, 0o700)  # mkdir's mode is filtered by the umask


def _parse_time(value: object) -> datetime | None:
    """``value`` as a timezone-aware datetime, or None.

    A naive time is refused: it cannot be compared with an aware one.
    """
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _load_record(path: Path) -> tuple[datetime, dict[str, Any]] | None:
    """The record in ``path`` and its ``written_at``, or None if the file cannot be used.

    Unusable means: unreadable, not JSON, not an object, ``version`` other than
    ``STATE_VERSION``, or ``written_at`` missing or not an ISO time with a timezone.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return None
    if not isinstance(data, dict):
        return None
    version = data.get("version")
    if isinstance(version, bool) or version != STATE_VERSION:
        return None
    written_at = _parse_time(data.get("written_at"))
    if written_at is None:
        return None
    return written_at, data


def _session_files(directory: Path) -> list[Path]:
    """The session files in ``directory``: ``.json`` files that are not in-progress writes.

    Subdirectories and other files are ignored.
    """
    return [
        entry
        for entry in directory.iterdir()
        if entry.name.endswith(SUFFIX)
        and not entry.name.startswith(TEMP_PREFIX)
        and entry.is_file()
    ]


def _age_key(path: Path) -> tuple[datetime, str]:
    """Sort key, oldest first: ``written_at``, then the file name. Unusable files come first."""
    record = _load_record(path)
    return (_OLDEST if record is None else record[0], path.name)


def _prune(directory: Path, keep: Path) -> None:
    """Delete the oldest session files in ``directory`` until ``MAX_SESSIONS`` remain.

    ``keep``, the file just written, is never deleted, even if a clock set back or a tie makes
    it sort as the oldest. Failures are swallowed: pruning must not undo a successful write.
    """
    try:
        others = sorted(
            (path for path in _session_files(directory) if path.name != keep.name),
            key=_age_key,
        )
    except OSError:
        return
    excess = len(others) + 1 - MAX_SESSIONS
    for path in others[: max(excess, 0)]:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            continue


def write_state(
    *,
    project: Path,
    session_id: str | None,
    branch: str | None,
    head: str | None,
    message: str,
) -> Path:
    """Replace the state file of this session of ``project`` atomically and return its path.

    The file is written to a temporary file in the same directory and then renamed over the
    target, so a reader sees either the old file or the new one. On failure the temporary
    file is removed and the exception is raised. After a successful write only the newest
    ``MAX_SESSIONS`` session files of the project are kept.
    """
    session = session_id if isinstance(session_id, str) else None
    target = state_path(project, session)
    # One level at a time: mkdir(parents=True) would create the parents without mode 0700.
    _ensure_dir(state_dir())
    _ensure_dir(target.parent)
    data = {
        "version": STATE_VERSION,
        "project": str(project),
        "session_id": session,
        "written_at": _now().isoformat(timespec="seconds"),
        "branch": branch,
        "head": head,
        "message": clip_message(message),
    }
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=TEMP_PREFIX, suffix=SUFFIX)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, target)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    _prune(target.parent, target)
    return target


def read_states(project: Path) -> list[dict[str, Any]]:
    """Every usable saved record for ``project``, newest first.

    Records are ordered by ``written_at``, ties by file name, both descending. Unusable files
    (see ``_load_record``) are skipped. A project with no state directory yields ``[]``.
    """
    try:
        files = _session_files(project_state_dir(project))
    except OSError:
        return []
    loaded = []
    for path in files:
        record = _load_record(path)
        if record is not None:
            loaded.append((record[0], path.name, record[1]))
    loaded.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [data for _, _, data in loaded]
