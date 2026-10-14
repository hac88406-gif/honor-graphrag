# M3 模块说明 — LangGraph 编排层

> 规格书 9.1-1：每个模块交付时附带三段说明（为什么这么设计 / 会被问什么 / 怎么答）。
> 覆盖 `app/agent/`（state / coref / routing / nodes / graph）与 `app/memory/checkpointer.py`，
> 以及 M3 最小骨架 `app/api/chat.py`。

## 1. 为什么这么设计

**为什么用 LangGraph 而不是一串 if/else。**
这不是「用了新框架」，而是规格书 4.8 列了七条必须实际用到的特性，每条都对应一个 if/else 要手写的东西：

| 4.8 特性 | 本项目的落点 | 手写 if/else 的代价 |
| --- | --- | --- |
| 显式 `TypedDict` State | `state.py` 的 `AgentState` | 散装 dict 在节点间传，字段名写错就是**静默丢数据**（不报错） |
| 条件边 | `route_after_intent` / `route_after_confidence` / `route_after_graph_query` | 手写 `if intent == ...: node = ...`，分支一多就是嵌套地狱 |
| 并行分支 | `branches_for` 返回列表 → 图谱与向量同一超步并行 | 手写 `asyncio.gather` + 手写汇聚同步原语 |
| Checkpointer（`thread_id=session_id`） | `AsyncSqliteSaver` | 手写 Redis/文件会话存储：序列化、并发写、恢复全要自己造 |
| 降级节点 | `graph_query` 捕获 `GraphUnavailable` | 手写 try/except 穿透到 API 层，最后变成 500 |
| `astream_events` | `stream_events` 输出节点级事件（5.3 SSE） | 手写回调或事件总线 |
| 可选 `interrupt` | `clarify` 节点的 hitl 分支 | 手写状态机暂停/恢复 |

**并行分支是「返回列表」而不是手写同步。** 条件边路由函数返回 `["graph_query", "vector_search"]` 时，
LangGraph 会在**同一超步**内并行执行这两个节点，而 `fuse` 作为它们的共同下游会等两者都完成才执行一次
（join 语义）。混合类意图（ITEM_BUILD / MATCHUP）因此天然并行，不需要手写 `asyncio.gather` + 汇合计数。

**降级为什么是一条边，而不是节点里的一个 try/except。**
`graph_query` 把 Neo4j 异常收敛成 `degraded=True` 后，**`route_after_graph_query` 才把「降级为纯向量检索」变成真的会执行的动作**：
图谱单路意图（COUNTER_BY / COUNTER_OF / SYNERGY / INSCRIPTION）本来不排 `vector_search`，
若只标记 `degraded` 而不补一条边，链路里根本没有向量检索 —— 用户会因为「图谱没了」被拒答，
而 Chroma 里其实躺着相关攻略文本。这正是「报告声称了降级、实际什么也没做」的静默失败，
所以把降级做成图结构的一部分（可被 `draw_mermaid()` 看见），而不是藏在节点内部的一个标记位。
混合意图的 `vector_search` 已在同一超步跑过，这条边会判断 `intent` 避免重复检索。

**checkpointer 为什么是异步的。**
两个实测约束同时成立：① `astream_events` 是异步接口，会调用 checkpointer 的 `aget_tuple`，
同步 `SqliteSaver` 未实现异步方法 → 流式路径抛 `NotImplementedError`；② LangGraph 在工作线程池里执行节点，
`sqlite3` 连接跨线程复用 → `ProgrammingError`。`aiosqlite` 在内部线程执行 sqlite，一次解决两者，
避免「同步能跑、流式报错」的半可用状态。**代价**：aiosqlite 连接绑定事件循环，
测试里跨事件循环复用会抛 `bound to a different event loop`（见 DECISIONS.md M3 条）。

**为什么不手写 Redis 做多轮记忆。**
`2.3/2.4` 已裁定「最简依赖」：本项目真正的外部依赖只有 Neo4j 一个。多轮状态的并发写入、序列化、
恢复是框架原生能力，手写 Redis 等于把这些重造一遍，还要多引入一个中间件。单机演示场景下
SQLite 文件足够，且可随项目目录一起清理重建（已进 `.gitignore`）。

**指代消解为什么规则优先、且集中在一个模块。**
4.10 明确「禁止依赖把历史塞进 prompt 让模型自己理解」。规则 1（指代词继承实体）在实体链接阶段即可判定；
规则 2/3（简短追问继承意图 / 省略主语继承实体）必须等意图路由给出结果后才能判定。
若把判定逻辑分别写在两个节点里，「指代词集合」「简短阈值」「追问标记」就会有两份定义，
任何一处改动都可能漏改另一处（口径漂移）—— 本项目反复踩过的坑。故集中在 `coref.py`，两节点共用。

