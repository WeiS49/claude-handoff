"""Fixtures build throwaway git repos. Never use real session data or real user paths."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def _run_git(cwd: Path, *args: str) -> None:
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "-C",
            str(cwd),
            *args,
        ],
        check=True,
        capture_output=True,
    )


@pytest.fixture(autouse=True)
def isolated_state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the state directory under tmp_path for every test, subprocesses included.

    No test can then read or write the real handoff state in the home directory.
    """
    state = tmp_path / "handoff-state"
    monkeypatch.setenv("CLAUDE_HANDOFF_STATE_DIR", str(state))
    return state


@pytest.fixture(autouse=True)
def attended_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove CLAUDE_CODE_SESSION_ATTENDED for every test, subprocesses included.

    ``./check`` may run inside an unattended Claude session, which sets it to ``0``; inherited
    by the hook subprocesses, it would mark every record unattended and hide it from briefings.
    """
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ATTENDED", raising=False)


@pytest.fixture(autouse=True)
def no_project_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove CLAUDE_PROJECT_DIR for every test, subprocesses included.

    ``./check`` may run inside a Claude session, which sets it for hook processes; inherited,
    it would make the hooks describe that directory instead of the test's ``cwd``.
    """
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)


@pytest.fixture
def run_git():
    """The helper that runs git with a fixed test identity."""
    return _run_git


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A git repo on branch ``main`` with one commit."""
    root = tmp_path / "demo"
    root.mkdir()
    _run_git(root, "init", "-b", "main")
    (root / "a.txt").write_text("one\n")
    _run_git(root, "add", "a.txt")
    _run_git(root, "commit", "-m", "Add a")
    return root
