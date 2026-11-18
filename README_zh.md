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
  当时的分支和 HEAD 写进本机的一份交接文件，每轮回复结束时覆盖一次。交接文件已能写入，尚未
  在简报里显示。

计划中，尚未实现：

- 在简报里显示上一个会话的交接文件。
- 过期检查：交接比最新 commit 旧，或者提到的分支、文件已不存在时，标记为可能过期。
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
会加入新会话的上下文。输入里的其他字段一律忽略。

```bash
echo '{"cwd": "/path/to/project"}' | uv run claude-handoff hook session-start
```

hook 不会让会话启动失败：stdin 为空、不是合法 JSON、没有 `cwd`、或 `cwd` 不是一个存在的目录
时，什么都不输出，退出码 0。

### 作为 Stop hook

Claude Code 每结束一轮回复就运行一次 Stop hook，并在 stdin 里给出 `last_assistant_message`。
`hook stop` 把这条回复、会话 id、分支和 HEAD 的完整 sha 写进该项目的交接文件，替换上一份。
项目以 `cwd` 所在 git 仓库的根目录为准；不在 git 仓库里时就是 `cwd` 本身。压缩不会触发 Stop
hook，所以压缩时不写入。

```bash
echo '{"cwd": "/path/to/project", "last_assistant_message": "Finished the parser."}' \
  | uv run claude-handoff hook stop
```

交接文件放在项目目录之外，不会出现在 `git status` 里，也不会被误提交。状态目录按以下顺序取第
一个可用的：

1. 环境变量 `CLAUDE_HANDOFF_STATE_DIR` 有值时用它；
2. `XDG_STATE_HOME` 有值时用 `$XDG_STATE_HOME/claude-handoff`；
3. 否则用 `~/.local/state/claude-handoff`。

每个项目在其中有一个文件，文件名是项目绝对路径的 sha256 十六进制前 16 位。目录以权限 `0700`
创建，文件权限为 `0600`。超过 4000 个字符的回复保存前 3999 个字符加 `…`。

hook 什么都不输出，退出码总是 0。输入不是 JSON 对象、`cwd` 不是一个存在的目录、或
`last_assistant_message` 缺失或只有空白时，不写入任何东西，已有的交接文件保持不变。

## 开发

一条命令决定改动能不能接受：

```bash
./check
```

它先跑 `checks/rules.tsv` 里的项目规则，再跑 ruff 和 pytest。测试用临时生成的 git 仓库，
仓库里不放任何真实的会话数据。

## 许可证

[MIT](LICENSE)
