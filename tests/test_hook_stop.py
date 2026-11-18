"""The Stop hook, run through the real entry point in a subprocess.

Every run points CLAUDE_HANDOFF_STATE_DIR at a directory under tmp_path that does not exist
yet, so nothing is ever written to the real home directory and the command creates the
directory itself.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import pytest

ENTRY = [sys.executable, "-m", "claude_handoff.cli", "hook", "stop"]
KEYS = {"version", "project", "session_id", "written_at", "branch", "head", "message"}


def _stop(stdin: bytes, state: Path, cwd: Path) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ENTRY,
        input=stdin,
        capture_output=True,
        cwd=cwd,
        env={**os.environ, "CLAUDE_HANDOFF_STATE_DIR": str(state)},
        timeout=60,
        check=False,
    )


def _payload(**fields: object) -> bytes:
    return json.dumps(fields).encode("utf-8")


def _stop_payload(cwd: Path, message: str = "Finished the parser.") -> bytes:
    return _payload(
        session_id="abc", cwd=str(cwd), hook_event_name="Stop", last_assistant_message=message
    )


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _project_dir(state: Path, project: Path) -> Path:
    return state / _digest(str(project.resolve()))


def _expected_file(state: Path, project: Path, session_id: str = "abc") -> Path:
    return _project_dir(state, project) / f"{_digest(session_id)}.json"


def _project_files(state: Path) -> list[Path]:
    """The files in the only project directory under ``state``."""
    projects = list(state.iterdir())
    assert len(projects) == 1
    assert projects[0].is_dir()
    return sorted(projects[0].iterdir())


def _only_file(state: Path) -> Path:
    files = _project_files(state)
    assert len(files) == 1
    return files[0]


def _messages(state: Path) -> dict[str | None, str]:
    """``session_id`` to ``message`` for every file in the only project directory."""
    records = [json.loads(path.read_text(encoding="utf-8")) for path in _project_files(state)]
    return {data["session_id"]: data["message"] for data in records}


def _head(repo: Path) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    )
    return out.stdout.strip()


@pytest.fixture
def state(tmp_path: Path) -> Path:
    """A state directory that does not exist yet."""
    return tmp_path / "state" / "claude-handoff"


def test_stop_writes_state_for_repo(repo: Path, state: Path, tmp_path: Path) -> None:
    result = _stop(_stop_payload(repo), state, tmp_path)
    assert result.returncode == 0
    path = _only_file(state)
    assert path == _expected_file(state, repo)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data) == KEYS
    assert data["version"] == 1
    assert data["project"] == str(repo.resolve())
    assert data["session_id"] == "abc"
    assert data["branch"] == "main"
    assert data["head"] == _head(repo)
    assert len(data["head"]) == 40
    assert data["message"] == "Finished the parser."
    written = datetime.fromisoformat(data["written_at"])
    assert written.tzinfo is not None
    assert written.utcoffset().total_seconds() == 0


def test_stop_overwrites_previous_state(repo: Path, state: Path, tmp_path: Path) -> None:
    assert _stop(_stop_payload(repo), state, tmp_path).returncode == 0
    assert _stop(_stop_payload(repo, "Second."), state, tmp_path).returncode == 0
    path = _only_file(state)
    assert json.loads(path.read_text(encoding="utf-8"))["message"] == "Second."


def test_stop_from_subdirectory_uses_repo_root(repo: Path, state: Path, tmp_path: Path) -> None:
    sub = repo / "pkg" / "inner"
    sub.mkdir(parents=True)
    assert _stop(_stop_payload(sub), state, tmp_path).returncode == 0
    path = _only_file(state)
    assert path == _expected_file(state, repo)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["project"] == str(repo.resolve())
    assert data["head"] == _head(repo)


def test_stop_non_git_directory(state: Path, tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    assert _stop(_stop_payload(plain), state, tmp_path).returncode == 0
    path = _only_file(state)
    assert path == _expected_file(state, plain)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["project"] == str(plain.resolve())
    assert data["branch"] is None
    assert data["head"] is None
    assert data["message"] == "Finished the parser."


def test_stop_repo_without_commits(state: Path, tmp_path: Path, run_git) -> None:
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    run_git(fresh, "init", "-b", "main")
    assert _stop(_stop_payload(fresh), state, tmp_path).returncode == 0
    data = json.loads(_only_file(state).read_text(encoding="utf-8"))
    assert data["project"] == str(fresh.resolve())
    assert data["branch"] == "main"
    assert data["head"] is None
    assert data["message"] == "Finished the parser."


def test_stop_relative_cwd_resolves_against_working_directory(repo: Path, state: Path) -> None:
    stdin = _payload(cwd=".", last_assistant_message="done")
    assert _stop(stdin, state, repo).returncode == 0
    path = _only_file(state)
    assert path == _project_dir(state, repo) / "unknown.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["project"] == str(repo.resolve())
    assert data["session_id"] is None


def test_stop_keeps_message_whitespace(repo: Path, state: Path, tmp_path: Path) -> None:
    message = "  Done.\n\nNext: tests.\n"
    assert _stop(_stop_payload(repo, message), state, tmp_path).returncode == 0
    data = json.loads(_only_file(state).read_text(encoding="utf-8"))
    assert data["message"] == message


def _with_cwd(repo: Path, **fields: object) -> bytes:
    return _payload(session_id="abc", cwd=str(repo), hook_event_name="Stop", **fields)


def _missing_dir(repo: Path) -> bytes:
    return _payload(cwd=str(repo / "does-not-exist"), last_assistant_message="done")


def _file_cwd(repo: Path) -> bytes:
    return _payload(cwd=str(repo / "a.txt"), last_assistant_message="done")


BAD_INPUTS: dict[str, Callable[[Path], bytes]] = {
    "empty": lambda _: b"",
    "not-json": lambda _: b"{not json",
    "json-not-object": lambda _: b'["cwd", "."]',
    "invalid-utf8": lambda _: b'{"cwd": "\xff\xfe", "last_assistant_message": "done"}',
    "deeply-nested-json": lambda _: b"[" * 100_000,
    "no-cwd": lambda _: _payload(session_id="abc", last_assistant_message="done"),
    "cwd-not-string": lambda _: _payload(cwd=42, last_assistant_message="done"),
    "cwd-empty-string": lambda _: _payload(cwd="", last_assistant_message="done"),
    "cwd-missing-dir": _missing_dir,
    "cwd-is-file": _file_cwd,
    "no-message": lambda repo: _with_cwd(repo),
    "message-not-string": lambda repo: _with_cwd(repo, last_assistant_message=["done"]),
    "message-null": lambda repo: _with_cwd(repo, last_assistant_message=None),
    "message-empty": lambda repo: _with_cwd(repo, last_assistant_message=""),
    "message-blank": lambda repo: _with_cwd(repo, last_assistant_message=" \n\t "),
}


@pytest.mark.parametrize("make_input", BAD_INPUTS.values(), ids=BAD_INPUTS.keys())
def test_stop_bad_input_writes_nothing(
    make_input: Callable[[Path], bytes], repo: Path, state: Path, tmp_path: Path
) -> None:
    result = _stop(make_input(repo), state, tmp_path)
    assert result.returncode == 0
    assert result.stdout == b""
    assert result.stderr == b""
    assert not state.exists() or list(state.iterdir()) == []


def test_stop_bad_input_keeps_existing_state(repo: Path, state: Path, tmp_path: Path) -> None:
    assert _stop(_stop_payload(repo), state, tmp_path).returncode == 0
    path = _only_file(state)
    before = path.read_bytes()
    result = _stop(_with_cwd(repo), state, tmp_path)
    assert result.returncode == 0
    assert result.stdout == b""
    assert result.stderr == b""
    assert _only_file(state) == path
    assert path.read_bytes() == before


def test_stop_truncates_long_message(repo: Path, state: Path, tmp_path: Path) -> None:
    message = "x" * 10_000
    assert _stop(_stop_payload(repo, message), state, tmp_path).returncode == 0
    saved = json.loads(_only_file(state).read_text(encoding="utf-8"))["message"]
    assert len(saved) == 4000
    assert saved.endswith("…")
    assert saved[:-1] == "x" * 3999


def test_stop_keeps_message_at_limit(repo: Path, state: Path, tmp_path: Path) -> None:
    message = "y" * 4000
    assert _stop(_stop_payload(repo, message), state, tmp_path).returncode == 0
    saved = json.loads(_only_file(state).read_text(encoding="utf-8"))["message"]
    assert saved == message


def test_stop_file_and_directory_permissions(repo: Path, state: Path, tmp_path: Path) -> None:
    assert not state.exists()
    assert _stop(_stop_payload(repo), state, tmp_path).returncode == 0
    assert stat.S_IMODE(state.stat().st_mode) == 0o700
    assert stat.S_IMODE(_project_dir(state, repo).stat().st_mode) == 0o700
    assert stat.S_IMODE(_only_file(state).stat().st_mode) == 0o600


def test_stop_unwritable_state_dir_is_silent(repo: Path, tmp_path: Path) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("a file where the state directory should be\n")
    result = _stop(_stop_payload(repo), blocker / "state", tmp_path)
    assert result.returncode == 0
    assert result.stdout == b""
    assert result.stderr == b""


def test_stop_is_silent(repo: Path, state: Path, tmp_path: Path) -> None:
    result = _stop(_stop_payload(repo), state, tmp_path)
    assert result.returncode == 0
    assert result.stdout == b""
    assert result.stderr == b""
    assert _only_file(state).is_file()


def _session_payload(cwd: Path, session_id: object, message: str) -> bytes:
    return _payload(
        session_id=session_id, cwd=str(cwd), hook_event_name="Stop", last_assistant_message=message
    )


def test_stop_keeps_one_file_per_session(repo: Path, state: Path, tmp_path: Path) -> None:
    a = _session_payload(repo, "session-A", "A: refactoring the parser, half done.")
    b = _session_payload(repo, "session-B", "B: answered a quick question.")
    assert _stop(a, state, tmp_path).returncode == 0
    assert _stop(b, state, tmp_path).returncode == 0
    assert _project_files(state) == sorted(
        [_expected_file(state, repo, "session-A"), _expected_file(state, repo, "session-B")]
    )
    assert _messages(state) == {
        "session-A": "A: refactoring the parser, half done.",
        "session-B": "B: answered a quick question.",
    }


def test_stop_same_session_replaces_its_own_file(
    repo: Path, state: Path, tmp_path: Path
) -> None:
    assert _stop(_session_payload(repo, "session-A", "A1"), state, tmp_path).returncode == 0
    assert _stop(_session_payload(repo, "session-B", "B"), state, tmp_path).returncode == 0
    assert _stop(_session_payload(repo, "session-A", "A2"), state, tmp_path).returncode == 0
    assert len(_project_files(state)) == 2
    assert _messages(state) == {"session-A": "A2", "session-B": "B"}
    data = json.loads(_expected_file(state, repo, "session-A").read_text(encoding="utf-8"))
    assert set(data) == KEYS
    assert data["message"] == "A2"


SESSIONLESS: dict[str, Callable[[Path], bytes]] = {
    "missing": lambda repo: _payload(cwd=str(repo), last_assistant_message="done"),
    "null": lambda repo: _session_payload(repo, None, "done"),
    "number": lambda repo: _session_payload(repo, 42, "done"),
    "list": lambda repo: _session_payload(repo, ["abc"], "done"),
}


@pytest.mark.parametrize("make_input", SESSIONLESS.values(), ids=SESSIONLESS.keys())
def test_stop_without_session_id_uses_unknown(
    make_input: Callable[[Path], bytes], repo: Path, state: Path, tmp_path: Path
) -> None:
    assert _stop(make_input(repo), state, tmp_path).returncode == 0
    path = _only_file(state)
    assert path == _project_dir(state, repo) / "unknown.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data) == KEYS
    assert data["session_id"] is None
    assert data["message"] == "done"


def test_stop_keeps_newest_five_sessions(repo: Path, state: Path, tmp_path: Path) -> None:
    for i in range(6):
        stdin = _session_payload(repo, f"session-{i}", f"message {i}")
        assert _stop(stdin, state, tmp_path).returncode == 0
    files = _project_files(state)
    assert len(files) == 5
    assert _expected_file(state, repo, "session-5") in files
