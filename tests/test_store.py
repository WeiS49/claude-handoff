"""The state store, called directly. Every test keeps the state directory under tmp_path."""

from __future__ import annotations

import json
import os
import re
import stat
from pathlib import Path

import pytest

from claude_handoff import store
from claude_handoff.store import project_root, read_state, state_dir, state_path, write_state


@pytest.fixture
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the store at a directory under tmp_path that does not exist yet."""
    directory = tmp_path / "state"
    monkeypatch.setenv("CLAUDE_HANDOFF_STATE_DIR", str(directory))
    return directory


def _write(project: Path, message: str = "Finished the parser.") -> Path:
    return write_state(
        project=project, session_id="abc", branch="main", head="0" * 40, message=message
    )


def test_state_dir_precedence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_HANDOFF_STATE_DIR", str(tmp_path / "explicit"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    assert state_dir() == tmp_path / "explicit"

    monkeypatch.delenv("CLAUDE_HANDOFF_STATE_DIR", raising=False)
    assert state_dir() == tmp_path / "xdg" / "claude-handoff"

    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert state_dir() == tmp_path / ".local" / "state" / "claude-handoff"


def test_state_dir_empty_variables_count_as_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_HANDOFF_STATE_DIR", "")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    assert state_dir() == tmp_path / "xdg" / "claude-handoff"

    monkeypatch.setenv("XDG_STATE_HOME", "")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert state_dir() == tmp_path / ".local" / "state" / "claude-handoff"


def test_state_path_is_stable_and_distinct(state: Path, tmp_path: Path) -> None:
    one = tmp_path / "one"
    two = tmp_path / "two"
    assert state_path(one) == state_path(one)
    assert state_path(one) != state_path(two)
    assert state_path(one).parent == state
    assert re.fullmatch(r"[0-9a-f]{16}\.json", state_path(one).name)


def test_project_root_is_repo_root(repo: Path) -> None:
    sub = repo / "sub"
    sub.mkdir()
    assert project_root(sub) == repo.resolve()
    assert project_root(repo) == repo.resolve()


def test_project_root_outside_git_is_cwd(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    assert project_root(plain) == plain.resolve()


def test_project_root_through_symlink(repo: Path, tmp_path: Path) -> None:
    link = tmp_path / "link"
    link.symlink_to(repo, target_is_directory=True)
    assert project_root(link) == project_root(repo)


def test_read_state_roundtrip(state: Path, tmp_path: Path) -> None:
    project = tmp_path / "project"
    path = _write(project)
    assert path == state_path(project)
    data = read_state(project)
    assert data is not None
    assert data["version"] == 1
    assert data["project"] == str(project)
    assert data["session_id"] == "abc"
    assert data["branch"] == "main"
    assert data["head"] == "0" * 40
    assert data["message"] == "Finished the parser."
    assert isinstance(data["written_at"], str)


def test_read_state_keeps_non_ascii(state: Path, tmp_path: Path) -> None:
    project = tmp_path / "project"
    _write(project, "解析器写完了。")
    assert read_state(project)["message"] == "解析器写完了。"
    assert "解析器" in state_path(project).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "content",
    [None, "{not json", "[1, 2]", json.dumps({"version": 2, "message": "x"})],
    ids=["missing", "not-json", "not-object", "version-2"],
)
def test_read_state_missing_or_corrupt_returns_none(
    content: str | None, state: Path, tmp_path: Path
) -> None:
    project = tmp_path / "project"
    if content is not None:
        state.mkdir()
        state_path(project).write_text(content, encoding="utf-8")
    assert read_state(project) is None


def test_write_leaves_no_temp_files(state: Path, tmp_path: Path) -> None:
    project = tmp_path / "project"
    path = _write(project)
    _write(project, "Second.")
    assert sorted(os.listdir(state)) == [path.name]


def test_failed_write_leaves_no_temp_file_and_keeps_old_state(
    state: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    path = _write(project)
    before = path.read_bytes()

    def broken_replace(src: object, dst: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(store.os, "replace", broken_replace)
    with pytest.raises(OSError):
        _write(project, "Second.")
    assert sorted(os.listdir(state)) == [path.name]
    assert path.read_bytes() == before


def test_write_truncates_long_message(state: Path, tmp_path: Path) -> None:
    project = tmp_path / "project"
    _write(project, "z" * 4001)
    saved = read_state(project)["message"]
    assert len(saved) == 4000
    assert saved == "z" * 3999 + "…"


def test_write_creates_private_directory_and_file(state: Path, tmp_path: Path) -> None:
    path = _write(tmp_path / "project")
    assert stat.S_IMODE(state.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_write_leaves_existing_directory_mode(state: Path, tmp_path: Path) -> None:
    state.mkdir()
    os.chmod(state, 0o755)
    _write(tmp_path / "project")
    assert stat.S_IMODE(state.stat().st_mode) == 0o755
