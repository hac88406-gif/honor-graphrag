"""生成后校验单测（规格书 4.9 生成约束补强）。

**核心用例来自需求方实测**：给两条资料（含「妲己克制后羿，因后羿怕高爆发法师」），
`deepseek-chat` 回答成「后羿怕高爆发的法师英雄，比如妲己」—— 把资料里的**解释**当成了**类别**。
`scripts/compare_llm_models.py` 复跑显示 v4-pro 与 flash 在基础/强化 prompt 下**均复现**，
故 prompt 挡不住，必须靠本层拦截。

同时把 guard 的**边界**一并固化（哪些情形放过、哪些情形拦下），
避免后人调规则时不知道原来的边界在哪里 —— 也如实记录启发式的局限。
"""
from __future__ import annotations

from app.llm.guard import check_answer
from app.schemas.chat import Evidence

# 需求方实测的原始资料与原始越界答案
LEAK_EVIDENCE = [Evidence(
    kind="graph", content="妲己 克制 后羿：后羿怕高爆发法师", source="official",
    relation="COUNTERS", patch="2026-10", hero_ids=["131", "169"],
)]
LEAK_ANSWER = "后羿怕高爆发的法师英雄，比如妲己。"


def _ev(content: str, kind: str = "graph") -> Evidence:
    return Evidence(kind=kind, content=content, source="official", patch="2026-10")


# ---------------------------------------------------------------- G3 类别化外推

def test_class_leak_observed_case_is_rejected():
    """需求方实测原案：把资料里的解释当类别 -> 必须拦下。"""
    g = check_answer(LEAK_ANSWER, LEAK_EVIDENCE, "后羿怕什么？")
    assert not g.ok
    assert g.reason == "class_leak"
    assert "怕高爆发的法师" in g.detail


def test_class_leak_with_other_relation_words():
    """同类形态的其它说法（克星 / 被克制 / 天敌）一并覆盖。"""
    for answer in (
        "后羿的克星是高爆发法师。",
        "后羿被刺客克制。",
        "后羿的天敌是法师英雄。",
    ):
        g = check_answer(answer, LEAK_EVIDENCE, "后羿怕什么？")
        assert not g.ok and g.reason == "class_leak", answer


def test_specific_hero_answer_passes():
    """正确形态：用资料里的**具体英雄**回答 -> 放行。"""
    g = check_answer("克制后羿的英雄是妲己。", LEAK_EVIDENCE, "后羿怕什么？")
    assert g.ok, g


def test_role_word_without_relation_context_passes():
    """边界：职业词不与关系词同现时不拦（如「妲己是法师」只是陈述资料事实）。

    启发式的取舍：宁可放过这种，也不误伤「资料里确实写了职业」的正常回答。
    """
    g = check_answer("妲己是法师，可以克制后羿。", LEAK_EVIDENCE, "后羿怕什么？")
    assert g.ok, g


def test_class_leak_traceable_to_evidence_is_exempt():
    """依据本身写了类别式句子时，模型**照抄**这句当结论 -> 可溯源，放行（M6 审核后的 R1）。

    旧口径（M6 审核前）要求「即使资料里写着这句，照抄当结论仍算越界」，但那与「引述 reason
    合规」自相矛盾，且实测误报率 87.5%。新口径按需求方 2026-10-16 裁定改为**按溯源判**：
    片段能在依据原文找到即属「有据」，guard 只查「答案是否越界」，不查「依据本身合不合规」。
    代价（如实标注）：依据自己写了类别式句子时，照抄会被放过。
    """
    assert "后羿怕高爆发法师" in LEAK_EVIDENCE[0].content
    g = check_answer("后羿怕高爆发法师。", LEAK_EVIDENCE, "后羿怕什么？")
    assert g.ok, g


# ---------------------------------------------------------------- G2 英雄名越界

def test_hero_not_in_evidence_is_rejected():
    """答案里出现资料中不存在的英雄 -> 拦下（4.9：不得引入资料外事实）。"""
    g = check_answer("克制后羿的英雄有妲己和铠。", LEAK_EVIDENCE, "后羿怕什么？")
    assert not g.ok
    assert g.reason == "hero_leak"
    assert g.detail == "铠"


