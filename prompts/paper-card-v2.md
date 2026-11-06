<!-- 由 pipeline/hs/steps/papers.py 的 CARD_PROMPT_V2 生成（CC BY 4.0），和子 agent 读到的 prompt.md 一致 -->
# 任务：给 HN 上被反复推荐的 arXiv 论文写一张卡片

输入是 JSONL，每行一篇论文：
`{"id", "title", "authors", "year", "categories", "abstract", "hn": {"people", "months", "first", "last", "by_year"}, "mentions": [{"stance", "quote", "why", "story_title", "year"}]}`
`mentions` 是 HN 评论者的原话摘录（最多 20 条，带立场标签）。

为每篇论文写一张卡片，每行输出一个 JSON（顺序与输入一致）：
```
{"id": <同输入>,
 "title_zh": "标题的中文译名（术语保留英文，如 Transformer）",
 "oneliner_zh": "一行中文摘要，不超过 40 个汉字：这篇论文是什么、讲了什么。用在列表里，不要以“本文”“这篇论文”开头。",
 "summary_zh": "2–3 句中文：这篇论文做了什么、核心结论是什么。准确、具体，不写空话。",
 "summary_en": "2–3 sentences in English, same content.",
 "why_hn": "一句中文：HN 上的人为什么反复提它、拿它说明什么（依据 mentions，不要编造）。",
 "type": "foundational | method | survey | empirical | position | tutorial | other",
 "difficulty": 1-5,
 "prerequisites": ["读懂它需要的前置知识，2–5 个中文短语；专业术语保留英文原词，例如“Transformer 架构”“贝叶斯推断（Bayesian inference）”“λ 演算（lambda calculus）”"],
 "shelf_life": "evergreen | dated",
 "reading_minutes": 整数（认真读一遍正文的时间，按页数和密度估）}
```
- difficulty：1 = 科普读者能读；3 = 本领域研究生；5 = 需要专门方向的深厚背景。
- shelf_life：dated = 结论绑定某个具体模型版本或时间点的评测、很快会过时；其余 evergreen。
- 只根据输入写，不要编造论文里没有的数字或结论；拿不准就写得保守。
只输出 JSONL 内容，不要解释。用 Write 工具把结果写到指定的输出文件。
