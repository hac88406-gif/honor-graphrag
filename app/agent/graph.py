"""LangGraph 编排图组装（规格书 4.8 七条特性）。

七条特性与本文件的对应关系（这是「为什么用 LangGraph 而不是 if/else」的答案清单）：
  1. StateGraph + 显式 TypedDict State  -> `app/agent/state.py` 的 `AgentState`
  2. 条件边 `add_conditional_edges`      -> `route_after_intent` / `route_after_confidence`
  3. 并行分支（混合意图下图谱与向量并行） -> `route_after_intent` 返回**列表**（LangGraph 在同一超步并行执行）
  4. Checkpointer 持久化（thread_id=session_id）-> `app/memory/checkpointer.py`
  5. 降级节点（Neo4j 失败不抛 500）      -> `app/agent/nodes/graph_query.py`
  6. 流式事件（4.8-6）                      -> `stream_events`
     **实现偏离**：4.8-6 原文写 `astream_events`，但实测（LangGraph 1.2.15）该接口**拿不到
     节点内 `get_stream_writer()` 推的自定义事件**，故改用 `astream(stream_mode=["custom","updates","debug"])`。
     偏离已登记 DECISIONS.md（2026-10-15 M4 条），对 SSE 协议（5.3）无影响。
  7. 可选 human-in-the-loop `interrupt`  -> `app/agent/nodes/clarify.py`（hitl=True 时生效）

图结构（与 `draw_mermaid()` 导出一致，README 用）：

    START -> entity_linking -> intent_routing
    intent_routing --条件边--> graph_query / vector_search（并行）/ clarify / reject
    graph_query & vector_search -> fuse -> confidence
    confidence --条件边--> generate / reject
    generate / clarify / reject -> memory -> END
"""
from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from langgraph.graph import END, START, StateGraph

from app.agent.nodes.clarify import clarify_node, reject_node
from app.agent.nodes.confidence import confidence_node
from app.agent.nodes.entity_linking import entity_linking_node
from app.agent.nodes.fuse import fuse_node
from app.agent.nodes.generate import generate_node
from app.agent.nodes.graph_query import graph_query_node
from app.agent.nodes.intent import intent_node
from app.agent.nodes.memory import memory_node
from app.agent.nodes.vector_search import vector_search_node
from app.agent.routing import HYBRID_INTENTS, branches_for
from app.agent.state import AgentState
from app.memory.checkpointer import get_checkpointer

logger = logging.getLogger(__name__)

# 节点名常量：流式事件（5.3 SSE 协议）与 mermaid 导出都按这些名字对齐。
# 写成常量而非散落字符串，避免改名时出现「事件名改了、图里没改」的不一致。
NODE_ENTITY = "entity_linking"
NODE_INTENT = "intent_routing"
NODE_GRAPH = "graph_query"
NODE_VECTOR = "vector_search"
NODE_FUSE = "fuse"
NODE_CONFIDENCE = "confidence"
NODE_GENERATE = "generate"
NODE_CLARIFY = "clarify"
NODE_REJECT = "reject"
NODE_MEMORY = "memory"

NODE_NAMES: tuple[str, ...] = (
    NODE_ENTITY, NODE_INTENT, NODE_GRAPH, NODE_VECTOR,
    NODE_FUSE, NODE_CONFIDENCE, NODE_GENERATE, NODE_CLARIFY, NODE_REJECT, NODE_MEMORY,
)

# 每个 token 帧最多这么多字（与 generate 节点的 _emit_text 取同一粒度）：
# 5.3 的示例是「一帧一小段文本」，整段一次推给前端就只剩「一次性显示」，不是流式。
_TOKEN_CHUNK = 8

# 条件边的候选目标（path_map 用列表声明，返回列表即并行）
_AFTER_INTENT_TARGETS = [NODE_GRAPH, NODE_VECTOR, NODE_CLARIFY, NODE_REJECT]
_AFTER_GRAPH_TARGETS = [NODE_VECTOR, NODE_FUSE]
_AFTER_CONFIDENCE_TARGETS = [NODE_GENERATE, NODE_REJECT]


# ---------------------------------------------------------------- 条件边路由