def test_hero_from_question_counts_as_traceable():
    """问句里出现的英雄（本次提问对象）不算越界 —— 用户自己说的，不是模型编的。"""
    evidence = [_ev("貂蝉 克制 兰陵王：理由")]
    g = check_answer("貂蝉确实克制兰陵王。", evidence, "貂蝉克制谁？")
    assert g.ok, g


def test_item_name_is_not_treated_as_hero():
    """装备名不参与英雄名越界判定（G2 只查英雄，避免把装备名误判为编造）。"""
    evidence = [_ev("暗影战斧：价格 2090（攻击类装备）")]
    g = check_answer("推荐出暗影战斧和铁剑。", evidence, "铠怎么出装？")
    assert g.ok, g


# ---------------------------------------------------------------- G1 空答案

def test_empty_answer_is_rejected():
    assert check_answer("", LEAK_EVIDENCE, "后羿怕什么？").reason == "empty"
    assert check_answer("   \n ", LEAK_EVIDENCE, "后羿怕什么？").reason == "empty"


def test_guard_result_is_truthy_when_ok():
    """GuardResult 支持布尔语义，调用方可直接 `if not result:`。"""
    assert bool(check_answer("妲己克制后羿。", LEAK_EVIDENCE, "后羿怕什么？")) is True
    assert bool(check_answer(LEAK_ANSWER, LEAK_EVIDENCE, "后羿怕什么？")) is False


# ------------------------------------------------ G3 豁免 R1/R2（2026-10-15 二审裁定 B-1）
# 加入依据：scripts/measure_guard_fp.py 用真实数据筛测例，实测拦下 7 例、误报 7 例（FP=100%），
# 故按裁定放松规则。以下用例把两条豁免的**边界**钉住，防止后人把豁免放大成「一律不判」。
#
# R1 在 M6 审核后**收窄**（2026-10-16）：旧粒度是「问句含为什么/为何即整个 G3 关闭」，
# 需求方实测点出这是原则缺陷 —— 真实语料里 0 条含「后羿怕高爆发法师」，可只要问句带「为什么」，
# 模型自编的这类类别主张就完全不被检查；而「问原因」恰是类别外推的高发场景。
# 新粒度：**命中片段能在依据原文里溯源才豁免**（引述 reason 合规），溯源不到仍判 G3。
# 注意下面的 `evidence` 都不含类别句 —— 与真实语料一致（0 条含「后羿怕高爆发法师」）。

def test_traceable_reason_quote_is_exempt():
    """R1 新口径：答案把依据里的 reason 原样引述 -> 可溯源，豁免。

    豁免与「问不问原因」**无关**，只看片段能不能在依据里找到。
    """
    evidence = [_ev("东皇太一 克制 司马懿：硬控十分克制刺客的突袭，会让司马懿无法进场输出")]
    g = check_answer(
        "东皇太一克制司马懿的原因是：硬控十分克制刺客的突袭，会让司马懿无法进场输出。",
        evidence, "东皇太一克制司马懿吗？",   # 问句不含「为什么」，照样豁免
    )
    assert g.ok, g


def test_reason_question_no_longer_disables_g3():
    """R1 收窄的**核心断言**：问句带「为什么」不再整体关闭 G3。

    实测依据（需求方 2026-10-16）：真实语料里 0 条含「后羿怕高爆发法师」，
    旧 R1 却让「后羿怕哪些英雄？为什么？」下的自编类别主张全被放行（应拦）。
    """
    evidence = [_ev("妲己 克制 后羿：后羿血量低、位移差，容易被贴脸")]
    for answer in ("后羿怕高爆发法师。", "后羿的克星是高爆发法师英雄。"):
        g = check_answer(answer, evidence, "后羿怕哪些英雄？为什么？")
        assert not g.ok and g.reason == "class_leak", answer


def test_leak_not_traceable_caught_without_reason_word():
    """R1 边界：片段溯源不到时，问句含不含「为什么」都要拦。"""
    evidence = [_ev("妲己 克制 后羿：后羿血量低、位移差，容易被贴脸")]
    g = check_answer("后羿怕高爆发法师。", evidence, "后羿怕什么？")
    assert not g.ok and g.reason == "class_leak"


