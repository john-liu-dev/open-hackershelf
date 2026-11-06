# HackerShelf

How HackerShelf is built: ranking the papers and free books Hacker News keeps recommending, with Claude Code sub-agents.

**The shelf: <https://john-liu-dev.github.io/shelf/>** · [中文说明](README.zh-CN.md)

[![HackerShelf home page: a row of book spines and the evergreen shelf](deploy/public/repo/screenshots/home.png)](https://john-liu-dev.github.io/shelf/)

HackerShelf goes through twenty years of Hacker News and keeps the arXiv papers and free books that different people kept recommending in different months: 1,800 papers and 90 open books, each with a Chinese reading guide and the original HN comments, linked back. The site is in Chinese; titles stay in English. This repository is the method behind it: the pipeline, the prompts, the site code and the sub-agent batching. It ships no data.

## How it works

### 1. HN mentions

- The data is every Hacker News story and comment since October 2006, about 50 million items. It comes from the [open-index/hacker-news](https://huggingface.co/datasets/open-index/hacker-news) dump on Hugging Face up to 2026-08-21, and from the [HN Algolia API](https://hn.algolia.com/api) after that, because the dump stopped updating.
- A **mention** is a comment that links to the paper and has at least 100 characters of the commenter's own words (links and `>` quotes don't count), or the paper itself submitted as a story.
- Links in every form (arxiv.org abs/pdf/html, ar5iv, alphaXiv, Hugging Face papers, the `10.48550` DOI) collapse to one arXiv ID. Counted this way, 26,947 distinct arXiv papers have at least one mention; counting every link regardless of length, plus plain-text `arXiv:` IDs, it would be 28,435 (data through 2026-11-01).

### 2. Three people, three months

- A paper goes on the **main shelf** when at least 3 different people mentioned it in at least 3 different calendar months.
- Two people in two months puts it in a **candidate** tier. Candidates are listed but never labeled, so the site only says "mentioned".
- A month of hype can't get a paper in; a classic that keeps coming up does. Data through 2026-11-03: 1,800 main-shelf papers and 2,785 candidates.

### 3. Stance labels, sample first

- A sub-agent labels every main-shelf comment as `strong_rec`, `rec`, `reference`, `joke` or `critical`. The label is about *this* paper, read with the thread title and the parent comment. Links are masked as `[PAPER]`, `[OTHER_PAPER]` and `[LINK]` so the model knows which link it is judging.
- Before any full run: 200 random mentions, labeled independently by Haiku and by Sonnet, agreement measured, prompt revised. Version 3 added one rule: telling someone to go read the paper is `rec`; posting the link as evidence is `reference`. That brought agreement to 97.0% on the five labels and 99.0% on recommend-or-not.
- Full run: Haiku labeled all 8,152 main-shelf mentions, with v2 (v3 came the next morning). The 951 with confidence below 0.6, or with a "go read this" cue, went to Sonnet with prompt v3, which changed 207 of them. Final mix: reference 78%, rec 17%, critical 3%, strong_rec 1%, joke 0.5%.
- Books are harder: a book is often where you send someone to learn a thing ("see [BOOK] for X"), and the two models agreed on 89.5% of the sample. So Sonnet labeled all 8,403 book mentions directly, at most 3 per book per month since the score only counts months. It also flagged links that weren't really about the book (128) and authors posting their own book (304, counted as `reference`).

### 4. Score

```
score = months_rec + 0.5 × months_strong
```

- `months_rec` is the number of distinct months with at least one `rec` or `strong_rec`; `months_strong` counts months with at least one `strong_rec`.
- Each person counts for at most 2 months. One person once posted the same paper 84 times in 15 months.
- Papers with no positive label say "mentioned", never "recommended".
- Up to 20 comments are kept per paper (recommendations and critiques first, different people first); all the counts use every mention.

### 5. Chinese guides and learning paths

All written by Sonnet sub-agents:

- **Cards** for every main-shelf paper and book: a Chinese title, a one-line summary, a 2–3 sentence guide, why HN keeps citing it (taken from the comments, not invented), type, difficulty, prerequisites, evergreen or dated, and reading time. Books also get how to read them and who they're for.
- **Glosses**: one Chinese sentence under each HN quote saying what the commenter used the paper for. 7,504 for papers, 1,727 for books.
- **Learning paths**: the paper's references from OpenAlex, intersected with the shelf (one more level if too few, at most 40 candidates). Sonnet picks 3–8 of them in reading order and says why to read each and which part. 666 of the 711 papers with a reference on the shelf have one.
- **Topics**: title and abstract embeddings (bge-small-en-v1.5), spherical k-means into 100 clusters, and one Sonnet call that names them: 14 areas, 96 categories.

### 6. Static site

- A Next.js static export on GitHub Pages: no server, and no model API anywhere. The catalog (SQLite) is read at build time. Browse filters and search run in the browser on two JSON files (1.0 MB and 1.5 MB before gzip).
- Covers are generated: the pattern from the arXiv ID, the color from the topic. Nothing is derived from the PDFs, and no paper text is hosted.
- Each paper page links to arXiv, the PDF and alphaXiv. It also has two buttons: copy a question prompt (prompt, link and Chinese guide, to paste into any chat model) and copy a Markdown note.
- A GitHub Actions job rebuilds a "fresh" shelf twice a day: Hugging Face Daily Papers, papers HN discussed in the last 36 hours, and a few arXiv categories. It fetches metadata only and calls no model ([`fresh.mjs`](deploy/public/scripts/fresh.mjs), [`pages.yml`](deploy/public/repo/pages.yml)).

### 7. Monthly update

- `hs monthly start` backs up the build, pulls the new month from Algolia, rebuilds, and prepares only the new model work: stance (Haiku) → review (Sonnet) → cards → glosses.
- In Claude Code, the [monthly-update skill](.claude/skills/monthly-update/SKILL.md) dispatches the sub-agents and stops before publishing. Any task over about 1,000 items waits for a human OK.
- The first update covered two days of data: 20 stance labels, 1 card, 18 glosses, about 180K tokens, 11 minutes end to end.

## Sub-agents instead of an API

Borrowed from HackerTube. No code calls a model API. A script writes each task to disk as batches:

```
data/llm/<task>/prompt.md        the instructions (see prompts/)
data/llm/<task>/in/0001.md       one batch, as Markdown for the sub-agent to read
data/llm/<task>/in/0001.jsonl    the same batch as JSONL
data/llm/<task>/out/0001.jsonl   written by the sub-agent: one JSON line per input id
```

- The main Claude Code session then starts one sub-agent per batch, Haiku or Sonnet, up to 13 at a time. Each reads `prompt.md` and its batch and writes its output file with the Write tool.
- The merge step accepts only ids that exist in the input and only valid labels. A batch with missing or broken lines counts as not done, so a failed batch is simply sent out again.
- Prompts, inputs, outputs and per-batch token counts all stay on disk, so any label can be traced and any task re-run. It runs on a Claude subscription, not API billing.

Code: [`pipeline/hs/llm_batch.py`](pipeline/hs/llm_batch.py). Prompts: [`prompts/`](prompts/).

## Numbers

| Task | Model | Items | Tokens | Wall clock |
|---|---|---|---|---|
| Paper stance samples (v1–v3, 200 × 2 models each) | Haiku + Sonnet | 1,200 | 2.5M | ~7 min per round |
| Paper stance, whole main shelf (plus re-runs of truncated comments) | Haiku | 8,152 | 17.7M | 55 min, 13 in parallel |
| Paper stance review | Sonnet | 951 | 1.3M | 4.4 min |
| Paper cards (30-card sample, then all) | Sonnet | 1,829 | 5.3M | ~20 min |
| Paper glosses (200 × 2 models sample, then all) | Sonnet (sample also Haiku) | 7,886 | 4.7M | ~25 min |
| Topic names | Sonnet | 100 clusters | 0.13M | 2.4 min |
| Learning paths (5, a 50-paper sample, then the rest) | Sonnet | 711 papers | 4.0M | 12 min for the last 656 |
| Book or not? (list entries passing 2/2) | Sonnet | 821 | 0.6M | |
| Book stance samples (v1–v2, 200 × 2 models each) | Haiku + Sonnet | 800 | 1.5M | |
| Book stance | Sonnet | 8,403 | 7.0M | |
| Book cards and glosses | Sonnet | 90 + 1,750 | 2.3M | |
| First monthly update | Haiku + Sonnet | 39 | 0.18M | 11 min |

About 47 million tokens in all, on a subscription. The "Items" column counts what was sent, including samples. The site is about 400 MB with share images (GitHub Pages allows 1 GB) and scores 90+ on mobile Lighthouse.

## Limitations

- **Only Hacker News's taste.** A paper has to be linked in HN comments by different people over time. HN leans toward systems, programming languages, machine learning and math; whole fields barely appear, and older papers have had more years to collect mentions. Popular on HN is not the same as important.
- **Books are counted only through links to the official free edition.** Comments that just name a book ("read SICP") don't count, so famous books are undercounted. Where an official site moved, old official addresses were added by hand for only a few books (SICP, the Rust book, MacKay). Licenses were checked by hand for the 100 most-linked books; 90 made it onto the shelf.
- **The models get things wrong.** The agreement figures compare two models with each other, not with human judgment. Chinese guides, glosses and learning paths are written by Claude and can be wrong. Every quote links back to the original comment, and the site says so.
- **Coverage.** The Hugging Face dump ends 2026-08-21; later data comes from Algolia, which leaves out dead and deleted items. Candidate-tier papers aren't labeled. Only arXiv papers for now.

## Run it

### One month of data: 24 minutes in a test run

Requires [uv](https://docs.astral.sh/uv/), Node 24 and [Claude Code](https://claude.com/claude-code). No API keys.

```bash
git clone https://github.com/john-liu-dev/open-hackershelf
cd open-hackershelf
claude          # then say: run the demo
```

The demo runs the whole flow on March 2023 alone: download, mentions, thresholds, stance labels, cards, glosses, catalog, static site. A test run took 24 minutes and 0.6M tokens, most of the time spent downloading 107 MB on a slow connection (0.13 MB/s). Step by step and with numbers: [demo/README.md](demo/README.md).

### The full pipeline

`cp .env.example .env` and fill in `CONTACT_EMAIL` and `OPENALEX_API_KEY` (free). Then, from the repository root:

```bash
P="uv run --project pipeline"
$P hs fetch-hf && $P hs fetch-delta && $P hs build-db --rebuild-links      # all of HN: tens of GB to download
$P python -m hs.steps.papers extract
$P python -m hs.steps.papers tiers
$P python -m hs.steps.papers meta                                            # arXiv API, one request per 3 s
$P python -m hs.steps.papers openalex
$P python -m hs.steps.papers stance-sample && $P python -m hs.steps.papers stance-sample-v3   # 200 × Haiku/Sonnet
$P python -m hs.steps.papers stance-agree --suffix _v3                       # check before the full run
$P python -m hs.steps.papers stance-inc-prepare --tag full                   # everything unlabeled, Haiku
$P python -m hs.steps.papers stance-inc-review-prepare --tag full            # low confidence → Sonnet
$P python -m hs.steps.papers cards-inc-prepare --tag full
$P python -m hs.steps.shelf embed && $P python -m hs.steps.shelf cluster     # one Sonnet sub-agent names the clusters
$P python -m hs.steps.shelf taxonomy && $P python -m hs.steps.shelf related
$P python -m hs.steps.papers catalog
$P python -m hs.steps.papers why-zh-inc-prepare --tag full
$P python -m hs.steps.study paths-prepare --all-core --sample 50             # then the rest; paths-merge
$P python -m hs.steps.papers catalog
deploy/public/build.sh                                                       # static site → web/.next-public
```

- After each `*-prepare`, dispatch one sub-agent per batch, as the [demo skill](.claude/skills/demo/SKILL.md) does.
- Open books follow the same steps in [`hs/steps/books.py`](pipeline/hs/steps/books.py): seed, signal, kind, label, score, cards, why-zh, export.
- To publish, set `HS_PUBLIC_REPO` to a GitHub Pages repository's working tree before `build.sh`, then commit and push there.

## Layout

```
pipeline/hs/          the pipeline: download, mentions, tiers, stance, cards, catalog, topics, books, monthly
pipeline/config.toml  thresholds, rate limits, sources
prompts/              the sub-agent prompts, written out from the code
web/                  the static site (Next.js; routes are *.public.tsx)
deploy/public/        build, privacy and size check, local preview, daily fresh shelf and Pages workflow
demo/                 the one-month demo
.claude/skills/       demo and monthly-update skills for Claude Code
CLAUDE.md             project instructions for Claude Code, kept as a template
```

This repository is exported from a private working repository: a whitelist of files, a few patches that take out personal setup (a paused self-hosted reading site, note syncing, local paths), and a scan for private strings before anything lands here. Code comments mention decision numbers such as D46; those point to the private decision log, and the decisions that matter are described above.

## Credits

- The method borrows from Andrej Karpathy's [HackerTube](https://hackertube.org/), which does the same for YouTube videos: long-term community signal (at least 3 people in at least 3 months, at least 100 characters of your own words), LLM stance labels read with the thread title, the months-based score, "mentioned" versus "recommended", and Claude Code sub-agents doing the labeling. HackerShelf applies it to papers and free books and adds Chinese guides, learning paths, two-model sample checks and the per-person cap.
- Data sources (none of it is included here):
  - Hacker News: [open-index/hacker-news](https://huggingface.co/datasets/open-index/hacker-news) (ODC-By 1.0) and the [HN Algolia API](https://hn.algolia.com/api). Quotes on the site keep the commenter's name and link to the comment.
  - Paper metadata: the arXiv API. Thank you to arXiv for use of its open access interoperability.
  - Citations and references: [OpenAlex](https://openalex.org/) (CC0).
  - Fresh shelf: Hugging Face Daily Papers, the HN Algolia API, arXiv RSS.
  - Book list: [EbookFoundation/free-programming-books](https://github.com/EbookFoundation/free-programming-books) (CC BY 4.0).
  - Embeddings: [BAAI/bge-small-en-v1.5](https://huggingface.co/BAAI/bge-small-en-v1.5) (MIT), run locally with fastembed.

## License

- Code: MIT, see [LICENSE](LICENSE).
- Documentation, prompts and hand-curated metadata: CC BY 4.0, see [LICENSE-CC-BY-4.0.txt](LICENSE-CC-BY-4.0.txt). This covers the Markdown files (READMEs, CLAUDE.md, `prompts/`, `demo/`, the skills), the prompt text in `pipeline/hs/steps/` (the `*_PROMPT*` string constants), and the two hand-curated book files [`pipeline/books_licenses.jsonl`](pipeline/books_licenses.jsonl) (license checks of the 100 most-linked books against their official pages) and [`pipeline/books_extra.toml`](pipeline/books_extra.toml) (hand-picked books, extra official addresses and short names).
- Attribution: "HackerShelf by Yuehua Liu (john-liu-dev), https://github.com/john-liu-dev/open-hackershelf".
- No data is included. Whatever you build with it falls under the source licenses above; ODC-By 1.0 requires attributing the HN data.
