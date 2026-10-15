"""生成节点单测（规格书 4.2 步骤 5 / 4.9 / M4 验收）。

覆盖三件事：

  1. **template 路径**（默认）：确定性证据组装，答案里只有 evidence 的内容，
     满足 M4 验收「答案中的英雄名全部能在 evidence 中找到」；
  2. **llm 路径**：成功时用模型正文，**失败（未配置/网络/空答案/截断/校验不通过）一律回落**；
  3. **多意图告知**（M3 审核·修改三）：命中多个意图时答案里显式说明本次回答了哪个。

LLM 路径全部用 `fake_cloud`（假客户端）驱动 —— 离线、无费用、结果确定。
"""
from __future__ import annotations

import pytest

from app.agent.nodes.generate import INTENT_LABELS, generate_node
from app.config import settings
from app.llm.client import LLMGenerationError, LLMUnavailableError
from app.schemas.chat import Evidence

GRAPH_EV = Evidence(
    kind="graph", content="兰陵王 克制 铠：理由", source="official",
    relation="COUNTERS", patch="2026-10", hero_ids=["153", "166"],
)
VECTOR_EV = Evidence(kind="vector", content="铠 对线思路：前期稳住发育……", source="guide", patch="2026-10", score=0.8)

LEAK_ANSWER = "铠怕高爆发法师。"   # 需求方实测的越界形态


def _state(evidence, *, response_type="answer", intent="COUNTER_BY", matched=None, degraded=False):
    return {
        "evidence": list(evidence),
        "response_type": response_type,
        "intent": intent,
        "matched_intents": matched if matched is not None else [intent],
        "question": "铠被谁克制",
        "degraded": degraded,
        "degradation_note": "图谱不可用，以下依据来自攻略文本检索" if degraded else None,
    }


# ---------------------------------------------------------------- template 路径

def test_template_mode_uses_evidence_only():
    out = generate_node(_state([GRAPH_EV, VECTOR_EV]))

    assert out["generation_info"]["mode"] == "template"
    assert out["generation_info"]["fallback"] is False
    assert "【图谱依据】" in out["answer"]
    assert GRAPH_EV.content in out["answer"]
    assert VECTOR_EV.content in out["answer"]
    assert out["response_type"] == "answer"
    assert len(out["citations"]) == 2


def test_template_answer_hero_names_all_traceable_to_evidence():
    """M4 验收：答案中的英雄名必须全部能在 evidence 中找到。

    template 路径是**逐条摘录** evidence，构造上不可能引入外部英雄名；此处固化该性质。
    """
    from app.retrieval.entity_linking import link

    out = generate_node(_state([GRAPH_EV, VECTOR_EV]))
    corpus = "\n".join(e.content for e in [GRAPH_EV, VECTOR_EV]) + "铠被谁克制"
    names = [e.canonical_name for e in link(out["answer"]).entities if e.entity_type == "hero"]
    assert names, "答案里应至少出现一个英雄名"
    for name in names:
        assert name in corpus, f"答案出现 evidence 之外的英雄名：{name}"


def test_low_confidence_prefix_is_kept():
    out = generate_node(_state([VECTOR_EV], response_type="low_confidence"))
    assert out["answer"].startswith("以下内容依据较少，仅供参考。")


def test_degraded_note_is_kept():
    out = generate_node(_state([VECTOR_EV], degraded=True))
    assert "图谱不可用" in out["answer"]


# ---------------------------------------------------------------- 多意图告知

def test_multi_intent_notice_names_the_answered_intent():
    """命中多个意图时，答案必须说明本次只回答了哪个（此前只有日志留痕，用户不知情）。"""
    out = generate_node(_state(
        [GRAPH_EV], intent="ITEM_BUILD", matched=["ITEM_BUILD", "INSCRIPTION"],
    ))

    assert INTENT_LABELS["ITEM_BUILD"] in out["answer"]
    assert INTENT_LABELS["INSCRIPTION"] in out["answer"]
    assert "可以继续追问" in out["answer"]


def test_single_intent_has_no_notice():
    out = generate_node(_state([GRAPH_EV], intent="COUNTER_BY", matched=["COUNTER_BY"]))
    assert "本次只回答了" not in out["answer"]


def test_notice_absent_when_only_the_chosen_intent_is_in_matched():
    """matched_intents 里只有主意图（例如规则路径只命中一个）时不得出现告知文案。"""
    out = generate_node(_state([GRAPH_EV], intent="COUNTER_BY", matched=[]))
    assert "本次只回答了" not in out["answer"]


# ---------------------------------------------------------------- llm 路径：成功