**规则 3 是补出来的，不是规格书原文。**
4.10 的必测链「貂蝉怕什么 → 怎么打」是**省略主语**的追问：既无指代词（规则 1 不适用），
意图又能被「怎么打」关键词判定（规则 2 不适用），按两条规则的字面条件都不会继承，但语义上必须继承「貂蝉」。
补的规则加了三个门控（无实体 + 命中意图关键词 + 简短），保证不会把「今天天气怎么样」这类短问句误继承。

**追问标记词刻意不收「怎么」。**
4.10 原文写「含呢/怎么」，但「今天天气怎么样」含「怎么」却是越界问句，收进去会把无关问句误判为追问
并继承上一轮意图（静默串味）。改用「呢 / 还有 / 那么」—— 它们几乎只出现在追问语境，误报面小得多。

**记忆写入为什么有两条「不覆盖」策略。**
否则一句「今天天气怎么样」就会把上一轮的「铠」擦掉，下一轮追问再无实体可继承
—— 「多轮记忆被自己清空」的典型静默失败。且 `ENTITY_UNKNOWN` / `OUT_OF_SCOPE` 不是用户的真实问题类型，
写进 `last_intent` 会让规则 2 继承到一个无意义的值。

**`/api/chat/sync` 为什么本层不包 try/except。**
5.2 明确该接口必须存在（M6 批量评测依赖它）。但降级是 `graph_query` 节点的职责，异常在编排层内部已收敛；
若在 API 层再包一层「Neo4j 异常 → 200」，会把真正的编程错误（如 State 字段拼错）一起吞掉。
M3 验收要的是「Neo4j 断开时返回 200」，这条性质由**编排层的降级**保证，而不是由 API 层的兜底保证。

## 2. 会被问什么

1. 为什么用 LangGraph 而不是一串 if/else？（对应 4.8 的七条特性，逐条说）
2. 并行分支怎么实现的？需要手写同步原语吗？`fuse` 为什么只执行一次？
3. 降级到底降了什么？为什么降级要做成一条条件边，而不是节点里一个标记位？
4. checkpointer 为什么选 SQLite 而不是 Redis？为什么是**异步**实现？
5. 多轮记忆怎么不把自己写坏？（两条「不覆盖」策略）
6. 指代消解为什么规则优先？「怎么打」这种省略主语的追问怎么处理？
7. `hitl` 默认为什么是 False？`interrupt` 怎么 resume？
8. Neo4j 断开时为什么是 200 而不是 500？异常在哪一层被吃掉？

## 3. 怎么答

- **LangGraph vs if/else**：逐条对 4.8 七条特性说落点。要点是「每条特性都替代了一段本来要手写的状态管理/并发/恢复代码」，
  而不是「因为新所以用」。并行分支、checkpointer 恢复、流式事件这三条手写成本最高。
- **并行**：条件边返回**列表**即在同一超步并行；共同下游节点 `fuse` 等两路都完成才执行一次（join），
  不需要手写 `gather` + 计数。混合意图（ITEM_BUILD / MATCHUP）走这条；图谱单路意图退化为单元素列表。
- **降级**：`graph_query` 捕获 `GraphUnavailable` → `degraded=True` + 标注；
  `route_after_graph_query` 判断「降级 + 原意图不含向量路」时**补一次 `vector_search`**，
  否则图谱单路意图降级后链路里没有向量检索，用户会被拒答而知识库里其实有攻略文本。
  混合意图不重复检索。异常在编排层内部收敛，所以 API 层不会 500。
- **checkpointer**：选 SQLite 是「最简依赖」（外部依赖只保留 Neo4j）；选**异步**是因为 `astream_events`
  需要 `aget_tuple`，且节点在线程池执行、sqlite 连接不能跨线程。`thread_id = session_id` 实现按会话隔离记忆。
- **记忆不写坏**：本轮无实体不覆盖 `last_entities`；`ENTITY_UNKNOWN`/`OUT_OF_SCOPE` 不覆盖 `last_intent`。
  否则一次越界提问就把上下文擦掉，下一轮追问失效。
- **指代消解**：规则 1（指代词 → 继承实体）、规则 2（简短追问 + 意图无法判定 → 继承意图、只换实体）、
  规则 3（省略主语 + 意图已判定 + 简短 → 继承实体）。三条规则集中在 `coref.py`，两节点共用一套阈值与词表，
  避免口径漂移。继承动作写入 `coref_resolved` 并在日志打印（4.10 规则 3 要求显式记录）。
- **hitl**：默认 False，澄清直接返回文本；M6 批量跑分不能因为澄清挂起而卡死。`hitl=True` 时
  澄清节点 `interrupt()` 暂停图，`Command(resume=...)` 继续，resume 后 memory 节点照常写入。
- **200 而非 500**：Neo4j 异常在 `graph_query` 节点内被收敛成 `degraded=True`，不穿透到 API 层。
  API 层故意**不**加兜底 try/except —— 那会把 State 字段拼错之类的编程错误一起吞掉。
