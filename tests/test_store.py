"""The state store, called directly. Every test keeps the state directory under tmp_path."""

from __future__ import annotations

import hashlib
import itertools
import json
import os
import re
import stat
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from claude_handoff import store
from claude_handoff.store import (
    MAX_SESSIONS,
    project_root,
    project_state_dir,
    read_states,
    state_dir,
    state_path,
    write_state,
)

START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the store at a directory under tmp_path that does not exist yet."""
    directory = tmp_path / "state"
    monkeypatch.setenv("CLAUDE_HANDOFF_STATE_DIR", str(directory))
    return directory


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Iterator[datetime]:
    """Make every write one second later than the one before, starting at START."""
    times = (START + timedelta(seconds=i) for i in itertools.count())
    monkeypatch.setattr(store, "_now", lambda: next(times))
    return times


def _write(
    project: Path, message: str = "Finished the parser.", session_id: str | None = "abc"
) -> Path:
    return write_state(
        project=project, session_id=session_id, branch="main", head="0" * 40, message=message
    )


def _session_ids(project: Path) -> list[str | None]:
    return [data["session_id"] for data in read_states(project)]


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _record(written_at: object = "2026-01-01T12:00:00+00:00", **fields: object) -> str:
    data = {"version": 1, "session_id": "x", "written_at": written_at, "message": "m"}
    data.update(fields)
    return json.dumps(data)


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
    assert state_path(one, "abc") == state_path(one, "abc")
    assert state_path(one, "abc") != state_path(two, "abc")
    assert state_path(one, "abc") != state_path(one, "def")
    assert project_state_dir(one) != project_state_dir(two)
    assert project_state_dir(one).parent == state
    assert project_state_dir(one).name == _digest(str(one))
    assert re.fullmatch(r"[0-9a-f]{16}", project_state_dir(one).name)
    assert state_path(one, "abc").parent == project_state_dir(one)
    assert state_path(one, "abc").name == f"{_digest('abc')}.json"
    assert re.fullmatch(r"[0-9a-f]{16}\.json", state_path(one, "abc").name)


@pytest.mark.parametrize("session_id", [None, 42, ["abc"]], ids=["none", "int", "list"])
def test_state_path_without_session_id_is_unknown(
    session_id: object, state: Path, tmp_path: Path
) -> None:
    project = tmp_path / "project"
    assert state_path(project, session_id) == project_state_dir(project) / "unknown.json"


def test_state_path_hashes_empty_session_id(state: Path, tmp_path: Path) -> None:
    project = tmp_path / "project"
    assert state_path(project, "").name == f"{_digest('')}.json"


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
    assert path == state_path(project, "abc")
    records = read_states(project)
    assert len(records) == 1
    data = records[0]
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
    assert read_states(project)[0]["message"] == "解析器写完了。"
    assert "解析器" in state_path(project, "abc").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "content",
    [None, "{not json", "[1, 2]", _record(version=2)],
    ids=["missing", "not-json", "not-object", "version-2"],
)
def test_read_state_missing_or_corrupt_returns_none(
    content: str | None, state: Path, tmp_path: Path
) -> None:
    project = tmp_path / "project"
    if content is not None:
        path = state_path(project, "abc")
        path.parent.mkdir(parents=True)
        path.write_text(content, encoding="utf-8")
    assert read_states(project) == []


def test_write_leaves_no_temp_files(state: Path, tmp_path: Path) -> None:
    project = tmp_path / "project"
    path = _write(project)
    _write(project, "Second.")
    assert sorted(os.listdir(state)) == [path.parent.name]
    assert sorted(os.listdir(path.parent)) == [path.name]


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
    assert sorted(os.listdir(state)) == [path.parent.name]
    assert sorted(os.listdir(path.parent)) == [path.name]
    assert path.read_bytes() == before


def test_write_truncates_long_message(state: Path, tmp_path: Path) -> None:
    project = tmp_path / "project"
    _write(project, "z" * 4001)
    saved = read_states(project)[0]["message"]
    assert len(saved) == 4000
    assert saved == "z" * 3999 + "…"


def test_write_creates_private_directory_and_file(state: Path, tmp_path: Path) -> None:
    path = _write(tmp_path / "project")
    assert stat.S_IMODE(state.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_write_leaves_existing_directory_mode(state: Path, tmp_path: Path) -> None:
    state.mkdir()
    os.chmod(state, 0o755)
    path = _write(tmp_path / "project")
    assert stat.S_IMODE(state.stat().st_mode) == 0o755
    os.chmod(path.parent, 0o750)
    _write(tmp_path / "project", "Second.")
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o750


def test_project_directory_permissions(state: Path, tmp_path: Path) -> None:
    project = tmp_path / "project"
    path = _write(project)
    assert path.parent == project_state_dir(project)
    assert stat.S_IMODE(project_state_dir(project).stat().st_mode) == 0o700
    assert stat.S_IMODE(state.stat().st_mode) == 0o700


def test_project_directory_permissions_under_existing_state_dir(
    state: Path, tmp_path: Path
) -> None:
    state.mkdir()
    os.chmod(state, 0o755)
    project = tmp_path / "project"
    _write(project)
    assert stat.S_IMODE(project_state_dir(project).stat().st_mode) == 0o700


def test_write_keeps_one_file_per_session(state: Path, tmp_path: Path, clock) -> None:
    project = tmp_path / "project"
    a = _write(project, "A.", session_id="session-A")
    b = _write(project, "B.", session_id="session-B")
    assert a != b
    assert sorted(os.listdir(project_state_dir(project))) == sorted([a.name, b.name])
    assert [data["message"] for data in read_states(project)] == ["B.", "A."]


def test_write_same_session_replaces_its_file(state: Path, tmp_path: Path, clock) -> None:
    project = tmp_path / "project"
    _write(project, "A1.", session_id="session-A")
    _write(project, "B.", session_id="session-B")
    _write(project, "A2.", session_id="session-A")
    assert len(os.listdir(project_state_dir(project))) == 2
    assert [data["message"] for data in read_states(project)] == ["A2.", "B."]


def test_write_without_session_id_saves_null(state: Path, tmp_path: Path) -> None:
    project = tmp_path / "project"
    path = _write(project, session_id=None)
    assert path.name == "unknown.json"
    assert json.loads(path.read_text(encoding="utf-8"))["session_id"] is None


def test_write_prunes_to_newest_five(state: Path, tmp_path: Path, clock) -> None:
    project = tmp_path / "project"
    for i in range(7):
        _write(project, f"message {i}", session_id=f"session-{i}")
    directory = project_state_dir(project)
    assert len(os.listdir(directory)) == MAX_SESSIONS == 5
    assert set(_session_ids(project)) == {f"session-{i}" for i in range(2, 7)}
    assert not state_path(project, "session-0").exists()
    assert not state_path(project, "session-1").exists()


def test_write_prunes_oldest_when_sixth_session_arrives(
    state: Path, tmp_path: Path, clock
) -> None:
    project = tmp_path / "project"
    for i in range(5):
        _write(project, session_id=f"session-{i}")
    assert len(os.listdir(project_state_dir(project))) == 5
    _write(project, session_id="session-5")
    assert len(os.listdir(project_state_dir(project))) == 5
    assert not state_path(project, "session-0").exists()


def test_write_prunes_by_written_at_not_mtime(state: Path, tmp_path: Path, clock) -> None:
    project = tmp_path / "project"
    for i in range(5):
        _write(project, session_id=f"session-{i}")
    # The oldest record gets the newest modification time; it must still be pruned first.
    os.utime(state_path(project, "session-0"), (2_000_000_000, 2_000_000_000))
    _write(project, session_id="session-5")
    assert not state_path(project, "session-0").exists()
    assert state_path(project, "session-1").exists()


def test_write_never_prunes_the_file_just_written(
    state: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    times = iter(
        [START + timedelta(hours=1 + i) for i in range(5)] + [START]  # the clock went back
    )
    monkeypatch.setattr(store, "_now", lambda: next(times))
    for i in range(6):
        _write(project, session_id=f"session-{i}")
    assert state_path(project, "session-5").exists()
    assert not state_path(project, "session-0").exists()
    assert len(os.listdir(project_state_dir(project))) == 5


def test_write_never_prunes_the_file_just_written_on_tie(
    state: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    monkeypatch.setattr(store, "_now", lambda: START)
    paths = [_write(project, session_id=f"session-{i}") for i in range(6)]
    newest = paths[-1]
    assert newest.exists()
    remaining = sorted(os.listdir(project_state_dir(project)))
    assert len(remaining) == 5
    assert newest.name in remaining
    # Among the others, ties fall back to file names: the smallest name counts as oldest.
    others = sorted(path.name for path in paths[:-1])
    assert others[0] not in remaining


def test_prune_removes_unusable_files_first(state: Path, tmp_path: Path, clock) -> None:
    project = tmp_path / "project"
    for i in range(4):
        _write(project, session_id=f"session-{i}")
    broken = project_state_dir(project) / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    # Five files: nothing is pruned, not even the unusable one.
    assert len(os.listdir(project_state_dir(project))) == 5
    _write(project, session_id="session-4")
    assert len(os.listdir(project_state_dir(project))) == 5
    assert not broken.exists()
    assert state_path(project, "session-0").exists()


def test_prune_ignores_other_entries(state: Path, tmp_path: Path, clock) -> None:
    project = tmp_path / "project"
    _write(project, session_id="session-0")
    directory = project_state_dir(project)
    (directory / "notes.txt").write_text("keep me", encoding="utf-8")
    (directory / ".tmp-inflight.json").write_text("{", encoding="utf-8")
    (directory / "sub.json").mkdir()
    for i in range(1, 8):
        _write(project, session_id=f"session-{i}")
    assert (directory / "notes.txt").exists()
    assert (directory / ".tmp-inflight.json").exists()
    assert (directory / "sub.json").is_dir()
    assert set(_session_ids(project)) == {f"session-{i}" for i in range(3, 8)}


def test_prune_failure_keeps_the_write(
    state: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock
) -> None:
    project = tmp_path / "project"
    for i in range(5):
        _write(project, session_id=f"session-{i}")

    def broken_unlink(self: Path, missing_ok: bool = False) -> None:
        raise PermissionError("read-only")

    monkeypatch.setattr(store.Path, "unlink", broken_unlink)
    path = _write(project, "Sixth.", session_id="session-5")
    assert json.loads(path.read_text(encoding="utf-8"))["message"] == "Sixth."
    assert len(os.listdir(project_state_dir(project))) == 6


def test_read_states_newest_first(state: Path, tmp_path: Path, clock) -> None:
    project = tmp_path / "project"
    for name in ["first", "second", "third"]:
        _write(project, session_id=name)
    _write(project, session_id="first")
    assert _session_ids(project) == ["first", "third", "second"]
    times = [datetime.fromisoformat(data["written_at"]) for data in read_states(project)]
    assert times == sorted(times, reverse=True)
    assert len(set(times)) == 3


def test_read_states_ties_break_by_file_name(
    state: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    monkeypatch.setattr(store, "_now", lambda: START)
    paths = {name: _write(project, session_id=name) for name in ["a", "b", "c"]}
    expected = sorted(paths, key=lambda name: paths[name].name, reverse=True)
    assert _session_ids(project) == expected


UNUSABLE = {
    "not-json": "{not json",
    "not-object": "[1, 2]",
    "version-2": _record(version=2),
    "written-at-missing": json.dumps({"version": 1, "session_id": "x", "message": "m"}),
    "written-at-unparseable": _record(written_at="yesterday"),
    "written-at-not-string": _record(written_at=1_700_000_000),
    "written-at-naive": _record(written_at="2026-01-01T12:00:00"),
    "version-true": _record(version=True),
}


def test_read_states_skips_unusable_files(state: Path, tmp_path: Path) -> None:
    project = tmp_path / "project"
    good = _write(project, "The good one.")
    for name, content in UNUSABLE.items():
        (good.parent / f"{name}.json").write_text(content, encoding="utf-8")
    records = read_states(project)
    assert len(records) == 1
    assert records[0]["message"] == "The good one."


def test_read_states_ignores_other_entries(state: Path, tmp_path: Path) -> None:
    project = tmp_path / "project"
    good = _write(project)
    (good.parent / "other.txt").write_text(_record(), encoding="utf-8")
    (good.parent / ".tmp-inflight.json").write_text(_record(), encoding="utf-8")
    (good.parent / "sub.json").mkdir()
    assert _session_ids(project) == ["abc"]


def test_read_states_missing_project_is_empty(state: Path, tmp_path: Path) -> None:
    assert read_states(tmp_path / "project") == []
    _write(tmp_path / "other")
    assert read_states(tmp_path / "project") == []


def test_read_states_ignores_old_top_level_file(state: Path, tmp_path: Path) -> None:
    project = tmp_path / "project"
    state.mkdir()
    legacy = state / f"{_digest(str(project))}.json"
    legacy.write_text(_record(), encoding="utf-8")
    assert read_states(project) == []
    _write(project)
    assert legacy.read_text(encoding="utf-8") == _record()
    assert _session_ids(project) == ["abc"]
