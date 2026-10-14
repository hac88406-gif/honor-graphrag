"""LangGraph 编排层（规格书 4.8 / 附录 A）。

分层：
  - `state.py`   —— AgentState TypedDict（节点间唯一契约）
  - `nodes/`     —— 各节点实现（实体链接 / 意图 / 图谱 / 向量 / 融合 / 置信 / 生成 / 澄清 / 记忆）
  - `graph.py`   —— StateGraph 组装（条件边 / 并行分支 / checkpointer / 降级 / 流式 / mermaid 导出）

本包只做**编排**：检索与实体链接复用 `app.retrieval`，记忆复用 `app.memory`。
不在本层重复实现检索逻辑，避免同一口径出现两份实现（本项目的历史教训）。
"""