def route_after_intent(state: AgentState) -> list[str] | str:
    """意图 -> 检索分支（4.8-2 条件边 / 4.8-3 并行）。

    返回**列表**时 LangGraph 在同一超步并行执行这些节点（混合意图下图谱与向量并行）。
    澄清与拒答在检索**之前**分流：实体没认出来时不该白跑一趟检索（4.3/4.9）。
    """
    intent = state.get("intent", "")
    if state.get("need_clarify") or intent == "ENTITY_UNKNOWN":
        return NODE_CLARIFY
    if intent == "OUT_OF_SCOPE":
        return NODE_REJECT

    branches = branches_for(intent)
    # 分支表没覆盖到的意图（理论上不存在，枚举封闭）也不允许静默卡住：走 fuse 让置信度层兜底
    return branches or NODE_FUSE


def route_after_confidence(state: AgentState) -> str:
    """置信度 -> 生成 / 拒答（4.9：拒答判定由确定性规则给出，此处只按结果分流）。"""
    return NODE_REJECT if state.get("response_type") == "reject" else NODE_GENERATE


def route_after_graph_query(state: AgentState) -> str:
    """图谱查询 -> 融合 / 向量兜底（4.8-5「降级为纯向量检索」的落点）。

    **为什么降级要在这里补一条边**：意图分两路（4.4 主路径列）——图谱单路
    （COUNTER_BY/COUNTER_OF/SYNERGY/INSCRIPTION）与混合路（ITEM_BUILD/MATCHUP）。
    图谱单路意图**本来不排 vector_search**，所以 Neo4j 一断，`degraded=True` 只是把
    `graph_evidence` 清空，链路里根本没有向量检索 —— 「降级为纯向量检索」等于没落地，
    用户会因为「图谱没了」而被拒答，而 Chroma 里其实躺着相关攻略文本。
    这条边把「降级」变成真的会执行的动作：
      - 混合意图：vector_search 已在同一超步并行跑过 -> 直接进 fuse（不重复检索）；
      - 图谱单路意图：补一次 vector_search -> fuse。
    """
    if state.get("degraded") and state.get("intent") not in HYBRID_INTENTS:
        return NODE_VECTOR
    return NODE_FUSE


# ---------------------------------------------------------------- 图组装


def build_graph(checkpointer: Any = None):
    """组装并编译编排图。

    checkpointer 为 None 时编译出无记忆版本（仅用于画图/结构测试）；
    生产与多轮测试必须传入 checkpointer，否则 `last_*` 记忆不跨轮保留。
    """
    graph = StateGraph(AgentState)

    graph.add_node(NODE_ENTITY, entity_linking_node)
    graph.add_node(NODE_INTENT, intent_node)
    graph.add_node(NODE_GRAPH, graph_query_node)
    graph.add_node(NODE_VECTOR, vector_search_node)
    graph.add_node(NODE_FUSE, fuse_node)
    graph.add_node(NODE_CONFIDENCE, confidence_node)
    graph.add_node(NODE_GENERATE, generate_node)
    graph.add_node(NODE_CLARIFY, clarify_node)
    graph.add_node(NODE_REJECT, reject_node)
    graph.add_node(NODE_MEMORY, memory_node)

    graph.add_edge(START, NODE_ENTITY)
    graph.add_edge(NODE_ENTITY, NODE_INTENT)

    # 条件边：按 intent 分流；返回列表即并行（4.8-2 / 4.8-3）
    graph.add_conditional_edges(NODE_INTENT, route_after_intent, _AFTER_INTENT_TARGETS)

    # 图谱查询后：正常进 fuse；降级（Neo4j 不可用）且原意图不含向量路时补一次向量检索
    graph.add_conditional_edges(NODE_GRAPH, route_after_graph_query, _AFTER_GRAPH_TARGETS)
    graph.add_edge(NODE_VECTOR, NODE_FUSE)
    graph.add_edge(NODE_FUSE, NODE_CONFIDENCE)

    graph.add_conditional_edges(NODE_CONFIDENCE, route_after_confidence, _AFTER_CONFIDENCE_TARGETS)

    for terminal in (NODE_GENERATE, NODE_CLARIFY, NODE_REJECT):
        graph.add_edge(terminal, NODE_MEMORY)
    graph.add_edge(NODE_MEMORY, END)

    return graph.compile(checkpointer=checkpointer)


_compiled = None


async def get_graph():
    """进程级编译单例（带 checkpointer，供 FastAPI 与流式使用）。"""
    global _compiled
    if _compiled is None:
        _compiled = build_graph(await get_checkpointer())
    return _compiled


async def reset_graph() -> None:
    """丢弃编译单例（checkpointer 变更或测试后调用）。"""
    global _compiled
    _compiled = None


# ---------------------------------------------------------------- 调用入口


def _config(session_id: str) -> dict:
    # 4.8-4：thread_id = session_id，多轮记忆按会话隔离
    return {"configurable": {"thread_id": session_id}}


