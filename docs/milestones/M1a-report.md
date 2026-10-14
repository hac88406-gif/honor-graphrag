# M1a 交付报告 — 数据层（抓取与样例阶段）

> 生成日期：2026-10-14　规格书：v1.3　快照：`data/raw/20261014-214848`
> 格式依据：规格书 11.3（四项缺一视为未完成）。
> **状态：已完成，按 11.4-4 停下等待需求方数据审核，未进入 M1b。**

---

## 1. 变更文件清单

### 1.1 新增（M1a）

| 文件 | 说明 |
| --- | --- |
| `scripts/fetch_official.py` | 全量抓取 133 英雄 + 115 装备 + 93 铭文，落原始快照；含乱码断言与关系配对断言 |
| `scripts/build_graph_data.py` | 从最新快照导出阶段一入库数据（heroes/relations/items/inscriptions + hero_lookup） |
| `scripts/init_graph.py` | Neo4j 约束/索引 + MERGE 幂等导入（节点与四类关系） |
| `scripts/init_chroma.py` | 语料语义切分（300~500 字/重叠 100）+ bge embedding + Chroma 幂等重建 |
| `scripts/build_guides.py` | 由快照自动生成 C1 官方聚合语料（不经人工改写） |
| `scripts/build_review.py` | 由 `data/graph/*.json` 与 `data/guides/*.md` 自动生成 `data/REVIEW.md` |
| `scripts/download_embedding_model.py` | 从 ModelScope 拉取 bge-large-zh-v1.5 到 `models/`（断点续跑） |
| `data/raw/20261014-214848/` | 原始抓取快照（herolist/item/ming + parsed + herodetail 页 + fetch_meta.json） |
| `data/fetch_report.md` | 三项关系覆盖率统计 + 解析失败清单（自动生成） |
| `data/DATA_SCOPE.md` | 重点英雄清单 20 个（按规格书 1.12 规则）+ 规则自检 |
| `data/graph/{heroes,relations,items,inscriptions,hero_lookup}.json` | 阶段一入库数据 |
| `data/guides/*.md`（10 篇） | C1 官方聚合 5 篇 + C2 对线思路 5 篇 |
| `data/hero_aliases.json` | 5 个样例英雄别名（每英雄 6 个，≥5 要求） |
| `data/REVIEW.md` | 数据审核清单（逐条官方 URL + llm_assisted 单列 + 不确定项） |
| `requirements-ml.txt` | ML 重依赖（sentence-transformers，M1a 阶段安装） |

### 1.2 修改（M1a）

| 文件 | 说明 |
| --- | --- |
| `app/config.py` | 新增 `EMBEDDING_MODEL_DIR`（本地模型目录优先加载，避免运行时联网） |
| `.env.example` | 同步新增 `EMBEDDING_MODEL_DIR` 及注释 |
| `.gitignore` | 新增 `models/`（1.24GB 本地模型不入库） |
| `DECISIONS.md` | 追加 M1a 数据层决策 8 条（分路/装备/铭文编码映射、样例英雄名单、桩节点口径、语料构成、C2 metadata、缺失装备、embedding 下载源、Chroma 幂等 + 过滤算子 + EF 显式加载） |

### 1.3 生成物（非版本库）

- `models/bge-large-zh-v1.5/`（1.24GB，`.gitignore` 排除）
- `data/chroma/`（向量库持久化目录，`.gitignore` 排除）

---

## 2. 真实运行证据

### 2.1 抓取（`python scripts/fetch_official.py`，产物见 `data/fetch_report.md`）

```
- 快照目录：data/raw/20261014-214848/
- 官方英雄总数：133，本次成功解析：133，失败：0
- 装备：115 件；铭文：93 个
- 关系总数（已含 hr3 方向反转）：798 条
| 最佳搭档 hr1 | 133 | 100.0% |
| 压制英雄 hr2 | 133 | 100.0% |
| 被压制英雄 hr3 | 133 | 100.0% |
- 有铭文搭配的英雄：133 / 133；有推荐出装的英雄：133 / 133
- 解析失败清单：无。三项关系区块的「英雄列表长度 == 理由列表长度」断言全部通过。
```

### 2.2 Neo4j 幂等导入（连续执行两次 `python scripts/init_graph.py`）

