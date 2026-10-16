# 缺陷 D1 · 「关系」类问法被误判为英雄未识别 — 修复交付报告

> 来源：需求方（阿枢）缺陷报告 D1（2026-10-16，**前端聊天页手测**发现）
> 性质：**质量缺陷修复（Defect）**，不是设计取舍
> 报告日期：2026-10-16
> 判定：**不阻塞项目二**（网关只转发工具调用），但项目二 M7 工具使用评测开始前**必须先修掉**（见 §11）

---

## 0. 一句话结论

缺陷的三层根因（L1 残句被话题词污染 / L2 澄清分支优先序颠倒 / L3 无方向「克制关系」无意图可匹配）**全部落地修复**；L3 按需求方 2026-10-16 裁定走**方向澄清**（反问「镜克制谁」还是「谁克制镜」），**不新增意图、不动 4.4 的封闭枚举**；L4 的评测准入规则**机制化落地**（不是写进文档的口号，而是 `pytest` 会红）。全量三元组 **368 passed / 0 skipped / 0 failed**，既有 294 条测试**零改动**。

---

## 1. 交付范围（文件级）

| 类型 | 文件 | 说明 |
| --- | --- | --- |
| 修改（L1 核心） | `app/retrieval/entity_linking.py` | 删掉本模块自维护的 `STOPWORDS`，改由 `stopwords()` = 通用功能词 ∪ **意图层话题词**（唯一真源）；`_residuals()` 重写为**两层防污染**；新增 `_cover_stopwords()` |
| 修改（L1 真源 / L3 标记） | `app/retrieval/intent.py` | 新增 `topic_words()`（话题词唯一真源）、`_RELATION_TOPIC` / `_COUNTER_TOPIC`、`_relation_clarify_kind()`、`IntentResult.clarify_kind`；路由两处澄清分支回填 `clarify_kind` |
| 修改（L2 核心） | `app/agent/nodes/clarify.py` | `_clarify_question()` **调换分支优先序**（`entities` 提到 `unrecognized` 之前）+ 新增方向澄清分支；`_candidates()` 按场景分派候选（不再一律返回固定英雄名单） |
| 修改（契约） | `app/agent/state.py` | 新增 `clarify_kind` 字段（意图层 → 澄清层的契约） |
| 修改（传播 + 边界） | `app/agent/nodes/intent.py` | 把路由的 `clarify_kind` 写进 State；**指代消解改写意图时清零**（规则 2 继承上一轮意图时，用户并不是在问无方向关系） |
| 新增（回归） | `tests/unit/test_d1_relation_clarify.py` | 20 条：防漂移 + 关系类标记/文案/候选 + 防 L2 改过头 |
| 新增（编排级回归） | `tests/integration/test_d1_relation_clarify_e2e.py` | 3 条：走完整编排图，确认澄清卡带方向候选回到用户面前 |
| 新增（L4 门禁） | `tests/unit/test_eval_case_policy.py` | 7 条：把「零提示自然说法」准入规则机制化 |
| 修改（L4 用例） | `tests/eval/freeform.yaml` | 追加 **F-75 ~ F-78** 四条带可追溯来源的零提示用例（**纯新增 49 行，0 删除**） |
| 新增（取证） | `docs/milestones/D1-verify-output.txt` | 真实 HTTP（端口 8001）端到端取证：11 句、澄清卡全文、点选候选答案、SSE 逐帧 |
| 新增（取证） | `docs/milestones/D1-probe-output.txt` | 规则层 `route()` + `link()` 逐句输出（含未识别残句） |
| 新增（取证） | `docs/milestones/D1-pytest-output.txt` | 全量 pytest 真实输出 |
| **未改动** | `app/agent/graph.py` / `app/api/**` / `app/retrieval/neo4j_client.py` / **任何既有测试文件与断言** | 零改动 |

**只加不改自检**（`git diff --stat` 实测）：

