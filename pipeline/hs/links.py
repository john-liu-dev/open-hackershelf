"""链接分类与 ID 规范化（规则见 docs/DATA.md 第 1 节）。

`arxiv_id(url)`：从各种 arXiv 相关 URL 里取出规范化的 arXiv ID（去版本号），取不到返回 None。
`paper_domain(url)`：其他论文域名分组（doi / openreview / acl / ...），留给以后。
`book_link(url)`：图书链接分组和 ID（amazon ASIN / goodreads / openlibrary / bookshop / gutenberg）。
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, unquote, urlsplit

# 新式 ID：YYMM.NNNN（2007-04 至 2014-12）或 YYMM.NNNNN（2015-01 起）
_NEW = r"(?P<new>\d{4}\.\d{4,5})(?:v\d+)?"
# 旧式 ID：archive(.SUBJ)?/YYMMNNN，如 math/9404236、hep-th/9901001、cs.AI/0101001
_OLD = r"(?P<old>[a-z][a-z\-]*(?:\.[A-Za-z]{2})?/\d{7})(?:v\d+)?"
_ID_IN_PATH = re.compile(rf"(?<![\d.])(?:{_NEW}|{_OLD})(?![\d])")
_TEXT_REF = re.compile(rf"\barxiv\s*:\s*(?:{_NEW}|{_OLD})(?![\d])", re.I)

# arXiv 本站及镜像、阅读器、聚合站：host 后缀 → 允许的路径前缀（None = 任意路径）
_ARXIV_HOSTS: dict[str, tuple[str, ...] | None] = {
    "arxiv.org": ("/abs/", "/pdf/", "/html/", "/format/", "/ps/", "/src/", "/e-print/", "/v/"),
    "export.arxiv.org": ("/abs/", "/pdf/", "/html/", "/format/", "/ps/"),
    "xxx.lanl.gov": ("/abs/", "/pdf/", "/ps/", "/format/"),
    "ar5iv.org": ("/abs/", "/html/", "/papers/"),
    "ar5iv.labs.arxiv.org": ("/abs/", "/html/"),
    "arxiv-vanity.com": ("/papers/",),
    "alphaxiv.org": ("/abs/", "/overview/", "/pdf/", "/html/", "/"),
    "huggingface.co": ("/papers/",),
    "scirate.com": ("/arxiv/",),
    "semanticscholar.org": ("/arxiv/",),
    "paperswithcode.com": ("/paper/arxiv:",),
}


def _host(url: str) -> str:
    try:
        h = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""
    return h[4:] if h.startswith("www.") else h


def arxiv_source(url: str) -> str | None:
    """URL 属于哪个 arXiv 相关站点（规范化后的 host 键），不是则 None。"""
    h = _host(url)
    for key in _ARXIV_HOSTS:
        if h == key or h.endswith("." + key):
            return key
    return None


def _valid_new(new_id: str) -> bool:
    yymm, num = new_id.split(".")
    yy, mm = int(yymm[:2]), int(yymm[2:])
    if not (1 <= mm <= 12) or yy < 7 or (yy == 7 and mm < 4):
        return False
    return len(num) == (4 if yy < 15 else 5)


def _norm_old(old_id: str) -> str:
    archive, num = old_id.split("/")
    return f"{archive.split('.')[0].lower()}/{num}"


def _from_match(m: re.Match) -> str | None:
    if m.group("new"):
        return m.group("new") if _valid_new(m.group("new")) else None
    return _norm_old(m.group("old"))


def arxiv_id(url: str) -> str | None:
    """arXiv 相关 URL → 'arxiv:<id>'（去版本号），否则 None。也认 doi.org/10.48550/arXiv.X。"""
    src = arxiv_source(url)
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    path = unquote(parts.path)
    if src is None:
        h = _host(url)
        if h.endswith("doi.org"):
            m = re.match(rf"/10\.48550/arxiv\.(?:{_NEW}|{_OLD})", path, re.I)
            if m:
                rid = _from_match(m)
                return f"arxiv:{rid}" if rid else None
        return None
    prefixes = _ARXIV_HOSTS[src]
    if prefixes and not any(path.startswith(p) for p in prefixes):
        return None
    if src == "alphaxiv.org" and path.startswith("/") and not re.match(r"/(abs|overview|pdf|html)/", path):
        # alphaxiv.org/2401.12345 这种直达形式
        if not re.match(rf"/{_NEW}", path):
            return None
    m = _ID_IN_PATH.search(path)
    if not m and src == "arxiv.org" and parts.query:
        m = _ID_IN_PATH.search(unquote(parts.query))
    if not m:
        return None
    rid = _from_match(m)
    return f"arxiv:{rid}" if rid else None


def arxiv_text_refs(text: str) -> list[str]:
    """纯文本里的 'arXiv:1706.03762' 写法（不是链接）。"""
    out = []
    for m in _TEXT_REF.finditer(text or ""):
        rid = _from_match(m)
        if rid:
            out.append(f"arxiv:{rid}")
    return out


# ---------------- 其他论文域名（Phase 0 只计数） ----------------
_PAPER_DOMAINS = [
    ("doi.org", "doi"), ("openreview.net", "openreview"), ("aclanthology.org", "acl"), ("aclweb.org", "acl"),
    ("dl.acm.org", "acm"), ("ieeexplore.ieee.org", "ieee"), ("papers.nips.cc", "neurips"),
    ("proceedings.neurips.cc", "neurips"), ("proceedings.mlr.press", "pmlr"), ("jmlr.org", "jmlr"),
    ("biorxiv.org", "biorxiv"), ("medrxiv.org", "medrxiv"), ("ssrn.com", "ssrn"),
    ("semanticscholar.org", "semanticscholar"), ("researchgate.net", "researchgate"),
    ("nature.com", "nature"), ("science.org", "science"), ("sciencemag.org", "science"),
    ("link.springer.com", "springer"), ("sciencedirect.com", "sciencedirect"), ("pnas.org", "pnas"),
    ("plos.org", "plos"), ("ncbi.nlm.nih.gov", "pubmed"), ("pubmed.ncbi.nlm.nih.gov", "pubmed"),
    ("eprint.iacr.org", "iacr"), ("usenix.org", "usenix"), ("citeseerx.ist.psu.edu", "citeseerx"),
    ("hal.science", "hal"), ("hal.archives-ouvertes.fr", "hal"), ("jstor.org", "jstor"),
    ("cell.com", "cell"), ("onlinelibrary.wiley.com", "wiley"), ("academic.oup.com", "oup"),
    ("journals.aps.org", "aps"), ("iopscience.iop.org", "iop"), ("osf.io", "osf"),
    ("paperswithcode.com", "paperswithcode"),
]


def paper_domain(url: str) -> str | None:
    h = _host(url)
    if not h:
        return None
    for dom, key in _PAPER_DOMAINS:
        if h == dom or h.endswith("." + dom):
            if key == "doi":
                return "doi_arxiv" if "10.48550/arxiv" in url.lower() else "doi"
            if key == "usenix" and "/presentation/" not in url and "/system/files/" not in url:
                return None
            if key == "semanticscholar" and "/paper/" not in url:
                return None
            return key
    return None


# ---------------- 图书链接 ----------------
_ASIN = re.compile(r"/(?:dp|gp/product|exec/obidos/(?:asin|ASIN|tg/detail/-)|o/ASIN|gp/aw/d|d)/([0-9A-Z]{10})(?:[/?#]|$)")
_AMAZON_HOST = re.compile(r"(^|\.)amazon\.(com|co\.uk|de|fr|ca|co\.jp|in|com\.au|es|it|nl|com\.br|com\.mx|cn|se|pl|sg)$")


def book_link(url: str) -> tuple[str, str | None] | None:
    """图书链接 → (来源, ID)。ID 取不到时为 None（例如 amzn.to 短链）。不是图书链接返回 None。"""
    h = _host(url)
    if not h:
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    path = parts.path
    if _AMAZON_HOST.search(h):
        m = _ASIN.search(path)
        return ("amazon", m.group(1)) if m else None
    if h in ("amzn.to", "amzn.com", "a.co", "amzn.eu"):
        m = re.match(r"/([0-9A-Z]{10})(?:[/?#]|$)", path)
        return ("amazon_short", m.group(1) if m and h == "amzn.com" else None)
    if h.endswith("goodreads.com"):
        m = re.match(r"/book/show/(\d+)", path)
        return ("goodreads", m.group(1)) if m else None
    if h.endswith("openlibrary.org"):
        m = re.match(r"/(works|books)/(OL\d+[WM])", path)
        return ("openlibrary", m.group(2)) if m else None
    if h.endswith("bookshop.org"):
        m = re.match(r"/(?:p/)?(?:books|a/\d+)/[^/]+/(\d{13})", path) or re.search(r"/(\d{13})(?:[/?#]|$)", path)
        return ("bookshop", m.group(1) if m else None) if re.match(r"/(p/books|books|a/\d+|shop)", path) else None
    if h.endswith("gutenberg.org"):
        m = re.match(r"/(?:ebooks|files|cache/epub)/(\d+)", path)
        return ("gutenberg", m.group(1)) if m else None
    if h.endswith("standardebooks.org"):
        m = re.match(r"/ebooks/([^/]+/[^/]+)", path)
        return ("standardebooks", m.group(1)) if m else None
    if h == "books.google.com" or (h.startswith("books.google.")):
        q = parse_qs(parts.query).get("id")
        return ("google_books", q[0] if q else None)
    return None
