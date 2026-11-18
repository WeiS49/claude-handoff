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

计划中，尚未实现：

- 在 SessionStart hook 里注入简报。
- 会话结束或压缩时写一份交接文件，每次覆盖。
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

## 开发

一条命令决定改动能不能接受：

```bash
./check
```

它先跑 `checks/rules.tsv` 里的项目规则，再跑 ruff 和 pytest。测试用临时生成的 git 仓库，
仓库里不放任何真实的会话数据。