第一次：
```
[graph] 导入前节点： {'Hero': 83, 'Inscription': 93, 'Item': 115}
[graph] 导入前关系： {'COUNTERS': 99, 'RECOMMENDS_INSCRIPTION': 30, 'RECOMMENDS_ITEM': 57, 'SYNERGIZES': 20}
[graph] 本次写入： {'full_heroes': 5, 'stub_heroes': 78, 'items': 115, 'inscriptions': 93,
                    'hero_rel_rows': 120, 'item_edge_rows': 57, 'ins_edge_rows': 30,
                    'skipped_item_refs': 3, 'skipped_ins_refs': 0}
[graph] 导入后节点： {'Hero': 83, 'Inscription': 93, 'Item': 115}
[graph] 导入后关系： {'COUNTERS': 99, 'RECOMMENDS_INSCRIPTION': 30, 'RECOMMENDS_ITEM': 57, 'SYNERGIZES': 20}
```
第二次：**输出与第一次逐项一致**（节点 83/93/115、关系 99/30/57/20 均未增加）→ 幂等成立。

约束/索引与完整性实测：
```
MATCH (n) RETURN count(n) = 291
约束： ['hero_id', 'inscription_id', 'item_id']
索引： ['hero_id', 'hero_name', 'hero_roles']
source 为空节点数： 0
patch 为空节点数： 0
```

> **核账方式（用脚本/查询统计，不靠手数）** —— 数据源 `relations.json` 与 Neo4j 边数**相差 1**，是去重所致，非口径不一致：
> - 数据源实测 **120 行**（COUNTERS **100** / SYNERGIZES 20）。核账命令：
>   `python -c "import json,collections;d=json.load(open('data/graph/relations.json',encoding='utf-8'));print(len(d),dict(collections.Counter(r['type'] for r in d)))"`
> - Neo4j 实测 **119 条边**（COUNTERS **99** / SYNERGIZES 20）。核账查询：
>   `MATCH ()-[r:COUNTERS|SYNERGIZES]->() RETURN type(r) AS t, count(r) AS c`
> - 差值 1 条 = 兰陵王→鲁班七号 COUNTERS 被两处官方页各述一次，按唯一键 `起点+类型+终点+patch` MERGE 合并（见 §4.3）。
> - 因此：**§2.2 输出的 `COUNTERS: 99` 是 Neo4j 去重后的边数，不是 relations.json 的行数**；`REVIEW.md` §2 各英雄条目数合计 120（30+35+7+31+17）与 `relations.json` 一致。
> - §3 表中的「关系 206」是 Neo4j **全部四类边**之和（COUNTERS 99 + SYNERGIZES 20 + RECOMMENDS_ITEM 57 + RECOMMENDS_INSCRIPTION 30）。

### 2.3 Chroma 导入（连续执行两次 `python scripts/init_chroma.py`）

```
[chroma] 语料 10 篇 -> chunk 24 条
[chroma] 每篇 chunk 数：{'c1-diaochan-official': 4, 'c1-donghuangtaiyi-official': 5, 'c1-houyi-official': 3,
                        'c1-lanlingwang-official': 4, 'c1-yase-official': 3,
                        'c2-diaochan-laning': 1, 'c2-donghuangtaiyi-roaming': 1, 'c2-houyi-laning': 1,
                        'c2-lanlingwang-jungle': 1, 'c2-yase-laning': 1}
[chroma] chunk 字数 min/median/max = 169/413/499
[chroma] 已删除旧 collection guides（幂等重建）
[chroma] collection.count() = 24
[chroma] 抽查 query('貂蝉怎么出装', hero_ids=141) 命中：
  - c1-diaochan-official#3: 静之靴 → 噬神之书 → 暴烈之甲 → 痛苦面具 → 极寒风暴 → 辉月 - T...
  - c2-diaochan-laning#0: 貂蝉是一位靠持续位移与被动印记打输出的法刺，上手难度较高。她的核心是二技能缘·心...
```
两次运行 `collection.count()` 均为 24，无漂移。

### 2.4 pytest

```
..                                                                       [100%]
2 passed in 3.79s
```

### 2.5 /api/health（真实 HTTP 请求，uvicorn 起服务）

