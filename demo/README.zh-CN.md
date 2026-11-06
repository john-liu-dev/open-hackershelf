# 一个月 demo

[English](README.md)

只用一个月的 Hacker News 数据，2023 年 3 月（GPT-4 发布的那个月），把 HackerShelf 的整条流程跑一遍：下载 → 提及 → 门槛 → 立场标注 → 卡片 → 中文说明 → 目录 → 静态站。模型任务和完整流程一样，由 Claude Code 子 agent 来做。

## 要准备什么

- [uv](https://docs.astral.sh/uv/)（会自己装 Python 3.12）、Node 24 和 npm、能跑子 agent 的 [Claude Code](https://claude.com/claude-code)。
- 约 1 GB 磁盘：这个月的数据、本地数据库和 `web/node_modules`。
- 可选：Google Chrome，只用来生成分享图；没有就跳过，页面不受影响。
- 不需要任何 API key。在 `.env` 里写上 `CONTACT_EMAIL`，arXiv 请求的间隔会减半。

## 在 Claude Code 里跑

```bash
git clone https://github.com/john-liu-dev/open-hackershelf
cd open-hackershelf
claude
```

然后说 **跑 demo**。[demo skill](../.claude/skills/demo/SKILL.md) 会按下面的步骤走，每个模型任务每批派一个子 agent，最后停在本机预览。不提交，也不发布。

## 一步一步跑

```bash
demo/run.sh data      # 下载这个月、建库、抽提及、按门槛分档、查 arXiv 元数据
demo/run.sh stance    # 准备立场标注 → data/llm/stance_inc_demo/        （Haiku）
demo/run.sh review    # 低置信度复核 → data/llm/stance_inc_demo_review/ （Sonnet；可能没有要复核的）
demo/run.sh cards     # 卡片 → data/llm/cards_inc_demo/                 （Sonnet）
demo/run.sh why       # 先建一次目录，再准备中文说明 → data/llm/why_zh_inc_demo/（Sonnet）
demo/run.sh catalog   # 合并全部结果 → data/build/catalog.db
demo/run.sh site      # npm ci，静态导出到 web/.next-public，检查私有内容
node deploy/public/serve.mjs     # 预览：http://localhost:4173/shelf/
demo/run.sh status    # 每个模型任务还剩几批
```

`stance`、`review`、`cards`、`why` 这四步之后，要先让子 agent 跑完批次，再做下一步：在 Claude Code 里每个 `in/NNNN.md` 派一个子 agent，说明见 [skill](../.claude/skills/demo/SKILL.md)。`demo/run.sh status` 显示还剩什么；缺条或 JSON 坏了的批次，重跑那一批就行。

## 和完整流程的区别

- **门槛。** 一个月的数据凑不出“3 个不同的月份”，所以 [`config.toml`](config.toml) 只把月份门槛降到 1：主书架 3 个人，候选层 2 个人。它通过 `HS_CONFIG=demo/config.toml`（`run.sh` 会设好）叠在 `pipeline/config.toml` 上。
- **跳过的：** OpenAlex（被引数和参考文献，所以没有学习路径；它要一个免费 key）、embedding（所以没有主题树和相关论文）、开源书、每日新鲜书架。网站都能应付：没有按主题的书架，没有学习路径，图书书架是空的。关于页仍然写的是完整规则。
- 准备批次用的是月度更新那组命令（`stance-inc-prepare` 等），tag 是 `demo`：构建是空的时候，主书架上的所有提及都算新的。

## 实测一次

2026-11-06 在这个仓库的干净副本上跑了一次，当时网速很慢：

| 步骤 | 耗时 | 结果 |
|---|---|---|
| `data` | 14 分 8 秒，其中 13.5 分钟是下载 107 MB（0.13 MB/s） | 407,941 条 HN 帖子和评论、636 条 arXiv 提及；主书架 22 篇（3 人以上），候选层 35 篇；57 篇的 arXiv 元数据一次请求查完 |
| `stance` | 2 个 Haiku 子 agent 并行，2.4 分钟 | 标了 119 条评论 |
| `review` | 1 个 Sonnet 子 agent，28 秒 | 复核 17 条（低置信度 15、“让人去读”线索 2），改了 5 条 |
| `cards` | 3 个 Sonnet 子 agent 并行，54 秒 | 22 张卡片 |
| `why` | 2 个 Sonnet 子 agent 并行，48 秒 | 116 条中文说明（中位数 29 字，7 条超过要求的 40 字） |
| `catalog` 和 `site` | 约 1 分钟，含 `npm ci` | 360 个文件、15.8 MB、23 张分享图 |

- 从头到尾约 24 分钟。四个模型步骤的墙钟是 9 分钟，含步骤之间的时间。
- 共 60 万 token：Haiku 21.2 万（立场），Sonnet 39.1 万（复核、卡片、中文说明）。
- 最后的立场：reference 102、rec 13、strong_rec 2、critical 1、joke 1。主书架 22 篇里 8 篇算“被推荐”，其余写“被提及”。
- 排在前面的：Sparks of Artificial General Intelligence（14 人）、GPTQ（10 人）、GPT-4 Technical Report（9 人）、Toolformer（7 人）、Language Is Not All You Need（7 人）、LoRA（6 人）。
- 没有主题树，封面都是同一种灰色。
- npm 11 会提示 better-sqlite3、esbuild、fsevents 的安装脚本没有运行。这三个包都自带预编译文件，不用再做什么。

## 清理

demo 写的东西都在 `data/`、`pipeline/.venv/`、`web/node_modules/`、`web/.next/` 和 `web/.next-public/` 里（实测共约 1 GB），删掉就能从头再来。
