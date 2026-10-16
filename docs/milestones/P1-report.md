# 补丁 P1 · 能力端点补齐 — 交付报告

> 契约：`项目一-补丁P1-能力端点补齐契约.md`
> 性质：**补丁级改动**（新增 3 个端点 / 1 个复位脚本 / 1 个共享契约模块），不是重做，也不是「项目一没做完」。
> 日期：2026-10-16

---

## 0. 交付范围

| 类型 | 文件 | 状态 |
| --- | --- | --- |
| 新增 router | `app/api/graph.py`（P1-1 只读 + P1-3 写） | 新增 |
| 新增 router | `app/api/retrieval.py`（P1-2 只读） | 新增 |
| 新增共享契约 | `app/api/_contract.py`（错误形状 / `patches` 校验 / 英雄消歧） | 新增 |
| 新增脚本 | `scripts/reset_graph.py`（删全部关系 + 复用 `import_all` 重建） | 新增 |
| 新增测试 | `tests/integration/test_p1_apis.py` | 新增（44 条） |
| 修改（最小） | `app/main.py`（注册 2 个 router + `ContractError` 应用级处理器） | 修改 |
| 修改（最小） | `app/retrieval/neo4j_client.py`（新增 `run_cypher` 写入侧唯一入口） | 修改 |
| **未改动** | `app/api/chat.py` / `app/api/docs.py` / `app/agent/**` / **任何既有测试文件与断言** | 零改动 |

**只加不改自检**（`git diff --stat` 实测）：

```
 DECISIONS.md                  | 15 +++++++++++++++      (文档同步)
 README.md                     | 25 +++++++++++++++++++++++--  (文档同步)
 app/main.py                   | 28 ++++++++++++++++++++++------  (注册 2 个 router + ContractError 处理器)
 app/retrieval/neo4j_client.py | 22 ++++++++++++++++++++++        (新增 run_cypher，纯新增无删改)
 4 files changed, 82 insertions(+), 8 deletions(-)
```

既有代码**仅 2 处**被触碰，其余既有源文件零改动；`git diff --name-only` 输出**不含任何 `tests/` 路径** → **既有测试文件与断言零改动**。`main.py` 的 8 处删除全部来自模块 docstring 与 import 行的替换（非行为改动）。

---

## 1. 验收三元组（契约 §6-1 / §6-2-1）

```
$ REQUIRE_SERVICES=1 .\.venv\Scripts\python -m pytest -q
338 passed, 1 warning in 35.28s
```

| 项 | 数值 |
| --- | --- |
| **passed** | **338** |
| **skipped** | **0** |
| **failed** | **0** |

- **跳过项逐条理由**：**无跳过项**（`skipped = 0`），故无需理由说明，满足 §6-1「`skipped > 0` 不算通过」。
- 其中既有测试 **294** 条全绿且**零改动**；本补丁新增 **44** 条（`tests/integration/test_p1_apis.py`，`pytest --collect-only` 实测 44）。
- `1 warning` 为 chromadb 上游 `DeprecationWarning`（`BgeEmbeddingFunction` 缺 `is_legacy`），与本次改动无关，既有测试同样触发。

---

## 2. 新增用例 → 契约 §6-1 要求映射

