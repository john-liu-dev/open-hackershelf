"""Phase 5 开源书候选名单（hs/steps/books.py）：链接规范化、前缀规则、书单条目解析、按链接去重。不读 data/。"""

from __future__ import annotations

from pathlib import Path

from hs.steps.books import dedupe_by_links, norm_url, parse_fpb, url_prefixes


def test_norm_url():
    assert norm_url("https://www.Example.com/A/B/?x=1#y") == "example.com/a/b"
    assert norm_url("http://worrydream.com/#!/MagicInk") == "worrydream.com/magicink"  # 前端路由当路径
    assert norm_url("http://example.com:8080/") == "example.com"
    assert norm_url("https://www.microsoft.com/en-us/download/details.aspx?id=29263", keep_query=True) == \
        "microsoft.com/en-us/download/details.aspx?id=29263"
    assert norm_url("http://[broken/x") == "[broken/x"  # 评论里坏掉的链接不报错


def test_prefix_rules():
    # 目录页代表整本书的网页版，取所在目录
    assert url_prefixes("https://www.craftinginterpreters.com/contents.html") == \
        ["craftinginterpreters.com/contents.html", "craftinginterpreters.com"]
    assert url_prefixes("https://sarabander.github.io/sicp/html/index.xhtml") == \
        ["sarabander.github.io/sicp/html/index.xhtml", "sarabander.github.io/sicp/html"]
    # 同一个目录下的几本手册：只认这一页
    assert url_prefixes("https://www.gnu.org/software/emacs/manual/emacs.html") == ["gnu.org/software/emacs/manual/emacs.html"]
    # PDF 只认这个文件，不扩到大学主页的目录
    assert url_prefixes("https://www.cs.cornell.edu/jeh/book.pdf") == ["cs.cornell.edu/jeh/book.pdf"]
    # 公共站点至少两段路径；还有别的内容的网站不能只剩域名
    assert url_prefixes("https://github.com/aosabook/500lines") == ["github.com/aosabook/500lines"]
    assert url_prefixes("https://github.com/aosabook") == []
    assert url_prefixes("http://www.paulgraham.com/") == []
    assert url_prefixes("http://www.paulgraham.com/onlisp.html") == ["paulgraham.com/onlisp.html"]
    assert url_prefixes("https://cs.stanford.edu/") == []
    # 靠查询串区分的下载页：带上查询串
    assert url_prefixes("https://www.microsoft.com/en-us/download/details.aspx?id=29263") == \
        ["microsoft.com/en-us/download/details.aspx?id=29263"]


def test_parse_fpb(tmp_path: Path):
    p = tmp_path / "list.md"
    p.write_text("""### Index
* [Lisp](#lisp)
### 0 - Meta-Lists
* [Bitsavers.org](http://bitsavers.trailing-edge.com)
### Lisp
#### Common Lisp
* [Practical Common Lisp](http://www.gigamonkeys.com/book/) - Peter Seibel (HTML)
* [Structure and Interpretation of Computer Programs](https://web.mit.edu/6.001/6.037/sicp.pdf) - Harold Abelson, Gerald Jay Sussman (PDF) (CC BY-SA)
""")
    rows = parse_fpb(p)
    assert [r["title"] for r in rows] == ["Practical Common Lisp", "Structure and Interpretation of Computer Programs"]
    assert rows[0]["authors"] == "Peter Seibel" and rows[0]["section"] == "Lisp" and rows[0]["subsection"] == "Common Lisp"
    assert rows[1]["license"] == "CC-BY-SA" and rows[0]["license"] is None


def test_dedupe_by_links_merges_renamed_entries():
    rows = [
        {"id": "book:a", "title": "Advanced R Programming", "urls": ["http://adv-r.had.co.nz/"], "prefixes": ["adv-r.had.co.nz"],
         "aliases": [], "license": None, "sections": ["R"], "source": "fpb"},
        {"id": "book:b", "title": "Advanced R", "urls": ["https://adv-r.hadley.nz/", "http://adv-r.had.co.nz/"],
         "prefixes": ["adv-r.had.co.nz", "adv-r.hadley.nz"], "aliases": [], "license": None, "sections": ["R"], "source": "extra"},
        {"id": "book:c", "title": "R for Data Science", "urls": ["https://r4ds.hadley.nz/"], "prefixes": ["r4ds.hadley.nz"],
         "aliases": [], "license": None, "sections": ["R"], "source": "fpb"},
    ]
    kept, n = dedupe_by_links(rows)
    assert n == 1 and sorted(r["id"] for r in kept) == ["book:b", "book:c"]
    b = next(r for r in kept if r["id"] == "book:b")
    assert "Advanced R Programming" in b["aliases"] and b["merged"] == ["book:a"]


def test_license_label():
    from hs.steps.books import license_label

    assert license_label("CC-BY-NC-SA-4.0") == ("CC BY-NC-SA 4.0", True)
    assert license_label("CC-BY-NC-ND-3.0-US") == ("CC BY-NC-ND 3.0 US", True)
    assert license_label("CC-BY-NC") == ("CC BY-NC", True)
    assert license_label("Apache-2.0 OR MIT") == ("Apache 2.0 / MIT", True)
    assert license_label("free-online") == ("官方免费在线", False)
    assert license_label("unknown") == ("官方免费（许可证没写清）", False)
    assert license_label("Public-Domain") == ("公有领域", True)


def test_author_short():
    from hs.steps.books import author_short

    assert author_short("Harold Abelson, Gerald Jay Sussman, Julie Sussman") == "Abelson 等"
    assert author_short("Robert Nystrom") == "Nystrom"
    assert author_short("Joey de Vries") == "de Vries"
    assert author_short("Patricio Gonzalez Vivo, Jen Lowe") == "Gonzalez Vivo 等"
    assert author_short("Benjamin C. Pierce 等") == "Pierce 等"
    assert author_short("why the lucky stiff") == "_why"
    assert author_short("") == ""
