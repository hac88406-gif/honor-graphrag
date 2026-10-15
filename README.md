# 王者荣耀 GraphRAG 问答 Agent

自然语言提问 → 实体链接 + 意图识别 → **Neo4j 图谱**（结构化关系）与 **Chroma 向量库**（非结构化攻略）双路召回**可追溯依据** → 融合生成**带来源标注**的回答；依据不足时拒答或澄清反问。

（README 骨架，M0。完整版含架构图 / 启动步骤 / 数据来源声明 / 技术决策记录，见 M7。）

## 三条核心设计

1. **图谱引导向量**（graph-guided retrieval）：混合类问题由图谱先取结构化事实作为扩展查询词喂给向量检索，两路融合——GraphRAG 相对普通 RAG 的价值所在（规格书 2.1）。
2. **模板化 Cypher**：LLM 只输出 `{intent, slots}`，绝不接触查询字符串（规格书 2.2 / 4.7）。
3. **三档置信度 + 确定性拒答**：澄清反问 / 拒答 / 低置信降级 / 正常回答，判定由确定性规则完成（规格书 4.9）。

## 技术栈

Python 3.12 · FastAPI · LangGraph（SqliteSaver 多轮记忆）· Neo4j 5.x · Chroma（嵌入式）· bge-large-zh-v1.5 · BM25 混合检索 · Vue3 单页

外部依赖**仅 Neo4j 一个**（Docker 或 Desktop）；Chroma 与会话记忆零外部依赖（规格书 4.12）。

## 当前里程碑状态

| 里程碑 | 状态 |
| --- | --- |
| M0 骨架与环境 | ✅ 完成 |
| M1a 数据层（抓取 + 样例） | ✅ 完成（需求方审核通过） |
| M1b 数据层（全量 133 英雄） | ✅ 完成（需求方审核通过） |
| M2 检索层 | ✅ 完成（需求方审核通过，见 `docs/milestones/M2-report.md`） |
| M3 LangGraph 编排 | ✅ 完成（需求方审核通过，三项修改已落实，见 `docs/milestones/M3-report.md`） |
| M4 生成层 | ✅ 完成（需求方二审通过；裁定 A / B1–B3 / C1 已落实，见 `docs/milestones/M4-report.md`） |
| M5 前端 | ✅ 完成（待需求方审核；按 1.6 边界：来源卡片 + 过程展示 + 拒答/澄清差异化渲染，不引 Pinia/Router/UI 库，见 `docs/milestones/M5-report.md`） |
| M6 评测 | ⏳ |
| M7 打磨 | ⏳ |

## 启动（M0 阶段可用部分）

```powershell
# 1) 建 venv 并装依赖（Windows，Python 3.12）
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt

# 2) 启动 Neo4j（Docker 方案；守护进程需先启动 Docker Desktop）
#    注：本机 docker compose 子命令不可用，统一使用 docker-compose（带横线）
docker-compose up -d

# 3) 启动 API
.\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 4) 验证
curl http://127.0.0.1:8000/api/health
```

## 前端（M5，最简聊天页）

```powershell
# 1) 后端先起来（见上「启动」）
.\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 2) 前端开发模式（Vite，/api 自动代理到 8000）
cd frontend
npm install
npm run dev          # http://127.0.0.1:5173

# 3) 生产构建（产出静态文件到 frontend/dist）
npm run build
```

前端依赖仅 `vue` + `vite`（**无 Pinia / Router / UI 库**，规格书 1.6 边界）。
功能：多轮消息列表、SSE 流式逐字显示、节点过程指示、可展开的来源卡片、
拒答 / 澄清反问的差异化渲染（澄清候选可点选）。`dist/` 与 `node_modules/` 均不入版本库。

## 数据层构建（M1b，可复现）

```powershell
# 1) 抓取官方数据（全量 133 英雄 + 装备 + 铭文），落快照并生成覆盖率报告
.\.venv\Scripts\python scripts\fetch_official.py

# 2) 从快照导出入库数据（全量 133 英雄）
.\.venv\Scripts\python scripts\build_graph_data.py

# 3) 从快照重建 C1 官方聚合语料（每英雄一篇，确定性：publish_date 取自快照 fetch_meta.json）
#    注：C1（data/guides/c1-*.md）为**派生数据**，不入版本库（.gitignore），由本步从 data/raw/ 重建
.\.venv\Scripts\python scripts\build_guides.py

# 4) 导入 Neo4j（MERGE 幂等）
.\.venv\Scripts\python scripts\init_graph.py

# 5) 导入 Chroma（切分 + bge embedding，删库重建保证幂等）
.\.venv\Scripts\python scripts\init_chroma.py

# 6) 生成审核清单与度数画像
.\.venv\Scripts\python scripts\build_review.py
.\.venv\Scripts\python scripts\data_profile.py

# 7) 回归测试（幂等 / 配对 / 算子差异 / EF 重启）
.\.venv\Scripts\python -m pytest -v
```

