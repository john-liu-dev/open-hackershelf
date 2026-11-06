"""OpenAlex：按 DOI 批量查被引数、参考文献、主题。

- arXiv 论文在 OpenAlex 里通常有一条 preprint 记录（DOI 10.48550/arXiv.<id>）；如果 arXiv 元数据里写了期刊 DOI，再查一次正式发表版本。
  被引数取两者较大值（正式版本的被引往往多得多，例如 Thurston 那篇 preprint 5 次、期刊版 655 次）。
- 只用 list 端点（每次 $0.0001），不用 search（$0.001）：4,576 篇约 110 次请求、约 $0.01，远低于每天 $1 的免费额度。
- API key 只拼进实际请求，不进磁盘缓存（Http.get 的 secret_params）。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from hs.config import env
from hs.http import Http

BASE = "https://api.openalex.org/works"
SELECT_PREPRINT = ("id,doi,title,cited_by_count,counts_by_year,publication_year,type,primary_topic,topics,"
                   "referenced_works,primary_location")
SELECT_PUBLISHED = "id,doi,cited_by_count,publication_year,type,primary_location"
SELECT_SEARCH = "id,doi,title,cited_by_count,publication_year,type,primary_location,authorships"
# 不当作"正式发表版本"的类型
NOT_PUBLISHED = {"preprint", "book-review", "paratext", "erratum", "retraction", "peer-review", "letter", "editorial", "other"}


def arxiv_doi(aid: str) -> str:
    return "10.48550/arxiv." + aid.removeprefix("arxiv:").lower()


def norm_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    d = doi.strip().lower()
    for p in ("https://doi.org/", "http://doi.org/", "doi:"):
        d = d.removeprefix(p)
    return d or None


def _chunks(xs: list[str], n: int) -> Iterable[list[str]]:
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def lookup_dois(http: Http, dois: list[str], select: str, *, chunk: int = 50,
                progress: Callable[[int, int], None] | None = None) -> dict[str, dict]:
    """DOI（小写、不带前缀）→ OpenAlex work。DOI 里的 '|' 和 ',' 会破坏过滤语法，跳过。"""
    key = env("OPENALEX_API_KEY")
    if not key:
        raise RuntimeError("OPENALEX_API_KEY 没有设置（.env）")
    ok = sorted({d for d in dois if d and "|" not in d and "," not in d})
    out: dict[str, dict] = {}
    done = 0
    for part in _chunks(ok, chunk):
        r = http.get(BASE, {"filter": "doi:" + "|".join(part), "per-page": "200", "select": select},
                     secret_params={"api_key": key})
        if r.status_code != 200:
            raise RuntimeError(f"OpenAlex HTTP {r.status_code}（{len(part)} 个 DOI）")
        for w in r.json().get("results", []):
            d = norm_doi(w.get("doi"))
            if d:
                out[d] = w
        done += len(part)
        if progress:
            progress(done, len(ok))
    return out


def lookup_arxiv_landing(http: Http, aids: list[str], select: str, *, chunk: int = 50) -> dict[str, dict]:
    """DOI 查不到的 arXiv 论文，按 locations.landing_page_url = http://arxiv.org/abs/<id> 查（list 端点）。
    命中的常常是合并了 arXiv 版本的正式发表记录（会议/期刊），被引数更全。"""
    key = env("OPENALEX_API_KEY")
    plain = [a.removeprefix("arxiv:") for a in aids]
    want = {f"http://arxiv.org/abs/{p}".lower(): f"arxiv:{p}" for p in plain}
    out: dict[str, dict] = {}
    for part in _chunks(plain, chunk):
        r = http.get(BASE, {"filter": "locations.landing_page_url:" + "|".join(f"http://arxiv.org/abs/{p}" for p in part),
                            "per-page": "200", "select": select + ",locations"}, secret_params={"api_key": key})
        if r.status_code != 200:
            raise RuntimeError(f"OpenAlex HTTP {r.status_code}（{len(part)} 个 landing page）")
        for w in r.json().get("results", []):
            for loc in w.get("locations") or []:
                a = want.get((loc.get("landing_page_url") or "").lower())
                # 同一篇有多条记录时取被引多的
                if a and (a not in out or (w.get("cited_by_count") or 0) > (out[a].get("cited_by_count") or 0)):
                    out[a] = w
    return out


def slim_topic(t: dict | None) -> dict | None:
    if not t:
        return None
    return {"id": t.get("id", "").rsplit("/", 1)[-1], "name": t.get("display_name"),
            "subfield": (t.get("subfield") or {}).get("display_name"), "field": (t.get("field") or {}).get("display_name"),
            "domain": (t.get("domain") or {}).get("display_name"), "score": t.get("score")}


def venue(w: dict | None) -> str | None:
    src = ((w or {}).get("primary_location") or {}).get("source") or {}
    return src.get("display_name")


def norm_title(t: str | None) -> str:
    import re
    import unicodedata
    t = unicodedata.normalize("NFKD", t or "").lower()
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def _surnames(names: list[str]) -> set[str]:
    out = set()
    for n in names:
        parts = norm_title(n).split()
        if parts:
            out.add(parts[-1])
    return out


def search_published(http: Http, title: str, year: int | None, authors: list[str], preprint_id: str | None):
    """按标题搜索（search 端点，$0.001/次），找同一篇论文的正式发表版本。
    返回 (match 或 None, 响应头)。匹配条件：标题规范化后相同（或相似度 ≥0.95）、不是 arXiv 预印本、
    类型像正式发表、年份在 arXiv 年份 -1 到 +6 之间、至少一个作者姓氏重合。同时命中多条时取被引最多的。"""
    from difflib import SequenceMatcher

    key = env("OPENALEX_API_KEY")
    if not key:
        raise RuntimeError("OPENALEX_API_KEY 没有设置（.env）")
    q = " ".join(norm_title(title).split()[:30])
    r = http.get(BASE, {"search": q, "select": SELECT_SEARCH, "per-page": "10"}, secret_params={"api_key": key})
    if r.status_code != 200:
        return None, r
    want = norm_title(title)
    sur = _surnames(authors)
    best = None
    for w in r.json().get("results", []):
        wid = (w.get("id") or "").rsplit("/", 1)[-1]
        if wid == preprint_id or (norm_doi(w.get("doi")) or "").startswith("10.48550/"):
            continue
        if w.get("type") in NOT_PUBLISHED:
            continue
        src = (((w.get("primary_location") or {}).get("source") or {}).get("display_name") or "").lower()
        if "arxiv" in src:
            continue
        got = norm_title(w.get("title"))
        if got != want and SequenceMatcher(None, got, want).ratio() < 0.95:
            continue
        y = w.get("publication_year")
        if year and y and not (year - 1 <= y <= year + 6):
            continue
        names = [((a.get("author") or {}).get("display_name") or "") for a in (w.get("authorships") or [])]
        if sur and names and not (sur & _surnames(names)):
            continue
        if best is None or (w.get("cited_by_count") or 0) > (best.get("cited_by_count") or 0):
            best = w
    return best, r
