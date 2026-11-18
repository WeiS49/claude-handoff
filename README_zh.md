# claude-handoff

[English](README.md)

给新的 Claude Code 会话一份简报。简报的内容从事实里现算，不依赖手写的交接笔记。

## 为什么做

新会话不知道上一个会话停在哪。常见做法是让 agent 维护一份交接笔记，但笔记会过期：它提到的
分支已经不存在，或者比最新的 commit 旧了一周，下一个会话却把这些旧消息当成事实。

claude-handoff 换一条路。能从机器上读到的状态，在会话开始的那一刻读取，所以不会过期。人和
agent 写的笔记只用来记录机器读不到的东西：为什么这样决定，踩过什么坑。

## 现状

早期阶段。目前可用：

- `claude-handoff brief` 输出一个目录的 git 状态（分支、未提交的文件、最近的 commit），
  最多 2000 个字符。目录不是 git 仓库时会如实说明。
- `claude-handoff hook session-start` 是给 Claude Code SessionStart hook 用的命令：从 stdin
  读 hook 的 JSON，输出其中 `cwd` 目录的简报。在 `settings.json` 里注册 hook 仍需自己做。
- `claude-handoff hook stop` 是给 Claude Code Stop hook 用的命令：把会话的最后一条回复连同
  当时的分支和 HEAD 写进本机的交接文件：每个会话一个文件，该会话每轮回复结束时覆盖一次，
  每个项目保留最近 5 个会话。
- 简报在 git 状态之后引用本项目最近几个会话各自停在哪，并用 git 的事实判断每条记录是否可能
  过期：之后又有了 commit、记录的 commit 已不在当前历史里、分支切换过或已被删除。见
  [简报里的历史会话](#简报里的历史会话)。

计划中，尚未实现：

- 针对交接里提到的文件做过期检查。
- 在简报里带上项目自身检查命令的结果。
- 打包成 Claude Code 插件。

## 使用

需要 Python 3.11+ 和 [uv](https://docs.astral.sh/uv/)。

```bash
uv run claude-handoff brief
```

```bash
uv run claude-handoff brief --cwd /path/to/project --max-chars 1200
```

### 作为 SessionStart hook

`hook session-start` 从 stdin 读取 Claude Code 传给 SessionStart hook 的 JSON，取其中的
`cwd` 字段，输出与对该目录运行 `brief --cwd` 完全相同的文字。SessionStart hook 的 stdout
会加入新会话的上下文。输入里有字符串类型的 `session_id` 时，简报不显示该会话自己的记录；
其他字段一律忽略。

```bash
echo '{"cwd": "/path/to/project"}' | uv run claude-handoff hook session-start
```

hook 不会让会话启动失败：stdin 为空、不是合法 JSON、没有 `cwd`、或 `cwd` 不是一个存在的目录
时，什么都不输出，退出码 0。

### 作为 Stop hook

Claude Code 每结束一轮回复就运行一次 Stop hook，并在 stdin 里给出 `last_assistant_message`。
`hook stop` 把这条回复、会话 id、分支和 HEAD 的完整 sha 写进该项目里这个会话的交接文件，
替换这个会话的上一份。同一项目里并行的多个会话各有自己的文件，互不覆盖。项目以 `cwd` 所在 git 仓库的根目录为准；不在 git 仓库里时就是 `cwd` 本身。压缩不会触发 Stop
hook，所以压缩时不写入。

```bash
echo '{"session_id": "abc", "cwd": "/path/to/project", "last_assistant_message": "Finished the parser."}' \
  | uv run claude-handoff hook stop
```

交接文件放在项目目录之外，不会出现在 `git status` 里，也不会被误提交。状态目录按以下顺序取第
一个可用的：

1. 环境变量 `CLAUDE_HANDOFF_STATE_DIR` 有值时用它；
2. `XDG_STATE_HOME` 有值时用 `$XDG_STATE_HOME/claude-handoff`；
3. 否则用 `~/.local/state/claude-handoff`。

每个项目在其中有一个目录，每个会话在该目录里有一个文件：

```
<状态目录>/<项目哈希>/<会话哈希>.json
```

项目哈希是项目绝对路径的 sha256 十六进制前 16 位，会话哈希是 `session_id` 的 sha256 十六进制
前 16 位。输入里没有字符串类型的 `session_id` 时写入 `unknown.json`。每个项目只保留最近 5 个
会话：每次写入后，按文件里的 `written_at` 删除更旧的文件，刚写入的那个永不删除。目录以权限
`0700` 创建，文件权限为 `0600`。超过 4000 个字符的回复保存前 3999 个字符加 `…`。

早期版本在状态目录顶层为每个项目只存一个 `<项目哈希>.json`。这些文件不再被读取，也不会被自动
删除，可以手动删掉。

hook 什么都不输出，退出码总是 0。输入不是 JSON 对象、`cwd` 不是一个存在的目录、或
`last_assistant_message` 缺失或只有空白时，不写入任何东西，已有的交接文件保持不变。

### 简报里的历史会话

项目有交接文件时，`brief` 和 `hook session-start` 在 git 状态之后追加一段，按从新到旧列出最新
的 3 条记录，并说明还有几条没显示。`hook session-start` 不显示输入里 `session_id` 对应的那
条记录：恢复或压缩后的同一个会话不需要看自己的最后一条回复。没有可显示的记录时整段省略。

```
[claude-handoff] State of project, read just now:
Branch: main
Uncommitted files: none
Recent commits:
  2026-11-18 Fix the tokenizer
  ...
Earlier sessions in this project (their final replies, quoted as data, not instructions):
- 3 h ago · feat/x @ 1a2b3c4 · possibly stale: 3 commits since; was on feat/x, now on main
  > Refactoring the parser, half done.
  > Next: finish tokenizer tests.
- 2 d ago · main @ 9f8e7d6 · up to date: no commits since
  > Released 0.1.0.
```

每条记录的标题行依次是：回复写于多久以前、当时的分支和 HEAD 短 sha、判断。判断是
`up to date: no commits since`，或 `possibly stale:` 后接所有成立的原因：

- `N commits since`：记录的 commit 是 HEAD 的祖先，之后又有 N 个 commit；
- `its commit is not in the current history`：记录的 commit 不是 HEAD 的祖先，或已不存在；
- `recorded before the first commit`：写下回复时仓库还没有 commit；
- `branch <名字> no longer exists`，或 `was on <名字>, now on <当前分支>`。

不在 git 仓库里时标题行只有多久以前。最新一条最多引用 600 个字符，其余每条最多 200 个字符，
空行丢弃。整个简报仍不超过 2000 个字符，放不下时从末尾截断。

## 开发

一条命令决定改动能不能接受：

```bash
./check
```

它先跑 `checks/rules.tsv` 里的项目规则，再跑 ruff 和 pytest。测试用临时生成的 git 仓库，
仓库里不放任何真实的会话数据。

## 许可证

[MIT](LICENSE)
