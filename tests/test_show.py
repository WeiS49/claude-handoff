"""``show``: saved replies in full, and the line in the briefing that says how to get them.

The autouse fixture in conftest.py points the state directory under tmp_path, so the
subprocess runs below inherit it through ``os.environ``.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from claude_handoff import store
from claude_handoff.briefing import (
    MAX_CHARS,
    TRUNCATION_MARK,
    build_briefing,
    render_saved,
)
from claude_handoff.gitstate import read_git_state

HINT = "Full text of these replies: "
T0 = datetime(2026, 11, 18, 12, 0, 0, tzinfo=UTC)
NOW = T0 + timedelta(hours=1)


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


def _show(cwd: Path, *extra: str) -> subprocess.CompletedProcess[bytes]:
    return _run(["show", "--cwd", str(cwd), *extra], b"", cwd)


def _record(
    monkeypatch: pytest.MonkeyPatch, cwd: Path, session_id: str, message: str, at: datetime
) -> None:
    git = read_git_state(cwd)
    monkeypatch.setattr(store, "_now", lambda: at)
    store.write_state(
        project=store.project_root(cwd),
        session_id=session_id,
        branch=git.branch,
        head=git.head_sha,
        message=message,
    )


def _five(monkeypatch: pytest.MonkeyPatch, repo: Path) -> None:
    """Records ``s0`` (oldest) to ``s4`` (newest), one minute apart."""
    for number in range(5):
        _record(
            monkeypatch,
            repo,
            f"s{number}",
            f"Reply number {number}.",
            T0 + timedelta(minutes=number),
        )


def _long_reply() -> str:
    """About 3000 characters with blank lines, a fenced code block and a quoted line."""
    head = "First paragraph of the reply.\n\n```python\nprint('inside the fence')\n```\n\n"
    quoted = "> a quoted line from the user\n\n"
    filler = "".join(f"Filler line {n} of the middle part.\n" for n in range(80))
    message = head + quoted + filler + "\nThe very last line of the reply."
    assert 2500 < len(message) < store.MAX_MESSAGE_CHARS
    return message


# --- through the real entry point -------------------------------------------------------


def test_show_prints_full_reply(repo: Path) -> None:
    _stop(repo, "A", _long_reply())
    result = _show(repo)
    assert result.returncode == 0
    out = result.stdout.decode("utf-8")
    assert "  > print('inside the fence')" in out
    assert "  > > a quoted line from the user" in out
    assert "  > Filler line 79 of the middle part." in out
    assert "  > The very last line of the reply." in out
    assert out.endswith("The very last line of the reply.\n")


def test_show_no_sessions(repo: Path) -> None:
    result = _show(repo)
    assert result.returncode == 0
    assert result.stdout.decode("utf-8") == "No saved sessions for this project.\n"


def test_show_missing_directory_has_no_sessions(tmp_path: Path) -> None:
    result = _run(["show", "--cwd", str(tmp_path / "missing")], b"", tmp_path)
    assert result.returncode == 0
    assert result.stdout.decode("utf-8") == "No saved sessions for this project.\n"


@pytest.mark.parametrize("index", ["9", "0"])
def test_show_index_out_of_range(repo: Path, index: str) -> None:
    _stop(repo, "A", "Only reply.")
    result = _show(repo, "--index", index)
    assert result.returncode == 1
    assert result.stdout == b""
    assert f"No saved session {index}; this project has 1." in result.stderr.decode("utf-8")


def test_show_index_through_entry_point(repo: Path) -> None:
    _stop(repo, "A", "Only reply.")
    result = _show(repo, "--index", "1")
    assert result.returncode == 0
    lines = result.stdout.decode("utf-8").splitlines()
    assert lines[0].startswith(f"[claude-handoff] Saved sessions of {repo.name} ")
    assert lines[1].startswith("[1] ")
    assert lines[2:] == ["  > Only reply."]


def test_briefing_hint_command_runs(repo: Path) -> None:
    message = _long_reply()
    _stop(repo, "A", message)
    out = _session_start(repo, "B")
    last = out.splitlines()[-1]
    assert last.startswith(HINT)
    result = subprocess.run(
        shlex.split(last[len(HINT) :]),
        capture_output=True,
        env={**os.environ},
        timeout=60,
        check=False,
    )
    assert result.returncode == 0
    assert "  > The very last line of the reply." in result.stdout.decode("utf-8")


def test_briefing_hint_names_this_directory(repo: Path) -> None:
    _stop(repo, "A", "Some reply.")
    last = _session_start(repo, "B").splitlines()[-1]
    parts = shlex.split(last[len(HINT) :])
    assert parts[:4] == [sys.executable, "-m", "claude_handoff.cli", "show"]
    assert parts[4] == "--cwd"
    assert Path(parts[5]).resolve() == repo.resolve()


def test_no_hint_without_sessions(repo: Path) -> None:
    assert "Full text of these replies" not in _session_start(repo, "B")


def test_no_hint_when_only_own_session(repo: Path) -> None:
    _stop(repo, "A", "My own reply.")
    assert "Full text of these replies" not in _session_start(repo, "A")


def test_hint_survives_truncation(repo: Path) -> None:
    for number in range(5):
        _stop(repo, f"s{number}", "x\n" * 2000)
    out = _session_start(repo, "fresh")
    assert len(out) <= MAX_CHARS + 1
    assert TRUNCATION_MARK in out
    assert out.splitlines()[-1].startswith(HINT)


# --- direct calls -----------------------------------------------------------------------


def _saved(repo: Path, index: int | None = None) -> list[str]:
    records = store.read_states(store.project_root(repo))
    return render_saved(records, read_git_state(repo), repo, NOW, index)


def test_show_lists_all_newest_first_with_numbers(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _five(monkeypatch, repo)
    text = "\n".join(_saved(repo))
    positions = [text.index(f"\n[{number}] ") for number in range(1, 6)]
    assert positions == sorted(positions)
    for number in range(1, 6):
        assert f"  > Reply number {5 - number}." in text
    first = text.splitlines()
    assert first[1].startswith("[1] 56 min ago")
    assert first[2] == "  > Reply number 4."


def test_show_index_selects_one(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _five(monkeypatch, repo)
    lines = _saved(repo, index=2)
    assert len(lines) == 3
    assert lines[0].startswith("[claude-handoff] Saved sessions of ")
    assert lines[1].startswith("[2] ")
    assert lines[2] == "  > Reply number 3."


def test_show_title_matches_briefing_title(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _record(monkeypatch, repo, "A", "One reply.", T0)
    shown = _saved(repo)[1]
    briefing = build_briefing(repo, now=NOW)
    titles = [line for line in briefing.splitlines() if line.startswith("- ")]
    assert len(titles) == 1
    assert shown.removeprefix("[1] ") == titles[0].removeprefix("- ")


def test_show_keeps_blank_lines_as_bare_prefix(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _record(monkeypatch, repo, "A", "\n\nFirst line.\n\n   \nThird line.  \nLast.\n\n", T0)
    lines = _saved(repo)
    assert lines[2:] == ["  > First line.", "  >", "  >", "  > Third line.  ", "  > Last."]


def test_show_message_not_a_string_prints_title_only(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _record(monkeypatch, repo, "A", "placeholder", T0)
    path = store.state_path(store.project_root(repo), "A")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["message"] = 42
    path.write_text(json.dumps(data), encoding="utf-8")
    lines = _saved(repo)
    assert len(lines) == 2
    assert lines[1].startswith("[1] ")


def test_hint_dropped_when_ceiling_too_small(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _record(monkeypatch, repo, "A", "One reply.", T0)
    assert HINT in build_briefing(repo, now=NOW)
    text = build_briefing(repo, max_chars=60, now=NOW)
    assert HINT not in text
    assert len(text) <= 60
