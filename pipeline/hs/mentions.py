"""从一条 HN story/comment 里抽 arXiv 提及（Phase 0 探针和 Phase 1 抽取共用）。

一条提及 = (HN 条目, arXiv ID, 来源)。同一条目里同一篇论文出现多次只算一条，来源优先级：
story_url > comment_link / story_text_link > text_ref。
"""

from __future__ import annotations

from hs.links import arxiv_id, arxiv_source, arxiv_text_refs
from hs.text import hrefs, own_len, to_text

# 抽候选行用的 SQL 条件（宽松，Python 侧再精确判断）
ARXIV_SQL_FILTER = """(
    url ILIKE '%arxiv%' OR url ILIKE '%huggingface.co/papers%' OR url ILIKE '%ar5iv%' OR url ILIKE '%10.48550%'
    OR text ILIKE '%arxiv%' OR text ILIKE '%huggingface.co/papers%' OR text ILIKE '%ar5iv%' OR text ILIKE '%10.48550%'
)"""


def _form(url: str) -> str:
    """链接形式：arxiv_abs / arxiv_pdf / arxiv_html / alphaxiv / hf_papers / 其他镜像。"""
    src = arxiv_source(url) or "doi"
    if src in ("arxiv.org", "export.arxiv.org", "xxx.lanl.gov"):
        low = url.lower()
        for k in ("/abs/", "/pdf/", "/html/"):
            if k in low:
                return "arxiv_" + k.strip("/")
        return "arxiv_other"
    return {"alphaxiv.org": "alphaxiv", "huggingface.co": "hf_papers", "doi": "doi_10.48550"}.get(src, "mirror_" + src)


def arxiv_mentions(hn_id: int, type_: int, by: str | None, time, url: str | None, text: str | None) -> list[dict]:
    out: dict[str, dict] = {}
    olen = own_len(text) if text else 0

    def add(aid: str, src: str, form: str) -> None:
        if aid not in out:
            out[aid] = {"hn_id": hn_id, "type": type_, "by": by, "time": time, "arxiv": aid,
                        "src": src, "form": form, "own_len": olen if src != "story_url" else None}

    if type_ == 1 and url:
        aid = arxiv_id(url)
        if aid:
            add(aid, "story_url", _form(url))
    link_src = "comment_link" if type_ == 2 else "story_text_link"
    for h in hrefs(text):
        aid = arxiv_id(h)
        if aid:
            add(aid, link_src, _form(h))
    if text and "arxiv" in text.lower():
        for aid in arxiv_text_refs(to_text(text)):
            add(aid, "text_ref", "text_ref")
    return list(out.values())
