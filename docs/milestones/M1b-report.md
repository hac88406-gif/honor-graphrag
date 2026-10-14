# M1b 交付报告 — 数据层（全量 133 英雄入库）

> 生成日期：2026-10-14　规格书：v1.4　快照：`data/raw/20261014-230459`
> 格式依据：规格书 11.3（四项缺一视为未完成）。
> **状态：已完成，按 11.4-4 停下等待需求方审核，未进入 M2。**

---

## 1. 变更文件清单

### 1.1 新增（M1b）

| 文件 | 说明 |
| --- | --- |
| `app/utils/chroma.py` | **统一 collection 入口**（规格书 4.6 强制项）：`get_collection()` 内部固定传 bge EF，消除「裸取回退默认 ONNX 模型」的静默失败 |
| `scripts/data_profile.py` | COUNTERS 出度/入度画像 + `hr3 反向引用 = 0` 边界英雄清单 |
| `data/data_profile.md` | 数据画像产物（由上一脚本生成） |
| `tests/conftest.py` | 把项目根与 `scripts/` 加入 `sys.path`，供测试直接 import 脚本模块 |
| `tests/test_data_pipeline.py` | 四项回归用例（幂等 / 配对 / 算子差异 / EF 重启回归） |
| `docs/milestones/M1b-report.md` | 本报告 |

### 1.2 修改（M1b）

| 文件 | 说明 |
| --- | --- |
| `scripts/build_graph_data.py` | 由「只导出 5 样例英雄」改为**全量 133 英雄**；别名缺省为空列表；桩节点预期为 0 |
| `scripts/build_guides.py` | 由「5 篇 C1」改为**全量 133 篇 C1**（每英雄一篇） |
| `scripts/init_chroma.py` | EF 加载与 client 获取改从 `app/utils/chroma.py` import（删除脚本内第二份 EF 定义）；新增 `$in` vs `$contains` 算子对照打印；chunk 数断言由 `≥10` 提至 `≥100` |
| `scripts/init_graph.py` | 文档字符串对齐 M1b 全量口径（桩节点数降为 0；建桩逻辑保留兼容部分入库） |
| `scripts/build_review.py` | 审核清单改为 M1b 全量口径（全量关系汇总 + 5 演示英雄逐条 + C1:C2 比例 + 别名口径） |
| `scripts/fetch_official.py` | 细化「出装引用缺失」段：4 个 ID、双向核对非解析遗漏、`91040` 命名空间说明 |
| `data/REVIEW.md` | 重生成（798 关系 / 138 篇语料 / 4 缺失装备 / 5 重复边） |
| `data/fetch_report.md` | 重生成（含「出装引用缺失」完整说明） |
| `README.md` | 里程碑状态更新；新增「数据层构建（可复现）」；数据来源声明替换为真实规模 + 数据洞察 + 数据局限 |
| `DECISIONS.md` | 追加 M1b 数据层决策 3 条（统一 `get_collection()`、全量入库范围、语料构成 C1:C2） |
| `.gitignore` | 新增 `data/raw/`（含 136 个 `.bin` 缓存，约 16.7MB；快照可重跑，不入库） |

### 1.3 生成物（非版本库）

- `data/chroma/`（向量库持久化，`.gitignore` 排除）
- `models/bge-large-zh-v1.5/`（1.24GB，`.gitignore` 排除）
- `data/raw/`（抓取快照，`.gitignore` 排除，可由 `fetch_official.py` 重跑）

---

## 2. 真实运行证据

### 2.1 Neo4j 全量导入（`python scripts/init_graph.py`）

```
[graph] 导入前节点： {'Hero': 133, 'Inscription': 93, 'Item': 115}
[graph] 导入前关系： {'COUNTERS': 527, 'RECOMMENDS_INSCRIPTION': 798, 'RECOMMENDS_ITEM': 1574, 'SYNERGIZES': 266}
[graph] 本次写入： {'full_heroes': 133, 'stub_heroes': 0, 'items': 115, 'inscriptions': 93,
                    'hero_rel_rows': 798, 'item_edge_rows': 1574, 'ins_edge_rows': 798,
                    'skipped_item_refs': 20, 'skipped_ins_refs': 0}
[graph] 导入后节点： {'Hero': 133, 'Inscription': 93, 'Item': 115}
[graph] 导入后关系： {'COUNTERS': 527, 'RECOMMENDS_INSCRIPTION': 798, 'RECOMMENDS_ITEM': 1574, 'SYNERGIZES': 266}
```

