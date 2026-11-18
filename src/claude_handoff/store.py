"""Per-project state kept on this machine, outside the project directory.

One JSON file per project, replaced as a whole on every write. It lives outside the project so
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

from .gitstate import git_toplevel

STATE_VERSION = 1
MAX_MESSAGE_CHARS = 4000
ELLIPSIS = "…"


def _env(name: str) -> str | None:
    """An environment variable's value; an empty string counts as unset."""
    return os.environ.get(name) or None


def state_dir() -> Path:
    """Where state files live.

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
    """The project ``cwd`` belongs to: the git work tree root, or ``cwd`` itself outside git.

    ``cwd`` is resolved first, so a directory reached through a symlink maps to the same project.
    """
    resolved = cwd.resolve()
    return git_toplevel(resolved) or resolved


def state_path(project: Path) -> Path:
    """The state file for ``project``, named by a hash of its path."""
    digest = hashlib.sha256(str(project).encode("utf-8")).hexdigest()[:16]
    return state_dir() / f"{digest}.json"


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


def write_state(
    *,
    project: Path,
    session_id: str | None,
    branch: str | None,
    head: str | None,
    message: str,
) -> Path:
    """Replace the state file for ``project`` atomically and return its path.

    The file is written to a temporary file in the same directory and then renamed over the
    target, so a reader sees either the old file or the new one. On failure the temporary
    file is removed and the exception is raised.
    """
    target = state_path(project)
    _ensure_dir(target.parent)
    data = {
        "version": STATE_VERSION,
        "project": str(project),
        "session_id": session_id,
        "written_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "branch": branch,
        "head": head,
        "message": clip_message(message),
    }
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=".tmp-", suffix=".json")
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
    return target


def read_state(project: Path) -> dict[str, Any] | None:
    """The saved state for ``project``, or None if there is none or it cannot be used."""
    try:
        data = json.loads(state_path(project).read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return None
    if not isinstance(data, dict):
        return None
    version = data.get("version")
    if isinstance(version, bool) or version != STATE_VERSION:
        return None
    return data
