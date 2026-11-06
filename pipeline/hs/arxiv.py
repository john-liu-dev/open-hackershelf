"""arXiv API 元数据（id_list 批量查询）。走统一 HTTP 客户端：每 3 秒 1 个请求、单连接（无联系邮箱时 6 秒），结果写磁盘缓存。

arXiv API 不返回许可证；`can_redistribute` 先一律按 false 处理（最保守），以后需要时用 OAI-PMH 补。
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from hs.http import Http

API = "https://export.arxiv.org/api/query"
NS = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom", "os": "http://a9.com/-/spec/opensearch/1.1/"}
_VER = re.compile(r"v(\d+)$")


def _id_from_abs(url: str) -> tuple[str, int | None]:
    raw = url.split("/abs/", 1)[-1]
    m = _VER.search(raw)
    return (raw[: m.start()] if m else raw), (int(m.group(1)) if m else None)


def _clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def parse_feed(xml: bytes) -> list[dict]:
    root = ET.fromstring(xml)
    out = []
    for e in root.findall("a:entry", NS):
        abs_url = (e.findtext("a:id", default="", namespaces=NS) or "").strip()
        if "/abs/" not in abs_url:  # 错误条目
            continue
        aid, ver = _id_from_abs(abs_url)
        prim = e.find("arxiv:primary_category", NS)
        out.append({
            "id": f"arxiv:{aid}",
            "version": ver,
            "title": _clean(e.findtext("a:title", namespaces=NS)),
            "abstract": _clean(e.findtext("a:summary", namespaces=NS)),
            "authors": [_clean(a.findtext("a:name", namespaces=NS)) for a in e.findall("a:author", NS)],
            "published": e.findtext("a:published", namespaces=NS),
            "updated": e.findtext("a:updated", namespaces=NS),
            "primary_category": prim.get("term") if prim is not None else None,
            "categories": [c.get("term") for c in e.findall("a:category", NS)],
            "comment": _clean(e.findtext("arxiv:comment", namespaces=NS)) or None,
            "journal_ref": _clean(e.findtext("arxiv:journal_ref", namespaces=NS)) or None,
            "doi": _clean(e.findtext("arxiv:doi", namespaces=NS)) or None,
        })
    return out


def fetch_meta(http: Http, ids: list[str], batch: int = 100, progress=None) -> dict[str, dict]:
    """ids 形如 'arxiv:1706.03762'。返回 id → 元数据；查不到的不在结果里。"""
    plain = sorted({i.removeprefix("arxiv:") for i in ids})
    res: dict[str, dict] = {}
    for k in range(0, len(plain), batch):
        chunk = plain[k : k + batch]
        r = http.get(API, {"id_list": ",".join(chunk), "max_results": len(chunk)})
        if r.status_code != 200:
            continue
        for m in parse_feed(r.content):
            res[m["id"]] = m
        if progress:
            progress(k + len(chunk), len(plain), r.from_cache)
    return res
