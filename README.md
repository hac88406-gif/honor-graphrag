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
| M6 评测 | ✅ 完成（待需求方审核；评测集 38+74 条、8.2 全指标实测、四项裁定已落地，见 [`docs/eval_report.md`](docs/eval_report.md)） |
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

## 接口清单（与规格书 5.2 表**逐条一致**）

> 规格书 v1.6 §5.2 要求「README 的接口清单必须与本表一致，不得出现『README 列了但没实现』」。
> 下表与 5.2 表逐条对应，含实现状态。

| 方法 | 路径 | 说明 | 实现状态 |
| --- | --- | --- | --- |
| POST | `/api/chat` | SSE 流式问答 | ✅ 已实现（M5） |
| POST | `/api/chat/sync` | 同步问答（评测用，返回完整 `ChatResponse`） | ✅ 已实现 |
| GET | `/api/health` | 返回 `{neo4j, chroma, llm}` 三项状态 | ✅ 已实现 |
| DELETE | `/api/session/{session_id}` | 清空会话状态 | ✅ 已实现（M6，幂等；清 checkpointer 中 `thread_id = session_id` 的全部 checkpoint） |
| POST | `/api/docs/upload` | 上传攻略文本（multipart，必须带 metadata） | 📌 归 M7（与 C1 语料版权声明一并处理） |
| POST | `/api/graph/import` | 导入图谱数据（幂等，整体校验后才写入） | ❌ v1 不实现（见「非目标」） |

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

## 已知偏差（**显式记录，不是隐藏缺陷**）

### 首 token 延迟：正常回答路径达不到 3.4 的「≤2.5s」

规格书 3.4 的目标是「首 token ≤ 2.5s（流式）」。**本实现在「正常 answer + llm 路径」下达不到**，
原因是 M5 明确的取舍 —— **校验优先于观感**：

- guard 必须拿**完整正文**才能判（G2 英雄名越界要全篇比对、G3 类别化外推要按句子窗口判），
  未校验的内容**推出去就撤不回**，故正文在**校验通过之后**才按块推；
- `_prefix_lines` 只在 `degraded` / `low_confidence` / 多意图提示三种情况有内容，
  **正常回答路径 prefix 为空** → 正文首字节要等「完整生成 + guard 校验」完成之后；
- 推理模型（deepseek-v4-pro）单次生成含 250~290 token 思考，完整生成约 3~6 秒。

**范围澄清**：`_template_body` 路径**构造上不可能越界**（只摘录 evidence，不归纳不改写），无需等校验，
故**拒答 / 降级 / template 路径的首 token 是快的**；**只有「正常 answer + llm 路径」慢**。

**处置**（规格书 v1.6 §3.4）：

1. 本条即第 1 项要求 —— 在 README 与 M6 评测报告中显式记录，说明原因（校验优先于观感）；
2. **M6 必须实测首 token 延迟并给出真实数字**（8.2 本就要求分开统计）；
3. M6 评估**句级增量校验**：G2/G3 绝大多数单句可判，但**跨句的类别外推会漏检**
   （「妲己克制后羿。它是高爆发法师。」—— 第二句才暴露，第一句已推出）。
   这是「少量漏检换流式体验」的取舍，**由 M6 的数字决定是否切换**，不在 M5 拍脑袋改。

**M6 实测结论（2026-10-16，见 [`docs/eval_report.md`](docs/eval_report.md) §2.5）**：

| 路径 | 首 token（mean） | 完整回答（mean） | n |
| --- | --- | --- | --- |
| llm 生成路径 | **4.22s**（min 0.44 / max 9.62） | 6.74s | 7 |
| template / 非生成路径 | **0.02s** | 0.02s | 3 |

- 全量评测集（116 turn）端到端：`answer` n=68 **mean 6.06s / p50 3.15s / max 29.3s**。
- **句级增量校验裁定：不切换。** 直连模型流实测整段答案**只有 1 句**（推理模型先出 reasoning
  再一次性吐正文），句级提前推送正文收益 **0.00s**；82 条真实 LLM 答案中「全文判越界但句级前缀
  判不出」的跨句依赖样本 **0 条**。即该改法**换不来收益却要付出漏检风险**，维持「完整生成 + 全文校验」。
- 结论：**本偏差在现有架构下不可消除**，只能显式登记（本条 + DECISIONS.md）。

### 感知改善：citation 已提前到生成之前推（v1.6 §3.4）

依据在检索阶段就已确定（citation 就是融合后 evidence 的 1-based 序号），故 `citation` 事件
**在生成开始前就推给前端**，用户立刻看到「查到了这些依据」，来源卡片也更早渲染 —— 感知延迟大降。
注意这**不满足**「首 token」的字面指标（那是 `token` 事件），改善的是实际体验。

> 实现细节：`citation` 挂在 `node_start(generate)` 处推，而**不是**在 fuse 之后无条件推 ——
> `reject_node` / `clarify_node` 明确返回 `citations=[]`（拒答不给来源卡片），
> 而**低置信拒答**这条路径是跑过 fuse 的，若在 fuse 处无条件推会出现「推了来源、终态却说没有来源」。
> 挂在 generate 起点则只在「真要出答案」的分支推，与终态 citations 必然一致。
> 每条路径**恰好一次** `citation` 事件（拒答/澄清在末尾补一次空 citation）。

## 非目标（v1 明确不做）

- **`POST /api/graph/import`**：幂等导入的**核心能力已存在且被测试覆盖** ——
  `scripts/init_graph.py` 支持幂等重跑，`tests/...::test_neo4j_import_idempotent` 钉住了该行为。
  API 端点只是对同一能力的 HTTP 包装，**边际价值低**；而实现它需要额外的鉴权、大文件分片、
  部分失败回滚等设计，性价比不足。故 v1 明确不提供该端点（规格书 v1.6 §5.2）。
- 登录 / 历史会话管理页 / 设置页 / 主题切换 / 移动端适配 / 动画特效（规格书 1.6）。

## 已知局限

- **多意图合并：永久不做（M6 裁定）。** 评测原始记录实测，一个 turn 命中 ≥2 个意图的仅
  **5/116 = 4.3%**，且这 5 条没有一条是用户真要两个答案 —— 4 条是**关键词误命中**
  （「貂蝉的铭文怎么搭配」里「搭配」命中 SYNERGY、「貂蝉对线思路」里「对线」命中 MATCHUP），
  1 条是同一关系的两种说法。为 4.3% 且多为误命中的场景做合并，是把复杂度花在噪声上。
  当前行为：**一次只答一个意图**，其余命中的意图在 `matched_intents` 留痕并在回答中告知。
  详见 [`docs/eval_report.md`](docs/eval_report.md) §2.9。
- **意图路由对自由口语的覆盖有上限**：泛化集（74 条真实用户口吻）准确率 **85.1%**，
  11 条错误**全部**是「关键词表覆盖不到自由口语」（如「能打过谁」「怎么发育」「配谁」），
  **没有一条是路由逻辑判错**。同批 108 条上 LLM 意图路径只有 **41.7%**、延迟是规则的 330 倍，
  故生产路径继续走规则（`route_llm` 仅作可选开关保留）。

## 技术决策记录

见 [DECISIONS.md](DECISIONS.md)（规格书 0.1 铁律 2：未定义决策先记录再实现）。
