"""`uv run hs <step>`：每一步也能用 `uv run python -m hs.steps.<step>` 单独跑。"""

from __future__ import annotations

import importlib
import sys
import time

STEPS = {
    "fetch-hf": "hs.steps.fetch_hf",
    "fetch-delta": "hs.steps.fetch_delta",
    "build-db": "hs.steps.build_db",
    # 月度更新（D47）：拉增量 → 重建目录 → 增量模型任务 → catalog（流程见 .claude/skills/monthly-update/SKILL.md）
    "monthly": "hs.steps.monthly",
}


def run(step: str, args: list[str]) -> int:
    mod_name, _, func = STEPS[step].partition(":")
    mod = importlib.import_module(mod_name)
    t0 = time.time()
    print(f"== {step} ==", flush=True)
    rc = getattr(mod, func or "main")(args) or 0
    print(f"== {step} done rc={rc} ({time.time()-t0:.0f}s) ==", flush=True)
    return rc


def main() -> int:
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print("用法: hs <step> [args]\n" + "\n".join(f"  {s}" for s in STEPS)
              + "\n其余步骤用 uv run python -m hs.steps.<papers|shelf|study|books> <子命令>")
        return 0
    step, rest = argv[0], argv[1:]
    if step not in STEPS:
        print(f"未知步骤：{step}")
        return 2
    return run(step, rest)


if __name__ == "__main__":
    sys.exit(main())
