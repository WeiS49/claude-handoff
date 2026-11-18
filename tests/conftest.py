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
