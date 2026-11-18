from pathlib import Path

from claude_handoff.gitstate import read_git_state


def test_not_a_repo(tmp_path: Path) -> None:
    state = read_git_state(tmp_path)
    assert state.is_repo is False
    assert state.branch is None
    assert state.dirty_files == ()


def test_clean_repo(repo: Path) -> None:
    state = read_git_state(repo)
    assert state.is_repo is True
    assert state.branch == "main"
    assert state.dirty_files == ()
    assert len(state.recent_commits) == 1
    assert state.recent_commits[0].endswith("Add a")
    assert state.last_commit_iso is not None


def test_dirty_files_listed(repo: Path) -> None:
    (repo / "a.txt").write_text("two\n")
    (repo / "new file.txt").write_text("x\n")
    state = read_git_state(repo)
    assert sorted(state.dirty_files) == ["a.txt", "new file.txt"]


def test_renamed_file_listed_once_under_new_name(repo: Path, run_git) -> None:
    run_git(repo, "mv", "a.txt", "b.txt")
    assert read_git_state(repo).dirty_files == ("b.txt",)


def test_recent_commits_capped_and_newest_first(repo: Path, run_git) -> None:
    for i in range(7):
        (repo / "a.txt").write_text(f"{i}\n")
        run_git(repo, "commit", "-am", f"Change {i}")
    state = read_git_state(repo, max_commits=5)
    assert len(state.recent_commits) == 5
    assert state.recent_commits[0].endswith("Change 6")


def test_detached_head_has_no_branch(repo: Path, run_git) -> None:
    run_git(repo, "checkout", "--detach")
    assert read_git_state(repo).branch is None


def test_repo_without_commits(tmp_path: Path, run_git) -> None:
    run_git(tmp_path, "init", "-b", "main")
    state = read_git_state(tmp_path)
    assert state.is_repo is True
    assert state.recent_commits == ()
    assert state.last_commit_iso is None