## 数据来源与数据画像（M1b）

> 数据来自王者荣耀官方页面脚本抓取（`scripts/fetch_official.py`，端点清单见规格书 6.1b），
> 每条数据带真实 `source` URL 与 `patch=2026-10`。**仅本地演示用，勿用于生产。**

> **版本库内数据范围**：`data/graph/*.json`（结构化事实）与 `data/guides/c2-*.md`（5 篇 LLM 生成语料，
> **须提交以保证评测可复现**）在库内；`data/raw/`（抓取快照）与 `data/guides/c1-*.md`（133 篇，
> 从快照解析出的**派生数据**）**不入库**（见 `.gitignore`），由上方「数据层构建」步骤重建
> —— 故库内**不含官方表达性文本**，而本地重建后语料完整、检索质量不受影响。

> **关系计数口径（全项目统一）**：关系计数分三层，本文所有关系数字均注明层级——
> **源数据层**（`parsed/relations_all.json`，798 行 / COUNTERS 532）·
> **导出层**（`data/graph/relations.json`，798 行 / COUNTERS 532，**未去重**）·
> **入库后层**（Neo4j 按唯一键 MERGE 去重，793 边 / COUNTERS 527）。

**规模**：英雄 133 · 装备 115 · 铭文 93 · 英雄关系 **798 条（源数据层；COUNTERS 532 / SYNERGIZES 266；入库后 793 / COUNTERS 527）** · 语料 **138** 篇（C1 133 + C2 5）。
抓取与覆盖率详见 [`data/fetch_report.md`](data/fetch_report.md)，审核清单见 [`data/REVIEW.md`](data/REVIEW.md)，
COUNTERS 出度/入度画像与边界英雄清单见 [`data/data_profile.md`](data/data_profile.md)。

### 数据洞察：反向遍历拿到的信息比正向查询多

官方每个英雄详情页只给 **2 条「压制英雄」+ 2 条「被压制英雄」**，正向看每个英雄的克制数据都均等地是 2+2。
但同一批事实在 133 个页面里互相引用，因此把 hr3 方向反转入库后，**反向遍历能恢复出远超 2 条的度数**：

- **出度**（本英雄压制别人）最高（**源数据层口径**）：花木兰 27、兰陵王 24、貂蝉 19；
- **入度**（本英雄被别人压制）最高（**源数据层口径**）：鲁班七号 29、后羿 20、王昭君 17。

> 入库后去重口径下，5 个含重复边的英雄出度各 −1（花木兰 26、兰陵王 23、王昭君 9、孙膑 8、露娜 3），
> 对应 5 个英雄入度各 −1（墨子 6、鲁班七号 28、李白 7、吕布 9、虞姬 4）；逐条对照见 `data/data_profile.md`。

例：兰陵王被 **22** 个英雄（**源数据层口径**）列为压制对象，而亚瑟 **0** 个。这个差异本身就是**版本强度的信号**，
也正是图的价值所在——「谁克制 X / X 克制谁」这类问题只有反向遍历才能拿到完整答案。

### 数据局限

1. **官方克制数据稀疏且非对称**：每页恒为 2+2 条，密度低于玩家社区认知；官方不提供关系权重，
   `weight` 统一 1.0（语义仅为「官方认定该关系存在」，见 DECISIONS.md）。
2. **71 个英雄的 hr3 反向引用 = 0**（从未被任何其他英雄页面列为「被压制英雄」，其中包含亚瑟）。
   对这些英雄问「XX 被谁克制」时，图谱**必然返回空**，会走拒答或降级——这是真实边界情况，
   是 M6 评测集的重要素材，完整清单见 [`data/data_profile.md`](data/data_profile.md)。
3. **4 个装备 ID 缺失**（`1223`/`1225`/`1722`/`91040`，共 20 处引用）不在官方 `item.json` 中，
   对应 `RECOMMENDS_ITEM` 边**未建立、未造桩节点**（缺失装备在任何数据源中都不存在，造桩即编造）。
   详见 [`data/fetch_report.md`](data/fetch_report.md)。
4. **C2 语料为 LLM 生成**（5 篇对线思路，事实源为官方页面，`data_source=llm_assisted`），非官方原文，
   已在 [`data/REVIEW.md`](data/REVIEW.md) §3.1 单列待审。
5. **数据随版本变化**：当前 `patch=2026-10`，需重新抓取才能跟进新版本。

## 技术决策记录

见 [DECISIONS.md](DECISIONS.md)（规格书 0.1 铁律 2：未定义决策先记录再实现）。