```
GET http://127.0.0.1:8000/api/health
{"neo4j":{"ok":true,"detail":"connected: bolt://localhost:7687"},
 "chroma":{"ok":true,"detail":"persistent@ data/chroma, collections=1"},
 "llm":{"ok":true,"detail":"mode=local, intent_model=qwen2.5:3b, ollama_models=['qwen2.5:3b','qwen3-embedding:0.6b']}}

GET http://127.0.0.1:8000/
{"name":"honor-graphrag","doc":"/docs","health":"/api/health"}
```

### 2.6 中文乱码抽查（独立核验脚本）

5 个样例英雄名称 + 3 条关系理由，均正常无乱码：
```
Hero id=141 name='貂蝉' aliases=['蝉儿','貂蝉妹妹','貂婵','貂禅','刁蝉','貂蝉小姐姐']
Hero id=153 name='兰陵王' aliases=['兰陵','老兰陵','兰凌王','蓝陵王','兰陵皇','隐身王']
Hero id=166 name='亚瑟' aliases=['亚瑟王','老亚瑟','亚瑟瑟','亚色','亚瑟君','亚瑟大王']
Hero id=169 name='后羿' aliases=['后裔','后弈','老后羿','后羿射日','后一','后羿哥']
Hero id=187 name='东皇太一' aliases=['东皇','太一','东皇太乙','东皇太1','东皇大人','东皇太一神']
Rel 貂蝉->廉颇 [COUNTERS]: '廉颇不能很容易控制到灵活的貂蝉'
Rel 小乔->东皇太一 [COUNTERS]: '东皇太一：因为通过二技能命中之后的被动位移加速以及通过不断一技能骚扰…'
```

### 2.7 关系配对检查

- 全量快照 `parsed/parse_errors.json` 为 **0 字节**（无解析失败项）。
- `data/fetch_errors.log` **不存在**（配对断言在抓取时执行，不匹配即抛错并写入该日志；不存在即全部通过）。
- 断言逻辑：`scripts/fetch_official.py` 中 `hero_ids = next((v for v in candidates.values() if len(v) == len(reasons)), None)`，无等长候选即抛错。

### 2.8 官方 URL 可达性 + 原文命中（辅助需求方抽查）

对 5 条关系 `source` URL 做真实请求（HTTP 200），并核验原文确实出现在页面上：
```
https://pvp.qq.com/web201605/herodetail/lianpo.shtml      status=200  contains=True   ("廉颇不能很容易控制到灵活的貂蝉")
https://pvp.qq.com/web201605/herodetail/gongsunli.shtml   status=200  contains=True   ("阿离面对强控时，会很难进场输出")
https://pvp.qq.com/web201605/herodetail/diaochan.shtml    status=200  contains=True   ("貂蝉是一个比较怕控制的英雄")
（另 daji.shtml / lubanqihao.shtml 亦返回 200）
```

---

## 3. 验收项逐条结论（对照规格书 M1a 验收）

| # | 验收标准 | 结论 | 证据 |
| --- | --- | --- | --- |
| 1 | 抓取脚本可重复执行、限速合规（间隔 ≥ 0.5s） | **通过** | 限速 0.6s/请求（`data/fetch_report.md`）；脚本带快照缓存，重复执行命中缓存（本次耗时 0.3s） |
| 2 | 中文乱码检查：抽查 3 个英雄名称与关系理由，确认 GBK 解码正确 | **通过** | §2.6：5 英雄名 + 3 理由均无乱码；抓取脚本对每个名称/理由/技能描述执行 `assert_no_mojibake` |
| 3 | 关系配对检查：断言英雄列表长度 == 理由列表长度，不一致记入 `fetch_errors.log` | **通过** | §2.7：`parse_errors.json` 0 字节、`fetch_errors.log` 不存在；133/133 英雄断言全过 |
| 4 | `GET /api/health` 全绿 | **通过** | §2.5：neo4j/chroma/llm 三项 `ok=true` |
| 5 | 导入脚本对同一份数据执行两次，节点数不增加 | **通过** | §2.2（Neo4j 83/93/115 不变）、§2.3（Chroma 24 不变） |
| 6 | 需求方抽查 5 条关系，点开 `source` URL 确认官网页面上写着该关系 | **待需求方执行** | 已提供辅助证据 §2.8（5 URL 可达 + 3 条原文命中）；`data/REVIEW.md` 第 2 节给出全部 120 条关系的 URL |

