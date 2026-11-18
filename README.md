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

Planned, not built yet:

- A SessionStart hook that injects the briefing.
- A handoff file written when a session ends or is compacted, replaced each time.
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

## Develop

One command decides whether a change is acceptable:

```bash
./check
```

It runs the project rules in `checks/rules.tsv`, then ruff and pytest. Tests build throwaway
git repositories; the repository never contains real session data.

## Licence

[MIT](LICENSE)
