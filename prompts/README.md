# Prompts / 提示词

These are the exact instructions the Claude Code sub-agents read: each file is written out from a string constant in `pipeline/hs/steps/` and matches the `prompt.md` a batch gets, apart from the one-line source comment at the top. The prompts are in Chinese because the site is. They are licensed CC BY 4.0, both here and as the constants in the code.

这里是子 agent 读到的原文：每个文件都由 `pipeline/hs/steps/` 里的字符串常量写出，和批次目录里的 `prompt.md` 一字不差（只多开头一行来源注释）。许可证是 CC BY 4.0，代码里的这些常量同样适用。

| 文件 | 做什么 | 模型 | 谁准备批次 |
|---|---|---|---|
| [paper-stance-v3.md](paper-stance-v3.md) | 一条“评论 × 论文”的立场：strong_rec / rec / reference / joke / critical，加置信度、原话摘录、一句英文 why | Haiku 全量，Sonnet 复核 | `papers stance-inc-prepare`、`stance-inc-review-prepare`、`stance-review-prepare` |
| [paper-card-v2.md](paper-card-v2.md) | 主书架每篇一张卡片：中文标题、一行摘要、导读、HN 为什么提它、类型、难度、前置知识、时效、阅读时长 | Sonnet | `papers cards-prepare --all-core`、`cards-inc-prepare` |
| [paper-why-zh.md](paper-why-zh.md) | 详情页每条 HN 原话下面的一句中文说明 | Sonnet | `papers why-zh-prepare`、`why-zh-inc-prepare` |
| [paper-learning-path.md](paper-learning-path.md) | 从“参考文献 ∩ 书架”里挑 3–8 篇，排出读目标论文之前的顺序，每步写为什么读、读哪部分 | Sonnet | `study paths-prepare` |
| [book-stance-v3.md](book-stance-v3.md) | 一条“评论 × 书”的立场，另外判断链接是不是真在说这本书、是不是作者本人在贴自己的书 | Sonnet | `books label-prepare`、`label-inc` |
| [book-card.md](book-card.md) | 每本书的卡片：中文书名、导读、HN 为什么推荐、怎么读（2–4 条）、适合谁、前置知识、难度、小时数、书架分类 | Sonnet | `books cards-prepare` |
| [book-why-zh.md](book-why-zh.md) | 书的每条 HN 原话下面的一句中文说明 | Sonnet | `books why-zh-prepare` |

命令都在仓库根目录运行，前面加 `uv run --project pipeline python -m hs.steps.`（例如 `uv run --project pipeline python -m hs.steps.papers stance-inc-prepare --tag 20261201`）。

## 一个批次长什么样

```
data/llm/<任务>/
  prompt.md        上面某一份提示词
  manifest.json    条数、批大小、输出字段、该用的模型
  in/0001.md       给子 agent 读的这一批（Markdown，每条一节，长文本折行）
  in/0001.jsonl    同一批的 JSONL（合并时用它核对 id）
  out/0001.jsonl   子 agent 用 Write 工具写的输出：每条输入一行 JSON，id 原样照抄
  runs.jsonl       每批的模型、token、耗时（主会话记）
```

- 输入里的链接先换成占位符：这篇论文 `[PAPER]`、别的 arXiv 论文 `[OTHER_PAPER]`、这本书 `[BOOK]`、其他 `[LINK]`；评论超过 2,000 字时保留开头和占位符附近的一段。
- 合并只认输入里有的 id、合法的立场值；缺条或 JSON 坏了的批次算没跑完（`llm_batch.pending`），重派那一批就行。
- 同一条提及有多个任务的结果时，后面的覆盖前面的：样本 → 全量 → Sonnet 复核 → 每月增量（按日期）。

## 版本和一致率

- 论文立场：v1 → v2 → v3，每一版都在同样的 200 条随机样本上让 Haiku 和 Sonnet 各标一遍，比两个模型的一致率。
  v2 是 93.5%（五类）/ 95%（推荐与否）；v3 补了一条“明确让别人去读算 rec，只贴链接当论据算 reference”，到 97.0% / 99.0%。
- 书的立场：同样 200 条，v2 是 89.5% / 92.5%，“是不是在说这本书” 98%。书常被当成学东西的去处（“See [BOOK] for X”），推荐和引用更难分；
  v3 把“叫人去读、去学算 rec”和“作者本人贴自己的书一律算引用”写到最前面，全量直接用 Sonnet 标。
- 这些都是两个模型之间的一致率，不是和人工标注比。`papers stance-review-sheet` 会生成 50 条的人工核对表，填完用 `stance-review-score` 算一致率。