- 节点合计 **341**（Hero 133 + Item 115 + Inscription 93），关系合计 **3165**。
- `stub_heroes = 0`：全量入库后关系端点全在 133 个英雄之内，M1a 的邻居桩节点机制自然消失。
- `skipped_item_refs = 20`：4 个缺失装备 ID 的 20 处引用未建 `RECOMMENDS_ITEM` 边（不造桩，见 §4.1）。
- `RECOMMENDS_ITEM = 1574` 的构成（**脚本统计，不手数**）：源引用 **1594** = 133 英雄 × 2 套 × 6 件 **− 2**
  （`元流之子(法师)` 两套出装官方各只给 **5 件**；全量 266 套中 264 套为 6 件、仅此 2 套为 5 件，且这 10 个 ID 均有效），
  再减 20 处缺失装备引用 = **1574**。核账命令：
  `python -c "import json,collections;h=json.load(open('data/graph/heroes.json',encoding='utf-8'));print(sum(len(b) for x in h for b in x['item_sets']), dict(collections.Counter(len(b) for x in h for b in x['item_sets'])))"`

**幂等**：`tests/test_data_pipeline.py::test_neo4j_import_idempotent` 对同一份数据连续 `import_all` 两次，
断言节点数/关系数逐项不变——已通过（见 §2.4）。

> **核账方式（用脚本/查询统计，不靠手数）** —— 数据源 `relations.json` 的行数与 Neo4j 边数**相差 5**，是去重所致：
> - 数据源实测 **798 行**（COUNTERS **532** / SYNERGIZES 266）。核账命令：
>   `python -c "import json,collections;d=json.load(open('data/graph/relations.json',encoding='utf-8'));print(len(d),dict(collections.Counter(r['type'] for r in d)))"`
> - Neo4j 实测 **793 条英雄-英雄边**（COUNTERS **527** / SYNERGIZES 266）。核账查询：
>   `MATCH ()-[r:COUNTERS|SYNERGIZES]->() RETURN type(r) AS t, count(r) AS c`
> - 差值 **5** = 5 条 COUNTERS 被两处官方页各述一次，按唯一键 `起点+类型+终点+patch` MERGE 合并
>   （清单见 `data/REVIEW.md` §4.2）：花木兰→墨子、兰陵王→鲁班七号、孙膑→李白、王昭君→吕布、露娜→虞姬。
> - 因此 Neo4j 侧 `COUNTERS: 527` 是**去重后**的边数；而 `data/data_profile.md` 的度数画像基于**导出的 `relations.json`**
>   （798 行 / COUNTERS 532），其「出边合计 = 入边合计 = 532」即由此而来。两者差 5 条即上述重复边，
>   两个口径各自自洽，不矛盾。

### 2.2 Chroma 全量导入（`python scripts/init_chroma.py`）

```
[chroma] 语料 138 篇 -> chunk 540 条
[chroma] chunk 字数 min/median/max = 114/444/580
[chroma] 已删除旧 collection guides（幂等重建）
[chroma] collection.count() = 540
[chroma] 抽查 query('貂蝉怎么出装', hero_ids=141) 命中：
  - c1-diaochan-official#3: 静之靴 → 噬神之书 → 暴烈之甲 → 痛苦面具 → 极寒风暴 → 辉月 - T...
  - c2-diaochan-laning#0: 貂蝉是一位靠持续位移与被动印记打输出的法刺，上手难度较高。她的核心是二技能缘·心...
[chroma] 对照：$in 命中 0 条（预期 0），$contains 命中 2 条（预期 >0）
```

- 138 篇语料（C1 133 + C2 5）切分为 **540** chunk，满足 M1b「chunk ≥ 100」。
- 每次运行先删同名 collection 再重建，重复执行 `count()` 不漂移（幂等）。
- 末尾的算子对照即规格书 4.6 陷阱一的现场复现：**列表字段 `hero_ids` 用 `$in` 静默返回 0，用 `$contains` 命中 2**。
- 字数区间 114/444/580：目标 300~500（含 100 字重叠时上限约 600）；`min 114` 来自短列表项段落。

### 2.3 数据画像（`python scripts/data_profile.py`）

```
[profile] 英雄 133；出边合计 532；入边合计 532
[profile] hr3 反向引用=0：71 个
[profile] 入度=0：0 个 -> []
[profile] 出度=0：0 个 -> []
[profile] 出度 Top5：[('花木兰', 27), ('兰陵王', 24), ('貂蝉', 19), ('孙尚香', 16), ('项羽', 15)]
[profile] 入度 Top5：[('鲁班七号', 29), ('后羿', 20), ('王昭君', 17), ('黄忠', 13), ('妲己', 11)]
```