def test_llm_mode_uses_model_answer(fake_cloud):
    client = fake_cloud(content="克制铠的英雄是兰陵王。", reasoning="内部思考过程",
                        completion_tokens=180, reasoning_tokens=120)

    out = generate_node(_state([GRAPH_EV]))

    info = out["generation_info"]
    assert info["mode"] == "llm"
    assert info["fallback"] is False
    assert info["finish_reason"] == "stop"
    assert info["completion_tokens"] == 180          # 含思考
    assert info["reasoning_tokens"] == 120
    assert info["reasoning_chars"] == len("内部思考过程")
    assert out["answer"] == "克制铠的英雄是兰陵王。"
    assert "内部思考过程" not in out["answer"], "思考绝不能混入答案"
    assert client.calls and client.calls[0][0] == "chat"


def test_llm_mode_prompt_contains_evidence(fake_cloud):
    client = fake_cloud(content="克制铠的英雄是兰陵王。")
    generate_node(_state([GRAPH_EV]))

    messages = client.calls[0][1]
    assert messages[0]["role"] == "system"
    assert GRAPH_EV.content in messages[1]["content"]
    assert "铠被谁克制" in messages[1]["content"]


def test_llm_mode_keeps_prefix_lines_with_model_body(fake_cloud):
    """前缀行（低置信提示 / 多意图告知）属于答案的一部分，必须与模型正文一起给出。"""
    fake_cloud(content="克制铠的英雄是兰陵王。")
    out = generate_node(_state(
        [GRAPH_EV], response_type="low_confidence", intent="ITEM_BUILD",
        matched=["ITEM_BUILD", "INSCRIPTION"],
    ))

    assert "以下内容依据较少，仅供参考。" in out["answer"]
    assert "可以继续追问" in out["answer"]
    assert out["answer"].endswith("克制铠的英雄是兰陵王。")


# ---------------------------------------------------------------- llm 路径：回落

def test_llm_unavailable_falls_back_to_template(fake_cloud):
    fake_cloud(error=LLMUnavailableError("云端返回 HTTP 500"))
    out = generate_node(_state([GRAPH_EV]))

    info = out["generation_info"]
    assert info["fallback"] is True
    assert "LLMUnavailableError" in info["error"]
    assert GRAPH_EV.content in out["answer"], "回落必须是确定性的证据组装"
    assert "【图谱依据】" in out["answer"]


def test_llm_empty_answer_falls_back_to_template(fake_cloud):
    """实测的「HTTP 200 + 空答案」在客户端层已抛错，节点必须回落而不是把空答案交出去。"""
    fake_cloud(error=LLMGenerationError("生成结果不可用：空答案（finish_reason=length）"))
    out = generate_node(_state([GRAPH_EV]))

    assert out["generation_info"]["fallback"] is True
    assert out["answer"].strip()
    assert GRAPH_EV.content in out["answer"]


def test_llm_guard_rejects_class_leak_and_falls_back(fake_cloud):
    """需求方实测的越界归纳：prompt 挡不住 -> guard 拦下 -> 回落确定性组装。"""
    fake_cloud(content=LEAK_ANSWER)
    out = generate_node(_state([GRAPH_EV]))

    info = out["generation_info"]
    assert info["fallback"] is True
    assert info["guard"]["ok"] is False
    assert info["guard"]["reason"] == "class_leak"
    assert LEAK_ANSWER not in out["answer"], "越界答案绝不能交给用户"
    assert GRAPH_EV.content in out["answer"]


def test_guard_can_be_disabled_by_config(fake_cloud, monkeypatch):
    """`GUARD_ENABLED=False` 时放行（保留开关，便于对照实验与 M6 评测）。"""
    monkeypatch.setattr(settings, "GUARD_ENABLED", False)
    fake_cloud(content=LEAK_ANSWER)
    out = generate_node(_state([GRAPH_EV]))

    assert out["generation_info"]["fallback"] is False
    assert out["answer"] == LEAK_ANSWER


def test_llm_client_missing_falls_back(fake_cloud, monkeypatch):
    """云端未配置（get_cloud_client 返回 None）同样按失败处理，不得静默。"""
    monkeypatch.setattr("app.agent.nodes.generate.get_cloud_client", lambda: None)
    monkeypatch.setattr(settings, "GENERATION_MODE", "llm")
    out = generate_node(_state([GRAPH_EV]))

    assert out["generation_info"]["fallback"] is True
    assert "未配置" in out["generation_info"]["error"]
    assert GRAPH_EV.content in out["answer"]


def test_llm_mode_without_evidence_uses_template(fake_cloud):
    """没有证据时不必打云端（拒答/澄清分支不会走到 generate，此处只做防御）。"""
    fake_cloud()   # 切到 llm 模式并注入假客户端（不调用则仍是 template，测不到该分支）
    out = generate_node(_state([], response_type="low_confidence"))
    assert out["generation_info"]["mode"] == "llm"
    assert out["generation_info"]["fallback"] is True
    assert "知识库中没有找到" in out["answer"]
