<!-- 由 pipeline/hs/steps/papers.py 的 STANCE_PROMPT_V3 生成（CC BY 4.0），和子 agent 读到的 prompt.md 一致 -->
# 任务：判断 HN 评论对它链接的那篇论文是什么立场（v3）

输入是 JSONL 的 Markdown 视图，每条"评论 × 论文"：
`{"id", "paper_title", "story_title", "parent_snippet", "text"}`
- `paper_title`：评论链接的那篇 arXiv 论文的标题。
- `story_title`：评论所在 HN 讨论串的标题；`parent_snippet`：它回复的那条评论的开头（可能为空）。只用来理解语境。
- `text`：评论全文。指向这篇论文的链接写成 `[PAPER]`，指向其他 arXiv 论文的写成 `[OTHER_PAPER]`，其他链接写成 `[LINK]`。

只判断评论者对**这篇论文（[PAPER] / paper_title）本身**的态度。按下面的顺序判断，第一条符合的就是答案：

1. `joke`：论文本身被拿来当笑点、梗或讽刺对象。评论语气幽默、但论文是被认真引用的 → 不是 joke。
2. `critical`：评论者批评**这篇论文本身**——方法、证据、结论、严谨性、新意、宣传炒作。
   以下都**不是** critical：反驳别的评论者、批评文章/公司/产品/讨论串、论文本身报告的是负面结果、评论者只是说"这不能彻底解决问题"但没有指出论文的毛病。
3. `strong_rec`：热情推荐，有明确的强烈措辞：fantastic / brilliant / must-read / one of the best / changed how I think / no other work comes close / 强烈推荐 等。
4. `rec`：评论者认为这篇论文**值得看**，满足下面任意一条：
   - 明确让别人去读、去看它，把它当成帮对方弄懂问题的读物："I'd point you to [PAPER]" "go read [PAPER]" "you'd be interested in [PAPER]" "you might like/enjoy" "check out" "worth reading" "I recommend" "read this paper"。
   - 说这篇论文把某件事讲得好，或对论文质量给出正面评价："[PAPER] explains this well" "a good overview" "great/excellent/interesting paper"。
5. `reference`：其余所有情况。包括：只把链接贴出来当论据或出处，支撑自己的说法（"as shown in [PAPER]" "source: [PAPER]" "see [PAPER]" 后面没有让人去读的意思）、给出新闻背后的原始论文、回答"有没有出处"时贴链接、"here's the link / paper"、"there's a paper on this"、"reminds me of [PAPER]"、只引用摘要不评价、"I haven't read it yet"、介绍论文内容但不表态。

rec 和 reference 的分界：评论者是在**建议对方去读它**（rec），还是**拿它支撑自己的说法**（reference）。

拿不准时：rec 和 reference 之间选 reference；strong_rec 和 rec 之间选 rec；critical 和 reference 之间选 reference。confidence 如实反映把握。

每行输出一个 JSON（顺序与输入一致，每个 id 都要有一行）：
```
{"id": <同输入>, "stance": "...", "confidence": 0.0-1.0, "quote": "评论里最能说明立场的一句原话，逐字摘录，≤300 字符", "why": "≤15 个英文词：按这条评论，读者能从论文里得到什么（joke/critical 可以留空）"}
```
只输出 JSONL 内容，不要解释。用 Write 工具把结果写到指定的输出文件。
