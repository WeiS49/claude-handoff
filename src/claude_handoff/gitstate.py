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


class GitFailed(Exception):
    """A git command could not be started, did not finish in time, or failed unexpectedly."""


def _git_code(cwd: Path, *args: str) -> int:
    """Run a git command for its exit code only. Raises ``GitFailed`` if it cannot run."""
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), *args],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GitFailed(str(exc)) from exc
    return result.returncode


def commits_since(cwd: Path, sha: str) -> int | None:
    """How many commits HEAD has on top of ``sha``: 0 if ``sha`` is HEAD itself.

    None if ``sha`` is not an ancestor of HEAD, names no object in the repository, or the
    repository has no commit yet. Raises ``GitFailed`` if git cannot answer.
    """
    if not sha or sha.startswith("-"):
        return None  # never let a recorded value be read as a git option
    # Ancestry first: rev-list --count prints 0 for a commit that is not an ancestor, too.
    code = _git_code(cwd, "merge-base", "--is-ancestor", sha, "HEAD")
    if code in (1, 128):
        return None
    if code != 0:
        raise GitFailed(f"git merge-base --is-ancestor exited with {code}")
    count = _git(cwd, "rev-list", "--count", f"{sha}..HEAD")
    if count is None or not count.isdigit():
        raise GitFailed("git rev-list --count gave no count")
    return int(count)


def branch_exists(cwd: Path, name: str) -> bool:
    """Whether the local branch ``name`` exists. Raises ``GitFailed`` if git cannot answer."""
    return _git_code(cwd, "show-ref", "--verify", "--quiet", f"refs/heads/{name}") == 0


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


def git_common_root(cwd: Path) -> Path | None:
    """The root of the main checkout of the repository that contains ``cwd``, or None.

    Every work tree of one repository (``git worktree add``) maps to the same directory: the
    parent of the shared ``.git`` directory. When the common git directory is not named
    ``.git`` (a work tree of a bare repository, a submodule) the root of the work tree that
    contains ``cwd`` is returned instead. None outside a repository, and whenever git fails.
    """
    common = _git(cwd, "rev-parse", "--git-common-dir")
    if not common:
        return None
    common_dir = (cwd / common).resolve()  # an absolute output replaces cwd
    if common_dir.name == ".git":
        return common_dir.parent
    return git_toplevel(cwd)


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
