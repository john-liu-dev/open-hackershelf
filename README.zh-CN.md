# HackerShelf

HackerShelf 是怎么做出来的：用 Claude Code 子 agent，给 Hacker News 上被反复推荐的论文和免费书排名。

**网站：<https://john-liu-dev.github.io/shelf/>** · [English](README.md)

[![HackerShelf 首页：一排书脊和长青榜](deploy/public/repo/screenshots/home.png)](https://john-liu-dev.github.io/shelf/)

HackerShelf 翻了 Hacker News 二十年的评论，留下被不同的人在不同月份反复推荐的 arXiv 论文和免费书：论文 1,800 篇、开源书 90 本，每篇配中文导读和 HN 原话（链回原评论）。网站是中文界面，标题保留英文原名。这个仓库放的是背后的方法：管线、提示词、网站代码和子 agent 批处理。不附带任何数据。

## 流程

### 1. HN 提及

- 数据是 2006 年 10 月以来 Hacker News 的全部帖子和评论，约 5,000 万条。2026-08-21 之前来自 Hugging Face 上的 [open-index/hacker-news](https://huggingface.co/datasets/open-index/hacker-news) 存档，之后存档停更，改用 [HN Algolia API](https://hn.algolia.com/api) 补。
- 一条**提及**：评论里链接到这篇论文，评论者自己写的文字不少于 100 个字符（链接和 `>` 引用不算）；或者论文本身被发成帖子。
- 各种写法的链接（arxiv.org 的 abs/pdf/html、ar5iv、alphaXiv、Hugging Face papers、`10.48550` 开头的 DOI）都归到同一个 arXiv 编号。按这个口径，至少有一条提及的 arXiv 论文共 26,947 篇；不限字数、所有链接和纯文本的 `arXiv:` 编号都算的话是 28,435 篇（数据截至 2026-11-01）。

### 2. 3 个人、3 个月

- 至少 3 个不同的人、在至少 3 个不同的月份提到过，进**主书架**。
- 2 个人、2 个月的进**候选层**：页面上列出来，但不标立场，一律写“被提及”。
- 只火一个月进不来，一直有人提的经典能进来。数据截至 2026-11-03：主书架 1,800 篇，候选层 2,785 篇。

### 3. 立场标注：先跑样本

- 子 agent 给主书架的每条评论标一个立场：`strong_rec`、`rec`、`reference`、`joke`、`critical`。只看对*这篇*论文的态度，结合帖子标题和它回复的那条评论来判断。链接先换成 `[PAPER]`、`[OTHER_PAPER]`、`[LINK]`，模型知道自己在判断哪一个。
- 全量之前先跑样本：随机 200 条，Haiku 和 Sonnet 各标一遍，算两个模型的一致率，再改提示词。v3 加了一条：明确让别人去读算 `rec`，只把链接当论据贴出来算 `reference`。五类一致率到 97.0%，“是不是推荐”到 99.0%。
- 全量：Haiku 标了主书架全部 8,152 条，用的是 v2（v3 是第二天早上定的）；置信度低于 0.6、或者文本里有“让人去读”线索的 951 条交给 Sonnet 用 v3 复核，改了 207 条。最后的分布：reference 78%、rec 17%、critical 3%、strong_rec 1%、joke 0.5%。
- 书更难判：书常被当成学东西的去处（“see [BOOK] for X”），样本上两个模型只有 89.5% 一致。所以书的 8,403 条提及直接用 Sonnet 标；分数只看月份，每本书每个月最多标 3 条。同时标出链接其实不是在说这本书的（128 条），和作者本人贴自己的书的（304 条，一律算 `reference`）。

### 4. 打分

```
score = months_rec + 0.5 × months_strong
```

- `months_rec` 是至少有一条 `rec` 或 `strong_rec` 的不同月份数；`months_strong` 是至少有一条 `strong_rec` 的月份数。
- 同一个人最多算 2 个月：有人把同一篇论文在 15 个月里贴了 84 次。
- 没有正向立场的论文写“被提及”，不写“被推荐”。
- 每篇最多留 20 条评论（先推荐和批评、先不同的人）；所有数字都按全部提及算。

### 5. 中文导读和学习路径

都由 Sonnet 子 agent 写：

- **卡片**：主书架每篇论文、每本书一张。中文标题、一句话摘要、两三句导读、HN 上为什么反复提它（依据评论，不编造）、类型、难度、前置知识、常青还是会过时、阅读时长。书另外有“怎么读”和“适合谁”。
- **中文说明**：每条 HN 原话下面一句中文，说这位评论者拿这篇论文说明什么。论文 7,504 条，书 1,727 条。
- **学习路径**：OpenAlex 里这篇论文的参考文献 ∩ 书架（不够再往下找一层，最多 40 篇候选），Sonnet 挑 3–8 篇排出阅读顺序，每步写为什么读、读哪部分。参考文献里有书架论文的 711 篇里，666 篇排出了路径。
- **主题树**：标题和摘要算 embedding（bge-small-en-v1.5），球面 k-means 聚成 100 簇，一次 Sonnet 调用命名：14 个领域、96 个类目。

### 6. 静态站

- Next.js 静态导出，放在 GitHub Pages：没有服务器，任何地方都不调模型 API。构建时读目录（SQLite）；浏览页的筛选和搜索在浏览器里用两份 JSON 算（压缩前 1.0 MB 和 1.5 MB）。
- 封面是生成的：图案由 arXiv 编号决定，底色由领域决定。不用任何由 PDF 派生的图，也不托管论文原文。
- 论文页链到 arXiv、PDF 和 alphaXiv，另有两个按钮：复制提问提示词（提示词、链接和中文导读，贴进任意聊天模型）、复制 Markdown 笔记。
- GitHub Actions 每天两次生成“新鲜”书架：Hugging Face 每日论文、HN 最近 36 小时在讨论的论文、几个 arXiv 分类的新论文。只抓元数据，不调模型（[`fresh.mjs`](deploy/public/scripts/fresh.mjs)、[`pages.yml`](deploy/public/repo/pages.yml)）。

### 7. 月度更新

- `hs monthly start`：先备份当前产物，从 Algolia 拉新的一个月，重建目录，只准备新增的模型任务：立场（Haiku）→ 复核（Sonnet）→ 卡片 → 中文说明。
- 在 Claude Code 里按 [monthly-update skill](.claude/skills/monthly-update/SKILL.md) 派子 agent，发布之前停下来。某个任务超过约 1,000 条，先等人确认。
- 第一次更新覆盖两天的数据：立场 20 条、卡片 1 张、中文说明 18 条，约 18 万 token，从头到尾 11 分钟。

## 用子 agent 代替 API

这个做法来自 HackerTube。代码里不调任何模型 API，而是由脚本把每个任务切成批次写到磁盘上：

```
data/llm/<任务>/prompt.md        说明（见 prompts/）
data/llm/<任务>/in/0001.md       一批，Markdown，给子 agent 读
data/llm/<任务>/in/0001.jsonl    同一批的 JSONL
data/llm/<任务>/out/0001.jsonl   子 agent 写的结果：每条输入一行 JSON
```

- Claude Code 的主会话每批派一个子 agent（Haiku 或 Sonnet，最多 13 个同时跑）。每个子 agent 读 `prompt.md` 和自己那一批，用 Write 工具写结果文件。
- 合并只认输入里有的 id 和合法的标签。缺条或 JSON 坏了的批次算没跑完，重派那一批就行。
- 提示词、输入、输出、每批的 token 都留在磁盘上，任何一条标签都能追溯，任何任务都能复跑。走 Claude 订阅额度，不走 API 计费。

代码：[`pipeline/hs/llm_batch.py`](pipeline/hs/llm_batch.py)。提示词：[`prompts/`](prompts/)。

## 数字

| 任务 | 模型 | 条数 | token | 墙钟 |
|---|---|---|---|---|
| 论文立场样本（v1–v3，每版 200 条 × 2 个模型） | Haiku + Sonnet | 1,200 | 250 万 | 每轮约 7 分钟 |
| 论文立场，主书架全量（另有截断的评论重跑） | Haiku | 8,152 | 1,770 万 | 55 分钟，13 路并行 |
| 论文立场复核 | Sonnet | 951 | 130 万 | 4.4 分钟 |
| 论文卡片（先 30 张样本，再全量） | Sonnet | 1,829 | 530 万 | 约 20 分钟 |
| 论文中文说明（先 200 条 × 2 个模型样本，再全量） | Sonnet（样本还有 Haiku） | 7,886 | 470 万 | 约 25 分钟 |
| 主题命名 | Sonnet | 100 簇 | 13 万 | 2.4 分钟 |
| 学习路径（先 5 篇，再 50 篇样本，再剩下的） | Sonnet | 711 篇 | 400 万 | 最后 656 篇 12 分钟 |
| 是不是书（书单里过 2/2 的条目） | Sonnet | 821 | 60 万 | |
| 书的立场样本（v1–v2，每版 200 条 × 2 个模型） | Haiku + Sonnet | 800 | 150 万 | |
| 书的立场 | Sonnet | 8,403 | 700 万 | |
| 书的卡片和中文说明 | Sonnet | 90 + 1,750 | 230 万 | |
| 第一次月度更新 | Haiku + Sonnet | 39 | 18 万 | 11 分钟 |

合计约 4,700 万 token，走订阅额度。“条数”是发出去的条数，含样本。网站带分享图约 400 MB（GitHub Pages 上限 1 GB），手机 Lighthouse 90 分以上。

## 局限

- **只看 HN 的口碑。** 论文要被不同的人在 HN 评论里长期链接才进得来。HN 偏系统、编程语言、机器学习和数学，有的领域几乎看不到；老论文有更多年头积累提及。在 HN 上热门不等于重要。
- **图书只按官方免费版的链接算。** 只写书名的评论（“去读 SICP”）不算，名著会被低估。官方网站搬过家的，只给少数几本手工补了旧地址（SICP、Rust 书、MacKay 那本）。许可证只人工核实了被链接最多的 100 本，上架 90 本。
- **模型会判错。** 上面的一致率是两个模型之间比，不是和人工判断比。中文导读、中文说明和学习路径都由 Claude 写，可能有错；每条原话都链回原评论，网站上也写明了。
- **覆盖范围。** Hugging Face 存档到 2026-08-21 为止；之后的数据来自 Algolia，不含已删除和被降权的条目。候选层不标立场。暂时只有 arXiv 论文。

## 自己跑

### 一个月的数据：实测 24 分钟

要装 [uv](https://docs.astral.sh/uv/)、Node 24 和 [Claude Code](https://claude.com/claude-code)。不需要任何 API key。

```bash
git clone https://github.com/john-liu-dev/open-hackershelf
cd open-hackershelf
claude          # 然后说：跑 demo
```

demo 只用 2023 年 3 月一个月的数据把整条流程跑一遍：下载、提及、门槛、立场标注、卡片、中文说明、目录、静态站。实测一次 24 分钟、60 万 token，大部分时间花在下载那 107 MB 上（网速很慢，0.13 MB/s）。分步说明和实测数字见 [demo/README.zh-CN.md](demo/README.zh-CN.md)。

### 完整管线

`cp .env.example .env`，填上 `CONTACT_EMAIL` 和 `OPENALEX_API_KEY`（免费）。然后在仓库根目录：

```bash
P="uv run --project pipeline"
$P hs fetch-hf && $P hs fetch-delta && $P hs build-db --rebuild-links      # HN 全量：要下载几十 GB
$P python -m hs.steps.papers extract
$P python -m hs.steps.papers tiers
$P python -m hs.steps.papers meta                                            # arXiv API，3 秒一次
$P python -m hs.steps.papers openalex
$P python -m hs.steps.papers stance-sample && $P python -m hs.steps.papers stance-sample-v3   # 200 条 × Haiku/Sonnet
$P python -m hs.steps.papers stance-agree --suffix _v3                       # 看过一致率再全量
$P python -m hs.steps.papers stance-inc-prepare --tag full                   # 还没标的全部，Haiku
$P python -m hs.steps.papers stance-inc-review-prepare --tag full            # 低置信度 → Sonnet
$P python -m hs.steps.papers cards-inc-prepare --tag full
$P python -m hs.steps.shelf embed && $P python -m hs.steps.shelf cluster     # 一个 Sonnet 子 agent 给簇命名
$P python -m hs.steps.shelf taxonomy && $P python -m hs.steps.shelf related
$P python -m hs.steps.papers catalog
$P python -m hs.steps.papers why-zh-inc-prepare --tag full
$P python -m hs.steps.study paths-prepare --all-core --sample 50             # 再排剩下的；paths-merge
$P python -m hs.steps.papers catalog
deploy/public/build.sh                                                       # 静态站 → web/.next-public
```

- 每个 `*-prepare` 之后，每批派一个子 agent，做法同 [demo 的 skill](.claude/skills/demo/SKILL.md)。
- 开源书的步骤在 [`hs/steps/books.py`](pipeline/hs/steps/books.py)：seed、signal、kind、label、score、cards、why-zh、export。
- 要发布：`build.sh` 之前把 `HS_PUBLIC_REPO` 设成一个 GitHub Pages 仓库的工作区，再在那里提交、推送。

## 目录

```
pipeline/hs/          管线：下载、提及、门槛、立场、卡片、目录、主题、图书、月度更新
pipeline/config.toml  门槛、限速、数据源
prompts/              子 agent 的提示词（从代码里写出）
web/                  静态站（Next.js，路由是 *.public.tsx）
deploy/public/        构建、私有内容和大小检查、本机预览、每日新鲜书架和 Pages 工作流
demo/                 一个月 demo
.claude/skills/       Claude Code 的 demo 和月度更新 skill
CLAUDE.md             给 Claude Code 的项目说明（模板）
```

这个仓库是从私有的工作仓库导出来的：白名单里的文件，几个补丁去掉个人环境（暂停的自托管阅读站、笔记同步、本机路径），进来之前再扫一遍私有字符串。代码注释里的 D46 这类编号指私有仓库的决策记录，重要的决定上面都写了。

## 致谢

- 方法借鉴 Andrej Karpathy 的 [HackerTube](https://hackertube.org/)，它对 YouTube 视频做了同样的事：社区长期口碑（至少 3 个人、至少 3 个月、自己的文字至少 100 个字符）、结合帖子标题的 LLM 立场标注、按月份算的分数、“被提及”和“被推荐”分开写，以及用 Claude Code 子 agent 做标注。HackerShelf 把它用到论文和免费书上，另加了中文导读、学习路径、两个模型的样本对比和每人最多算两个月。
- 数据来源（这里都不附带）：
  - Hacker News：[open-index/hacker-news](https://huggingface.co/datasets/open-index/hacker-news)（ODC-By 1.0）和 [HN Algolia API](https://hn.algolia.com/api)。网站上的原话保留评论者的名字，并链回原评论。
  - 论文元数据：arXiv API。Thank you to arXiv for use of its open access interoperability.
  - 被引数和参考文献：[OpenAlex](https://openalex.org/)（CC0）。
  - 新鲜书架：Hugging Face Daily Papers、HN Algolia API、arXiv RSS。
  - 书单：[EbookFoundation/free-programming-books](https://github.com/EbookFoundation/free-programming-books)（CC BY 4.0）。
  - embedding：[BAAI/bge-small-en-v1.5](https://huggingface.co/BAAI/bge-small-en-v1.5)（MIT），用 fastembed 在本机算。

## 许可证

- 代码：MIT，见 [LICENSE](LICENSE)。
- 文档、提示词和手工整理的元数据：CC BY 4.0，见 [LICENSE-CC-BY-4.0.txt](LICENSE-CC-BY-4.0.txt)。包括 Markdown 文件（README、CLAUDE.md、`prompts/`、`demo/`、skill）；`pipeline/hs/steps/` 里的提示词文本（名字带 `_PROMPT` 的字符串常量）；以及两份手工整理的图书文件：[`pipeline/books_licenses.jsonl`](pipeline/books_licenses.jsonl)（被链接最多的 100 本书逐本到官方页面核实的许可证）和 [`pipeline/books_extra.toml`](pipeline/books_extra.toml)（手选的书、补的官方地址和简称）。
- 署名写：“HackerShelf by Yuehua Liu (john-liu-dev), https://github.com/john-liu-dev/open-hackershelf”。
- 不附带任何数据。用它做出来的东西，按上面各数据源的许可证来；HN 数据的 ODC-By 1.0 要求署名。
