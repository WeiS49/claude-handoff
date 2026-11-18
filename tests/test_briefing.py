from pathlib import Path

from claude_handoff.briefing import MAX_CHARS, TRUNCATION_MARK, build_briefing, fit, render_git
from claude_handoff.cli import main
from claude_handoff.gitstate import GitState


def test_non_repo_is_stated_plainly(tmp_path: Path) -> None:
    text = build_briefing(tmp_path)
    assert "not a git repository" in text


def test_clean_repo_briefing(repo: Path) -> None:
    text = build_briefing(repo)
    assert "Branch: main" in text
    assert "Uncommitted files: none" in text
    assert "Add a" in text


def test_dirty_files_are_counted_and_capped() -> None:
    state = GitState(is_repo=True, branch="main", dirty_files=tuple(f"f{i}" for i in range(30)))
    lines = render_git(state)
    assert "Uncommitted files: 30" in lines
    assert "  … and 22 more" in lines
    assert "  f8" not in lines


def test_detached_head_is_named() -> None:
    assert "Branch: (detached HEAD)" in render_git(GitState(is_repo=True))


def test_fit_keeps_short_text_whole() -> None:
    assert fit(["a", "b"], 100) == "a\nb"


def test_fit_never_exceeds_the_ceiling() -> None:
    lines = [f"line {i} " + "x" * 50 for i in range(200)]
    for ceiling in (60, 200, 2000):
        text = fit(lines, ceiling)
        assert len(text) <= ceiling
        assert text.endswith(TRUNCATION_MARK)


def test_briefing_respects_default_ceiling(repo: Path) -> None:
    for i in range(300):
        (repo / f"file_{i:03d}_{'y' * 80}.txt").write_text("x")
    assert len(build_briefing(repo)) <= MAX_CHARS


def test_cli_brief_prints_briefing(repo: Path, capsys) -> None:
    assert main(["brief", "--cwd", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "Branch: main" in out