完整 133 英雄明细与边界清单见 `data/data_profile.md`。

### 2.4 pytest（`python -m pytest -v`）

```
tests/test_data_pipeline.py::test_neo4j_import_idempotent PASSED         [ 16%]
tests/test_data_pipeline.py::test_relation_pairing_lengths PASSED        [ 33%]
tests/test_data_pipeline.py::test_list_field_operator_in_vs_contains PASSED [ 50%]
tests/test_data_pipeline.py::test_ef_restart_regression PASSED           [ 66%]
tests/test_smoke.py::test_app_root PASSED                                [ 83%]
tests/test_smoke.py::test_health_returns_three_component_status PASSED   [100%]

============================= 6 passed in 15.94s ==============================
```

**测试数量 6，全部通过**（M1b 新增 4 项数据层用例 + M0 原有 2 项冒烟）。四项用例对应关系：

| 用例 | 对应 M1b 要求 |
| --- | --- |
| `test_neo4j_import_idempotent` | 幂等：同一份数据跑两次，节点数/关系数不变 |
| `test_relation_pairing_lengths` | 配对：每页三区块「英雄列表长度 == 理由列表长度」（不等即失败） |
| `test_list_field_operator_in_vs_contains` | 算子差异：`$in` 返回空、`$contains` 有命中 |
| `test_ef_restart_regression` | EF 重启回归：重启后重取 collection，同一句查询结果一致 |

### 2.5 度数口径（消除方向歧义）

官方每页给两段克制关系：`hr2` 压制英雄 = 本英雄压制对方；`hr3` 被压制英雄 = 对方压制本英雄。
图谱中 `COUNTERS` 出边（`from_id`=本英雄）= 本英雄压制别人；入边（`to_id`=本英雄）= 别人压制本英雄。

三层计数：**本页正向**（本英雄自己页面上的条数，官方恒为 2）+ **反向引用**（本英雄出现在其他英雄页面区块的次数）= **图谱合计**。

- 出边合计 = 入边合计 = 532（每条边同时是某英雄的出边、另一英雄的入边）。
- 出度 Top：花木兰 27、兰陵王 24、貂蝉 19（= 本页 2 + 反向引用 25/22/17）。
- 入度 Top：鲁班七号 29、后羿 20、王昭君 17（= 反向引用 27/18/15）。

---

## 3. 验收项逐条结论（对照规格书 M1b 验收）

| # | 验收标准 | 结论 | 证据 |
| --- | --- | --- | --- |
| 1 | 全量 133 英雄入库（英雄节点 133） | **通过** | §2.1：Hero 节点 133，`stub_heroes=0` |
| 2 | 关系数 ≥ 500 | **通过** | §2.1：英雄-英雄边 793（源 798 行）；含出装/铭文搭配共 3165 |
| 3 | 装备 115 / 铭文 93 | **通过** | §2.1：Item 115 / Inscription 93 |
| 4 | 语料 ≥ 100 篇、chunk ≥ 100 | **通过** | §2.2：138 篇 → 540 chunk |
| 5 | 导入幂等（同一份数据两次不增长） | **通过** | §2.4 `test_neo4j_import_idempotent`；Chroma 删库重建 count 不漂移 |
| 6 | 关系配对断言固化 | **通过** | §2.4 `test_relation_pairing_lengths`（全量 133 页重解析，无 `RelationPairError`） |
| 7 | 算子差异固化（`$in` 空 / `$contains` 命中） | **通过** | §2.4 `test_list_field_operator_in_vs_contains` |
| 8 | EF 重启回归固化 | **通过** | §2.4 `test_ef_restart_regression` |
| 9 | 统一 `get_collection()` 入口，禁止裸取 collection | **通过** | `app/utils/chroma.py`；`init_chroma.py` 已改为 import 该模块 |
| 10 | C1 为主干（C1:C2 ≥ 3:1） | **通过** | §3 语料 C1 133 : C2 5 ≈ 27:1（`data/REVIEW.md` §3） |
| 11 | 数据画像（COUNTERS 出度/入度 + hr3=0 清单） | **通过** | §2.3 + `data/data_profile.md` |

M1b 交付物齐备性：

| 交付物 | 状态 |
| --- | --- |
| 全量抓取 + 入库脚本（幂等）+ 统一 EF 入口 | 完成 |
| 全量 133 英雄 / 装备 115 / 铭文 93 / 语料 138 篇入库 | 完成（Neo4j 341 节点、3165 关系；Chroma 540 chunk） |
| 四项 pytest 回归用例 | 完成（6 passed） |
| 数据画像（出度/入度 + 边界清单） | 完成（`data/data_profile.md`） |
| 审核清单 `data/REVIEW.md`（M1b 口径） | 完成 |
| 覆盖率报告 `data/fetch_report.md`（含缺失装备说明） | 完成 |