def test_hero_name_containing_role_word_is_exempt():
    """R2：命中落在含职业词的英雄名内 -> 不拦。

    实测依据：误报里「盾山怕元流之子(法师)」—— `元流之子` 有 法师/坦克/射手/辅助/刺客
    五个形态名，职业词是**英雄名的一部分**。
    """
    evidence = [_ev("元流之子(法师) 克制 盾山：元流之子-法师没有弹道技能，是一名不太惧怕盾山的法师英雄")]
    g = check_answer("盾山怕元流之子(法师)。", evidence, "盾山怕什么？")
    assert g.ok, g


def test_r2_exemption_is_position_based():
    """R2 必须**按位置**判：英雄名之外的裸职业词不被豁免，否则会漏掉真越界。

    「盾山怕法师，元流之子(法师)可以克制它」里的「怕法师」是模型自己的外推，
    不能因为同一句里恰好出现了含职业词的英雄名就一起放过。
    """
    evidence = [_ev("元流之子(法师) 克制 盾山：元流之子-法师没有弹道技能")]
    g = check_answer("盾山怕法师，元流之子(法师)可以克制它。", evidence, "盾山怕什么？")
    assert not g.ok and g.reason == "class_leak"


def test_r2_exemption_handles_fullwidth_parens():
    """R2 归一化：模型把英雄名里的半角括号写成**全角**（实测「元流之子（法师）」）也要豁免。

    实测依据：误报例 02 —— 不归一时 `text.find("元流之子(法师)")` 找不到，R2 豁免失效。
    """
    evidence = [_ev("元流之子(法师) 克制 盾山：元流之子-法师没有弹道技能")]
    g = check_answer("盾山怕元流之子（法师）。", evidence, "盾山怕什么？")
    assert g.ok, g


# ------------------------------------------------ M6 复核放松 R3 + G2 别名（2026-10-15）
# 加入依据：scripts/measure_guard_blocked.py 在常规评测集里把**真正被拦下**的 2 条逐条判定，
# 2 条全是误报（FP=100%），故按需求方「误报率 >20% 需放松规则」的裁定放松。以下钉住边界。

def test_role_description_exempts_class_leak():
    """R3：命中片段实为「以…为核心」的角色定位描述 -> 不拦（实测误报例 T-05）。"""
    evidence = [_ev("东皇太一：定位为游走/对抗路，以压制为核心")]
    g = check_answer("东皇太一定位为游走/对抗路，以压制为核心。", evidence, "东皇太一的玩法？")
    assert g.ok, g


def test_r3_boundary_real_relation_claim_still_caught():
    """R3 边界：真正把关系抬成类别的主张（不带「为核心」）且**溯源不到**时仍要拦下。"""
    evidence = [_ev("妲己 克制 后羿：后羿血量低、位移差，容易被贴脸")]
    g = check_answer("后羿怕高爆发法师。", evidence, "后羿怕什么？")
    assert not g.ok and g.reason == "class_leak"


def test_hero_alias_in_evidence_counts_as_traceable():
    """G2 放松：资料写的是简称「木兰」，答案照写规范名「花木兰」 -> 可溯源，不拦（实测误报例 F-48）。"""
    evidence = [_ev("钟馗 的最佳搭档：打野战士（刘备、木兰）")]
    g = check_answer("可打野的英雄有刘备、花木兰。", evidence, "这版本打野强势的有哪些？")
    assert g.ok, g


def test_g2_alias_relaxation_does_not_over_exempt():
    """G2 放松的边界：规范名与别名都没在资料里出现时，仍判英雄越界。"""
    g = check_answer("克制后羿的英雄有妲己和铠。", LEAK_EVIDENCE, "后羿怕什么？")
    assert not g.ok and g.reason == "hero_leak" and g.detail == "铠"


# ---------------------------------------------------------------- B2 降级可见

def test_guard_reports_degraded_when_lexicon_unavailable(monkeypatch):
    """B2：G2 词典不可用时 fail-open（放行），但降级必须**可见**（degraded=True）。

    只写 logger.warning 等于静默消失 —— 日志没人看。故由 GuardResult 透传到 debug。
    """
    import app.retrieval.entity_linking as el

    def _boom(_text):
        raise RuntimeError("词典不可用")

    monkeypatch.setattr(el, "link", _boom)
    g = check_answer("妲己克制后羿。", LEAK_EVIDENCE, "后羿怕什么？")
    assert g.ok is True
    assert g.degraded is True
