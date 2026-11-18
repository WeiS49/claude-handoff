# claude-handoff

[中文说明](README_zh.md)

Briefings for a new Claude Code session, derived from ground truth instead of hand-kept notes.

## Why

A new session starts without knowing where the last one stopped. The usual fix is a handoff
note that the agent is supposed to keep current. In practice the note goes stale: it names a
branch that no longer exists, or stops a week before the latest commit, and the next session
is told old news as if it were fact.

claude-handoff takes the other route. Whatever can be read from the machine is read at the
moment the session starts, so it cannot be out of date. Notes written by people and agents
are kept for what the machine cannot know: why a decision was made and what went wrong.

## Status

Early. What works today:

- `claude-handoff brief` prints the git state of a directory (branch, uncommitted files,
  recent commits) in at most 2000 characters. A directory that is not a git repository is
  reported as such.
- `claude-handoff hook session-start` is the command for a Claude Code SessionStart hook. It
  reads the hook's JSON from stdin and prints the briefing for its `cwd`. Registering the
  hook in `settings.json` is still up to you.
- `claude-handoff hook stop` is the command for a Claude Code Stop hook. It saves the
  session's last reply, with the branch and HEAD at that moment, to a handoff file on this
  machine, replaced every time a reply ends. The file is written but not yet shown in the
  briefing.

Planned, not built yet:

- Showing the last session's handoff in the briefing.
- Staleness checks: a handoff that is older than the latest commit, or that names a branch
  or file that no longer exists, is marked as possibly stale.
- The result of the project's own check command in the briefing.
- Packaging as a Claude Code plugin.

## Use

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv run claude-handoff brief
```

```bash
uv run claude-handoff brief --cwd /path/to/project --max-chars 1200
```

### As a SessionStart hook

`hook session-start` reads the JSON that Claude Code passes to a SessionStart hook on stdin,
takes its `cwd` field and prints the same text as `brief --cwd` for that directory. Claude
Code adds a SessionStart hook's stdout to the new session's context. Other fields in the
input are ignored.

```bash
echo '{"cwd": "/path/to/project"}' | uv run claude-handoff hook session-start
```

The hook never makes session start fail: if stdin is empty or not valid JSON, or `cwd` is
missing or does not name an existing directory, it prints nothing and exits 0.

### As a Stop hook

Claude Code runs a Stop hook each time it finishes a reply and passes `last_assistant_message`
on stdin. `hook stop` saves that message, the session id, the branch and the full HEAD sha
to the handoff file of the project, replacing the previous one. The project is the root of
the git repository that contains `cwd`, or `cwd` itself outside git. Compaction does not run
a Stop hook, so nothing is written at compaction.

```bash
echo '{"cwd": "/path/to/project", "last_assistant_message": "Finished the parser."}' \
  | uv run claude-handoff hook stop
```

The handoff file is kept outside the project, so it never shows in `git status` and cannot be
committed by mistake. The state directory is the first of:

1. `$CLAUDE_HANDOFF_STATE_DIR`, if set;
2. `$XDG_STATE_HOME/claude-handoff`, if `XDG_STATE_HOME` is set;
3. `~/.local/state/claude-handoff`.

Each project has one file there, named after the first 16 hex digits of the sha256 of the
project's absolute path. The directory is created with mode `0700` and the file with `0600`.
A reply longer than 4000 characters is cut to 3999 characters plus `…`.

The hook prints nothing and always exits 0. If the input is not a JSON object, `cwd` does not
name an existing directory, or `last_assistant_message` is missing or blank, nothing is
written and an existing handoff file is left as it was.

## Develop

One command decides whether a change is acceptable:

```bash
./check
```

It runs the project rules in `checks/rules.tsv`, then ruff and pytest. Tests build throwaway
git repositories; the repository never contains real session data.

## Licence

[MIT](LICENSE)
