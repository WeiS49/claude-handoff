"""Unattended sessions (``claude -p`` and the like): recorded and marked, kept out of briefings.

Claude Code sets ``CLAUDE_CODE_SESSION_ATTENDED`` for hook processes: ``1`` in an interactive
session, ``0`` in an unattended one. Only the exact value ``0`` marks a record unattended. The
autouse fixture in conftest.py removes the variable, so each test below sets it explicitly.
"""

from __future__ import annotations

import itertools
import json
import os
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from claude_handoff import store
from claude_handoff.briefing import build_briefing
from claude_handoff.gitstate import read_git_state

VARIABLE = "CLAUDE_CODE_SESSION_ATTENDED"
UNSET = None
START = datetime(2026, 11, 18, 12, 0, 0, tzinfo=UTC)
NOW = START + timedelta(hours=1)
SEVEN_KEYS = {"version", "project", "session_id", "written_at", "branch", "head", "message"}


# --- helpers ------------------------------------------------------------------------------


def _env(attended: str | None) -> dict[str, str]:
    """``os.environ`` with ``CLAUDE_CODE_SESSION_ATTENDED`` set to ``attended``, or removed."""
    if attended is UNSET:
        env = dict(os.environ)
        env.pop(VARIABLE, None)
        return env
    return {**os.environ, VARIABLE: attended}


def _run(
    args: list[str], stdin: bytes, cwd: Path, attended: str | None = UNSET
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-m", "claude_handoff.cli", *args],
        input=stdin,
        capture_output=True,
        cwd=cwd,
        env=_env(attended),
        timeout=60,
        check=False,
    )


def _stop(cwd: Path, session_id: str, message: str, attended: str | None) -> None:
    payload = {"session_id": session_id, "cwd": str(cwd), "last_assistant_message": message}
    result = _run(["hook", "stop"], json.dumps(payload).encode("utf-8"), cwd, attended)
    assert result.returncode == 0
    assert result.stdout == b""


def _session_start(cwd: Path, session_id: str) -> str:
    payload = {"session_id": session_id, "cwd": str(cwd), "source": "startup"}
    result = _run(["hook", "session-start"], json.dumps(payload).encode("utf-8"), cwd)
    assert result.returncode == 0
    return result.stdout.decode("utf-8")


def _saved(cwd: Path, session_id: str) -> dict[str, object]:
    path = store.state_path(store.project_root(cwd), session_id)
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Iterator[datetime]:
    """Make every write one second later than the one before, starting at START."""
    times = (START + timedelta(seconds=i) for i in itertools.count())
    monkeypatch.setattr(store, "_now", lambda: next(times))
    return times


def _write(project: Path, session_id: str, *, attended: bool | None = None) -> Path:
    return store.write_state(
        project=project,
        session_id=session_id,
        branch="main",
        head="0" * 40,
        message=f"Reply of {session_id}.",
        attended=attended,
    )


def _exists(project: Path, session_id: str) -> bool:
    return store.state_path(project, session_id).exists()


def _count(project: Path) -> int:
    return len(os.listdir(store.project_state_dir(project)))


# --- writing, through the real entry point ------------------------------------------------


def test_stop_marks_unattended(repo: Path) -> None:
    _stop(repo, "script", "PROBE done.", "0")
    data = _saved(repo, "script")
    assert data["attended"] is False
    assert len(data) == 8
    assert set(data) == SEVEN_KEYS | {"attended"}
    assert list(data)[-1] == "attended"
    assert data["message"] == "PROBE done."


@pytest.mark.parametrize("attended", ["1", UNSET, "", "false", "00"])
def test_stop_attended_file_unchanged(repo: Path, attended: str | None) -> None:
    _stop(repo, "interactive", "Importer: CSV done, TSV next.", attended)
    data = _saved(repo, "interactive")
    assert "attended" not in data
    assert len(data) == 7
    assert set(data) == SEVEN_KEYS


# --- the briefing and show, through the real entry point ----------------------------------