```
 app/agent/nodes/clarify.py      |  70 +++++++++++++++++++++++++--
 app/agent/nodes/intent.py       |  10 +++-
 app/agent/state.py              |   4 ++
 app/retrieval/entity_linking.py | 102 ++++++++++++++++++++++++++++++++++------
 app/retrieval/intent.py         |  61 +++++++++++++++++++++++-
 tests/eval/freeform.yaml        |  49 +++++++++++++++++++
 6 files changed, 273 insertions(+), 23 deletions(-)
```

`git diff --name-only` 在 `tests/` 下**只出现 `tests/eval/freeform.yaml` 一个路径**，且该文件 diff 为 `49 insertions(+), 0 deletions(-)` → **既有测试文件与断言零改动**（§4-5 的硬要求）。

---

## 2. 验收三元组（报告 §4-6）

```
$ REQUIRE_SERVICES=1 .\.venv\Scripts\python -m pytest -q
368 passed, 1 warning in 35.42s
```

| 项 | 数值 |
| --- | --- |
| **passed** | **368** |
| **skipped** | **0** |
| **failed** | **0** |

- **跳过项逐条理由**：**无跳过项**（`skipped = 0`）。
  - 注：`test_eval_case_policy.py` 里对「非 clarify 类零提示用例」有一个 `pytest.skip` 分支，但**本轮 4 条零提示用例全部是 clarify 类型**，该分支未触发，故实际 `skipped = 0`。
- **组成**：既有 **294** + 补丁 P1 **44** + 本次 D1 **30**（20 单元 + 3 集成 + 7 准入门禁）= **368**。
- `1 warning` 为 chromadb 上游 `DeprecationWarning`（`BgeEmbeddingFunction` 缺 `is_legacy`），与本次改动无关，既有测试同样触发。

---

## 3. 验收 §4-1：11 句复现表 · 修复后新三元组

规则层实跑（`docs/milestones/D1-probe-output.txt`，`route()` + `link()` 逐句）：

| 问句 | 意图 | 是否澄清 | 认出的实体 | 未识别残句 | 修复前残句 |
| --- | --- | --- | --- | --- | --- |
| 镜的克制关系 | ENTITY_UNKNOWN | 是 | 镜 | **—** | 关系 |
| 铠的克制关系 | ENTITY_UNKNOWN | 是 | 铠 | **—** | 关系 |
| 镜的关系 | ENTITY_UNKNOWN | 是 | 镜 | **—** | 关系 |
| 铠关系 | ENTITY_UNKNOWN | 是 | 铠 | **—** | 关系 |
| 克制关系 | ENTITY_UNKNOWN | 是 | — | **—** | 关系 |
| 镜的搭档关系 | SYNERGY | 否 | 镜 | **—** | 搭档,关系 |
| 铠被谁克制 | COUNTER_BY | 否 | 铠 | **—** | — |
| 镜克制谁 | COUNTER_OF | 否 | 镜 | **—** | — |
| 谁能克制镜 | COUNTER_BY | 否 | 镜 | **—** | — |
| 镜怎么出装 | ITEM_BUILD | 否 | 镜 | **—** | — |
| 镜的铭文 | INSCRIPTION | 否 | 镜 | **—** | — |

**修复前 vs 修复后**（对照报告 §1 实测表）：

- **实体识别不变、且不再丢失**：前 5 句的实体（镜 / 铠 / —）与修复前**完全一致**——缺陷报告已指出「实体链接没有失败」，本次修复**没有动实体链接的召回**，只动了「认出之后」的处理。
- **未识别残句全部归零**：11 句的 `unrecognized` 由「关系 / 搭档,关系」变为**全空**。这直接修复了报告点名的「`unrecognized` 信号失真」——它是规格书 4.9 区分「实体没认出 → 澄清」与「知识库真没数据 → 拒答」的**唯一判据**。
- **意图不变**：后 6 句（`SYNERGY` / `COUNTER_BY` / `COUNTER_OF` / `ITEM_BUILD` / `INSCRIPTION`）意图与修复前一致 → 修复**没有扰动任何既有正常路径**。

---

## 4. 验收 §4-2：「镜的克制关系」的处理

### 4.1 与报告字面要求的偏差声明（重要，先讲清楚）