---

## 4. 未达标项及需需求方确认事项

**无硬性验收项未通过。** 以下为需需求方知晓 / 确认的事项（关键项均已记入 `DECISIONS.md`）：

1. **【已按要求补充】缺失装备 4 处，已跳过、未造桩。** 全量 133 英雄共 4 个装备 ID（`1223`(2)、`1225`(1)、`1722`(16)、`91040`(1)，共 20 处引用）不在官方 `item.json`（115 件）中：
   - 已确认是「`item.json` 里确实没有」而非解析遗漏——在原始 `item.json` 与解析结果中**双向核对**均查无此 ID；
   - `1223`/`1225`/`1722` 属常规 4 位 `item_id` 的编号缺口（`1722` 尤其明显：目录含 1721/1723/1724/1725/1727/1728，唯独缺 1722）；
   - `91040` 为 **5 位 ID，属另一套编号命名空间**（官方 5 位 ID 仅 8 个且全在 `11xxx`–`13xxx`，`91040` 落在 `9xxxx` 段）；
   - 已在 `data/fetch_report.md` 记一条，`data/REVIEW.md` §4.1 列全 4 个 ID。

2. **【已按要求修正】M1a 报告数字对账。** M1a 报告正文曾写 COUNTERS 99 / SYNERGIZES 20（合计 119），与当时 `relations.json`（COUNTERS 100 / SYNERGIZES 20 = 120）不符；根因是正文误用了 Neo4j 去重后的边数。`docs/milestones/M1a-report.md` §2.2 已补「核账方式」（附可复现的统计命令/查询），并注明差值 1 条来自兰陵王→鲁班七号重复边合并。**后续所有计数一律以脚本/查询为准，不手数。**

3. **【需知晓】重复关系由 1 条增至 5 条（全量口径）。** 5 条 COUNTERS 被两处官方页各述一次，导入时按唯一键合并（`data/REVIEW.md` §4.2）：花木兰→墨子、兰陵王→鲁班七号、孙膑→李白、王昭君→吕布、露娜→虞姬。事实与方向一致，语料与图谱不冲突。

4. **【需知晓】数据画像的边界英雄。** `hr3 反向引用 = 0` 的英雄 **71 个**（含亚瑟）；这些英雄从未被任何其他英雄页面列为「被压制英雄」，问「XX 被谁克制」时图谱**必然返回空** → 走拒答或降级。`COUNTERS` 入边 = 0 / 出边 = 0 的英雄均为 **0 个**。清单见 `data/data_profile.md`，并已写入 README「数据局限」。

5. **【已按要求完成】git 仓库与分组提交。** 已 `git init`，`.gitignore` 新增 `data/raw/`；按里程碑分组提交：M0 骨架 / M1a 抓取与数据 / M1b 全量入库与测试 / docs。`.env` 保持排除。

6. **【已按要求完成】C1 明显主导。** 语料构成 C1 133 : C2 5 ≈ 27:1（M1a 时 5:5 仅为样例），满足「≥3:1」。

7. **【已按要求说明】`RECOMMENDS_ITEM` 实测 1574 的差额来源。** 与「133 英雄 × 2 套 × 6 件 = 1596」估算相差 **22** = **20**（4 个缺失装备 ID 的引用，未建边）+ **2**（`元流之子(法师)` 两套出装官方各只给 **5 件**——全量 266 套中仅此 2 套为 5 件，其 10 个 ID 均有效，**非解析遗漏、也非缺失装备**）。核账方式见 §2.1（脚本统计，不手数）。

---

## 5. 下一步

按规格书 11.4-4，**M1b 结束停下等待需求方审核**，不进入 M2。请重点审核：

- `data/REVIEW.md`（798 关系汇总 + 5 演示英雄逐条 URL + §4 不确定项）；
- `data/data_profile.md` 的度数分布与边界英雄清单（M6 评测集素材）；
- `data/fetch_report.md` 的出装引用缺失说明；
- README 的「数据洞察 / 数据局限」表述是否恰当；
- 上文第 4 节的确认事项。

**M2 复核要求（需求方 2026-10-14 补充，已记入 `DECISIONS.md`）**：M2 完成后复跑一次同类数据层校验（节点/关系计数 + `source/patch/reason` 完整性），确认检索层未破坏数据，并在 M2 报告中附真实输出。