def test_briefing_hides_unattended(repo: Path) -> None:
    _stop(repo, "interactive", "Importer: CSV done, TSV next.", "1")
    _stop(repo, "script", "PROBE done.", "0")
    out = _session_start(repo, "new")
    assert "Earlier sessions in this project" in out
    assert "Importer: CSV done, TSV next." in out
    assert "PROBE done." not in out
    assert "more" not in out


def test_only_unattended_means_no_section(repo: Path) -> None:
    _stop(repo, "script-1", "PROBE one.", "0")
    _stop(repo, "script-2", "PROBE two.", "0")
    out = _session_start(repo, "new")
    assert out.startswith(f"[claude-handoff] State of {repo.name}")
    assert "Earlier sessions" not in out
    assert "Full text of these replies" not in out
    assert "PROBE" not in out


def test_brief_command_hides_unattended(repo: Path) -> None:
    _stop(repo, "interactive", "Importer: CSV done, TSV next.", "1")
    _stop(repo, "script", "PROBE done.", "0")
    result = _run(["brief", "--cwd", str(repo)], b"", repo)
    assert result.returncode == 0
    out = result.stdout.decode("utf-8")
    assert "Importer: CSV done, TSV next." in out
    assert "PROBE done." not in out


def _title_of(lines: list[str], quote: str) -> str:
    """The title line of the record whose quoted reply is ``quote``."""
    position = lines.index(f"  > {quote}")
    title = lines[position - 1]
    assert title.startswith("[")
    return title


def test_show_lists_unattended_with_suffix(repo: Path) -> None:
    _stop(repo, "interactive", "Importer: CSV done, TSV next.", "1")
    _stop(repo, "script", "PROBE done.", "0")
    result = _run(["show", "--cwd", str(repo)], b"", repo)
    assert result.returncode == 0
    lines = result.stdout.decode("utf-8").splitlines()
    assert "  > Importer: CSV done, TSV next." in lines
    assert "  > PROBE done." in lines
    assert sum(line.startswith("[") and "] " in line for line in lines[1:]) == 2
    assert _title_of(lines, "PROBE done.").endswith(" · unattended")
    assert "unattended" not in _title_of(lines, "Importer: CSV done, TSV next.")


def test_show_index_counts_unattended(repo: Path, clock) -> None:
    git = read_git_state(repo)
    project = store.project_root(repo)
    for session_id, attended in (("older", None), ("newer", False)):
        store.write_state(
            project=project,
            session_id=session_id,
            branch=git.branch,
            head=git.head_sha,
            message=f"Reply of {session_id}.",
            attended=attended,
        )
    result = _run(["show", "--cwd", str(repo), "--index", "1"], b"", repo)
    assert result.returncode == 0
    lines = result.stdout.decode("utf-8").splitlines()
    assert lines[1].startswith("[1] ")
    assert lines[1].endswith(" · unattended")
    assert lines[2:] == ["  > Reply of newer."]


# --- the briefing, called directly --------------------------------------------------------


NO_KEY = object()


def _hand_written(project: Path, number: int, *, attended: object = NO_KEY) -> None:
    """A state file written with ``json.dumps``, ``number`` minutes after START."""
    directory = store.project_state_dir(project)
    directory.mkdir(parents=True, exist_ok=True)
    data: dict[str, object] = {
        "version": 1,
        "project": str(project),
        "session_id": f"s{number}",
        "written_at": (START + timedelta(minutes=number)).isoformat(timespec="seconds"),
        "branch": None,
        "head": None,
        "message": f"Reply number {number}.",
    }
    if attended is not NO_KEY:
        data["attended"] = attended
    (directory / f"{number:016x}.json").write_text(json.dumps(data), encoding="utf-8")


def test_more_line_counts_only_attended(tmp_path: Path) -> None:
    cwd = (tmp_path / "plain").resolve()
    cwd.mkdir()
    project = store.project_root(cwd)
    for number in range(4):  # attended, oldest
        _hand_written(project, number)
    for number in range(4, 7):  # unattended, newest
        _hand_written(project, number, attended=False)
    out = build_briefing(cwd, now=NOW)
    for number in (3, 2, 1):
        assert f"  > Reply number {number}." in out
    for number in (0, 4, 5, 6):
        assert f"Reply number {number}." not in out
    assert sum(line.startswith("- ") for line in out.splitlines()) == 3
    assert "  … and 1 more" in out.splitlines()


