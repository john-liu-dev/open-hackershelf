<!-- 由 pipeline/hs/steps/books.py 的 BOOK_CARD_PROMPT 生成（CC BY 4.0），和子 agent 读到的 prompt.md 一致 -->
# 任务：给开源书书架写中文卡片

输入是 JSONL 的 Markdown 视图，每条一本书：
`{"id", "title", "authors", "url", "license", "sections", "unfinished", "hn", "mentions"}`
- 这些书都能在官方网站免费读全书（开放许可，或作者、出版社官方免费放出）。`url` 是官方免费版的地址，`license` 是许可证。
- `sections`：它在 free-programming-books 书单里的分类，只作参考。
- `unfinished`：true 表示书还没写完，只有一部分章节。
- `hn`：Hacker News 上提到它的统计：不同的人数、月份数、第一次和最近一次被提起、按年的提及数。
- `mentions`：HN 评论里提到这本书的原话（最多 20 条）。`stance` 是评论对书的态度（strong_rec 强烈推荐 / rec 推荐 / critical 批评 / reference 引用 / joke 玩笑），`quote` 是原话摘录（[BOOK] 是这本书的链接），`why` 是一句英文说明。

读者是想自学的中文读者。卡片放在书的详情页上，帮读者判断要不要读、怎么读。每本书输出一行 JSON：
```
{"id": <同输入>,
 "title_zh": "中文书名",
 "oneliner_zh": "一行中文介绍",
 "summary_zh": "导读，3–4 句",
 "why_hn": "一句中文",
 "how_to_read": ["建议读法，2–4 条"],
 "audience_zh": "一句中文",
 "prerequisites": ["0–4 个中文短语"],
 "difficulty": 1-5,
 "reading_hours": 整数,
 "subject": "书架分类 id"}
```
各字段：
- title_zh：中文书名。这本书有广为人知的中文译本时用译本的书名（例如 SICP 写“计算机程序的构造和解释”）；没有就意译。拿不准有没有译本时意译，不要编造“中文版”。
- oneliner_zh：不超过 40 个汉字，这本书讲什么、有什么特点。用在书架列表里，不要以“本书”“这本书”“一本”开头。
- summary_zh：3–4 句中文：讲什么、怎么讲（风格、方法、有没有练习或配套代码）、和同类的书比有什么不同。准确、具体，不写空话。
- why_hn：HN 上的人为什么反复推荐它、拿它说明什么。只依据 mentions 归纳，不要编造。有批评的，可以带一句批评的是什么。
- how_to_read：每条不超过 50 个汉字：从哪里开始、哪些部分先读或可以跳过、要不要做练习、和什么配合着读。依据你对这本书目录的了解和 mentions 里的说法；拿不准章节号就不写章节号。
- audience_zh：适合谁读，不超过 30 个汉字。
- prerequisites：读之前最好会的；专业术语保留英文原词，例如“C 语言指针”“微积分”“递归（recursion）”。入门书可以是空数组。
- difficulty：1 = 零基础能读；2 = 学过一点编程；3 = 有一两年编程经验；4 = 需要扎实的专业基础；5 = 需要研究生水平的数学或专门背景。
- reading_hours：认真读完一遍、做主要练习的大致小时数。
- subject 从下面选一个：
  - intro 编程入门：第一本编程书、程序设计方法（如 How to Design Programs、Learn to Program）
  - lang 编程语言：学一门具体的语言或它的生态（如 Rust、JavaScript、Erlang、Clojure、Haskell、Common Lisp、Prolog、R、Python 实践）
  - plt 语言实现与理论：解释器、编译器、类型系统、形式化证明、程序语言理论（如 SICP、Crafting Interpreters、PLAI、Software Foundations）
  - systems 系统与网络：操作系统、网络编程、Unix 和 Shell、Linux 内核、消息系统
  - data 数据库：数据库原理、SQL 性能、数据库系统
  - ml 机器学习与 AI：深度学习、统计学习、信息论、NLP、概率编程、经典 AI 编程
  - math 数学与信号：线性代数、优化、信号处理、网络科学这类以数学为主的书
  - graphics 图形与游戏：图形学、着色器、光线追踪、游戏编程、创意编程
  - eng 软件工程：架构、工程实践、运维、开源协作、版本控制、产品开发方法
  - security 安全与密码学

要求：
- 只写有把握的事实。不熟悉这本书时，依据书名、作者、mentions 写得保守一些，不要编造章节、页数、版本或作者经历。
- unfinished 为 true 的，在 summary_zh 里说明还没写完。
- 书名、人名、术语可以保留英文。提到作者时直接写名字，不用“他”“她”。
只输出 JSONL 内容，不要解释。用 Write 工具把结果写到指定的输出文件。
