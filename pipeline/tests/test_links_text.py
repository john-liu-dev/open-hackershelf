from hs.links import arxiv_id, arxiv_text_refs, book_link, paper_domain
from hs.text import hrefs, own_len, own_text, to_text


def test_arxiv_forms():
    cases = {
        "https://arxiv.org/abs/1706.03762": "arxiv:1706.03762",
        "https://arxiv.org/abs/1706.03762v5": "arxiv:1706.03762",
        "http://arxiv.org/pdf/1706.03762v1.pdf": "arxiv:1706.03762",
        "https://arxiv.org/pdf/1706.03762": "arxiv:1706.03762",
        "https://www.arxiv.org/html/2310.06825v1/#S2": "arxiv:2310.06825",
        "https://export.arxiv.org/abs/2401.00001": "arxiv:2401.00001",
        "https://arxiv.org/abs/math/9404236": "arxiv:math/9404236",
        "http://arxiv.org/abs/hep-th/9901001v2": "arxiv:hep-th/9901001",
        "http://arxiv.org/abs/cs.AI/0101001": "arxiv:cs/0101001",
        "https://arxiv.org/pdf/cs/0112017v1.pdf": "arxiv:cs/0112017",
        "https://www.alphaxiv.org/abs/2401.12345": "arxiv:2401.12345",
        "https://www.alphaxiv.org/overview/2401.12345v2": "arxiv:2401.12345",
        "https://huggingface.co/papers/2401.12345": "arxiv:2401.12345",
        "https://ar5iv.labs.arxiv.org/html/1706.03762": "arxiv:1706.03762",
        "https://www.arxiv-vanity.com/papers/1706.03762/": "arxiv:1706.03762",
        "https://doi.org/10.48550/arXiv.1706.03762": "arxiv:1706.03762",
        "https://arxiv.org/abs/0704.0001": "arxiv:0704.0001",
    }
    for url, want in cases.items():
        assert arxiv_id(url) == want, url


def test_arxiv_rejects():
    for url in [
        "https://arxiv.org/list/cs.AI/recent",
        "https://arxiv.org/a/vaswani_a_1",
        "https://huggingface.co/papers",
        "https://huggingface.co/meta-llama/Llama-2-7b",
        "https://arxiv.org/abs/1513.00001",   # 月份 13
        "https://arxiv.org/abs/1501.0001",    # 2015 起应为 5 位
        "https://example.com/abs/1706.03762",
        "https://github.com/foo/1706.03762",
    ]:
        assert arxiv_id(url) is None, url


def test_text_refs():
    assert arxiv_text_refs("see arXiv:1706.03762v2 and arxiv: math/9404236.") == ["arxiv:1706.03762", "arxiv:math/9404236"]


def test_paper_domain():
    assert paper_domain("https://doi.org/10.1145/3442188.3445922") == "doi"
    assert paper_domain("https://openreview.net/forum?id=abc") == "openreview"
    assert paper_domain("https://aclanthology.org/2020.acl-main.1/") == "acl"
    assert paper_domain("https://github.com/x") is None


def test_book_link():
    assert book_link("https://www.amazon.com/Structure-Interpretation/dp/0262510871/ref=sr_1_1") == ("amazon", "0262510871")
    assert book_link("https://www.amazon.co.uk/gp/product/B00ABC1234?x=1") == ("amazon", "B00ABC1234")
    assert book_link("https://www.goodreads.com/book/show/5470.1984") == ("goodreads", "5470")
    assert book_link("https://openlibrary.org/works/OL999456W/Title") == ("openlibrary", "OL999456W")
    assert book_link("https://www.gutenberg.org/ebooks/1342") == ("gutenberg", "1342")
    assert book_link("https://amzn.to/3abcd") == ("amazon_short", None)
    assert book_link("https://www.amazon.com/") is None
    assert book_link("https://aws.amazon.com/s3/") is None


HTML = ('I really liked this paper.<p>&gt; quoted bit that should not count'
        '<p><a href="https:&#x2F;&#x2F;arxiv.org&#x2F;abs&#x2F;1706.03762" rel="nofollow">https:&#x2F;&#x2F;arxiv.org&#x2F;abs&#x2F;1706.03...</a>'
        '<p>It&#x27;s <i>great</i>.')


def test_text():
    assert hrefs(HTML) == ["https://arxiv.org/abs/1706.03762"]
    assert "https://arxiv.org/abs/1706.03762" in to_text(HTML)
    assert own_text(HTML) == "I really liked this paper.\n\nIt's great."
    assert own_len(HTML) == len("I really liked this paper.") + len("It's great.")
