"""All work trees of one repository share one project, so their sessions see each other.

The autouse fixture in conftest.py points the state directory under tmp_path, so the
subprocess runs below inherit it through ``os.environ``, and ``store`` called in this process
finds the same directory.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from claude_handoff import store
from claude_handoff.gitstate import git_common_root
from claude_handoff.store import project_root, state_path

TITLE = "Earlier sessions in this project"

RunGit = Callable[..., None]


def _worktree(run_git: RunGit, repo: Path, path: Path, branch: str) -> Path:
    run_git(repo, "worktree", "add", "-b", branch, str(path))
    return path


def _run(args: list[str], stdin: bytes, cwd: Path) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-m", "claude_handoff.cli", *args],
        input=stdin,
        capture_output=True,
        cwd=cwd,
        env={**os.environ},
        timeout=60,
        check=False,
    )


def _stop(cwd: Path, session_id: str, message: str) -> None:
    payload = {"session_id": session_id, "cwd": str(cwd), "last_assistant_message": message}
    result = _run(["hook", "stop"], json.dumps(payload).encode("utf-8"), cwd)
    assert result.returncode == 0


def _session_start(cwd: Path, session_id: str) -> str:
    payload = {"session_id": session_id, "cwd": str(cwd), "source": "startup"}
    result = _run(["hook", "session-start"], json.dumps(payload).encode("utf-8"), cwd)
    assert result.returncode == 0
    return result.stdout.decode("utf-8")


def _head(cwd: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(cwd), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


# --- project_root and git_common_root, called directly ------------------------------------


def test_project_root_of_worktree_is_main_checkout(
    repo: Path, run_git: RunGit, tmp_path: Path
) -> None:
    worktree = _worktree(run_git, repo, tmp_path / "wt", "wt-a")
    assert project_root(worktree).resolve() == repo.resolve()


def test_project_root_of_worktree_subdirectory(
    repo: Path, run_git: RunGit, tmp_path: Path
) -> None:
    worktree = _worktree(run_git, repo, tmp_path / "wt", "wt-a")
    sub = worktree / "src" / "deep"
    sub.mkdir(parents=True)
    assert project_root(sub).resolve() == repo.resolve()


def test_project_root_plain_repo_unchanged(repo: Path) -> None:
    sub = repo / "src"
    sub.mkdir()
    assert project_root(repo).resolve() == repo.resolve()
    assert project_root(sub).resolve() == repo.resolve()


def test_project_root_outside_git_unchanged(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    assert project_root(plain).resolve() == plain.resolve()


def test_git_common_root_outside_git_is_none(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    assert git_common_root(plain) is None


def test_state_path_same_for_main_and_worktree(
    repo: Path, run_git: RunGit, tmp_path: Path
) -> None:
    worktree = _worktree(run_git, repo, tmp_path / "wt", "wt-a")
    assert state_path(project_root(repo), "s") == state_path(project_root(worktree), "s")


# --- the real hook entry points, run in a subprocess --------------------------------------


def test_worktree_session_sees_main_checkout_record(
    repo: Path, run_git: RunGit, tmp_path: Path
) -> None:
    worktree = _worktree(run_git, repo, tmp_path / "wt", "probe-wt")
    _stop(repo, "in-main", "Main checkout: halfway through the importer.")
    out = _session_start(worktree, "new")
    assert TITLE in out
    assert "Main checkout: halfway through the importer." in out


def test_main_checkout_sees_worktree_record(
    repo: Path, run_git: RunGit, tmp_path: Path
) -> None:
    worktree = _worktree(run_git, repo, tmp_path / "wt", "wt-a")
    _stop(worktree, "in-wt", "Worktree A: the exporter is wired up.")
    out = _session_start(repo, "new")
    assert TITLE in out
    assert "Worktree A: the exporter is wired up." in out
    headers = [line for line in out.splitlines() if line.startswith("- ")]
    assert any("wt-a @" in line for line in headers), out


def test_two_worktrees_share_records(repo: Path, run_git: RunGit, tmp_path: Path) -> None:
    first = _worktree(run_git, repo, tmp_path / "wt-a", "wt-a")
    second = _worktree(run_git, repo, tmp_path / "wt-b", "wt-b")
    _stop(first, "in-a", "Worktree A: tests for the parser pass.")
    _stop(second, "in-b", "Worktree B: the docs need a second pass.")

    seen_from_b = _session_start(second, "new")
    assert TITLE in seen_from_b
    assert "Worktree A: tests for the parser pass." in seen_from_b

    seen_from_a = _session_start(first, "new")
    assert TITLE in seen_from_a
    assert "Worktree B: the docs need a second pass." in seen_from_a


def test_stop_in_worktree_records_worktree_head(
    repo: Path, run_git: RunGit, tmp_path: Path
) -> None:
    worktree = _worktree(run_git, repo, tmp_path / "wt", "wt-a")
    (worktree / "b.txt").write_text("two\n")
    run_git(worktree, "add", "b.txt")
    run_git(worktree, "commit", "-m", "Add b")
    worktree_head = _head(worktree)
    main_head = _head(repo)
    assert worktree_head != main_head

    _stop(worktree, "in-wt", "Worktree A: committed b.")

    directory = store.project_state_dir(project_root(repo))
    files = sorted(directory.glob("*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert data["head"] == worktree_head
    assert data["head"] != main_head
    assert data["branch"] == "wt-a"