| §6-1 要求 | 用例 | 条数 |
| --- | --- | --- |
| P1-1：5 个 `relation` 枚举各一条 | `test_relation_enums_route_to_expected_template` | 5 |
| P1-1：`limit` 越界 → 400 | `test_limit_out_of_range_returns_400` | 3 |
| P1-1：英雄无法消歧 → 404 + `candidates` | `test_hero_not_found_returns_404_with_candidates` | 1 |
| P1-1：**Neo4j 断开 → 503（不是 200、不是 500）** | `test_graph_relations_returns_503_when_neo4j_down` | 1 |
| P1-1：`COUNTER_BY` 与 `COUNTER_OF` **方向性各一条断言** | `test_counter_direction_is_not_reversed` | 1 |
| P1-2：`top_k` 越界 → 400 | `test_retrieval_top_k_out_of_range_returns_400` | 2 |
| P1-2：**Chroma 不可用 → 503** | `test_retrieval_returns_503_when_chroma_down` | 1 |
| P1-3：新建 → `action=created` 且 `verified=true`；同键重写 → `action=updated` 且**不新增关系数** | `test_put_creates_then_updates_same_key_without_adding_edges` | 1 |
| P1-3：节点不存在 → 404 | `test_put_missing_node_returns_404_and_writes_nothing` | 1 |
| P1-3：`patch` 越窗 → 400 | `test_put_patch_error_echoes_current_window` + `test_put_field_validation_returns_400` | 见下 |
| P1-3：`type` 非枚举 → 400 | 同上 | 见下 |
| **复位**：写入 → `reset_graph.py` → `verify_data_layer.py` 回到 341 / 3165 / 527 | `test_write_then_reset_returns_to_baseline` + `test_reset_then_verify_data_layer_script_passes` | 2 |
| 字段校验（`type` / `patch` / `reason` / `source` / `weight` / `id` 各取值非法 → 400） | `test_put_field_validation_returns_400` | 10 |
| 其余边界（缺必填 → 422；`relation` 非枚举 → 400；`patches` 格式 → 400 / 元素类型 → 422；`query` 空或超长 → 400；检索 `hero` 无法消歧 → 404；`limit` 生效不静默截断；检索命中原文；不带 `hero` 也 200） | 分散于其余用例 | 15 |

**方向性断言细节**（§6-1 点名项）：`test_counter_direction_is_not_reversed` 对 `COUNTER_BY`（谁克制我，入边）与 `COUNTER_OF`（我克制谁，出边）**各自断言 `hero_ids` 中目标英雄的位置**——方向写反时查询**会返回结果而不是报错**，故必须比对内容而非仅看 `count`。

---

## 3. 服务环境状态（契约 §6-2-2）

| 服务 | 状态 | 说明 |
| --- | --- | --- |
| Neo4j（Docker） | **全程运行** | P1-1 / P1-3 真实 HTTP 证据、数据层复跑校验均依赖它；**本次未停过** |
| Chroma（嵌入式 `PersistentClient`） | **全程可用** | 本地嵌入式，非独立进程；P1-2 证据与数据层校验均依赖 |
| LLM 云端 API | 未涉及 | 补丁 P1 三个端点**不调用生成侧**，故不涉及 |
| uvicorn（本补丁证据服务） | 起于 **8001**，取证完毕后**已停止** | 见下「端口说明」 |

**降级路径（503）如何测的**：两条 503 用例均用 **`monkeypatch` 在进程内**替换依赖调用（`query_evidence` / `hybrid_search` 抛 `GraphUnavailable` / `VectorStoreUnavailable`），**没有真的把 Neo4j 或 Chroma 停掉**。因此**不存在「为测降级停过服务需要恢复」的情形**——Neo4j / Chroma 自始至终在线，无需恢复动作。

**端口说明（如实登记）**：本机 8000 端口上有一个**此前启动的 uvicorn 实例**（加载的是 P1 改动前的代码），本次取证**没有动它**，另起一个新实例于 **8001** 端口跑 P1 证据，避免与既有实例冲突或污染。取证结束后 8001 实例已停止；8000 的旧实例状态未变。

---

## 4. 数据层计数：改动前 / 改动后 / 复位后（契约 §6-2-3）

口径：**入库后层**（Neo4j，MERGE 唯一键 = 起点 + 类型 + 终点 + patch，已去重）。基线 = README 声明口径 **341 节点 / 3165 关系 / COUNTERS 527**。

