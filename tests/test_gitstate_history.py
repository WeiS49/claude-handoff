"""commits_since and branch_exists against real throwaway repositories."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from claude_handoff.gitstate import branch_exists, commits_since, read_git_state

MISSING = "0" * 40


def _commit(run_git: Callable[..., None], repo: Path, name: str) -> str:
    (repo / name).write_text(f"{name}\n")
    run_git(repo, "add", name)
    run_git(repo, "commit", "-m", f"Add {name}")
    head = read_git_state(repo).head_sha
    assert head is not None
    return head


def test_commits_since_equal(repo: Path) -> None:
    head = read_git_state(repo).head_sha
    assert head is not None
    assert commits_since(repo, head) == 0


def test_commits_since_ancestor(repo: Path, run_git: Callable[..., None]) -> None:
    start = read_git_state(repo).head_sha
    assert start is not None
    _commit(run_git, repo, "b.txt")
    assert commits_since(repo, start) == 1
    _commit(run_git, repo, "c.txt")
    assert commits_since(repo, start) == 2


def test_commits_since_not_ancestor(repo: Path, run_git: Callable[..., None]) -> None:
    run_git(repo, "switch", "-c", "feat/side")
    side = _commit(run_git, repo, "side.txt")
    run_git(repo, "switch", "main")
    assert commits_since(repo, side) is None


def test_commits_since_missing_object(repo: Path) -> None:
    assert commits_since(repo, MISSING) is None


def test_commits_since_no_commits_yet(tmp_path: Path, run_git: Callable[..., None]) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    run_git(empty, "init", "-b", "main")
    assert commits_since(empty, MISSING) is None


def test_commits_since_refuses_option_like_value(repo: Path) -> None:
    assert commits_since(repo, "--help") is None


def test_branch_exists(repo: Path, run_git: Callable[..., None]) -> None:
    assert branch_exists(repo, "main") is True
    assert branch_exists(repo, "feat/x") is False
    run_git(repo, "branch", "feat/x")
    assert branch_exists(repo, "feat/x") is True
    run_git(repo, "branch", "-D", "feat/x")
    assert branch_exists(repo, "feat/x") is False


def test_branch_exists_before_first_commit(tmp_path: Path, run_git: Callable[..., None]) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    run_git(empty, "init", "-b", "main")
    assert branch_exists(empty, "main") is False
