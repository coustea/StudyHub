---
name: create-mindmap
description: Generate detailed, complete Markdown mindmaps for course topics. Builds rich hierarchical trees with deep knowledge coverage, weak-point diagnosis, practical examples, and cross-topic extensions. Output goes to `markdown_to_mindmap` for rendering.
---

# Create Mindmap

## Core Principle

Generate **complete, detailed, learning-ready** mindmaps — not outlines, not summaries. Every node should teach something. The goal is a student can study from the mindmap alone.

## Workflow

1. Extract anchors: `topic`, `gap`, `need`, `extra`, profile hints
2. Map out ALL important sub-topics under the given topic — be exhaustive
3. Expand each sub-topic to at least 3 levels of depth with concrete details
4. Add dedicated gap-breaking branch with multi-angle analysis
5. Add practical examples, applications, and cross-domain connections
6. Final quality check: 40+ nodes total, no empty branches

## Structure Requirements

1. **First-level branches**: minimum 5, recommended 6-8
2. **Depth**: at least 4 levels (root → L1 → L2 → L3 → L4), key topics up to 5
3. **Density**: each non-leaf node has 3+ children, core branches have 4-6
4. **Node text**: informative (15-30 chars OK), use parenthetical annotations for clarity
5. **Total nodes**: aim for 40+ for a single topic mindmap

## Output Contract

1. Use exactly one root heading: `# Topic`
2. Use unordered lists only: `- `
3. Two spaces per indentation level
4. No tabs, no numbered lists, no tables, no blockquotes, no code fences
5. No prose before or after the Markdown
6. Node text can include parenthetical notes for clarity

## Map `need` to Structure

- `review`: complete knowledge framework + concept details + key connections + pitfalls + review highlights
- `exam`: high-frequency exam points + problem-solving strategies + common traps + comparison tables + mnemonics
- `deep`: concept essence + principle derivation + mechanism chains + boundary conditions + academic frontiers
- `practice`: workflow details + key steps + code examples + common bugs & debugging + performance tips

**Important**: Regardless of mode, content must be thorough and detailed. "Exam mode" does NOT mean listing only keywords.

## Handle `gap`

1. Create a dedicated deep-analysis branch (3+ levels deep)
2. Break through from multiple angles: definition → principle → comparison → pitfalls → practice advice
3. If gap involves concept confusion, add comparison/contrast sub-nodes
4. If gap is empty or "无", evenly deepen all branches instead

## Extension Requirements

Every mindmap MUST include these extension branches:

- **Prerequisites**: what foundation is needed to understand this topic
- **Advanced**: what advanced topics this leads to
- **Cross-domain**: connections to other subjects/fields
- **Frontier**: latest developments or research directions in this area

Extensions should be naturally integrated, with 2-4 levels of detail each.

## Node Writing Rules

Good nodes (specific, informative):
- "栈遵循后进先出原则(LIFO)"
- "数组实现的队列可能产生假溢出"
- "async/await只能在async函数中使用"
- "事件循环在多个任务间切换执行"

Bad nodes (vague, empty):
- "基本概念"
- "其他补充"
- "相关内容"
- "一些特点"

## Quality Bar

Before rendering, verify:

1. All important sub-topics are covered — no significant omissions
2. Each branch is deep enough — not just listing names but explaining content
3. Gap branch provides substantive help
4. Extensions connect naturally to core knowledge
5. Total node count reaches 40+
6. Markdown is clean and ready for `markdown_to_mindmap`

## Reference Example

# 异步编程 (Asyncio)
- 基本概念
  - 什么是异步编程
    - 并发 vs 并行的本质区别
    - 异步适合I/O密集型任务
    - 同步代码的可读性优势
  - 为什么需要异步
    - 阻塞式I/O的性能瓶颈
    - 高并发场景下的资源浪费
    - 事件驱动模型的效率优势
- 核心组件
  - 事件循环 (Event Loop)
    - 负责调度和执行所有异步任务
    - 持续运行直到所有任务完成
    - 可嵌套使用(子事件循环)
  - 协程 (Coroutine)
    - 用async def定义的函数
    - 必须通过await调用才能执行
    - 挂起时释放控制权给事件循环
  - Task 与 Future
    - Task是协程的包装器，用于并发调度
    - Future代表一个未来的运算结果
    - asyncio.create_task()立即调度执行
  - 常用API
    - asyncio.gather()并发运行多个协程
    - asyncio.wait()支持更灵活的等待策略
    - asyncio.run()运行顶层入口协程
- 关键语法
  - async/await 关键字
    - async声明协程函数
    - await挂起当前协程等待结果
    - await只能在async函数中使用
  - 异步上下文管理器 (async with)
    - 用于管理异步资源的获取与释放
    - 如aiohttp.ClientSession()
  - 异步迭代器 (async for)
    - 用于遍历异步数据流
    - 如数据库游标的逐行读取
- 难点突破：并发模型理解
  - 单线程为何能并发
    - 协程在I/O等待时主动让出CPU
    - 事件循环在多个任务间切换执行
    - 本质是协作式多任务而非抢占式
  - 异步与多线程的选择
    - CPU密集型用多进程(ProcessPool)
    - I/O密集型用异步(asyncio)
    - 混合型可组合使用
  - 常见陷阱
    - 忘记await导致协程未执行
    - 在异步代码中调用同步阻塞函数
    - 异步函数中捕获异常需要特别处理
- 应用场景
  - Web框架：FastAPI原生支持异步
  - 网络请求：aiohttp异步HTTP客户端
  - 数据库：asyncpg/sqlalchemy异步引擎
  - 爬虫：异步抓取大幅提升效率
- 知识拓展
  - 前置：迭代器、生成器、yield关键字
  - 进阶：消息队列、分布式异步任务(Celery)
  - 关联：Node.js事件循环、Go协程(goroutine)
  - 前沿：结构化并发(Structured Concurrency)