async def run(question: str, session_id: str, *, hitl: bool = False) -> dict:
    """同步跑完一轮，返回最终 State（`/api/chat/sync` 用）。

    hitl=False（默认）：澄清直接返回文本，不暂停图 —— M6 评测批量跑分依赖这条路径。
    """
    graph = await get_graph()
    return await graph.ainvoke(
        {"question": question, "session_id": session_id, "hitl": hitl},
        _config(session_id),
    )


async def stream_events(question: str, session_id: str, *, hitl: bool = False) -> AsyncIterator[dict]:
    """编排层 -> 规格书 5.3 的 SSE 事件（节点级 + 生成层自定义事件）。

    **为什么不用 `astream_events`**：实测（LangGraph 1.2.15）`astream_events(version="v2")`
    只暴露框架内建事件，**拿不到节点内用 `get_stream_writer()` 推的自定义事件**（thinking / token）。
    改用 `astream(stream_mode=["custom","updates","debug"])` 三路合一：
      - `custom`  —— 节点内推送的事件（generate 节点的 thinking / token）；
      - `debug`   —— 节点启动边界（type == "task" 且 payload.name 是节点名）-> node_start；
      - `updates` —— 节点输出增量（fuse 的 evidence）-> evidence。

    事件映射：
      debug(task)          -> node_start
      custom(thinking)     -> thinking（「正在思考」，**不含思考正文**）
      custom(token)        -> token（LLM 路径下逐段推送，前缀行先推）
      updates(fuse)        -> evidence（逐条推送来源）
      结束时               -> token（template 路径整段答案）/ citation / done
    """
    graph = await get_graph()
    config = _config(session_id)
    inputs = {"question": question, "session_id": session_id, "hitl": hitl}

    async for mode, chunk in graph.astream(inputs, config, stream_mode=["custom", "updates", "debug"]):
        if mode == "custom":
            # 节点内自定义事件已经是 5.3 的 {"event":..., "data":...} 形态，直接透传
            if isinstance(chunk, dict) and chunk.get("event"):
                yield chunk
        elif mode == "debug":
            payload = chunk.get("payload") or {}
            if chunk.get("type") == "task" and payload.get("name") in NODE_NAMES:
                yield {"event": "node_start", "data": {"node": payload["name"]}}
        elif mode == "updates":
            for node, output in (chunk or {}).items():
                if node == NODE_FUSE and isinstance(output, dict):
                    for e in output.get("evidence", []):
                        payload = e.model_dump() if hasattr(e, "model_dump") else e
                        yield {"event": "evidence", "data": {"evidence": payload}}

    # 终态从 checkpointer 取：末尾节点（memory）只返回记忆增量，拿不到 answer/citations
    snapshot = await graph.aget_state(config)
    values = snapshot.values or {}
    info = values.get("generation_info") or {}
    # LLM 路径下正文已由 generate 节点逐段推送（含前缀行），此处不得重复推送整段答案
    if values.get("answer") and not info.get("streamed"):
        # template 路径（或 llm 回落）的整段答案在此处按小块推：一帧整段不算流式（5.3 是逐段）。
        # 这里推的是**终态 answer**，已经过 generate 节点组装/校验，不存在「未校验内容先到前端」。
        answer_text = values["answer"]
        for i in range(0, len(answer_text), _TOKEN_CHUNK):
            yield {"event": "token", "data": {"text": answer_text[i:i + _TOKEN_CHUNK]}}
    yield {
        "event": "citation",
        "data": {"citations": [c.model_dump() for c in values.get("citations", [])]},
    }
    yield {
        "event": "done",
        "data": {
            "type": values.get("response_type"),
            "confidence": values.get("confidence"),
            # 生成层是否回落到确定性组装（M4 新增字段，便于前端/评测看到「这次不是模型答的」）
            "fallback": bool(info.get("fallback")),
            "generation_mode": info.get("mode"),
            # 澄清候选（M5 新增字段）：type == "clarify" 时前端要渲染成可点选的问题，
            # 只靠 5.3 原协议的 done（type/confidence）拿不到候选，前端就无法差异化渲染澄清。
            "clarify_options": list(values.get("clarify_options") or []),
            "intent": values.get("intent") or "",
        },
    }


def draw_mermaid(*, checkpointer: Any = None) -> str:
    """导出图结构的 Mermaid 文本（M3 验收项；README 的架构图用它）。"""
    return build_graph(checkpointer).get_graph().draw_mermaid()