报告 §4-2 的字面要求是「「镜的克制关系」类问法**不得再进入澄清**」。**本条未按字面满足**——它**仍然进入澄清**，这是**需求方 2026-10-16 的裁定结果**，不是实现方的自行取舍：

> L3 取舍：用「反问他想要哪个方向」（候选给「镜克制谁」/「谁克制镜」），**不新增意图、不动封闭枚举**。

故本报告按**裁定后的口径**验收：澄清必须是**正确的方向澄清**——文案锚定已认出的英雄、候选是**可直接点选的方向问句**、点一下就拿到答案（澄清不再是死胡同）。该偏差同样写在测试文件的 docstring 里（`tests/unit/test_d1_relation_clarify.py` 顶部 ⚠️ 段），避免后来者误读为「漏做」。

**为什么这样裁定是安全的**：4.4 的意图枚举是**封闭**的、实现方不得私自新增取值。若强行新增 `COUNTER_BOTH`，会牵动 M6 评测集与「意图路由准确率」口径。故改用 `clarify_kind` **标记**表达「想查关系但没说方向」，枚举不动。

### 4.2 真实 HTTP 取证（端口 8001，`D1-verify-output.txt`）

```
[镜的克制关系] HTTP 200  type=clarify  intent=ENTITY_UNKNOWN  0.03s
  answer         : 「镜」的克制关系有两个方向，你想问哪个？（镜克制谁 / 谁克制镜）
  clarify_options: ['镜克制谁', '谁克制镜']
```

- **不再出现**「没认出「关系」，你是指下面哪个英雄？」——报告 §2-L2 点名的那句错问已消失。
- **候选锚定「镜」**，不再是那份与输入无关的 `_POPULAR` 十人清单。
- 报告 §2-L2 点名的「两张澄清卡候选完全一样」问题已消除，实测对照：

| 问句 | 澄清文案 | 候选 |
| --- | --- | --- |
| 镜的克制关系 | 「镜」的克制关系有两个方向，你想问哪个？ | `['镜克制谁', '谁克制镜']` |
| 镜的关系 | 「镜」的关系有好几种，你想问哪一种？ | `['镜克制谁', '谁克制镜', '镜的搭档']` |
| 克制关系 | 你想问哪个英雄的克制关系？ | 英雄清单（此处才是英雄清单该出现的场景） |
| 赛博坦这个英雄怎么样 | 没认出「赛博坦」，你是指下面哪个英雄？ | 英雄清单（真未识别场景，防 L2 改过头） |

### 4.3 点选候选后的真实答案（证明「一次点击即得答案」）

```
[点选候选 → 镜克制谁] HTTP 200  type=answer  intent=COUNTER_OF  confidence=0.75  citations=2  2.24s
  answer: 镜克制伽罗、西施。

[点选候选 → 谁克制镜] HTTP 200  type=answer  intent=COUNTER_BY  confidence=0.85  citations=3  3.21s
  answer: 澜、王昭君、项羽。

[点选候选 → 镜的搭档] HTTP 200  type=answer  intent=SYNERGY  confidence=0.75  citations=2  5.11s
  answer: 镜的官方推荐搭档有：瑶、鬼谷子。...
```

两个方向的候选都落到**真实可答**的意图上（`COUNTER_OF` / `COUNTER_BY`），并各自给出**带引用的真实答案**——澄清卡从「答废话」变成「一次点击即得答案」。

### 4.4 与报告 L3-(b) 的关系

报告给的 (b) 方案是「新增 `COUNTER_BOTH`，编排层并行跑两个方向、合并 evidence、答案分两段」。**本方案不采纳**（需求方裁定），故报告 §4-2 括号里「须给出实际答案且含两个方向的证据」**不适用于本实现**；对应地，本实现给出的是**两个方向的可点选候选**，由用户在澄清卡上选一个方向。

---

## 5. 验收 §4-3：「镜的搭档关系」的 unrecognized 必须为空

| 项 | 结果 |
| --- | --- |
| 意图 | `SYNERGY` |
| 是否澄清 | **否** |
| 实体 | 镜 |
| **unrecognized** | **`[]`（空）** ✅ |