| 阶段 | 节点 | 关系（合计） | COUNTERS | 说明 |
| --- | --- | --- | --- | --- |
| **改动前** | 341 | 3165 | **527** | 补丁 P1 开工时基线（`verify_data_layer.py` PASS） |
| **改动后** | 341 | **3166** | **528** | P1-3 真实 HTTP 写入 1 条 `COUNTERS`（`193 -[COUNTERS{2026-10}]-> 105`）；同键重写**不再增加**（仍为 528） |
| **复位后** | 341 | 3165 | **527** | `reset_graph.py` 执行「删全部关系 + `import_all` 全量重建」后回到基线 |

**复位后验收**：`scripts/reset_graph.py` 打印「复位前 COUNTERS 528 → 复位后 527」；`scripts/verify_data_layer.py` 结论 **PASS**，逐项断言 `入库后 COUNTERS（527）== 去重后口径`、`入库后 SYNERGIZES（266）== 去重后口径`、幂等性（连续两次导入计数不变）。

> 复位脚本实测输出：
> ```
> [reset] 复位前关系： {'COUNTERS': 528, 'RECOMMENDS_INSCRIPTION': 798, 'RECOMMENDS_ITEM': 1574, 'SYNERGIZES': 266}
> [reset] 复位后节点： {'Hero': 133, 'Inscription': 93, 'Item': 115}
> [reset] 复位后关系： {'COUNTERS': 527, 'RECOMMENDS_INSCRIPTION': 798, 'RECOMMENDS_ITEM': 1574, 'SYNERGIZES': 266}
> [verify] 结论：PASS —— 数据层复跑校验全部通过，检索层未破坏数据
> ```

---

## 5. 真实 HTTP 证据（13 条，端口 8001）

| # | 场景 | 请求 | 实测 |
| --- | --- | --- | --- |
| A | P1-1 我克制谁 | `{hero:"铠", relation:"COUNTER_OF", limit:3}` | **200**，`count=3`，首条 `铠 克制 元流之子(刺客)`，`hero_ids=["193","583"]` |
| B | P1-1 谁克制我（方向对照） | `{hero:"铠", relation:"COUNTER_BY", limit:3}` | **200**，`count=3`，首条 `公孙离 克制 铠`，`hero_ids=["199","193"]`（方向与 A 相反，未写反） |
| C | P1-1 `relation` 非枚举 | `{hero:"铠", relation:"NOPE"}` | **400** `relation_invalid`，detail 回显 5 个合法枚举 |
| D | P1-1 `limit` 越界 | `limit:99` | **400** `limit_out_of_range`「必须在 1~50 之间…（越界不静默截断）」 |
| E | P1-1 英雄无法消歧 | `hero:"完全不存在的英雄zzz"` | **404** `hero_not_found`，**带 `candidates: []`** |
| F | P1-2 混合检索 | `{query:"铠怎么出装", hero:"铠", top_k:3}` | **200**，`count=3`，首条 `kind="vector"`，内容为出装原文片段 |
| G | P1-2 `query` 为空 | `{query:"   "}` | **400** `query_empty` |
| H | P1-2 `top_k` 越界 | `top_k:99` | **400** `top_k_out_of_range` |
| I | P1-3 写入·新建 | `{from_id:"193", to_id:"105", type:"COUNTERS", patch:"2026-10", …}` | **200** `action="created"`、`verified=true` |
| J | P1-3 写入·同键重写 | 同上、改 `reason` | **200** `action="updated"`、`verified=true`（关系数不增，见 §4） |
| K | P1-3 节点不存在 | `to_id:"999999"` | **404** `node_not_found`，**回显 `missing:["999999"]`** |
| L | P1-3 `patch` 越窗 | `patch:"2020-01"` | **400** `patch_out_of_window`，detail **回显当前窗口** `2026-10/2026-09/2026-08` |
| M | P1-3 `type` 非枚举 | `type:"RECOMMENDS_ITEM"` | **400** `type_invalid`，说明「本次不开放写入」 |

错误响应形状统一为 `{"error": <机器可读码>, "detail": <人类可读说明>}`（+ 404 追加 `candidates` / `missing`），与契约 §1 通用约定一致。

---

## 6. 三处文档同步（契约 §6-2-4）

