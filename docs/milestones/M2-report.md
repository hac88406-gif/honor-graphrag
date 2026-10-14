# M2 交付报告 — 检索层（不接 LLM 生成）

> 生成日期：2026-10-14　规格书：v1.4　快照：`data/raw/20261014-230459`
> 格式依据：规格书 11.3（四项缺一视为未完成）。
> **状态：已完成，按 11.4-4 停下等待需求方审核，未进入 M3。**

---

## 1. 变更文件清单

### 1.1 新增（M2）

| 文件 | 说明 |
| --- | --- |
| `app/schemas/entity.py` | `LinkedEntity`（规格书 4.3 逐字段照搬；`entity_type`/`method` 封闭枚举） |
| `app/schemas/chat.py` | `Evidence` / `Citation` / `ChatResponse`（规格书 5.1 完整契约，M2 一次落齐避免 M3/M4 返工） |
| `app/schemas/__init__.py` | 统一导出契约 |
| `app/retrieval/entity_linking.py` | 实体链接层：归一化（繁简/全半角/ASCII 大小写/去空白）+ 三级策略（精确 / 别名表 / 拼音音节编辑距离） |
| `app/retrieval/intent.py` | 意图路由（10 个封闭意图）+ 槽位抽取；规则路径默认，LLM 路径可选且异常回落 |
| `app/retrieval/cypher_templates.py` | 7 个参数化 Cypher 模板注册表 + `INTENT_TO_TEMPLATE` 封闭映射 |
| `app/retrieval/neo4j_client.py` | Neo4j 访问封装：`run_template` / `rows_to_evidence` / `query_evidence`，失败抛 `GraphUnavailable` |
| `app/retrieval/chroma_client.py` | 向量检索封装：`build_where`（标量 `$in` / 列表 `$contains`）+ `raw_query` / `search` |
| `app/retrieval/bm25.py` | jieba 分词 + BM25 + RRF 融合（`hybrid_search`） |
| `tests/unit/test_entity_linking.py` | 实体链接单测（**51 个用例** + 7 个行为用例） |
| `tests/unit/test_cypher_templates.py` | 模板注册表 + **方向断言**（静态 6 + 动态 8） |
| `tests/unit/test_retrieval_chroma.py` | 算子差异 / EF 重启 / 版本过滤实际召回 / BM25-RRF（8 用例） |
| `scripts/verify_data_layer.py` | **数据层复跑校验**脚本（三层计数 + source/patch/reason 完整性） |
| `docs/milestones/M2-report.md` | 本报告 |
| `docs/module-notes/m2-retrieval.md` | M2 模块三段说明（规格书 9.1-1） |

### 1.2 修改（M2）

| 文件 | 说明 |
| --- | --- |
| `app/config.py` | 新增 `GRAPH_TOP_K`（模板 LIMIT）、`VECTOR_TOP_K` / `BM25_TOP_K` / `RRF_K` / `USE_BM25` |
| `app/utils/chroma.py` | `load_embedding_function()` 加进程内缓存（1.2GB 模型不再每次重载）；**不改「必须显式传 EF」契约** |
| `app/retrieval/neo4j_client.py` | `run_template` 首参改名 `template`（避免与 `HERO_BY_NAME` 的 `$name` 冲突） |
| `app/retrieval/entity_linking.py` | `normalize` 增加 ASCII 大小写归一（使 `AD`/`ADC` 分路口语可命中） |
| `data/hero_aliases.json` | 别名表由 5 个样例英雄扩展到 **38 个**（M1b 遗留项：全量别名按需补齐） |
| `data/graph/heroes.json` | 由 `build_graph_data.py` 重跑同步 aliases（别名并集） |
| `DECISIONS.md` | 追加 M2 决策 7 条 |
| `README.md` | 里程碑状态更新（M2 完成待审） |

> 说明：`data/hero_aliases.json` 的扩展由 `scripts/build_graph_data.py` 同步进 `heroes.json`（该脚本读两份别名取并集）。

---

## 2. 真实运行证据

### 2.1 pytest（`python -m pytest tests -v`）

```
tests/test_data_pipeline.py  ... 4 passed   (M1b 数据层回归)
tests/test_smoke.py          ... 2 passed   (M0 冒烟)
tests/unit/test_cypher_templates.py  ... 14 passed
tests/unit/test_entity_linking.py    ... 58 passed
tests/unit/test_retrieval_chroma.py  ...  8 passed
============================= 86 passed, 1 warning in 17.96s ==============================
```

