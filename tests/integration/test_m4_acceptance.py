"""M4 验收的编排级用例（规格书 M4 验收三条）。

M4 验收原文：「拒答用例（问不存在英雄 / 问知识库未收录内容 / 问无关话题）三种都正确触发
对应分支；答案中的英雄名全部能在 evidence 中找到；`type` 字段取值正确。」

三条拒答/澄清路径分别对应三种**不同**分支，混为一谈是典型误读（9.2-5 明令禁止
「实体未识别时走拒答」）：
  - 问不存在英雄     -> **澄清**（给候选让用户挑，绝不拒答）
  - 问知识库未收录   -> 拒答（无依据档）
  - 问无关话题       -> 拒答（OUT_OF_SCOPE）

「知识库未收录」用 monkeypatch 把两条检索路径都打成空来实现 —— 比真去找一个「恰好没数据」
的问句更可控、更可重复（同 test_graph_degrade.py 的做法）。
"""
from __future__ import annotations

import pytest

from app.schemas.chat import Evidence

GRAPH_EV = Evidence(
    kind="graph", content="兰陵王 克制 铠：兰陵王隐身突进，铠难反制", source="official",
    relation="COUNTERS", patch="2026-10", hero_ids=["153", "166"],
)


@pytest.fixture
def retrieval_stubbed(monkeypatch):
    """把图谱与向量检索都换成可控输入（不依赖 Neo4j / Chroma，结果确定）。"""
    def _install(*, graph: list[Evidence], vector: list[Evidence]):
        monkeypatch.setattr("app.agent.nodes.graph_query.query_evidence",
                            lambda template, **kw: list(graph))
        monkeypatch.setattr("app.agent.nodes.vector_search.hybrid_search",
                            lambda question, **kw: list(vector))
    return _install


# ---------------------------------------------------------------- 三种分支

async def test_unknown_hero_triggers_clarify_not_reject(graph, ask):
    """问不存在英雄 -> **澄清**（4.3 / 9.2-5：实体未识别必须澄清反问）。"""
    s = await ask("m4-unknown", "赛博坦这个英雄怎么样")

    assert s["intent"] == "ENTITY_UNKNOWN"
    assert s["response_type"] == "clarify"
    assert s["clarify_options"], "澄清必须给候选，否则用户无法继续"
    assert s["answer"], "澄清必须给出反问文案"


async def test_unindexed_content_triggers_reject(graph, ask, retrieval_stubbed):
    """问知识库未收录内容（检索两路皆空）-> 拒答，并给出可替代的提问方向。"""
    retrieval_stubbed(graph=[], vector=[])
    s = await ask("m4-unindexed", "铠被谁克制")

    assert s["response_type"] == "reject"
    assert s["evidence"] == []
    assert "换一种问法" in s["answer"] or "换一个英雄" in s["answer"]


async def test_out_of_scope_triggers_reject(graph, ask):
    """问无关话题 -> 拒答（OUT_OF_SCOPE，全程不碰检索）。"""
    s = await ask("m4-oos", "今天天气怎么样")

    assert s["intent"] == "OUT_OF_SCOPE"
    assert s["response_type"] == "reject"
    assert s["citations"] == []


async def test_type_field_values_are_legal(graph, ask, retrieval_stubbed):
    """`type` 字段取值必须在 5.1 的封闭枚举内（answer/low_confidence/reject/clarify）。"""
    retrieval_stubbed(graph=[GRAPH_EV], vector=[])
    s = await ask("m4-type", "铠被谁克制")
    assert s["response_type"] in {"answer", "low_confidence", "reject", "clarify"}


# ---------------------------------------------------------------- 答案可溯源

async def test_answer_hero_names_all_traceable_to_evidence(graph, ask, retrieval_stubbed):
    """M4 验收：答案中的英雄名全部能在 evidence 中找到（4.9 生成约束第一条）。

    生成节点是确定性组装，答案只由 evidence 摘录而来 —— 此处对**编排后**的最终答案再断言一次，
    确保后续接线（前缀行、多意图告知等）不会引入 evidence 之外的英雄名。
    """
    from app.retrieval.entity_linking import link

    retrieval_stubbed(graph=[GRAPH_EV], vector=[])
    s = await ask("m4-trace", "铠被谁克制")

    corpus = "\n".join(e.content for e in s["evidence"]) + s["question"]
    names = [e.canonical_name for e in link(s["answer"]).entities if e.entity_type == "hero"]
    assert names, "答案里应至少出现一个英雄名"
    for name in names:
        assert name in corpus, f"答案出现 evidence 之外的英雄名：{name}"


async def test_deterministic_answer_lines_are_verbatim_evidence(graph, ask, retrieval_stubbed):
    """确定性组装的每一行都必须是 evidence 的**原文摘录**（构造上不可能引入外部事实）。

    注意：这里**不**对组装结果跑生成后校验（guard）—— 资料原文里的原因说明（如
    「铠怕高爆发法师」）被原样摘录是允许的，它带着「谁克制谁：原因」的关系上下文，
    与「把解释当类别去回答」是两件事。guard 只作用于**模型生成的正文**（见 generate 节点）。
    """
    ev = Evidence(
        kind="graph", content="貂蝉 克制 铠：铠怕高爆发法师", source="official",
        relation="COUNTERS", patch="2026-10", hero_ids=["141", "166"],
    )
    retrieval_stubbed(graph=[ev], vector=[])
    s = await ask("m4-verbatim", "铠被谁克制")

    body_lines = [ln for ln in s["answer"].splitlines() if ln.startswith("- ")]
    assert body_lines, "答案应包含证据行"
    for line in body_lines:
        assert line[2:] in ev.content, f"答案行不是 evidence 原文摘录：{line}"
