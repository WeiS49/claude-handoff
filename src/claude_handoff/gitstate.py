"""Read the state of a working directory from git. Read-only."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class GitState:
    """What git knows about a directory right now."""

    is_repo: bool
    branch: str | None = None
    dirty_files: tuple[str, ...] = ()
    recent_commits: tuple[str, ...] = field(default=())
    last_commit_iso: str | None = None
    head_sha: str | None = None
    toplevel: Path | None = None


def _git(cwd: Path, *args: str) -> str | None:
    """Run a git command; return stdout without the trailing newline, or None on failure."""
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), *args],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.rstrip("\n")


def _parse_status(raw: str) -> tuple[str, ...]:
    """Paths from ``git status --porcelain -z``; -z keeps spaces and non-ASCII names unquoted."""
    paths: list[str] = []
    entries = iter(raw.split("\0"))
    for entry in entries:
        if len(entry) <= 3:
            continue
        paths.append(entry[3:])
        if entry[0] in "RC":
            next(entries, None)  # a rename or copy is followed by its original path
    return tuple(paths)


def git_toplevel(cwd: Path) -> Path | None:
    """The resolved root of the work tree that contains ``cwd``, or None outside a work tree."""
    top = _git(cwd, "rev-parse", "--show-toplevel")
    return Path(top).resolve() if top else None


def read_git_state(cwd: Path, max_commits: int = 5) -> GitState:
    """Collect branch, uncommitted files, recent commits, HEAD and work tree root for ``cwd``.

    A directory that is not inside a git work tree yields ``GitState(is_repo=False)``.
    ``head_sha`` is None before the first commit; ``branch`` is None on a detached HEAD.
    """
    if _git(cwd, "rev-parse", "--is-inside-work-tree") != "true":
        return GitState(is_repo=False)

    branch = _git(cwd, "branch", "--show-current") or None
    dirty = _parse_status(_git(cwd, "status", "--porcelain", "-z") or "")
    log = _git(cwd, "log", f"-{max_commits}", "--date=short", "--format=%ad %s") or ""
    commits = tuple(line for line in log.splitlines() if line)
    last = _git(cwd, "log", "-1", "--format=%cI") or None
    head = _git(cwd, "rev-parse", "--verify", "HEAD") or None
    return GitState(
        is_repo=True,
        branch=branch,
        dirty_files=dirty,
        recent_commits=commits,
        last_commit_iso=last,
        head_sha=head,
        toplevel=git_toplevel(cwd),
    )