规则层（`D1-probe-output.txt`）与 HTTP（`D1-verify-output.txt`，`type=answer`）两处均确认；并由 `test_synergy_relation_phrase_answers_without_clarify` 钉住。修复前该句残句为 `['搭档', '关系']`。

---

## 6. 验收 §4-4：新增回归测试（30 条）

| 报告要求 | 用例 | 条数 |
| --- | --- | --- |
| **防漂移测试**（遍历意图词表，§3-L1） | `test_topic_words_is_not_empty`（防测试自身空转，断言真源 ≥50 词）+ `test_topic_words_never_leak_into_unrecognized`（遍历 `topic_words()`，断言 `link("铠"+w).unrecognized` 不含 `w`） | 2 |
| 「XX的克制关系」「XX的关系」「XX关系」共 ≥3 条，断言关系类问法走正确路径 | `test_relation_phrasing_marks_direction_clarify`（4 条参数化：镜的克制关系 / 铠的克制关系 / 镜的关系 / 铠关系，断言实体认出 + 残句为空 + `clarify_kind` 正确）+ `test_relation_clarify_question_keeps_hero_and_drops_unrecognized_wording`（4 条） | 8 |
| 澄清候选必须可点选、且与输入相关 | `test_relation_clarify_candidates_are_clickable_direction_phrases` + `test_candidates_differ_between_hero_and_no_hero_relation_question` + `test_direction_candidate_is_a_working_question`（3 条参数化） | 5 |
| 无英雄的关系问法问「哪个英雄」 | `test_relation_without_hero_asks_which_hero` | 1 |
| 「镜的搭档关系」直接作答 | `test_synergy_relation_phrase_answers_without_clarify` | 1 |
| **「没认出凯旋门」这类真未识别场景仍应走澄清**（防 L2 改过头） | `test_pure_unrecognized_still_clarifies`（赛博坦）+ `test_kai_rotating_door_still_clarifies_not_rejects`（没认出凯旋门） | 2 |
| L2 核心断言（英雄已认出 + 有残句 → 反问英雄而非残句） | `test_entity_branch_takes_priority_over_unrecognized`（铠的老婆是谁） | 1 |
| 编排级端到端（走完整图，确认澄清卡带方向候选回到用户面前） | `test_d1_relation_clarify_e2e.py` | 3 |
| L4 准入规则门禁 | `test_eval_case_policy.py` | 7 |

**「≥3 条关系类」的字面要求**：本实现**4 条**（超过 3），且 `test_relation_phrasing_marks_direction_clarify` 与 `test_relation_clarify_question_keeps_hero_and_drops_unrecognized_wording` **各覆盖这 4 条**，共 8 条断言。
**「断言 need_clarify=False」的字面要求**：按 §4.1 的裁定改为断言「方向澄清被正确标记 + 候选可点选 + 文案不含『没认出』」。

**防漂移测试的机制**（报告 §3-L1 点名「关键，防下次再犯」）：

```python
for w in intent_mod.topic_words():
    got = link(f"铠{w}").unrecognized
    if w in got:
        leaks.append(...)
```

以后**意图关键词表加词、而停用词表没同步**时，本测试**立刻失败**——而不是等用户撞上。这正是 D1 的 L1 根因（「同一件事两份维护」）的机制性防线。

---

## 7. 验收 §4-5：既有 294 条全绿且零改动

| 项 | 结果 |
| --- | --- |
| 既有测试 | **294 条全绿** |
| 既有测试文件与断言改动 | **零改动**（`git diff --name-only` 在 `tests/` 下只有 `tests/eval/freeform.yaml`，且该文件为纯新增 49 行） |
| 是否修改既有断言以迁就修复 | **否** |

注：`tests/eval/freeform.yaml` 是**评测集数据文件**（非测试断言），本次为**追加** 4 条用例，未改动任何既有用例的 `expect_type` / `expected_intent`。

---

## 8. 验收 §4-6：服务环境状态

