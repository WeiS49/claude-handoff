# 本仓库的规则

<!-- dev-repo-init:begin (managed block; edit outside it) -->
## 检查与交付

- 交付前运行 `./check`，必须通过。CI 跑的是同一条命令。
- 项目规则在 `checks/rules.tsv`，违反时报错信息会告诉你怎么改。改代码，不要改规则。
- 不要为了通过检查而修改 `check`、`checks/`、`.github/` 或删改测试；也不要加 `noqa`、`type: ignore`、`skip` 之类的豁免。确实需要时停下来，在 issue 里说明原因。
- 改了行为就补测试。能运行的入口要有真实运行它的测试。
- 只走新分支，不直接推默认分支；不改历史。
- 不提交密钥；不加「由 AI 生成」之类的署名。
- 最后用简体中文总结：改了哪些文件、实际跑的命令和输出、没做的部分。
<!-- dev-repo-init:end -->
