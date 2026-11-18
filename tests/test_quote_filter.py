"""Quoting earlier replies: fenced code blocks and ``>`` lines are left out of the excerpt.

The autouse fixture in conftest.py points the state directory under tmp_path, so the
subprocess runs below inherit it through ``os.environ``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from claude_handoff.briefing import render_sessions
from claude_handoff.gitstate import GitState

T0 = datetime(2026, 11, 18, 12, 0, 0, tzinfo=UTC)
NOT_GIT = GitState(is_repo=False)
PREFIX = "  > "
FENCE = "```"


def _message(*lines: str) -> str:
    return "\n".join(lines)


EXAMPLE = _message(
    "Done: the importer handles CSV now.",
    "",
    "Example output:",
    "",
    FENCE,
    "Earlier sessions in this project:",
    "- just now · main",
    "  > an old quoted reply",
    FENCE,
    "",
    "> quoted from the issue: must support TSV",
    "",
    "Next: add TSV support.",
)


def _record(message: object) -> dict[str, Any]:
    return {"written_at": T0.isoformat(), "branch": None, "head": None, "message": message}


def _quoted_lines(message: str, tmp_path: Path) -> list[str]:
    """The quoted lines of the only record, prefixes removed."""
    lines = render_sessions([_record(message)], NOT_GIT, tmp_path, T0)
    assert lines[1] == "- just now"
    body = lines[2:]
    assert all(line.startswith(PREFIX) for line in body)
    return [line[len(PREFIX) :] for line in body]


def test_fenced_block_is_dropped(tmp_path: Path) -> None:
    assert _quoted_lines(EXAMPLE, tmp_path) == [
        "Done: the importer handles CSV now.",
        "Example output:",
        "Next: add TSV support.",
    ]


def test_tilde_fence_is_dropped(tmp_path: Path) -> None:
    message = _message("before", "~~~", "inside", FENCE, "still inside", "~~~", "after")
    assert _quoted_lines(message, tmp_path) == ["before", "after"]


def test_fence_with_language_tag(tmp_path: Path) -> None:
    message = _message("before", FENCE + "python", "print('hi')", FENCE, "after")
    assert _quoted_lines(message, tmp_path) == ["before", "after"]


def test_unclosed_fence_drops_to_end(tmp_path: Path) -> None:
    message = _message("kept one", "kept two", FENCE + "sh", "dropped", "", "also dropped")
    assert _quoted_lines(message, tmp_path) == ["kept one", "kept two"]


def test_indented_fence_and_quote_lines(tmp_path: Path) -> None:
    message = _message(
        "intro",
        "  indented prose",
        "    " + FENCE,
        "\tcode",
        "\t" + FENCE,
        " \t> quoted",
        "\t~~~",
        "x",
        "  ~~~",
        "end",
    )
    assert _quoted_lines(message, tmp_path) == ["intro", "  indented prose", "end"]


def test_blockquote_lines_are_dropped(tmp_path: Path) -> None:
    message = _message("first", "> quoted", ">also quoted", "a > b", "last")
    assert _quoted_lines(message, tmp_path) == ["first", "a > b", "last"]


def test_falls_back_when_nothing_is_left(tmp_path: Path) -> None:
    message = _message(FENCE, "only code", "", "> inside", FENCE)
    assert _quoted_lines(message, tmp_path) == [FENCE, "only code", "> inside", FENCE]


def test_only_quote_lines_fall_back(tmp_path: Path) -> None:
    message = _message("> one", "", "> two")
    assert _quoted_lines(message, tmp_path) == ["> one", "> two"]


def test_limit_applies_after_filtering(tmp_path: Path) -> None:
    code = _message(*["c" * 99] * 5)
    prose = _message(*["p" * 99] * 7)
    message = _message(FENCE, code, FENCE, prose)
    quoted = "\n".join(_quoted_lines(message, tmp_path))
    assert len(quoted) == 600
    assert quoted.endswith("…")
    assert "c" not in quoted
    assert quoted == prose[:599] + "…"


def test_inline_code_at_line_start_is_not_a_fence(tmp_path: Path) -> None:
    inline = FENCE + "cmd" + FENCE + " runs it"
    message = _message("intro", inline, "next line", "last")
    assert _quoted_lines(message, tmp_path) == ["intro", inline, "next line", "last"]


def test_second_fence_pair_handled(tmp_path: Path) -> None:
    message = _message("one", FENCE, "code a", FENCE, "middle", "~~~", "code b", "~~~", "two")
    assert _quoted_lines(message, tmp_path) == ["one", "middle", "two"]


def test_older_sessions_are_filtered_too(tmp_path: Path) -> None:
    lines = render_sessions([_record("newest"), _record(EXAMPLE)], NOT_GIT, tmp_path, T0)
    assert lines[3:] == [
        "- just now",
        PREFIX + "Done: the importer handles CSV now.",
        PREFIX + "Example output:",
        PREFIX + "Next: add TSV support.",
    ]


# --- through the real entry point -------------------------------------------------------


def _run(args: list[str], payload: dict[str, str], cwd: Path) -> str:
    result = subprocess.run(
        [sys.executable, "-m", "claude_handoff.cli", *args],
        input=json.dumps(payload).encode("utf-8"),
        capture_output=True,
        cwd=cwd,
        env={**os.environ},
        timeout=60,
        check=False,
    )
    assert result.returncode == 0
    return result.stdout.decode("utf-8")


def test_session_start_filters_quote(repo: Path) -> None:
    stop = {"session_id": "A", "cwd": str(repo), "last_assistant_message": EXAMPLE}
    _run(["hook", "stop"], stop, repo)
    start = {"session_id": "B", "cwd": str(repo), "source": "startup"}
    out = _run(["hook", "session-start"], start, repo)
    assert "  > Next: add TSV support." in out
    assert "  > Done: the importer handles CSV now." in out
    assert "an old quoted reply" not in out
    assert "must support TSV" not in out