M2 新增 **80 个用例**，全部通过（1 warning 为 chromadb 内部 `is_legacy` DeprecationWarning，与断言无关）。
其中 `test_entity_linking.py` 的 51 个参数化用例即规格书 M2 验收要求的「20+ 别名/错别字用例」。

用例对应 M2 验收项：

| 文件 / 用例 | 对应验收项 |
| --- | --- |
| `test_entity_linking.py`（51 参数化 + 行为用例） | 实体链接单测（≥20 别名/错别字；含昵称、简称、分路口语、繁体、全半角、模糊） |
| `test_cypher_templates.py::test_direction_arrows_in_template_text` | **静态方向断言**：被谁克制=入边 / 克制谁=出边 |
| `test_cypher_templates.py::test_counters_of_hero_rows_subject_is_queried_hero` | **动态方向断言**：出边查询 subject 恒为被查英雄 |
| `test_cypher_templates.py::test_counters_by_hero_rows_target_is_queried_hero` | **动态方向断言**：入边查询 target 恒为被查英雄 |
| `test_cypher_templates.py::test_counter_edge_cross_consistency_known_pair` | 方向正反交叉验证（兰陵王→李白，且无反向边） |
| `test_cypher_templates.py::test_counter_out_degree_dedup_caliber` | 出度对账（源 24 / 去重 23，落点=三层计数口径） |
| `test_cypher_templates.py::test_graph_version_filter_returns_no_rows_for_old_patch` | 图谱侧版本过滤（实际召回为空） |
| `test_cypher_templates.py::test_query_evidence_structure_matches_5_1` | evidence[] 结构符合 5.1 |
| `test_retrieval_chroma.py::test_metadata_operator_in_vs_contains` | **元数据算子差异**（`$in` 空 / `$contains` 命中） |
| `test_retrieval_chroma.py::test_ef_restart_regression` | **embedding function 重启回归** |
| `test_retrieval_chroma.py::test_version_filter_actual_recall` | **版本过滤测实际召回**（断言 ids，非 count） |
| `test_retrieval_chroma.py::test_hero_filter_actual_recall` | 英雄元数据过滤的实际召回（防跨英雄串味） |
| `test_retrieval_chroma.py::test_build_where_operator_mapping` / `test_rrf_fuse_ranks_shared_doc_first` / `test_tokenize_drops_punctuation` / `test_hybrid_search_returns_evidence` | 算子映射（离线）/ RRF / 分词 / 混合检索 |
| `test_cypher_templates.py`（其余） | 7 模板注册表、参数化无拼接、意图→模板封闭、出装/铭文/按名/按分路模板 |

### 2.2 数据层复跑校验（`python scripts/verify_data_layer.py`）— 真实输出

> 需求方 2026-10-14 要求：M2 完成后复跑一次同类数据层校验（节点/关系计数 + `source/patch/reason` 完整性），
> 确认检索层未破坏数据。以下为脚本**原样输出**（三层计数口径逐项标明）：

