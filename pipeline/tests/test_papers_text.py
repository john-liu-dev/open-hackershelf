from hs.steps.papers import clip_around_paper, mask_links


def test_clip_keeps_paper_marker():
    text = "x " * 1500 + "see [PAPER] for details." + " y" * 100
    out = clip_around_paper(text)
    assert "[PAPER]" in out and len(out) < 2100


def test_clip_short_text_unchanged():
    assert clip_around_paper("short [PAPER] text") == "short [PAPER] text"


def test_mask_links_marks_this_paper_only():
    t = "a https://arxiv.org/abs/1706.03762v5, b https://arxiv.org/pdf/2005.14165.pdf c https://example.com/x."
    out = mask_links(t, "arxiv:1706.03762")
    assert out == "a [PAPER], b [OTHER_PAPER] c [LINK]."


def test_read_jsonl_keeps_unicode_line_separators(tmp_path):
    import json

    from hs.llm_batch import read_jsonl

    p = tmp_path / "x.jsonl"
    p.write_text(json.dumps({"id": "a", "t": "line sep"}, ensure_ascii=False) + "\n" + json.dumps({"id": "b"}) + "\n")
    assert [x["id"] for x in read_jsonl(p)] == ["a", "b"]
