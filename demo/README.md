# One-month demo

[中文](README.zh-CN.md)

Runs the whole HackerShelf flow on a single month of Hacker News, March 2023 (the month GPT-4 came out): download → mentions → thresholds → stance labels → cards → Chinese glosses → catalog → static site. The model work is done by Claude Code sub-agents, exactly as in the full run.

## What you need

- [uv](https://docs.astral.sh/uv/) (it fetches Python 3.12), Node 24 with npm, and [Claude Code](https://claude.com/claude-code) on a plan that can run sub-agents.
- About 1 GB of disk: the month's data, the local database and `web/node_modules`.
- Optional: Google Chrome, only for the share images. Without it they are skipped and the pages are the same.
- No API keys. Putting a `CONTACT_EMAIL` in `.env` halves the wait between arXiv requests.

## In Claude Code

```bash
git clone https://github.com/john-liu-dev/open-hackershelf
cd open-hackershelf
claude
```

Then say **run the demo**. The [demo skill](../.claude/skills/demo/SKILL.md) runs the steps below, sends one sub-agent per batch for each model task, and stops at a local preview. Nothing is committed or published.

## Step by step

```bash
demo/run.sh data      # download the month, build the database, extract mentions, apply thresholds, fetch arXiv metadata
demo/run.sh stance    # prepare stance labels → data/llm/stance_inc_demo/        (Haiku)
demo/run.sh review    # low-confidence re-check → data/llm/stance_inc_demo_review/ (Sonnet; may be empty)
demo/run.sh cards     # cards → data/llm/cards_inc_demo/                         (Sonnet)
demo/run.sh why       # build the catalog once, then glosses → data/llm/why_zh_inc_demo/ (Sonnet)
demo/run.sh catalog   # merge everything → data/build/catalog.db
demo/run.sh site      # npm ci, static export to web/.next-public, privacy check
node deploy/public/serve.mjs     # preview at http://localhost:4173/shelf/
demo/run.sh status    # how many batches each model task still has
```

After `stance`, `review`, `cards` and `why`, the batches have to be run by sub-agents before the next step: in Claude Code, one sub-agent per `in/NNNN.md` file, with the instructions in the [skill](../.claude/skills/demo/SKILL.md). `demo/run.sh status` shows what is left; a batch with missing or broken lines is simply run again.

## How it differs from the full run

- **Thresholds.** One month can't contain "3 different months", so [`config.toml`](config.toml) lowers only the month threshold to 1: 3 people for the main shelf, 2 for candidates. It is loaded through `HS_CONFIG=demo/config.toml`, which `run.sh` sets, on top of `pipeline/config.toml`.
- **Skipped:** OpenAlex (citations and references, so no learning paths; it needs a free key), embeddings (so no topic tree and no related papers), open books, and the daily fresh shelf. The site copes: no topic shelves, no paths, an empty book shelf. The About page still describes the full rules.
- The batch commands are the monthly-update ones (`stance-inc-prepare` and so on) with the tag `demo`: on an empty build, everything on the main shelf counts as new.

## A test run

On 2026-11-06, from a fresh copy of this repository, on a slow connection:

| Step | Time | Result |
|---|---|---|
| `data` | 14 min 8 s, of which 13.5 min was the 107 MB download at 0.13 MB/s | 407,941 HN items and 636 arXiv mentions; 22 papers on the main shelf (3+ people), 35 candidates; arXiv metadata for all 57 in one request |
| `stance` | 2 Haiku sub-agents in parallel, 2.4 min | 119 comments labeled |
| `review` | 1 Sonnet sub-agent, 28 s | 17 re-checked (15 low confidence, 2 "go read this" cues), 5 changed |
| `cards` | 3 Sonnet sub-agents in parallel, 54 s | 22 cards |
| `why` | 2 Sonnet sub-agents in parallel, 48 s | 116 glosses (median 29 characters; 7 longer than the 40 asked for) |
| `catalog` and `site` | about 1 min, `npm ci` included | 360 files, 15.8 MB, 23 share images |

- About 24 minutes end to end. The four model steps took 9 minutes of wall clock, including the time between them.
- 602K tokens: 212K on Haiku for stance, 391K on Sonnet for the review, cards and glosses.
- Final labels: reference 102, rec 13, strong_rec 2, critical 1, joke 1. 8 of the 22 main-shelf papers count as "recommended"; the rest say "mentioned".
- Top of the shelf: Sparks of Artificial General Intelligence (14 people), GPTQ (10), the GPT-4 Technical Report (9), Toolformer (7), Language Is Not All You Need (7), LoRA (6).
- Without a topic tree, every cover is the same grey.
- npm 11 warns that the install scripts of better-sqlite3, esbuild and fsevents were skipped. All three ship prebuilt binaries, so nothing more is needed.

## Clean up

Everything the demo writes is in `data/`, `pipeline/.venv/`, `web/node_modules/`, `web/.next/` and `web/.next-public/` (about 1 GB in the test run). Delete them to start over.