```
========================================================================
[verify] 数据层复跑校验  快照 = 20261014-230459
========================================================================

【1】源数据层（data/raw/{snapshot}/parsed，未去重）
  英雄 = 133  装备 = 115  铭文 = 93
  关系行数 = 798
    COUNTERS                 = 532
    SYNERGIZES               = 266

【2】导出层（data/graph/relations.json，按页展开，仍不去重）
  英雄 = 133  装备 = 115  铭文 = 93
  关系行数 = 798
    COUNTERS                 = 532
    SYNERGIZES               = 266
  [ OK ] 导出层行数 == 源数据层行数（798，未去重）
  [ OK ] 英雄节点数 == 抓取英雄数（133，全量 133）
  导出层关系：source 空 = 0，patch 空 = 0，reason 空 = 0
  [ OK ] 导出层全部关系都有 source
  [ OK ] 导出层全部关系都有 patch
  源数据层重复边（会被 MERGE 合并）：COUNTERS 5 条，SYNERGIZES 0 条

【3】入库后层（Neo4j，MERGE 唯一键 = 起点+类型+终点+patch，已去重）
  [重导入] 幂等写入 data/graph/*.json ...
  本次写入：{'full_heroes': 133, 'stub_heroes': 0, 'items': 115, 'inscriptions': 93, 'hero_rel_rows': 798, 'item_edge_rows': 1574, 'ins_edge_rows': 798, 'skipped_item_refs': 20, 'skipped_ins_refs': 0}
  节点：{'Hero': 133, 'Inscription': 93, 'Item': 115}
  关系：{'COUNTERS': 527, 'RECOMMENDS_INSCRIPTION': 798, 'RECOMMENDS_ITEM': 1574, 'SYNERGIZES': 266}
  [ OK ] 幂等：连续两次导入后节点数/关系数逐项不变
  去重口径推导：源 COUNTERS 532 - 合并 5 = 527
              源 SYNERGIZES 266 - 合并 0 = 266
  [ OK ] 入库后 COUNTERS（527）== 去重后口径
  [ OK ] 入库后 SYNERGIZES（266）== 去重后口径
  完整性检查（空 = NULL 或 空串）：
    Hero.source 空            = 0
    Hero.patch 空             = 0
    Item.source 空            = 0
    Inscription.source 空     = 0
    关系.source 空              = 0
    关系.patch 空               = 0
    COUNTERS.reason 空        = 0
    SYNERGIZES.reason 空      = 0

【4】向量库（Chroma collection 'guides'）
  collection.count() = 540（文档数，M1b 验收要求 ≥ 100）
  缺 patch 元数据 = 0，缺 hero_ids = 0，缺 source_url = 0
  patch 分布 = {'2026-10': 540}
  [ OK ] 向量库文档数 540 ≥ 100
  [ OK ] 向量库元数据（patch / hero_ids / source_url）完整

========================================================================
[verify] 结论：PASS —— 数据层复跑校验全部通过，检索层未破坏数据
========================================================================
```

**三层计数口径（本轮复核，逐层自洽）**：

| 口径 | 层 | 关系行数 / 英雄-英雄边 | COUNTERS | SYNERGIZES |
| --- | --- | --- | --- | --- |
| 源数据层 | `parsed/relations_all.json` | 798 | 532 | 266 |
| 导出层 | `data/graph/relations.json` | 798（未去重） | 532 | 266 |
| 入库后层 | Neo4j（MERGE 去重） | 793 | 527 | 266 |

差值 5 = 5 条 COUNTERS 被两处官方页各述一次，按唯一键 `起点+类型+终点+patch` 合并
（花木兰→墨子、兰陵王→鲁班七号、孙膑→李白、王昭君→吕布、露娜→虞姬）。复跑校验脚本已把该推导打成
「源 COUNTERS 532 − 合并 5 = 527」并断言 `入库后 COUNTERS == 去重后口径`。

---

## 3. 验收项逐条结论（对照规格书 M2 验收 + 需求方 M2 开工要求）

| # | 验收标准 | 结论 | 证据 |
| --- | --- | --- | --- |
| 1 | 实体链接单测通过（含 20+ 别名/错别字用例） | **通过** | §2.1：51 参数化用例（精确 7 / 简称俗称 8 / 同音错字 10 / 昵称梗 8 / 分路口语 8 / 繁体全半角 5 / 模糊 5） |
| 2 | `COUNTER_BY` 与 `COUNTER_OF` 方向测试各写断言 | **通过** | §2.1：静态箭头断言 + 动态 subject/target 断言 + 已知边交叉验证（共 3 个方向用例） |
| 3 | 元数据算子断言（`$in` 空 / `$contains` 命中） | **通过** | §2.1 `test_metadata_operator_in_vs_contains` + `test_build_where_operator_mapping` |
| 4 | embedding function 重启回归 | **通过** | §2.1 `test_ef_restart_regression`（重开 client + 显式传 EF，ids/distances 一致） |
| 5 | 版本过滤测**实际召回结果**（不能只测 count） | **通过** | §2.1 `test_version_filter_actual_recall`（临时 collection 构造旧/新 patch 文档，断言 `old#0` 不被召回、`new#0` 被召回） |
| 6 | 输出 `evidence[]` 结构符合 5.1 | **通过** | §2.1 `test_query_evidence_structure_matches_5_1`（kind/relation/source/source_url/patch/score 逐字段） |
| 7 | 交付附「数据层复跑校验」真实输出（计数 + source/patch/reason 完整性） | **通过** | §2.2 脚本原样输出，结论 PASS |
| 8 | 附录 A 目录结构按需创建 | **通过** | `app/retrieval/`、`app/schemas/`、`tests/unit/` 已落地；`app/agent/nodes` 属 M3（见 §4-3） |

