"""HN 文本处理：HTML → 纯文本、抽 href、算"评论者自己的文字"。

HN 的 text 字段是 HTML：段落用 <p> 分隔，链接是 <a href="..." rel="nofollow">显示文本</a>（显示文本
通常就是 URL，长的会被截断成 "..."），斜体 <i>，代码 <pre><code>，实体如 &#x2F; &quot; &gt;。
引用的约定是段落以 ">" 开头。
"""

from __future__ import annotations

import html
import re

_A_RE = re.compile(r'<a\s+[^>]*?href="([^"]*)"[^>]*>(.*?)</a>', re.I | re.S)
_HREF_RE = re.compile(r'href="([^"]+)"', re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_P_RE = re.compile(r"<p>|</p>|<br\s*/?>", re.I)
_URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.I)
_WS_RE = re.compile(r"[ \t\r\f\v]+")


def hrefs(text_html: str | None) -> list[str]:
    """评论 HTML 里所有链接的完整 URL（已反转义）。"""
    if not text_html:
        return []
    return [html.unescape(h) for h in _HREF_RE.findall(text_html)]


def to_text(text_html: str | None) -> str:
    """HTML → 纯文本；链接保留完整 URL；段落之间空一行。"""
    if not text_html:
        return ""
    s = _A_RE.sub(lambda m: html.unescape(m.group(1)), text_html)
    s = _P_RE.sub("\n\n", s)
    s = _TAG_RE.sub("", s)
    s = html.unescape(s)
    paras = [_WS_RE.sub(" ", p).strip() for p in s.split("\n\n")]
    return "\n\n".join(p for p in paras if p)


def own_text(text_html: str | None) -> str:
    """评论者自己的文字：去掉链接（URL）和以 ">" 开头的引用段落。"""
    out = []
    for p in to_text(text_html).split("\n\n"):
        if p.lstrip().startswith(">"):
            continue
        p = _WS_RE.sub(" ", _URL_RE.sub(" ", p)).strip()
        if p:
            out.append(p)
    return "\n\n".join(out)


def own_len(text_html: str | None) -> int:
    """自己文字的字符数（段落间的换行不计）。"""
    return sum(len(p) for p in own_text(text_html).split("\n\n"))