def test_legacy_record_counts_as_attended(tmp_path: Path) -> None:
    cwd = (tmp_path / "plain").resolve()
    cwd.mkdir()
    _hand_written(store.project_root(cwd), 0)
    out = build_briefing(cwd, now=NOW)
    assert "Earlier sessions in this project" in out
    assert "  > Reply number 0." in out


@pytest.mark.parametrize("value", ["false", 0, None, True])
def test_only_boolean_false_is_unattended(tmp_path: Path, value: object) -> None:
    cwd = (tmp_path / "plain").resolve()
    cwd.mkdir()
    _hand_written(store.project_root(cwd), 0, attended=value)
    out = build_briefing(cwd, now=NOW)
    assert "  > Reply number 0." in out


def test_build_briefing_hides_unattended_from_write_state(repo: Path, clock) -> None:
    project = store.project_root(repo)
    _write(project, "interactive")
    _write(project, "script", attended=False)
    out = build_briefing(repo, now=NOW)
    assert "Reply of interactive." in out
    assert "Reply of script." not in out


# --- write_state ---------------------------------------------------------------------------


@pytest.mark.parametrize("attended", [True, None])
def test_write_state_adds_no_key_unless_false(
    tmp_path: Path, clock, attended: bool | None
) -> None:
    project = tmp_path / "project"
    path = _write(project, "a", attended=attended)
    assert set(json.loads(path.read_text(encoding="utf-8"))) == SEVEN_KEYS


# --- pruning --------------------------------------------------------------------------------


def test_prune_removes_unattended_first(tmp_path: Path, clock) -> None:
    project = tmp_path / "project"
    for number in range(4):
        _write(project, f"a{number}")
    _write(project, "u", attended=False)
    _write(project, "a4")
    assert _count(project) == 5
    assert not _exists(project, "u")
    assert all(_exists(project, f"a{number}") for number in range(5))
    assert all("attended" not in record for record in store.read_states(project))


def test_prune_oldest_unattended_first(tmp_path: Path, clock) -> None:
    project = tmp_path / "project"
    for number in range(5):
        _write(project, f"u{number}", attended=False)
    _write(project, "a")
    assert _count(project) == 5
    assert not _exists(project, "u0")
    assert all(_exists(project, f"u{number}") for number in range(1, 5))
    assert _exists(project, "a")


def test_prune_falls_back_to_oldest_attended(tmp_path: Path, clock) -> None:
    project = tmp_path / "project"
    for number in range(6):
        _write(project, f"a{number}")
    assert _count(project) == 5
    assert not _exists(project, "a0")
    assert all(_exists(project, f"a{number}") for number in range(1, 6))


def test_just_written_unattended_is_kept(tmp_path: Path, clock) -> None:
    project = tmp_path / "project"
    for number in range(5):
        _write(project, f"a{number}")
    _write(project, "u", attended=False)
    assert _count(project) == 5
    assert _exists(project, "u")
    assert not _exists(project, "a0")
    assert all(_exists(project, f"a{number}") for number in range(1, 5))


def test_prune_unusable_and_unattended_share_the_first_tier(tmp_path: Path, clock) -> None:
    project = tmp_path / "project"
    _write(project, "u", attended=False)  # usable, unattended, the oldest real time
    broken = store.project_state_dir(project) / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    for number in range(3):
        _write(project, f"a{number}")
    # Six files after the next write: the unusable one counts as the oldest of the first tier.
    _write(project, "a3")
    assert _count(project) == 5
    assert not broken.exists()
    assert _exists(project, "u")
    # One more: the unattended record goes before any attended one.
    _write(project, "a4")
    assert _count(project) == 5
    assert not _exists(project, "u")
    assert all(_exists(project, f"a{number}") for number in range(5))


# --- the conftest fixture -------------------------------------------------------------------


def test_conftest_clears_the_variable() -> None:
    """Meaningful only under ``CLAUDE_CODE_SESSION_ATTENDED=0 ./check``; a no-op otherwise."""
    assert VARIABLE not in os.environ