```
$ curl http://127.0.0.1:8000/api/health
{"neo4j":{"ok":true,"detail":"connected: bolt://localhost:7687"},
 "chroma":{"ok":true,"detail":"persistent@ data/chroma, collections=1"},
 "llm":{"ok":true,"detail":"model=deepseek-v4-pro, cloud_models=['deepseek-flash','deepseek-v4-pro']}}
```

| 服务 | 状态 | 说明 |
| --- | --- | --- |
| Neo4j（Docker，`bolt://localhost:7687`） | **全程运行** | 点选候选后的真实答案、HTTP 取证均依赖它；**本次未停过** |
| Chroma（嵌入式 `PersistentClient`，`data/chroma`） | **全程可用** | 本地嵌入式，非独立进程 |
| LLM（`deepseek-v4-pro`） | **可用** | 点选候选后的生成路径；澄清路径**不调用 LLM**（0.03s 级） |
| 服务依赖 | **未为测试降级** | 未停止任何在线服务，未改任何配置以迁就测试 |

**澄清路径不依赖服务**：澄清在检索之前分流（`app/agent/graph.py::route_after_intent`），故 D1 的核心回归（单元 + 编排级）**离线即可跑**，不依赖 Neo4j / Chroma / LLM。

---

## 9. L4 交付：评测准入规则机制化

**规则原文**（需求方 2026-10-16 裁定，**较报告原稿有收紧**）：

> 任何新功能或新意图，评测集必须包含 **≥3 条「第一次使用者的原话」**——不带方向词、不带术语、不照抄规格书例句；且**每条必须标注可追溯的真实来源（谁在何时打的）**，这批用例**不得由实现方自行编写**。

> 报告原稿的表述是「这批用例不得由实现方自行编写」，需求方进一步收紧为「**每条必须标注可追溯的真实来源（谁在何时打的）**」——光说「不是我写的」无法追溯，必须能指到人、指到日期。

**机制化落地**（`tests/unit/test_eval_case_policy.py`，7 条断言）：

1. 零提示类用例（`category: 零提示自然说法`）**必须 ≥3 条**；
2. 每条**必须带 `source` 字段**，且来源必须含**日期**（缺「何时」无法追溯）；
3. `source` **不得署名实现方**（违反「不得自行编写」）；
4. 每条必须标注 `expected_intent` 与 `expect_type`（否则「零提示」只是一句问句，无法判定）；
5. `expect_type: clarify` 的零提示用例，其 `expected_intent` **必须与规则路由结果一致**（澄清路径在检索之前分流，**离线可判**，不需要服务与模型）。

**新增的 4 条零提示用例**（`freeform.yaml`，`F-75 ~ F-78`）：

| id | 问句 | 期望意图 | 期望类型 | 来源 |
| --- | --- | --- | --- | --- |
| F-75 | 镜的克制关系 | ENTITY_UNKNOWN | clarify | 需求方（阿枢）2026-10-16 前端手测（缺陷报告 D1 §1） |
| F-76 | 克制关系 | ENTITY_UNKNOWN | clarify | 同上 |
| F-77 | 镜的关系 | ENTITY_UNKNOWN | clarify | 同上 |
| F-78 | 铠的克制关系 | ENTITY_UNKNOWN | clarify | 同上 |

- 4 条来源**均为需求方 2026-10-16 的真实手测问句**（缺陷报告 §1 实测表逐句可查），**非实现方自编**。
- `expect_type=clarify` 是**裁定后的设计预期**（走方向澄清），**不是把缺陷固化成预期**——这一点在 `freeform.yaml` 注释里显式写明。
- **历史存量不追溯**：`freeform.yaml` 在 2026-10-16 之前的 74 条用例由实现方编写、未标注来源，这是 D1 暴露出来的既成事实，**如实记录在案，不补造来源**（补造等于把这条规则本身变成摆设）。

---

## 10. 评测集规模变化与口径标注（防跨阶段对账混乱）

追加 F-75~F-78 后，评测集规模发生变化。**必须标注口径**，否则会与 M6 报告里的数字对不上：

