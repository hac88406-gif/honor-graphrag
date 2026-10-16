"""LangGraph 编排层状态定义（规格书 4.8-1 State 字段 + 4.10 多轮记忆三项）。

**为什么用显式 TypedDict 而不是自由 dict**（4.8-1 的「为什么用 LangGraph」答案之一）：
State 是图内各节点的唯一契约。写成 TypedDict 后，字段名/类型在编辑期即可被静态检查，
且 LangGraph 会为每个键建立独立 channel —— 节点返回的局部更新会被合并进总 State，
而不是各节点各自维护一份散装上下文（后者一旦字段名写错就是**静默丢数据**，不报错）。

**`total=False`**：所有字段可选。节点只返回自己负责的局部更新（LangGraph 的合并语义是
「缺省键保持原值」），若声明为必填，任一节点返回局部 dict 都会被判定为字段缺失。

记忆三项（`last_entities` / `last_intent` / `last_topic`）是 4.10 明确要求「在 State 中持久化」
的字段：它们由 `memory` 节点在每轮末尾写入，经 checkpointer（thread_id = session_id）
跨轮保留，供下一轮的指代消解读取。这是 SqliteSaver 替代手写 Redis 的落点。
"""
from __future__ import annotations

from typing import TypedDict

from app.schemas.chat import Citation, Evidence
from app.schemas.entity import LinkedEntity


class AgentState(TypedDict, total=False):
    # ---------- 输入 ----------
    question: str
    session_id: str
    # 可选 human-in-the-loop（规格书 4.8-7）：True 时澄清节点用 interrupt 暂停等用户补充。
    # 默认 False —— M6 评测脚本批量跑分必须走非交互路径（否则每条澄清都会挂起）。
    hitl: bool

    # ---------- [0] 实体链接（4.2 步骤 0） ----------
    entities: list[LinkedEntity]
    unrecognized: list[str]

    # ---------- 指代消解（4.10） ----------
    # 显式记录继承动作（4.10 规则 3「必须在日志中显式记录」），便于排查与 M6 评测归因。
    coref_resolved: str | None
    # 本轮实际用于检索/路由的问句（消解后形态）；仅作日志与调试用，路由仍以原问句为准。
    resolved_question: str

    # ---------- [1] 意图与槽位（4.2 步骤 1） ----------
    intent: str
    slots: dict
    need_clarify: bool
    intent_method: str            # rule | llm
    # 本轮命中的全部意图（按优先级序，M2 条件三）；用于 M6 归因「答案不全」。
    matched_intents: list[str]
    # 澄清类型标记（D1 缺陷 L3）：4.4 的意图枚举封闭、实现方不得新增取值，故用标记而非新意图
    # 表达「用户想查英雄之间的关系但没说方向」。取值见 `app/retrieval/intent.IntentResult.clarify_kind`：
    #   "" / "counter_direction"（反问克制方向）/ "relation_direction"（反问要哪种关系）。
    clarify_kind: str

    # ---------- [2] 检索（4.2 步骤 2） ----------
    graph_evidence: list[Evidence]
    vector_evidence: list[Evidence]
    # Neo4j 可达性：False 表示本轮走了降级（4.8-5 不允许抛 500）。
    graph_available: bool
    degraded: bool
    degradation_note: str | None

    # ---------- [3] 融合（4.2 步骤 3） ----------
    evidence: list[Evidence]
    # 向量侧 top1 相似度（4.9 三档判定的输入之一）；无向量证据时为 None。
    top_score: float | None

    # ---------- [4] 置信度三档（4.9） ----------
    confidence: float
    response_type: str            # answer | low_confidence | reject | clarify
    clarify_options: list[str]

    # ---------- [5] 生成（4.2 步骤 5） ----------
    answer: str
    citations: list[Citation]
    # 生成层留痕（M4）：mode / 模型名 / finish_reason / completion_tokens（含思考）/
    # reasoning_tokens / guard 结果 / 是否回落。这些都是「错了也不报错」的环节，
    # 不给出来就只能靠猜 —— 经 debug 字段对外暴露（仅 DEBUG=1）。
    generation_info: dict

    # ---------- [6] 记忆（4.2 步骤 6 / 4.10，经 checkpointer 跨轮保留） ----------
    last_entities: list[str]      # 上一轮识别到的规范实体 ID
    last_intent: str              # 上一轮意图
    last_topic: str               # 上一轮话题类型：graph / vector / hybrid / none

    # ---------- 兜底 ----------
    error: str | None
