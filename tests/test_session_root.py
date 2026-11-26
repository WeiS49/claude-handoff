"""The hooks keep a session in the project it started in, via ``$CLAUDE_PROJECT_DIR``.

``cwd`` in the hook input follows the session when it changes directory; the variable does not.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from claude_handoff import store
from claude_handoff.cli import main
from claude_handoff.hook import record_stop, session_start_text

MODULE = [sys.executable, "-m", "claude_handoff.cli"]


def _stop_input(cwd: Path, message: str, session_id: str = "s1") -> bytes:
    return json.dumps(
        {"session_id": session_id, "cwd": str(cwd), "last_assistant_message": message}
    ).encode("utf-8")


def _start_input(cwd: Path, session_id: str = "s2") -> bytes:
    return json.dumps({"session_id": session_id, "cwd": str(cwd), "source": "startup"}).encode(
        "utf-8"
    )


def _record(cwd: Path, message: str = "Finished the notes.") -> dict[str, Any]:
    path = record_stop(_stop_input(cwd, message))
    assert path is not None
    return json.loads(path.read_text(encoding="utf-8"))


def _head(repo: Path) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    )
    return out.stdout.strip()


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A directory that is not a git repository, with ``notes/deep`` inside."""
    root = tmp_path / "project"
    (root / "notes" / "deep").mkdir(parents=True)
    return root.resolve()


def test_stop_from_subfolder_is_recorded_under_session_directory(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    data = _record(project / "notes" / "deep")
    assert data["project"] == str(project)
    assert data["branch"] is None
    assert data["head"] is None
    assert [r["message"] for r in store.read_states(project)] == ["Finished the notes."]


def test_stop_from_nested_repository_uses_session_directory_for_project_and_git(
    project: Path, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nested = project / "repo"
    repo.rename(nested)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    data = _record(nested)
    assert data["project"] == str(project)
    assert data["branch"] is None
    assert data["head"] is None
    assert store.read_states(nested) == []


def test_stop_from_work_tree_keeps_work_tree_branch(
    repo: Path, tmp_path: Path, run_git: Callable[..., None], monkeypatch: pytest.MonkeyPatch
) -> None:
    tree = tmp_path / "tree"
    run_git(repo, "worktree", "add", "-b", "feature", str(tree))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    data = _record(tree)
    assert data["project"] == str(repo.resolve())
    assert data["branch"] == "feature"
    assert data["head"] == _head(tree)


@pytest.mark.parametrize("kind", ["unset", "empty", "relative", "missing", "file"])
def test_unusable_project_dir_falls_back_to_cwd(
    kind: str, project: Path, repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A relative value names a directory that exists from the hook's working directory,
    # so only its being relative can make it unusable.
    monkeypatch.chdir(project)
    a_file = tmp_path / "a-file"
    a_file.write_text("not a directory\n")
    values = {
        "unset": None,
        "empty": "",
        "relative": "notes",
        "missing": str(tmp_path / "missing"),
        "file": str(a_file),
    }
    value = values[kind]
    if value is None:
        monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    else:
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", value)
    data = _record(repo)
    assert data["project"] == str(repo.resolve())
    assert data["branch"] == "main"
    assert data["head"] == _head(repo)
    text = session_start_text(_start_input(repo))
    assert text.startswith(f"[claude-handoff] State of {repo.name}, read just now:")


def test_session_start_uses_session_directory_when_cwd_moved(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    deep = project / "notes" / "deep"
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    _record(deep)
    text = session_start_text(_start_input(deep))
    assert text.startswith(f"[claude-handoff] State of {project.name}, read just now:")
    assert "Finished the notes." in text
    assert text.rstrip("\n").endswith(shlex.join(["show", "--cwd", str(project)]))


def test_brief_and_show_ignore_project_dir_variable(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    other = (tmp_path / "other").resolve()
    other.mkdir()
    _record(other, "Reply in other.")
    _record(project, "Reply in project.")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))

    assert main(["brief", "--cwd", str(other)]) == 0
    brief = capsys.readouterr().out
    assert brief.startswith("[claude-handoff] State of other, read just now:")
    assert "Reply in other." in brief
    assert "Reply in project." not in brief
    assert shlex.join(["--cwd", str(other)]) in brief

    assert main(["show", "--cwd", str(other)]) == 0
    shown = capsys.readouterr().out
    assert "Reply in other." in shown
    assert "Reply in project." not in shown


def test_hooks_end_to_end_with_project_dir(project: Path, tmp_path: Path) -> None:
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project)}
    stop = subprocess.run(
        [*MODULE, "hook", "stop"],
        input=_stop_input(project / "notes" / "deep", "Finished the notes."),
        capture_output=True,
        cwd=tmp_path,
        env=env,
        timeout=60,
        check=False,
    )
    assert stop.returncode == 0
    assert stop.stdout == b""
    start = subprocess.run(
        [*MODULE, "hook", "session-start"],
        input=_start_input(project),
        capture_output=True,
        cwd=tmp_path,
        env=env,
        timeout=60,
        check=False,
    )
    assert start.returncode == 0
    out = start.stdout.decode("utf-8")
    assert out.startswith(f"[claude-handoff] State of {project.name}, read just now:")
    assert "Finished the notes." in out
