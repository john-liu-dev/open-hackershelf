<!-- 由 pipeline/hs/steps/books.py 的 BOOK_STANCE_PROMPT_V3 生成（CC BY 4.0），和子 agent 读到的 prompt.md 一致 -->
# 任务：判断 HN 评论对它链接的那本书是什么立场

输入是 JSONL 的 Markdown 视图，每条“评论 × 书”：
`{"id", "book_title", "book_authors", "commenter", "story_title", "parent_snippet", "text"}`
- `book_title`、`book_authors`：评论链接的那本书（开放许可或官方免费在线的书）。
- `commenter`：评论者的 HN 用户名。
- `story_title`：评论所在 HN 讨论串的标题；`parent_snippet`：它回复的那条评论的开头（可能为空）。只用来理解语境。
- `text`：评论全文。指向这本书（整本书或其中某一章、某一页）的链接写成 `[BOOK]`，其他链接写成 `[LINK]`。

先判断 `about_book`：评论里的 [BOOK] 是不是指这本书本身或它的某一章。链接只是碰巧在同一个网站、实际指的是别的东西（作者的博客文章、同站的其他项目、勘误页、讨论区），就是 false。

再判断评论者对**这本书本身**的态度。先看两条总规则：
- 叫人去读、去学（整本或其中某一节都算）→ rec；拿某一节当出处或证据，支撑自己的说法 → reference。
- 评论者就是这本书的作者，在贴自己的书（自称 I wrote / my book / author here，或者用户名明显是作者）→ 一律 reference，不管措辞多热情。author_self 写 true。

然后按下面的顺序判断，第一条符合的就是答案：
1. `joke`：书本身被拿来当笑点、梗或讽刺对象。
2. `critical`：批评这本书本身，比如内容过时、讲错了、写得不好、不适合入门。以下都**不是** critical：反驳别的评论者、批评书里讲的技术或语言、说“书很好但不适合你现在的需要”。
3. `strong_rec`：热情、强烈的推荐，有明确的强烈措辞：highly recommend、strongly recommend、can't recommend it enough、must-read、the best book on X、my favorite book、changed how I think / my career、强烈推荐。
   只说 great、excellent、good、nice、really helpful 的，算 rec，不算 strong_rec。
4. `rec`：评论者认为这本书值得读，满足任意一条：
   - 让对方去读它、从里面学东西：“check out [BOOK]” “start with [BOOK]” “See [BOOK] for how to do X” “read chapter 3 of [BOOK]” “you'd enjoy [BOOK]”。
   - 有人问“有什么书或资料可以看”，回答里给出了它。
   - 对书给出正面评价，或说自己读了有收获：“great book” “does an excellent job explaining X” “I learned X from it” “I keep coming back to it”。对作者说“写得很好”也算。
5. `reference`：其余情况。包括：
   - 拿书或某一章当事实出处、证据，支撑自己的论点（“as [BOOK] says, …” “according to chapter 5 of [BOOK]”），没有让人去读的意思。
   - 讨论书里的某个细节、提问、指出书里的小错误，但没有评价这本书。
   - “there's a free book on this”、只介绍书的内容、只贴链接不说话。

rec 和 reference 的分界：评论者是在**让对方去读它、学会某样东西**（rec），还是**引用它支撑自己的说法**（reference）。“See [BOOK] for X” 这种给对方指路的算 rec。
拿不准时：rec 和 reference 之间选 reference；strong_rec 和 rec 之间选 rec；critical 和 reference 之间选 reference。about_book 为 false 时，stance 写 reference。

每行输出一个 JSON（顺序与输入一致，每个 id 都要有一行）：
```
{"id": <同输入>, "about_book": true, "author_self": false, "stance": "...", "confidence": 0.0-1.0, "quote": "评论里最能说明立场的一句原话，逐字摘录，不超过 300 字符", "why": "不超过 15 个英文词：按这条评论，读者能从这本书里得到什么（joke 和 critical 可以留空）"}
```
只输出 JSONL 内容，不要解释。用 Write 工具把结果写到指定的输出文件。
