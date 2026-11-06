---
name: demo
description: HackerShelf 的一个月 demo：用 2023-03 一个月的 HN 数据把整条流程跑一遍（下载 → 提及 → 门槛 → 立场标注 → 卡片 → 中文说明 → catalog → 静态站），模型任务用子 agent 跑。用户说“跑 demo”“run the demo”时使用。
---

# 一个月 demo

所有命令都在仓库根目录运行。整个流程不提交、不推送。说明见 demo/README.md。

## 1. 数据（不调模型）

```
demo/run.sh data
```

- 下载 2023-03 一个月的 HN 存档（约 110 MB，Hugging Face），建本地 DuckDB，抽 arXiv 提及，按 demo/config.toml 的门槛分档（主书架 3 人、候选层 2 人，月份门槛降到 1），再查 arXiv 元数据。
- 大约 5–10 分钟，用 Bash 的 `run_in_background` 跑，跑完再看输出。

## 2. 模型任务：四步，每步“准备 → 派子 agent → 看状态”

按这个顺序：

| 步骤 | 准备 | 任务目录 | 模型 |
|---|---|---|---|
| 立场 | `demo/run.sh stance` | `data/llm/stance_inc_demo/` | haiku |
| 复核 | `demo/run.sh review` | `data/llm/stance_inc_demo_review/` | sonnet |
| 卡片 | `demo/run.sh cards` | `data/llm/cards_inc_demo/` | sonnet |
| 中文说明 | `demo/run.sh why` | `data/llm/why_zh_inc_demo/` | sonnet |

准备的输出说“不建任务”时，这一步没有要处理的，直接做下一步。

每一步准备好以后：

1. 每个批次（`in/` 下的 `NNNN.jsonl`）派一个子 agent：用 Agent 工具，subagent_type 选 general-purpose，model 用上表的 haiku 或 sonnet，可以并行。给子 agent 的说明如下，把 <task> 和 <批> 换成实际的：
   > 读 data/llm/<task>/prompt.md，按里面的要求处理 data/llm/<task>/in/<批>.md 里的每一条，用 Write 工具把结果写到 data/llm/<task>/out/<批>.jsonl：每条一行 JSON，id 原样照抄，条数和输入一样。只写这一个文件，不要运行命令，也不要改别的文件。写完回复一行：写了几条。
2. 子 agent 都回来后，记一下用量（token 数和耗时取 Agent 结果里的数字，拿不到就省略）：
   `uv run --project pipeline hs monthly log-run --task <task> --batch <批> --model <haiku|sonnet> --tokens <N> --ms <N>`
3. 运行 `demo/run.sh status`。缺条或 JSON 坏了的批次会显示“没跑完”，只重派那几批。

## 3. 收尾

1. `demo/run.sh catalog`：合并立场、卡片和中文说明，写 `data/build/catalog.db` 和 `search-index.json`。
2. `demo/run.sh site`：装 web 的依赖、构建静态站并检查。分享图要本机装了 Chrome，没有就跳过，不影响页面。
3. 预览：`node deploy/public/serve.mjs`（用 `run_in_background`），打开 http://localhost:4173/shelf/ 。看完把预览服务停掉。
4. 给用户报：主书架几篇、候选层几篇、每个模型任务的条数和 token、首页上排在前面的几篇。

## 量的闸门

- demo 一共两三百条（实测：立场 119、复核 17、卡片 22、中文说明 116），不会碰到闸门。改了 demo/config.toml（比如换成更热闹的月份、或者拉多个月）以后，某个任务超过约 1,000 条，先停下来，报条数和预计耗时，等用户确认后再派子 agent。
