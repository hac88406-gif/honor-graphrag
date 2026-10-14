"""M3 集成测试 —— 多轮追问四条链 / 指代消解 / 记忆 / 多意图留痕 / 图结构导出。

对应规格书 M3 验收（1026-1028）：
  - 多轮追问**四条测试链全部通过**（4.10 原文给定的四条）；
  - 图结构可用 `graph.get_graph().draw_mermaid()` 导出（README 要用）。
Neo4j 断开降级（M3 验收第三条）见 `tests/integration/test_graph_degrade.py`。

**断言的是语义结果**（继承到的实体 / 意图 / 槽位 / 响应类型 / 记忆字段），
不是节点调用次数——节点执行顺序由 `app/agent/graph.py` 的结构决定，
用 `draw_mermaid` 的结构断言（本文件末）覆盖，避免把实现细节写进测试。
"""
from __future__ import annotations

import pytest

from app.agent.graph import build_graph, draw_mermaid


def _names(state: dict) -> list[str]:
    return [e.canonical_name for e in state.get("entities") or []]


def _ids(state: dict) -> list[str]:
    return [e.canonical_id for e in state.get("entities") or []]


# ---------------------------------------------------------------- 四条链


async def test_chain1_kai_counter_by_then_inscription(ask):
    """链1（4.10）：「铠被谁克制」→「那铭文呢」——同一实体，跨意图。"""
    sid = "chain1"

    s1 = await ask(sid, "铠被谁克制")
    assert s1["intent"] == "COUNTER_BY"
    assert _names(s1) == ["铠"]
    assert s1["last_entities"] == _ids(s1)
    assert s1["last_topic"] == "graph"

    s2 = await ask(sid, "那铭文呢")
    # 追问句自带「铭文」关键词 -> 意图必须被重新判定为 INSCRIPTION（跨意图），
    # 而不是沿用上一轮的 COUNTER_BY —— 这是「只替换实体」与「换意图」的区分点。
    assert s2["intent"] == "INSCRIPTION"
    assert _names(s2) == ["铠"], "指代词「那」应继承上一轮实体"
    assert s2["slots"]["hero"] == _ids(s1)[0]
    assert s2["coref_resolved"], "4.10 规则3：继承必须在日志中显式记录"
    assert "规则1" in s2["coref_resolved"]
    assert "铠" in s2["resolved_question"]


async def test_chain2_arthur_item_build_then_counter_by(ask):
    """链2（4.10）：「亚瑟怎么出装」→「那他怕谁」——同一实体，跨检索路径。"""
    sid = "chain2"

    s1 = await ask(sid, "亚瑟怎么出装")
    assert s1["intent"] == "ITEM_BUILD"
    assert _names(s1) == ["亚瑟"]
    assert s1["last_topic"] == "hybrid", "ITEM_BUILD 是混合意图（图谱+文本）"

    s2 = await ask(sid, "那他怕谁")
    assert s2["intent"] == "COUNTER_BY"
    assert _names(s2) == ["亚瑟"], "指代词「他」应继承上一轮实体"
    assert s2["slots"]["hero"] == _ids(s1)[0]
    assert s2["last_topic"] == "graph", "检索路径从 hybrid 切到 graph（仅图谱侧）"
    assert "规则1" in (s2["coref_resolved"] or "")


