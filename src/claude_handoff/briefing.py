"""Render a short briefing for a new session from derived state."""

from __future__ import annotations

from pathlib import Path

from .gitstate import GitState, read_git_state

# Hard ceiling for the whole briefing. A briefing that does not fit is cut, never grown.
MAX_CHARS = 2000
MAX_DIRTY_SHOWN = 8
TRUNCATION_MARK = "… (truncated)"


def _clip(line: str, width: int = 100) -> str:
    return line if len(line) <= width else line[: width - 1] + "…"


def render_git(state: GitState) -> list[str]:
    """Lines describing the git state. Facts only, phrased as statements."""
    if not state.is_repo:
        return ["Git: this directory is not a git repository."]

    lines = [f"Branch: {state.branch or '(detached HEAD)'}"]
    count = len(state.dirty_files)
    if count == 0:
        lines.append("Uncommitted files: none")
    else:
        lines.append(f"Uncommitted files: {count}")
        lines += [f"  {_clip(path)}" for path in state.dirty_files[:MAX_DIRTY_SHOWN]]
        if count > MAX_DIRTY_SHOWN:
            lines.append(f"  … and {count - MAX_DIRTY_SHOWN} more")
    if state.recent_commits:
        lines.append("Recent commits:")
        lines += [f"  {_clip(commit)}" for commit in state.recent_commits]
    else:
        lines.append("Recent commits: none yet")
    return lines


def fit(lines: list[str], max_chars: int = MAX_CHARS) -> str:
    """Join lines, dropping from the end until the text fits in ``max_chars``."""
    text = "\n".join(lines)
    if len(text) <= max_chars:
        return text
    kept: list[str] = []
    used = len(TRUNCATION_MARK)
    for line in lines:
        if used + len(line) + 1 > max_chars:
            break
        kept.append(line)
        used += len(line) + 1
    return "\n".join([*kept, TRUNCATION_MARK])


def build_briefing(cwd: Path, max_chars: int = MAX_CHARS) -> str:
    """The briefing for ``cwd``: a header plus every section that has something to say."""
    lines = [f"[claude-handoff] State of {cwd.name}, read just now:"]
    lines += render_git(read_git_state(cwd))
    return fit(lines, max_chars)