M2 交付物齐备性：

| 交付物 | 状态 |
| --- | --- |
| 实体链接模块（三级策略，规则优先不调 LLM） | 完成 |
| 意图路由模块（10 封闭意图 + 槽位；规则默认 / LLM 可选） | 完成 |
| 7 个参数化 Cypher 模板 + Neo4j 封装 | 完成 |
| 向量检索模块（patch + hero_ids 两道过滤，`$in`/`$contains` 分治） | 完成 |
| BM25 混合检索 + RRF 融合（4.6 加分项，v1 加上） | 完成 |
| 三份 pytest 单测（80 用例，全通过） | 完成 |
| 数据层复跑校验脚本 + 真实输出 | 完成 |
| 模块三段说明 `docs/module-notes/m2-retrieval.md` | 完成 |

---

## 4. 未达标项及需需求方确认事项

**无硬性验收项未通过。** 以下为需需求方知晓 / 确认的事项（关键项已记入 `DECISIONS.md` 2026-10-14 M2 节）：

1. **【需确认】意图路由默认走规则路径，偏离规格书 4.2 的「LLM 意图识别」表述。**
   理由：意图枚举封闭（4.4 不得新增）+ 输入已带实体链接结果（4.3），关键词覆盖足够；确定性 = 可单测、
   零延迟、离线可跑，契合 M2 验收全为确定性断言。LLM 路径（Ollama qwen2.5:3b 结构化输出）**已实现并保留**，
   任何失败/超时/非法输出一律回落规则路径；M6 评测若意图准确率 < 85%，可切 `use_llm=True`。**请需求方裁定是否接受此默认。**

2. **【需知晓】实体链接对「单字实体」存在误命中风险（已知局限，未掩盖）。**
   单字英雄（铠/瑶/镜/影/曜/澜/苍/暃）与别名（凯/鲲）在「电影」「眼镜」「凯旋」这类普通词里会被误命中。
   本项目输入域是王者问答，这类词概率极低；若 M6 评测发现误报，再补上下文黑名单。

3. **【需知晓】`app/agent/nodes` 属 M3 交付物，M2 未创建。**
   附录 A 中 M2 实际需要的是 `app/retrieval` 与 `app/schemas`（已落地），`tests/unit`（已落地）。
   `app/agent/`（state / graph / nodes / prompts）是 M3 LangGraph 编排层的内容，提前建空目录无内容可放
   （且空目录无法进版本库）。M3 开工时一并创建。

4. **【已按要求完成】统一计数口径贯穿本批交付。**
   §2.2 复跑校验的三层计数逐项标注层级；`test_counter_out_degree_dedup_caliber` 把「源 24 / 去重 23」的落点
   （兰陵王→鲁班七号合并边）固化为断言。M1b 批次的统一口径改动见 commit `062edb8`。

5. **【已按要求完成】git 分组提交。**
   本批按「feat(m2): 检索层模块与单测」「chore(m2): 数据层复跑校验脚本」「docs(m2): 报告与模块说明」分组提交，
   工作树干净、无多余文件进版本库（`data/raw/`、`data/chroma/`、`models/` 均在 `.gitignore`）。

---

## 5. 下一步

按规格书 11.4-4，**M2 结束停下等待需求方审核**，不进入 M3。请重点审核：

- `app/retrieval/` 五个模块的实现口径（尤其意图路由「规则优先」的取舍，见 §4-1）；
- `tests/unit/` 三份单测与 `scripts/verify_data_layer.py` 的真实输出（§2）；
- `docs/module-notes/m2-retrieval.md` 的三段说明是否覆盖面试追问点；
- `DECISIONS.md` 2026-10-14 M2 节 7 条决策。

**需求方人工抽查（c2 语料质量 / 重点英雄合理性）与 M2 并行进行**：若发现问题只涉及语料内容，不回滚 M2；
若发现结构性问题会立刻叫停。