| 文档 | 改动位置 | 内容 |
| --- | --- | --- |
| `README.md` | 「接口清单」表（原 6 行 → 9 行） | 新增 3 行（`POST /api/graph/relations` / `POST /api/retrieval/search` / `PUT /api/graph/relations`）；`POST /api/graph/import` 行改为「v1 不实现完整版；**单条关系写入**由 `PUT /api/graph/relations` 以受限形式提供」 |
| `README.md` | 新增「图谱复位（补丁 P1，写脏后回基线）」小节 | 说明 `init_graph.py` 纯 MERGE 只写不删 → 脏关系修不回来；给出 `reset_graph.py` + `verify_data_layer.py` 用法 |
| `README.md` | 「非目标」节 | 批量导入端点仍不提供；补 P1 受限形式说明与「鉴权/限流/审计由下游网关负责」 |
| 规格书 `§5.2` | REST 接口表 | 与 README **同表**（9 行，逐条一致）；`graph/import` 行标注改为「❌ v1 不实现完整版；单条写入由 P1-3 提供」；session / docs upload 两行状态由「📌 归 M6/M7」更新为「✅ 已实现（M6/M7）」 |
| 规格书 `§5.2` | `graph/import` 说明段 | 追加「**【补丁 P1 追加】**」段，说明以受限形式补上单条写入 + 两个只读端点 |
| `DECISIONS.md` | 新增节「2026-10-16（补丁 P1 · 能力端点补齐）」 | 9 条记录：①graph/import 从「不做」到「受限形式补上」的**原因**（需求变了，非原判断错）②`run_cypher` 写入侧唯一入口 ③错误形状 `{error,detail}` 与**有意不改** docs.py 的差异 ④503 不降级 ⑤写端点三处静默失败防护 ⑥`UPSERT_TYPES` 复述集合（同步点）⑦复位脚本语义 ⑧测试计数 ⑨三处文档同步 |

**一致性自检**：README 接口清单表与规格书 §5.2 表**逐条一致（各 9 行）**，无「列了但没实现」的条目。

---

## 7. 四条硬约束自检（契约 §2）

| 硬约束 | 结论 | 依据 |
| --- | --- | --- |
| **1. 只加不改** | ✅ | 既有代码仅 2 处最小改动（`main.py` 注册 + `neo4j_client.py` 新增函数）；`app/api/chat.py` / `docs.py` / `app/agent/**` 零改动；**既有测试文件与断言零改动**（`git diff` 中不含任何既有测试文件） |
| **2. 复用已有函数，禁止第二套实现** | ✅ | 图谱模板取 `INTENT_TO_TEMPLATE` 键（不手抄枚举）；查询走 `query_evidence`；检索直调 `bm25.hybrid_search`；消歧走 `link_heroes`；数据结构复用 `Evidence`；窗口/上限取 `settings`；写入语义逐字对齐 `init_graph.py` 的 MERGE 键与 SET 字段；复位复用 `init_graph.import_all` |
| **3. 契约与实现一致** | ✅ | 三处文档已同步（§6）；错误码口径 400/404/500/503 与契约表逐条对齐；`verified` 强制字段已实现 |
| **4. 沿用既有注释与错误码风格** | ✅ | 新模块均为「写清为什么这么设计」的 docstring；错误码口径沿用 400=字段值 / 404=找不到 / 503=依赖不可用 |

---

## 8. 未做项（防范围蔓延，契约 §3 明确不做）

- ❌ 不做鉴权 / 限流 / 审计（下游网关职责）
- ❌ 不改 `/api/chat` 的意图路由、置信度口径、guard 校验、拒答策略
- ❌ 不引入新 Cypher 模板、不改既有模板
- ❌ 不开放 `RECOMMENDS_ITEM` / `RECOMMENDS_INSCRIPTION` 的关系写入
- ❌ 不做批量导入端点（`POST /api/graph/import` 完整版仍不提供）
- ❌ 不在 Python 侧改动任何向量化 / embedding / 检索逻辑
