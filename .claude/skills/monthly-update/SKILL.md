---
name: monthly-update
description: HackerShelf 月度更新（D47）。拉 HN 增量、重建论文目录，用子 agent 跑增量的立场标注、复核、卡片和中文说明，然后构建公开站，等用户确认后再推送。用户说“月度更新”“更新目录”“更新主书架”时使用。
---

# 月度更新（D47）

每月初跑一次。所有命令都在仓库根目录运行。整个流程不提交、不推送；最后推送公开站之前，必须等用户确认。

## 1. 开始

```
uv run --project pipeline hs monthly start
```

- 依次做这几件事：
  1. 备份当前产物。
  2. 刷新数据，不调用模型：拉 HN 增量、重建 links、抽提及、算阈值、补元数据和 OpenAlex、算 embedding、给新论文归类、算相关论文。
  3. 准备第一个模型任务。
- 大约要 10–30 分钟，大头是 build-db。用 Bash 的 `run_in_background` 跑，跑完再看输出。
- 上一次没做完时，它会拒绝开始，提示改用 `uv run --project pipeline hs monthly next` 接着做。
- 中途失败：看报错，修好后运行 `hs monthly next`，会从断点接着跑。

## 2. 循环：派子 agent，再运行 next

输出里出现“待跑子 agent：<task>（模型 X …）”时：

1. 每个没跑完的批次派一个子 agent：用 Agent 工具，subagent_type 选 general-purpose，model 用输出里写的 haiku 或 sonnet。可以并行，一波最多 13 个。给子 agent 的说明如下，把 <task> 和 <批> 换成实际的：
   > 读 data/llm/<task>/prompt.md，按里面的要求处理 data/llm/<task>/in/<批>.md 里的每一条，用 Write 工具把结果写到 data/llm/<task>/out/<批>.jsonl：每条一行 JSON，id 原样照抄，条数和输入一样。只写这一个文件，不要运行命令，也不要改别的文件。写完回复一行：写了几条。
2. 每个子 agent 回来后，记一下用量。token 数和耗时取 Agent 结果里的数字，拿不到就省略这两个参数：
   `uv run --project pipeline hs monthly log-run --task <task> --batch <批> --model <haiku|sonnet> --tokens <N> --ms <N>`
3. 全部回来后，运行 `uv run --project pipeline hs monthly next`。它会检查每一批的输出，缺条或 JSON 坏了的批次会重新列出来，重派那几批就行。

顺序是固定的：立场（Haiku）→ 复核（Sonnet）→ 卡片（Sonnet）→ catalog → 中文说明（Sonnet）→ catalog。没有要处理的阶段会自动跳过。

## 2b. 开源书：等着的书
- `pipeline/books_licenses.jsonl` 里 status 是 hold 的书（现在是 Real World Haskell），用 curl 看原站能不能打开（http 和 https 都试）。能打开了就告诉用户，等用户定要不要上架；不要自己改 status。

## 3. 量的闸门

- 正常一个月的量：立场 120–250 条，卡片约 20 张，中文说明几十到一两百条。
- 如果某个任务超过约 1,000 条（比如隔了几个月才更新，或者规则改过），先停下来，报条数和预计耗时，等用户确认后再派子 agent。这是 CLAUDE.md 里“大批量标注先试跑”的要求。

## 4. 结束

1. `next` 输出“月度更新 <tag> 完成”之后，看 `reports/monthly/<tag>.md`：新进主书架的论文、前后的数字、模型用量。再抽几张新卡片看看质量。
2. 构建公开站：运行 `deploy/public/build.sh`（设了 `HS_PUBLIC_REPO` 时会放进 Pages 仓库的工作区并打印产物清单），把清单和小结一起给用户看。
3. 用户确认后再发布：在 Pages 仓库里提交、推送，再看 Actions 的发布结果。
4. 代码改动照常提交，`data/` 不进 git。推送之前先问用户。

## 出问题时

- 要换回开始前的版本：备份在 `data/backups/monthly-<tag>/`，按相对路径拷回 `data/build/`，再运行一次 `deploy/public/build.sh`。
- 状态记在 `data/build/monthly.json`，用 `uv run --project pipeline hs monthly status` 看进度。
- Pages 仓库 60 天没有提交，GitHub 会停掉定时任务。每月推送一次就不会停；真停了就运行 `gh workflow enable Pages --repo <你的 Pages 仓库>`。