M1a 交付物齐备性：

| 交付物 | 状态 |
| --- | --- |
| `scripts/fetch_official.py`（全量抓取 133+装备+铭文，落快照） | 完成 |
| `data/fetch_report.md`（覆盖率 + 解析失败清单） | 完成 |
| `data/DATA_SCOPE.md`（20 重点英雄，按 1.12 规则） | 完成（**待需求方确认清单**） |
| 入库脚本（幂等）+ Neo4j 约束索引 + Chroma 导入脚本 | 完成 |
| 入库 5 英雄完整数据 + 装备 115 + 铭文 93 + 10 篇语料 | 完成（节点 291、关系 206、chunk 24） |
| `data/hero_aliases.json`（5 英雄，每英雄 ≥5 别名）+ `data/REVIEW.md` | 完成（每英雄 6 别名） |

---

## 4. 未达标项及需需求方确认事项

**无硬性验收项未通过。** 以下为需需求方知晓 / 确认的事项（均已记入 `DECISIONS.md`）：

1. **【需确认】规格书 4.6 示例过滤算子与库行为冲突。** 规格书把 `hero_ids` 定义为 `[String]` 列表，示例过滤写 `{"hero_ids": {"$in": [hero_id]}}`；但实测本机 **chromadb 1.5.9** 下 `$in` 对列表字段**返回空**（静默失效），正确算子为 `$contains`。当前实现：保留 `hero_ids` 为列表，抽查/后续 M2 过滤改用 `$contains`。**这一偏离规格书示例的算子选择请需求方确认。**（DECISIONS.md 2026-10-14 条）

2. **缺失装备 ID 对应出装边未建立。** 官方 `item.json`（115 件）中查无的装备 ID：全量 133 英雄共 4 个（`1223/1225/1722/91040`，20 处引用）；**5 个样例英雄涉及 2 个**（`1722`×2、`91040`×1，共 3 处引用，即 `init_graph.py` 的 `skipped_item_refs=3`）。按规格书 3.4「装备恰 115」不为其造桩节点，对应 `RECOMMENDS_ITEM` 边暂不建立，已列 `data/REVIEW.md` §4.1。待官方补齐后可重跑。

3. **同一关系被两处官方页面各陈述一次。** 兰陵王 → 鲁班七号（COUNTERS）在 `lubanqihao.shtml`（被压制英雄区块）与 `lanlingwang.shtml`（压制英雄区块）各出现一次，事实与方向一致；Neo4j 按唯一键 `起点+类型+终点+patch` 合并为 1 条（故 120 行关系 → 119 条边）。已列 `data/REVIEW.md` §4.2。

4. **【需知晓】重新打开 collection 必须显式传入 bge embedding function。** 裸用 `get_collection("guides")` 会回退到 chromadb 默认 ONNX 模型（`all-MiniLM-L6-v2`）并联网下载，本机握手超时导致查询报错；且会与入库的 bge 向量空间不一致。M1a 的 `/api/health` 只做 heartbeat，未触发此路径，**不影响 M1a 验收**；M2 向量检索必须显式传 EF。（DECISIONS.md 2026-10-14 条）

5. **【需知晓】项目尚未初始化 git 仓库。** `git status` 返回 `not a git repository`，M0/M1a 的代码尚未纳入版本控制。是否在 M1a 审核通过后统一 `git init` 并分组提交，请需求方指示。

6. **C2 五篇为 LLM 生成的"对线思路"，非官方原文。** `source_type=official`（事实出自官方页）+ `data_source=llm_assisted`（文本为生成），已在 `data/REVIEW.md` §3.1 单独列出，审核重点为「表达是否自然、有无模板腔、是否与官方事实一致」。

---

## 5. 下一步

按规格书 11.4-4，**M1a 结束停下等待需求方数据审核**，不进入 M1b。请重点审核：

- `data/REVIEW.md` §2 的 120 条关系（抽查 URL 与方向）；
- `data/DATA_SCOPE.md` 的 20 个重点英雄清单（是否调整）；
- `data/REVIEW.md` §3.1 的 C2 五篇语料（有无模板腔）；
- 上文第 4 节的 6 条确认事项。