| 口径 | 覆盖集 | 泛化集 | 合计 | 说明 |
| --- | --- | --- | --- | --- |
| **M6 指标口径**（固化答案集） | 69 turn | **74 turn** | **147 turn** | M6 全部指标（85.1% / 98.7% / 4.1% / 4.7% …）均基于此，**D1 未重跑、未改动该口径** |
| **D1 之后评测集文件规模** | 69 turn | **82 turn** | **151 turn** | 泛化集新增 4 条零提示用例 |

- **为什么 D1 不重跑 M6 评测**：4 条新增用例**全部落在澄清路径**，澄清在检索之前分流、**不调用 LLM**、不需要重新生成答案，**离线即可核验**（已由 `test_eval_case_policy.py` 第 5 条断言核验）。按项目既定原则「**离线可验证的改动不得触发答案重新生成**」（已写入 `DECISIONS.md`），故不重跑。
- **README / eval_report 的口径**：README「泛化集 74 条」指的是 **M6 指标口径**，仍然正确；本次在 README「评测结果」小节补一句脚注，说明 D1 之后泛化集文件为 82 条（新增 4 条零提示用例，离线可验，未纳入 M6 固化答案集）。

---

## 11. 未做项与已知边界（如实记录）

1. **L3-(b) 双方向合并答案：未做**。按需求方裁定走方向澄清（不新增意图、不动 4.4 封闭枚举）。若将来需求方改判为 (b)，则需同步更新 M6 评测集与「意图路由准确率」口径。
2. **历史 74 条泛化集用例的来源：未补造**。如实记录为「实现方编写、未标注来源」的历史存量（见 §9）。
3. **单字实体别名局限（不在 D1 范围内）**：`link("没认出凯旋门")` 会因单字别名「凯」误命中英雄「铠」。这是实体链接层**已知且已登记**的单字实体局限（见 `app/retrieval/entity_linking.py` 模块 docstring），**不属于 D1 的三层根因**；本次只用 `test_kai_rotating_door_still_clarifies_not_rejects` 钉住「**即便误命中，仍走澄清而非拒答**」这一条（4.3 / 9.2-5 绝不允许走拒答），**不把误命中当成正确行为**。
4. **`_candidates` 的英雄清单仍取 `_POPULAR` 十人**：这是「一个实体都没认出」场景下的兜底清单，与输入无关是**设计意图**（用户打错英雄名，给一份正确候选让他挑）。报告点名的「与输入无关的固定名单」问题，指的是**已认出实体时仍给这份清单**——该问题已修复。
5. **规格书同步**：本仓库内**不含规格书文件**（规格书 v1.6 为需求方侧文档，未随仓库分发），故本次无法直接改规格书；受影响的小节为 **§4.9（unrecognized 判据）/ §4.3（澄清分支）/ §4.4（意图枚举封闭）**，建议需求方侧同步，条目已登记在 `DECISIONS.md`。

---

## 12. 硬约束自检

| 硬约束 | 自检结果 |
| --- | --- |
| 4.9 的 `unrecognized` 不得失真 | ✅ 11 句残句全部归零；防漂移测试遍历意图词表钉住 |
| 4.3 / 9.2-5「有王者语境但实体没认出 → 澄清，绝不拒答」 | ✅ `test_pure_unrecognized_still_clarifies` / `test_kai_rotating_door_still_clarifies_not_rejects` |
| 4.4 意图枚举封闭、实现方不得新增取值 | ✅ 用 `clarify_kind` 标记，**未新增意图枚举** |
| 既有测试零改动 | ✅ `git diff --name-only` 在 `tests/` 下只有 `tests/eval/freeform.yaml`（纯新增数据） |
| 不得为测试降级停止在线服务 | ✅ Neo4j / Chroma / LLM 全程在线，未停未改 |
| 评测集不得修改来凑指标 | ✅ 只**追加** 4 条，未改动任何既有用例的期望值 |
| 单次口径不得静默变更 | ✅ §10 显式标注两个口径（147 turn vs 151 turn） |
| 缺测的数字不得硬报 | ✅ 未重跑 M6，故不重报 M6 指标；新增 4 条离线核验并说明理由 |
