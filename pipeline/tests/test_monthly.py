"""月度更新（D47）的增量任务：任务排序、标签合并的先后、复核挑选、新论文归类。只用临时目录，不碰仓库里的 data/。"""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import numpy as np
import pytest

from hs import llm_batch
from hs.config import Paths
from hs.steps import papers as P
from hs.steps.shelf import nearest_topics


@pytest.fixture
def llm(tmp_path, monkeypatch) -> Path:
    monkeypatch.setattr(llm_batch, "PATHS", Paths(llm=tmp_path))
    return tmp_path


def mk_task(root: Path, name: str, ins: list[dict], outs: list[dict] | None, model: str | None = None) -> None:
    d = root / name
    (d / "in").mkdir(parents=True)
    (d / "out").mkdir()
    (d / "in" / "0001.jsonl").write_text("".join(json.dumps(x) + "\n" for x in ins))
    if outs is not None:
        (d / "out" / "0001.jsonl").write_text("".join(json.dumps(x) + "\n" for x in outs))
    (d / "manifest.json").write_text(json.dumps({"task": name, "n_items": len(ins), "n_batches": 1, **({"model": model} if model else {})}))


def test_tasks_like_orders_by_date_with_review_after_its_batch(llm):
    for name in ("stance_inc_20261201", "stance_inc_20261104_review", "stance_inc_20261104", "stance_core"):
        mk_task(llm, name, [{"id": "1:a"}], None)
    (llm / "stance_inc_20270101").mkdir()  # 没有 manifest 的不算
    assert llm_batch.tasks_like("stance_inc_") == ["stance_inc_20261104", "stance_inc_20261104_review", "stance_inc_20261201"]


def test_prepare_records_model_in_manifest(llm):
    llm_batch.prepare("t", [{"id": "1", "text": "x"}], "prompt", model="claude-haiku-5-5")
    assert llm_batch.manifest("t")["model"] == "claude-haiku-5-5"
    llm_batch.prepare("u", [{"id": "1", "text": "x"}], "prompt")
    assert "model" not in llm_batch.manifest("u")


def test_stance_labels_increments_override_in_order(llm):
    mk_task(llm, "stance_core", [{"id": "1:arxiv:a"}, {"id": "2:arxiv:a"}],
            [{"id": "1:arxiv:a", "stance": "rec"}, {"id": "2:arxiv:a", "stance": "reference"}])
    mk_task(llm, "stance_inc_20261104", [{"id": "3:arxiv:b"}], [{"id": "3:arxiv:b", "stance": "rec"}], model=P.HAIKU)
    mk_task(llm, "stance_inc_20261104_review", [{"id": "3:arxiv:b"}], [{"id": "3:arxiv:b", "stance": "strong_rec"}], model=P.SONNET)
    # 下个月的增量里又标了一条旧提及（比如论文这个月才进主书架之前就有的），后来的覆盖
    mk_task(llm, "stance_inc_20261201", [{"id": "2:arxiv:a"}], [{"id": "2:arxiv:a", "stance": "critical"}])
    # 输出里编出来的 id、不认识的立场都不收
    mk_task(llm, "stance_inc_20261202", [{"id": "4:arxiv:c"}], [{"id": "9:arxiv:z", "stance": "rec"}, {"id": "4:arxiv:c", "stance": "meh"}])
    res = P.stance_labels()
    assert res["1:arxiv:a"] == {"id": "1:arxiv:a", "stance": "rec", "model": P.HAIKU}
    assert res["2:arxiv:a"]["stance"] == "critical" and res["2:arxiv:a"]["model"] == P.HAIKU  # 没写 model 时按名字推断
    assert res["3:arxiv:b"]["stance"] == "strong_rec" and res["3:arxiv:b"]["model"] == P.SONNET
    assert "9:arxiv:z" not in res and "4:arxiv:c" not in res


def test_review_picks_low_conf_invalid_and_rec_cues(llm):
    ins = [{"id": "1:arxiv:a", "text": "Source: [PAPER]"},
           {"id": "2:arxiv:a", "text": "You might enjoy [PAPER] if you like this."},
           {"id": "3:arxiv:a", "text": "Great paper [PAPER]"},
           {"id": "4:arxiv:a", "text": "[PAPER]"}]
    outs = [{"id": "1:arxiv:a", "stance": "reference", "confidence": 0.9},
            {"id": "2:arxiv:a", "stance": "reference", "confidence": 0.9},
            {"id": "3:arxiv:a", "stance": "rec", "confidence": 0.4}]  # 4 没有输出
    mk_task(llm, "stance_inc_T", ins, outs, model=P.HAIKU)
    P.cmd_stance_inc_review_prepare(Namespace(tag="T", min_conf=0.6))
    got = {k: v["_reason"] for k, v in llm_batch.inputs("stance_inc_T_review").items()}
    assert got == {"2:arxiv:a": "rec_cue", "3:arxiv:a": "low_conf", "4:arxiv:a": "invalid"}
    assert llm_batch.manifest("stance_inc_T_review")["model"] == P.SONNET
    # 下划线字段不进给模型看的 Markdown
    md = (llm / "stance_inc_T_review" / "in" / "0001.md").read_text()
    assert "_reason" not in md and "You might enjoy" in md


def test_review_skips_when_nothing_to_check(llm):
    mk_task(llm, "stance_inc_T", [{"id": "1:arxiv:a", "text": "x"}], [{"id": "1:arxiv:a", "stance": "rec", "confidence": 0.9}])
    P.cmd_stance_inc_review_prepare(Namespace(tag="T", min_conf=0.6))
    assert not (llm / "stance_inc_T_review").exists()


def test_why_zh_and_cards_include_increments(llm):
    mk_task(llm, "why_zh_core", [{"id": "1:x"}], [{"id": "1:x", "why_zh": "旧的说明"}])
    mk_task(llm, "why_zh_inc_20261104", [{"id": "1:x"}, {"id": "2:x"}],
            [{"id": "1:x", "why_zh": "新的说明。"}, {"id": "2:x", "why_zh": "  "}])
    assert P.why_zh_labels() == {"1:x": "新的说明"}
    mk_task(llm, "cards_core", [{"id": "arxiv:a"}], [{"id": "arxiv:a", "oneliner_zh": "旧"}])
    mk_task(llm, "cards_inc_20261104", [{"id": "arxiv:b"}], [{"id": "arxiv:b", "oneliner_zh": "新"}, {"id": "arxiv:c", "oneliner_zh": "编的"}])
    assert {k: v["oneliner_zh"] for k, v in P.card_outputs().items()} == {"arxiv:a": "旧", "arxiv:b": "新"}


def test_nearest_topics_assigns_only_new_papers():
    v = np.array([[1, 0], [0.9, 0.1], [0, 1], [0.1, 0.95], [0.7, 0.7]], dtype=np.float32)
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    ids = ["a", "b", "c", "d", "e"]
    topics = {"a": {"topic": "t1", "area": "A"}, "c": {"topic": "t2", "area": "B"}, "e": {"topic": "t2", "area": "B"}}
    new = nearest_topics(ids, v, topics)
    assert new == {"b": {"topic": "t1", "area": "A"}, "d": {"topic": "t2", "area": "B"}}
