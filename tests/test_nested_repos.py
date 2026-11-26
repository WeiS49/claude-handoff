"""Repositories directly inside a project directory that is not a git repository itself."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from claude_handoff.briefing import TRUNCATION_MARK, build_briefing

NOT_A_REPO = "Git: this directory is not a git repository."
TITLE = NOT_A_REPO + " Repositories directly inside it:"


def _git(cwd: Path, *args: str) -> None:
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
        capture_output=True,
        check=False,
    )


def _child(project: Path, name: str, *, commit: str | None = "First commit") -> Path:
    """A repository ``project/name`` on ``main``, with one commit titled ``commit`` or none."""
    root = project / name
    root.mkdir(parents=True)
    _git(root, "init", "-b", "main")
    if commit is not None:
        (root / "a.txt").write_text("one\n")
        _git(root, "add", "a.txt")
        _git(root, "commit", "-m", commit)
    return root


def _git_lines(text: str) -> list[str]:
    """The git part of a briefing: every line after the header."""
    return text.split("\n")[1:]


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    return root


def _line_for(lines: list[str], name: str) -> str:
    matches = [line for line in lines if line.startswith(f"  {name}/ · ")]
    assert len(matches) == 1, lines
    return matches[0]


def test_non_git_directory_lists_child_repository(project: Path) -> None:
    child = _child(project, "repo")
    (child / "notes.txt").write_text("untracked\n")
    lines = _git_lines(build_briefing(project))
    assert lines[0] == TITLE
    line = _line_for(lines, "repo")
    parts = line.split(" · ")
    assert parts[0] == "  repo/"
    assert parts[1] == "main"
    assert parts[2] == "1 uncommitted"
    assert parts[3].startswith("last commit ")
    assert parts[3].endswith(" First commit")
    assert len(lines) == 2


def test_clean_child_and_child_without_commits(project: Path) -> None:
    _child(project, "api", commit="Add health endpoint")
    _child(project, "empty", commit=None)
    lines = _git_lines(build_briefing(project))
    assert lines[0] == TITLE
    api = _line_for(lines, "api")
    assert api.startswith("  api/ · main · clean · last commit ")
    assert api.endswith(" Add health endpoint")
    assert _line_for(lines, "empty") == "  empty/ · main · clean · no commits yet"
    assert lines.index(api) < lines.index("  empty/ · main · clean · no commits yet")


def test_detached_head_child(project: Path) -> None:
    child = _child(project, "web", commit="Fix layout")
    _git(child, "checkout", "--detach")
    line = _line_for(_git_lines(build_briefing(project)), "web")
    assert line.startswith("  web/ · (detached HEAD) · clean · last commit ")
    assert line.endswith(" Fix layout")


def test_more_than_three_children_are_sorted_and_counted(project: Path) -> None:
    for name in ("e", "c", "a", "d", "b"):
        _child(project, name, commit=f"Commit in {name}")
    lines = _git_lines(build_briefing(project))
    assert lines[0] == TITLE
    assert [line.split(" · ")[0] for line in lines[1:4]] == ["  a/", "  b/", "  c/"]
    assert lines[4] == "  … and 2 more"
    assert len(lines) == 5
    assert not any(line.startswith(("  d/", "  e/")) for line in lines)


def test_hidden_symlinked_and_plain_children_are_skipped(project: Path, tmp_path: Path) -> None:
    _child(project, ".hidden")
    outside = _child(tmp_path, "outside")
    (project / "linked").symlink_to(outside, target_is_directory=True)
    (project / "plain").mkdir()
    (project / "plain" / "file.txt").write_text("x\n")
    (project / "README.md").write_text("docs\n")
    _child(project, "real")
    lines = _git_lines(build_briefing(project))
    assert lines[0] == TITLE
    assert len(lines) == 2
    assert lines[1].startswith("  real/ · main · clean · last commit ")


def test_child_with_broken_git_entry_is_unreadable(project: Path) -> None:
    broken = project / "broken"
    broken.mkdir()
    (broken / ".git").write_text("this is not a gitdir line\n")
    lines = _git_lines(build_briefing(project))
    assert lines == [TITLE, "  broken/ · unreadable"]


def test_child_with_empty_git_directory_is_unreadable(project: Path) -> None:
    (project / "ghost" / ".git").mkdir(parents=True)
    _child(project, "real")
    lines = _git_lines(build_briefing(project))
    assert lines[0] == TITLE
    assert lines[1] == "  ghost/ · unreadable"
    assert lines[2].startswith("  real/ · main · clean · ")


def test_no_child_repository_keeps_the_single_line(project: Path) -> None:
    (project / "docs").mkdir()
    (project / "notes.md").write_text("x\n")
    assert _git_lines(build_briefing(project)) == [NOT_A_REPO]


def test_inside_a_repository_nested_repositories_are_not_listed(project: Path) -> None:
    _git(project, "init", "-b", "main")
    _child(project, "inner")
    text = build_briefing(project)
    assert "Repositories directly inside it:" not in text
    assert "inner/ ·" not in text
    assert "Branch: main" in text


def test_briefing_with_nested_repositories_respects_max_chars(project: Path) -> None:
    for name in ("one", "two", "three", "four"):
        _child(project, name, commit=f"A fairly long commit title for repository {name}")
    text = build_briefing(project, max_chars=150)
    assert len(text) <= 150
    assert text.endswith(TRUNCATION_MARK)


def test_cli_brief_lists_child_repository(project: Path) -> None:
    child = _child(project, "repo")
    (child / "notes.txt").write_text("untracked\n")
    result = subprocess.run(
        [sys.executable, "-m", "claude_handoff.cli", "brief", "--cwd", str(project)],
        capture_output=True,
        text=True,
        env={**os.environ},
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    lines = result.stdout.rstrip("\n").split("\n")
    assert lines[0] == "[claude-handoff] State of proj, read just now:"
    assert lines[1] == TITLE
    assert lines[2].startswith("  repo/ · main · 1 uncommitted · last commit ")
    assert lines[2].endswith(" First commit")
