"""The SessionStart hook, run through the real entry point in a subprocess."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

ENTRY = [sys.executable, "-m", "claude_handoff.cli"]


def _run(args: list[str], stdin: bytes, cwd: Path) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [*ENTRY, *args], input=stdin, capture_output=True, cwd=cwd, timeout=60, check=False
    )


def _hook(stdin: bytes, cwd: Path) -> subprocess.CompletedProcess[bytes]:
    return _run(["hook", "session-start"], stdin, cwd)


def _payload(**fields: object) -> bytes:
    return json.dumps(fields).encode("utf-8")


def test_hook_prints_same_text_as_brief(repo: Path, tmp_path: Path) -> None:
    stdin = _payload(
        session_id="abc", cwd=str(repo), hook_event_name="SessionStart", source="startup"
    )
    hook = _hook(stdin, tmp_path)
    brief = _run(["brief", "--cwd", str(repo)], b"", tmp_path)
    assert brief.returncode == 0
    assert hook.returncode == 0
    assert hook.stdout == brief.stdout
    assert b"Branch: main" in hook.stdout
    assert hook.stdout.endswith(b"\n")
    assert hook.stderr == b""


def test_hook_non_git_cwd_says_not_a_repo(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    result = _hook(_payload(cwd=str(plain)), tmp_path)
    assert result.returncode == 0
    assert b"not a git repository" in result.stdout


def test_hook_ignores_unknown_fields(repo: Path, tmp_path: Path) -> None:
    only_cwd = _hook(_payload(cwd=str(repo)), tmp_path)
    with_extras = _hook(
        _payload(
            session_id="abc",
            cwd=str(repo),
            hook_event_name="SessionStart",
            source="resume",
            transcript_path=str(tmp_path / "transcript.jsonl"),
            model="some-model",
            unexpected={"nested": [1, 2, 3]},
        ),
        tmp_path,
    )
    assert only_cwd.returncode == 0
    assert with_extras.returncode == 0
    assert b"Branch: main" in only_cwd.stdout
    assert with_extras.stdout == only_cwd.stdout


def test_hook_relative_cwd_resolves_against_working_directory(repo: Path) -> None:
    result = _hook(_payload(cwd="."), repo)
    expected = _run(["brief", "--cwd", str(repo)], b"", repo)
    assert result.returncode == 0
    assert result.stdout == expected.stdout


def _missing_dir(tmp_path: Path) -> bytes:
    return _payload(cwd=str(tmp_path / "does-not-exist"))


def _file_cwd(tmp_path: Path) -> bytes:
    target = tmp_path / "a-file.txt"
    target.write_text("x\n")
    return _payload(cwd=str(target))


BAD_INPUTS: dict[str, Callable[[Path], bytes]] = {
    "empty": lambda _: b"",
    "not-json": lambda _: b"{not json",
    "json-not-object": lambda _: b'["cwd", "."]',
    "no-cwd": lambda _: _payload(session_id="abc", hook_event_name="SessionStart"),
    "cwd-not-string": lambda _: _payload(cwd=42),
    "cwd-empty-string": lambda _: _payload(cwd=""),
    "cwd-missing-dir": _missing_dir,
    "cwd-is-file": _file_cwd,
}


@pytest.mark.parametrize("make_input", BAD_INPUTS.values(), ids=BAD_INPUTS.keys())
def test_hook_bad_input_is_silent(make_input: Callable[[Path], bytes], tmp_path: Path) -> None:
    result = _hook(make_input(tmp_path), tmp_path)
    assert result.returncode == 0
    assert result.stdout == b""
    assert result.stderr == b""


UNEXPECTED_INPUTS: dict[str, bytes] = {
    "invalid-utf8": b'{"cwd": "\xff\xfe"}',
    "nul-in-cwd": _payload(cwd="a\u0000b"),
    "deeply-nested-json": b"[" * 100_000,
}


@pytest.mark.parametrize("stdin", UNEXPECTED_INPUTS.values(), ids=UNEXPECTED_INPUTS.keys())
def test_hook_unexpected_input_is_silent(stdin: bytes, tmp_path: Path) -> None:
    result = _hook(stdin, tmp_path)
    assert result.returncode == 0
    assert result.stdout == b""
    assert result.stderr == b""
