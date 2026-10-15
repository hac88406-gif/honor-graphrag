"""生成后校验（guard）：规格书 4.9 生成约束的**第二道防线**。

**为什么必须有这一层**（需求方 2026-10-15 实测 + 本机复跑）：
给两条资料（含「妲己克制后羿，因后羿怕高爆发法师」），`deepseek-chat` 回答成
「后羿怕高爆发的法师英雄，比如妲己」——把资料里的**解释**当成了**类别**来回答。
`scripts/compare_llm_models.py` 的用例 4a/4b 显示 `deepseek-v4-pro` 与 `deepseek-flash`
在基础 prompt 与强化 prompt 下**均复现**（4/4 命中），证明**光靠 prompt 不足**。

三条判定（全部为确定性启发式，**不调用 LLM**——把安全机制交给最不稳定的组件是反模式）：

  G1 空答案：正文为空（与 `client.is_success()` 互为补充，防止调用方漏判）。
  G2 英雄名越界：答案里出现的英雄名必须能在【资料】或【问题】里找到
     （拦住「资料没写但模型编出来」的英雄；装备/铭文同理，统一按实体链接结果比对）。
  G3 类别化外推：答案把**关系**归结为英雄**类别**（如「怕高爆发法师」「克星是法师英雄」）——
     正是需求方实测的越界形态。这是本项目最需要的拦截项。

**G3 的两条豁免（2026-10-15 二审裁定 B-1 后加入，依据是实测误报率）**：
`scripts/measure_guard_fp.py` 用**真实数据**筛测例（先扫 `relations.json` 的 COUNTERS reason，
挑出「reason 本身就会触发 G3」的边来出题 —— 这些边就是误报风险最高的样本），并在**同一批模型
回答**上对照「放松前 / 放松后」两条规则（差异只来自规则本身，不受采样波动影响）：

  放松前 —— 16 例**拦下 8 例**，逐例判定后**真越界仅 1 例、误报 7 例（FP=87.5%）**，故必须放松。
  放松后 —— 16 例**拦下 1 例**，该例为真越界（问「后羿怕什么」答「后羿怕高爆发法师」），**FP=0%**。

  7 例误报的形态（即下面两条豁免各自挡掉的那批）：
  R1 **问题在问「原因」时不判 G3**。6 例是「X为什么克制Y」，模型只是把资料的 reason
     原样抄回来（「因为硬控十分克制刺客的突袭」）——引述原因是**合规行为**，不是类别化外推。
     代价（如实标注）：问「为什么」时模型**自己编造**类别会漏过。取舍依据是需求方定的原则
     ——guard 是启发式下限不是安全底线，**误拦（把正常回答降级成机械罗列）代价大于漏拦**。
  R2 **命中片段落在英雄名内时不判 G3**。1 例是「盾山怕元流之子(法师)」——
     `元流之子` 有 法师/坦克/射手/辅助/刺客 五个形态名，职业词是**英雄名的一部分**。

**局限（如实标注，不粉饰）**：
  - 启发式只能覆盖**已观测**的失败形态；未观测到的外推方式（如用「克制类」「后排」等
    非职业词做类别）会漏过。guard 是**下限**而不是保证，M6 评测需按失败样本继续补规则。
  - G2 依赖实体链接的词典覆盖面（英雄/装备/铭文名），词典没收录的名字无法判定越界；
    **词典不可用时 G2 等效失效，属 fail-open，但降级必须可见**（`GuardResult.degraded`
    -> `debug.guard_degraded`），不能只写日志——日志没人看就等于静默消失。
  - 本层只做「拦下并回落」，不做「修正」——把越界答案改写成合规答案属于二次生成，
    会引入新的不确定性，不如直接回落到确定性的证据组装。
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.schemas.chat import Evidence

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# 英雄职业/分路词：官方资料里出现这些词时，通常是**原因说明**（「因后羿怕高爆发法师」），
# 而不是**可直接回答**的类别。模型把这类解释抬成答案主体即判越界。
_ROLE_WORDS = (
    "法师", "战士", "刺客", "坦克", "射手", "辅助", "打野", "边路",
    "对抗路", "中路", "发育路", "游走",
)

# G3：把**关系**归结为英雄**类别**的两种语序，都判越界：
#   - 关系词在前：「怕高爆发法师」「克星是法师英雄」「被刺客克制」；
#   - 职业词在前：「法师克制后羿」「刺客针对后排」。
# 窗口内禁止跨句读（。；！？）与并列停顿（，、），避免把两个独立短句连起来误判。
_ROLE_ALT = "|".join(_ROLE_WORDS)
_RELATION_WORDS = "怕|被克制|克制|压制|克星|天敌|打不过|被压|针对|counter"
_CLASS_LEAK = re.compile(rf"({_RELATION_WORDS})[^。；！？，、\n]{{0,12}}({_ROLE_ALT})")
_CLASS_LEAK_HEAD = re.compile(rf"({_ROLE_ALT})[^。；！？，、\n]{{0,6}}(克制|压制|针对|counter)")

# R1：问题在问「原因」时不判 G3（引述 reason 合规）。见模块头「G3 的两条豁免」。
_REASON_QUESTION = re.compile(r"为什么|为何|原因|缘由|怎么会|咋会|凭什么")

# 括号类全角 -> 半角折叠（R2 用）。模型常把英雄名里的半角括号写成全角
# （实测「元流之子（法师）」），不折叠 R2 就找不到英雄名 —— 实测误报例 02 正是如此。
#
# **不能整段 NFKC**：NFKC 会把全角逗号「，」也折成半角「,」，而 G3 的正则靠
# 「窗口内不跨标点」防止把两个独立短句连起来误判（见 `_CLASS_LEAK` 注释）——
# 折了逗号等于把这道防线拆了（实测会让「妲己是法师，可以克制后羿」被误拦）。
_PUNCT_FOLD = str.maketrans({"（": "(", "）": ")", "［": "[", "］": "]", "｛": "{", "｝": "}"})


@dataclass(frozen=True)
class GuardResult:
    ok: bool
    reason: str = ""     # 不通过时的机器可读原因：empty / hero_leak / class_leak
    detail: str = ""     # 命中的原文片段（写进 state.error 与 debug，便于排查）
    degraded: bool = False   # G2 因词典不可用而失效（fail-open，但必须可见）

    def __bool__(self) -> bool:
        return self.ok


def _evidence_corpus(evidence: list[Evidence]) -> str:
    return "\n".join(e.content for e in evidence)


@lru_cache(maxsize=1)
def _hero_names_with_role() -> tuple[str, ...]:
    """含职业词的英雄名（R2 用）。当前数据里只有 `元流之子` 的五个形态名。

    名字统一按 **NFKC 归一**返回（半角括号），与 `_first_class_leak` 归一后的文本对齐。
    """
    try:
        heroes = json.loads(
            (_PROJECT_ROOT / "data" / "graph" / "heroes.json").read_text(encoding="utf-8")
        )
    except Exception as e:  # noqa: BLE001 - 清单读不到时只是少一条豁免，不影响其余判定
        logger.warning("guard：英雄清单不可用，跳过英雄名豁免（R2）：%s", e)
        return ()
    return tuple(
        unicodedata.normalize("NFKC", h["name"])
        for h in heroes
        if any(w in h["name"] for w in _ROLE_WORDS)
    )


def _span_inside_hero_name(text: str, start: int, end: int) -> bool:
    """命中片段是否落在某个含职业词的英雄名内（R2）。

    必须按**位置**判：只看「答案里出现过该英雄名」会过度豁免
    （如「盾山怕法师，元流之子(法师)克制盾山」里那个裸的「法师」会被一起放过）。
    """
    for name in _hero_names_with_role():
        i = text.find(name)
        while i != -1:
            if start < i + len(name) and end > i:
                return True
            i = text.find(name, i + 1)
    return False


def _first_class_leak(text: str) -> str | None:
    """返回首个**未被 R2 豁免**的 G3 命中片段；无则 None。

    匹配前只做**括号折叠**（不动其它标点）：模型会把英雄名里的半角括号写成全角，
    不折叠就会漏掉 R2 豁免 —— 实测误报例 02 正是如此。
    """
    folded = text.translate(_PUNCT_FOLD)
    for pat in (_CLASS_LEAK, _CLASS_LEAK_HEAD):
        for m in pat.finditer(folded):
            if not _span_inside_hero_name(folded, m.start(), m.end()):
                return m.group(0)
    return None


def _hero_names(text: str) -> tuple[set[str], bool]:
    """文本中出现的英雄规范名（用实体链接的词典，与检索层同一份索引）。

    返回 `(名字集合, 是否降级)`：词典不可用时返回 `(set(), True)`，
    调用方须把降级标记透传到 `debug`（fail-open 但可见）。
    """
    from app.retrieval.entity_linking import link

    try:
        return {e.canonical_name for e in link(text).entities if e.entity_type == "hero"}, False
    except Exception as e:  # noqa: BLE001 - 词典不可用时不误伤：跳过 G2
        logger.warning("guard：实体链接不可用，跳过英雄名越界检查（G2 失效）：%s", e)
        return set(), True


def check_answer(answer: str, evidence: list[Evidence], question: str = "") -> GuardResult:
    """校验生成结果。`ok=False` 时调用方必须回落到确定性证据组装。"""
    text = (answer or "").strip()

    # ---- G1 空答案 ----
    if not text:
        return GuardResult(False, "empty", "生成结果为空")

    # ---- G3 类别化外推（先查 G3：它是需求方点名的形态，命中最具信息量） ----
    if not _REASON_QUESTION.search(question or ""):
        leak = _first_class_leak(text)
        if leak:
            return GuardResult(False, "class_leak", leak)

    # ---- G2 英雄名越界 ----
    corpus = _evidence_corpus(evidence) + "\n" + (question or "")
    names, degraded = _hero_names(text)
    for name in names:
        if name and name not in corpus:
            return GuardResult(False, "hero_leak", name, degraded=degraded)

    return GuardResult(True, degraded=degraded)
