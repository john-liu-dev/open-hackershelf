#!/usr/bin/env bash
# demo：用一个月的 HN 数据（2023-03）把整条流程跑一遍。步骤和说明见 demo/README.md。
#   demo/run.sh data     下载这一个月（约 110 MB）→ 建库 → 抽 arXiv 提及 → 门槛 → arXiv 元数据。不调模型
#   demo/run.sh stance   准备立场标注的批次（Haiku）
#   demo/run.sh review   准备低置信度和“让人去读”线索的复核（Sonnet；没有要复核的就不建任务）
#   demo/run.sh cards    准备卡片（Sonnet）
#   demo/run.sh why      先建一次 catalog，再准备 HN 原话下面的中文说明（Sonnet）
#   demo/run.sh catalog  合并全部结果 → data/build/catalog.db、search-index.json
#   demo/run.sh site     构建静态站、检查；预览用 node deploy/public/serve.mjs
#   demo/run.sh status   每个模型任务还剩几批没跑
# 模型步骤（stance、review、cards、why）之后，在 Claude Code 里让子 agent 跑完 data/llm/<任务>/ 的批次（.claude/skills/demo），再做下一步。
set -euo pipefail
cd "$(dirname "$0")/.."
export HS_CONFIG=demo/config.toml
TAG=${HS_DEMO_TAG:-demo}
py() { uv run --quiet --project pipeline python "$@"; }
papers() { py -m hs.steps.papers "$@"; }

case "${1:-}" in
  data)
    uv run --project pipeline hs fetch-hf --min-free-gb 2
    uv run --project pipeline hs build-db --rebuild-links
    papers extract
    papers tiers
    papers meta
    ;;
  stance) papers stance-inc-prepare --tag "$TAG" ;;
  review) papers stance-inc-review-prepare --tag "$TAG" ;;
  cards) papers cards-inc-prepare --tag "$TAG" ;;
  why)
    papers catalog
    papers why-zh-inc-prepare --tag "$TAG"
    ;;
  catalog) papers catalog ;;
  site)
    (cd web && npm ci --no-audit --no-fund)
    deploy/public/build.sh
    ;;
  status)
    py - "$TAG" <<'EOF'
import sys
from hs import llm_batch
tag = sys.argv[1]
for task in (f"stance_inc_{tag}", f"stance_inc_{tag}_review", f"cards_inc_{tag}", f"why_zh_inc_{tag}"):
    m = llm_batch.manifest(task)
    if not m:
        print(f"{task}: 还没准备（或者没有要处理的）")
        continue
    pend = llm_batch.pending(task)
    print(f"{task}: {m['n_items']} 条、{m['n_batches']} 批，模型 {m.get('model', '?')}，没跑完 {len(pend)} 批 {' '.join(pend)}")
EOF
    ;;
  *)
    sed -n '2,11p' "$0"
    exit 2
    ;;
esac