async def test_chain3_diaochan_counter_by_then_matchup_ellipsis(ask):
    """链3（4.10）：「貂蝉怕什么」→「怎么打」——省略主语。

    「怎么打」既无指代词（规则 1 不适用）、意图又能被关键词判定（规则 2 不适用），
    但语义上必须继承实体「貂蝉」，故由 `app/agent/coref.py` 补充的规则 3 处理。
    继承到的「貂蝉」是 MATCHUP 的**敌方**槽位；缺我方英雄 -> 4.3 要求澄清反问（不是拒答）。
    """
    sid = "chain3"

    s1 = await ask(sid, "貂蝉怕什么")
    assert s1["intent"] == "COUNTER_BY"
    assert _names(s1) == ["貂蝉"]

    s2 = await ask(sid, "怎么打")
    assert s2["intent"] == "MATCHUP"
    assert _names(s2) == ["貂蝉"], "省略主语应继承上一轮实体"
    assert s2["slots"]["hero_enemy"] == _ids(s1)[0]
    assert "hero_ally" not in s2["slots"]
    assert "规则3" in (s2["coref_resolved"] or "")
    # 只有敌方 -> 澄清（4.3/4.9：槽位不完整走澄清，绝不走拒答）
    assert s2["need_clarify"] is True
    assert s2["response_type"] == "clarify"
    assert "貂蝉" in s2["answer"]


async def test_chain4_donghuang_then_pronoun_counter_of(ask):
    """链4（4.10）：「东皇太一」→「他克制谁」——纯指代。"""
    sid = "chain4"

    s1 = await ask(sid, "东皇太一")
    assert s1["intent"] == "ENTITY_UNKNOWN", "有实体、无意图 -> 澄清（不是拒答）"
    assert s1["response_type"] == "clarify"
    assert s1["last_entities"] == _ids(s1)
    # ENTITY_UNKNOWN 不是用户的真实问题类型，不得写回 last_intent（否则规则 2 会继承到无意义值）
    assert s1.get("last_intent") is None

    s2 = await ask(sid, "他克制谁")
    assert s2["intent"] == "COUNTER_OF"
    assert _names(s2) == ["东皇太一"], "纯指代应继承上一轮实体"
    assert s2["slots"]["hero"] == _ids(s1)[0]
    assert "规则1" in (s2["coref_resolved"] or "")


# ---------------------------------------------------------------- 记忆策略


async def test_memory_isolated_across_sessions(ask):
    """thread_id = session_id（4.8-4）：新会话不得继承别的会话的记忆。

    「那他呢」在**有**上一轮意图的会话里继承意图，在**新**会话里因无上下文而落 OUT_OF_SCOPE。
    同一问句、两种结果 —— 这正是「记忆确实按会话隔离」的证据。
    """
    s1 = await ask("iso-a", "铠被谁克制")
    assert s1["intent"] == "COUNTER_BY"

    follow = await ask("iso-a", "那他呢")
    assert follow["intent"] == "COUNTER_BY", "同会话：规则 2 继承上一轮意图"
    assert _names(follow) == ["铠"]
    assert "规则2" in (follow["coref_resolved"] or "")

    fresh = await ask("iso-b", "那他呢")
    assert fresh["intent"] == "OUT_OF_SCOPE", "新会话无上一轮记忆 -> 无法继承，落越界"
    assert fresh["response_type"] == "reject"
    assert _names(fresh) == []
    assert fresh.get("last_entities") is None


async def test_memory_not_cleared_by_out_of_scope_turn(ask):
    """越界/无实体的一轮不得清空上一轮记忆（`memory` 节点的两条写入策略）。

    否则一句「今天天气怎么样」就会把「铠」擦掉，下一轮追问再无实体可继承
    —— 这是「多轮记忆被自己清空」的典型静默失败。
    """
    sid = "keepmem"
    s1 = await ask(sid, "铠被谁克制")
    kai_id = _ids(s1)[0]

    s2 = await ask(sid, "今天天气怎么样")
    assert s2["response_type"] == "reject"
    assert s2.get("last_entities") == [kai_id]
    assert s2.get("last_intent") == "COUNTER_BY"
    assert s2.get("last_topic") == "graph"

    s3 = await ask(sid, "那铭文呢")
    assert _names(s3) == ["铠"], "越界那一轮之后仍能继承到「铠」"


# ---------------------------------------------------------------- 多意图留痕


async def test_multi_intent_is_recorded(ask):
    """M2 审核条件三：多意图命中必须留痕（matched_intents），当前只取第一个、不做合并。

    「铠的出装和铭文」同时命中 ITEM_BUILD 与 INSCRIPTION。若不记录，用户只拿到半个答案
    而系统毫不知情 —— 属静默失败。此处断言两者都在 `matched_intents` 里可见。
    """
    s = await ask("multi", "铠的出装和铭文")
    matched = s["matched_intents"]
    assert {"ITEM_BUILD", "INSCRIPTION"} <= set(matched), f"多意图必须留痕：{matched}"
    assert s["intent"] == matched[0], "当前策略：主意图取优先级最高者（未做合并）"
    assert s["intent_method"] == "rule", "默认走规则路径（M2 审核裁定「规则优先」）"


# ---------------------------------------------------------------- 图结构导出


def test_draw_mermaid_contains_core_structure():
    """M3 验收：图结构可用 draw_mermaid 导出；节点与条件边逐条对齐 `graph.py` 的注释图。"""
    m = draw_mermaid()
    assert "graph TD" in m

    # 主干
    assert "__start__ --> entity_linking" in m
    assert "entity_linking --> intent_routing" in m

    # 条件边（虚线）：intent_routing 按 intent 分发到四个分支
    for target in ("graph_query", "vector_search", "clarify", "reject"):
        assert f"intent_routing -.-> {target}" in m

    # 并行两路汇聚到 fuse（4.8-3）；图谱查询后按是否降级走 fuse 或补一次向量检索（4.8-5）
    assert "graph_query -.-> fuse" in m
    assert "graph_query -.-> vector_search" in m
    assert "vector_search --> fuse" in m
    assert "fuse --> confidence" in m

    # 条件边：置信度 -> 生成 / 拒答
    assert "confidence -.-> generate" in m
    assert "confidence -.-> reject" in m

    # 三个终态节点都写记忆后结束（4.10）
    for terminal in ("generate", "clarify", "reject"):
        assert f"{terminal} --> memory" in m
    assert "memory --> __end__" in m


def test_graph_object_exportable():
    """验收原文要求的是 `graph.get_graph().draw_mermaid()` 这条调用链本身可用。"""
    compiled = build_graph(None)
    mermaid = compiled.get_graph().draw_mermaid()
    assert "intent_routing" in mermaid and "memory" in mermaid


# ---------------------------------------------------------------- human-in-the-loop


async def test_hitl_interrupt_then_resume(graph):
    """4.8-7 加分项：hitl=True 时澄清节点用 interrupt 暂停，Command(resume=...) 继续。"""
    from langgraph.types import Command

    sid = "hitl-on"
    cfg = {"configurable": {"thread_id": sid}}
    paused = await graph.ainvoke({"question": "东皇太一", "session_id": sid, "hitl": True}, cfg)

    assert "__interrupt__" in paused, "hitl=True 时澄清必须暂停图执行"
    payload = paused["__interrupt__"][0].value
    assert payload["type"] == "clarify"
    assert payload["options"], "澄清必须给候选，否则用户无法继续"
    assert "东皇太一" in payload["question"]

    resumed = await graph.ainvoke(Command(resume="貂蝉"), cfg)
    assert resumed["response_type"] == "clarify"
    assert "已收到补充：貂蝉" in resumed["answer"]
    # resume 后 memory 节点已执行，记忆照常写入
    assert resumed["last_entities"] == _ids(resumed)


async def test_default_path_does_not_interrupt(ask):
    """默认 hitl=False：澄清直接返回文本，不暂停图。

    M6 评测脚本批量跑分依赖这条路径 —— 若每条澄清都挂起，评测会卡死。
    """
    s = await ask("hitl-off", "东皇太一")
    assert "__interrupt__" not in s
    assert s["response_type"] == "clarify"
    assert "东皇太一" in s["answer"]
    assert s["clarify_options"]
