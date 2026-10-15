# M5 交付报告 — 前端（SSE 流式问答 + 来源可追溯）

> 生成日期：2026-10-15　规格书：**v1.5**　快照：`data/raw/20261014-230459`
> 格式依据：规格书 11.3（四项缺一视为未完成）。
> **状态：待需求方审核。**
> 本轮范围：M5 按 **1.6 边界**执行 —— 消息列表 / 输入框 / 来源卡片 / 过程指示 / 拒答与澄清差异化，
> **不引 Pinia / Router / UI 库**。规格书无需变更，仍为 v1.5。
> 附带修一处**实现缺口**（见 §4-2）：正文原先是「一帧整段」推给前端，不算流式，
> 与 M5 验收「SSE 流式逐字显示」不符。

---

## 1. 变更文件清单

### 1.1 新增（M5）

| 文件 | 说明 |
| --- | --- |
| `frontend/package.json` | 依赖仅 `vue` + `vite` + `@vitejs/plugin-vue`，**无 Pinia / Router / UI 库**（1.6 边界） |
| `frontend/vite.config.js` | 开发期 `/api` 代理到后端 8000，避免前端自己处理跨域 |
| `frontend/index.html` | 单页入口 |
| `frontend/src/main.js` | `createApp(App).mount('#app')` |
| `frontend/src/App.vue` | 根组件：消息列表（多轮）+ 事件循环 + 健康状态；状态用 `ref/reactive`，**不用 Pinia** |
| `frontend/src/api.js` | 与后端全部网络交互：`askStream()`（SSE 逐帧解析）/ `fetchHealth()` / 节点名→中文标签 |
| `frontend/src/styles.css` | 全局设计变量与基础样式（自写，**不引外部 CSS 库**） |
| `frontend/src/components/Composer.vue` | 输入框 + 发送（Enter 发送 / Shift+Enter 换行） |
| `frontend/src/components/MessageBubble.vue` | 消息气泡，按 `done.type` **差异化渲染**（answer / low_confidence / reject / clarify） |
| `frontend/src/components/ProcessPanel.vue` | 过程展示：只展示**已发生**的节点，不预测后续 |
| `frontend/src/components/SourceCards.vue` | 来源卡片：原生 `<details>` 可展开，按 citation index 配对 evidence 原文 |
| `tests/integration/test_api_sse.py` | 6 用例：SSE 事件序列 / 分帧粒度 / 三条路径 type 分流 / 非流式分支 |
| `docs/milestones/M5-report.md` | 本报告 |
| `docs/milestones/M5-verify-output.txt` | pytest（两模式）+ 数据层复跑校验 + C1 重建 + 前端构建 真实输出 |
| `docs/milestones/M5-sse-live-output.txt` | **端到端真实 SSE 事件流**（三条路径，可复跑） |
| `docs/module-notes/m5-frontend.md` | M5 模块三段说明（规格书 9.1-1） |

### 1.2 修改（M5）

| 文件 | 说明 |
| --- | --- |
| `app/api/chat.py` | 新增 `POST /api/chat`（SSE，**FastAPI 原生 `StreamingResponse`**，不引 sse-starlette）；`/api/chat/sync` 保留不变；抽出 `_to_response()` / `_sse()` 复用 |
| `app/agent/graph.py` | `done` 事件补 `clarify_options` / `intent`（否则前端拿不到澄清候选）；**template 路径正文改为按块推**（原先一帧整段） |
| `app/agent/nodes/generate.py` | 新增 `_emit_text()`：把**已校验通过**的正文按块推（原先一帧整段） |
| `app/main.py` | 文档字符串更新（SSE 已挂载；5.2 表中其余三条未挂载，归属待裁定） |
| `DECISIONS.md` | 追加「M5 前端」决策 **6 条** |
| `README.md` | 里程碑状态更新（M5 完成待审）+ 前端启动/构建步骤 |

---

## 2. 真实运行证据

> 原样输出见 [`M5-verify-output.txt`](M5-verify-output.txt)（pytest + 数据层 + C1 + 构建）
> 与 [`M5-sse-live-output.txt`](M5-sse-live-output.txt)（端到端 SSE），两份均可复跑。

### 2.1 pytest 全量

**开发模式**（`REQUIRE_SERVICES` 未设）：

```
262 passed, 1 warning in 19.72s
```

**验收模式**（`REQUIRE_SERVICES=1`，服务依赖用例不可 skip —— 11.3 v1.5）：

```
262 passed, 1 warning in 19.86s
```

两种模式均为 **262 passed / 0 skipped**（Neo4j 与 Chroma 在线，无静默 skip）。
1 warning 为 chromadb 内部 `is_legacy` DeprecationWarning（与断言无关，升级复跑要求已登记）。

| 文件 | 用例数 | 归属 |
| --- | --- | --- |
| M0–M4 既有 | 256 | — |
| `tests/integration/test_api_sse.py` | **6** | **M5** |
| **合计** | **262** | M5 新增 6 |

### 2.2 数据层复跑校验（**未破坏数据**）

```
【1】源数据层  英雄 133 · 装备 115 · 铭文 93 · 关系行数 798（COUNTERS 532 / SYNERGIZES 266）
【2】导出层    英雄 133 · 关系行数 798（COUNTERS 532 / SYNERGIZES 266）
【3】入库后层  节点 {'Hero':133,'Inscription':93,'Item':115}
              关系 {'COUNTERS':527,'RECOMMENDS_INSCRIPTION':798,'RECOMMENDS_ITEM':1574,'SYNERGIZES':266}
  [ OK ] 幂等：连续两次导入后节点数/关系数逐项不变
  [ OK ] 入库后 COUNTERS（527）== 去重后口径（源 532 − 合并 5）
  完整性：Hero/Item/Inscription 与关系的 source 空 = 0、patch 空 = 0；COUNTERS/SYNERGIZES 的 reason 空 = 0
【4】向量库    collection.count() = 540  缺 patch/hero_ids/source_url = 0/0/0  patch 分布 = {'2026-10': 540}
[verify] 结论：PASS —— 数据层复跑校验全部通过，检索层未破坏数据
```

**与 M1b / M3 / M4 完全一致**（133 英雄 / 798 行 / COUNTERS 入库后 527 / 空值全 0 / 540 chunk），
计数口径三层逐项标明（源数据层 / 导出层 / 入库后层）。

### 2.3 C1 语料确定性重建（裁定 C1 的复跑确认）

```
[guides] 快照=20261014-230459 产出 C1 133 篇
重建前后 SHA256 逐项比对 -> IDENTICAL（133 篇逐字节一致）
```

**仅凭 `data/raw/` 即可确定重建 C1**：`fetch_official.py` → `build_guides.py` → `init_chroma.py`。
`data/guides/c1-*.md` 与 `data/raw/` 均在 `.gitignore`；`c2-*.md`（5 篇）与 `data/graph/*.json` 留库。

### 2.4 端到端真实 SSE 事件流（`POST /api/chat`，三条路径）

> 完整原文见 [`M5-sse-live-output.txt`](M5-sse-live-output.txt)。真实 Neo4j + Chroma，
> `GENERATION_MODE=template`（确定性证据组装，不产生云端费用）。

**正常回答**（`铠被谁克制`）—— 事件序列与分帧粒度：

```
node_start(entity_linking) -> node_start(intent_routing) -> node_start(graph_query)
-> node_start(fuse) -> evidence ×4（逐条推来源）
-> node_start(confidence) -> node_start(generate) -> node_start(memory)
-> token ×17（正文分块，每帧 ≤ 8 字）
-> citation（4 条，index 与 evidence 顺序一一对应）
-> done {"type":"answer","confidence":0.85,"fallback":false,"generation_mode":"template","clarify_options":[],"intent":"COUNTER_BY"}
```

**拒答**（`今天天气怎么样`）：

```
node_start(entity_linking) -> node_start(intent_routing) -> node_start(reject) -> node_start(memory)
-> token ×8（给出可替代的提问方向）
-> citation []（拒答**不给来源卡片**）
-> done {"type":"reject","confidence":0.0,"intent":"OUT_OF_SCOPE"}
```

**澄清**（`赛博坦这个英雄怎么样`）：

```
node_start(entity_linking) -> node_start(intent_routing) -> node_start(clarify) -> node_start(memory)
-> token ×4 -> citation []
-> done {"type":"clarify","intent":"ENTITY_UNKNOWN",
         "clarify_options":["亚瑟","后羿","鲁班七号","貂蝉","铠","东皇太一","兰陵王","蔡文姬","孙悟空","安琪拉"]}
```

三条路径的 `done.type` 互不相同、且 `clarify` 带候选、`reject` 无来源 —— 前端据此差异化渲染的依据全部落地。

### 2.5 前端生产构建

```
> vite v5.4.21 building for production...
✓ 21 modules transformed.
dist/index.html                  0.40 kB │ gzip:  0.31 kB
dist/assets/index-40etcv6q.css   7.66 kB │ gzip:  1.99 kB
dist/assets/index-Dcw_P5A6.js   73.86 kB │ gzip: 29.88 kB
✓ built in 724ms
```

`frontend/dist/` 已在 `.gitignore`（构建产物不入库）。

---

## 3. 验收项逐条结论

### 3.1 M5 验收四项（规格书 §M5）

| # | 验收标准 | 结论 | 证据 |
| --- | --- | --- | --- |
| 1 | **SSE 流式逐字显示** | **通过** | 正文按块推（每帧 ≤ 8 字；实测整段 17 帧而非 1 帧），前端逐帧 `append` 渲染；§2.4；`test_token_frames_are_incremental_not_one_shot` |
| 2 | **节点进度可见** | **通过** | `node_start` 逐节点推送；`ProcessPanel` 按到达顺序展示已发生节点；§2.4 |
| 3 | **来源卡片可展开** | **通过** | `citation` 与 `evidence` 按 1-based index 配对，`SourceCards` 用原生 `<details>` 展开 evidence **原文** + `source_url` + `patch`；§2.4 |
| 4 | **拒答与澄清有差异化样式** | **通过** | `MessageBubble` 按 `done.type` 分流：reject 中性灰 + 「拒答」标；clarify 琥珀 + 「需要澄清」标 + **候选可点选**；low_confidence 提示色；answer 无额外标记；§2.4 |

### 3.2 交付与边界（规格书 §M5 交付 / 1.6）

| # | 要求 | 结论 | 证据 |
| --- | --- | --- | --- |
| 1 | Vue3 单页（Vite） | **通过** | `frontend/` 骨架 + `vite build` 通过（§2.5） |
| 2 | **不引入 Pinia / Router / UI 库** | **通过** | `package.json` 依赖仅 `vue` / `vite` / `@vitejs/plugin-vue`；无状态库、无路由、无组件库；样式全部自写 |
| 3 | 1.6 五项必含（消息列表 / 输入框+发送 / 来源卡片 / 过程指示 / 拒答澄清差异化） | **通过** | 见 §3.1 与 §1.1 组件清单 |
| 4 | 1.6 明确不做（登录 / 历史会话管理页 / 设置页 / 主题切换 / 移动端适配 / **动画特效**） | **通过** | 均未实现；过程指示的「当前节点」用**静态**实心点+描边环区分（**未用动画**，避免踩 1.6 的「动画特效」）；无 media query |

### 3.3 对 5.3 协议的两处**有意扩展**（已登记 DECISIONS）

| 扩展 | 原因 | 证据 |
| --- | --- | --- |
| `done` 事件新增 `clarify_options` | 5.3 原协议 `done` 只有 `type`/`confidence`，**拿不到澄清候选**，前端就无法把候选渲染成可点选项（1.6 第 5 条要求的差异化展示落不了地） | §2.4 澄清路径；`test_clarify_path_carries_options` |
| `done` 事件新增 `intent` | 过程展示与排查需要知道本轮意图；`matched_intents` 已在 M3 留痕，`intent` 是同一口径的单值视图 | §2.4 三条路径的 `intent` 字段 |

> 另：M4 已登记新增 `thinking` 事件（5.3 原集合无「思考中」）。M5 前端已消费该事件（生成中展示「正在思考…」）。

---

## 4. 未达标项及需需求方确认事项

**M5 四项验收全部通过，无硬性未达标项。** 以下为需知晓 / 裁定事项：

1. **【需知晓】前端未用 `EventSource`，用 `fetch` + `ReadableStream`。**
   规格书 §M5 交付原文写「原生 `fetch` + `EventSource`」。但 5.2 把问答定义为 **`POST /api/chat`**
   （请求体带 `session_id` + `question`），而浏览器原生 `EventSource` **只能发 GET**。
   用 `EventSource` 就得把问题塞进 query string 并另开一个 GET 端点 —— 为迁就一个客户端类去改服务端契约。
   `fetch` + `resp.body.getReader()` 是原生能力，能发 POST 也能逐帧读 SSE。已登记 DECISIONS。

2. **【已修正·本轮发现】正文原先「一帧整段」，不符合「流式逐字显示」。**
   原实现下（template 路径与 llm 路径皆然）整段答案作为**单个** `token` 帧推出，
   前端只能一次性显示 —— 协议上也不再是 5.3 那种逐段形态。已改为**按块推**（每帧 ≤ 8 字），
   并新增 `test_token_frames_are_incremental_not_one_shot` 钉住粒度（防退回一帧整段）。
   **口径说明（如实标注）**：分块粒度是「每帧 ≤ 8 字」，不是逐字符；
   且**块在 guard 校验通过之后才推** —— 因为 G2（英雄名越界）要拿全篇英雄名比对、
   G3 要按句子窗口判，必须**完整正文**才判得准，边收边推会让未校验内容先到前端（推出去撤不回）。
   这是「真流式」与「校验后才交付」之间的取舍，取舍方向与 M4 一致（校验优先）。

3. **【待裁定】5.2 表中其余三条接口尚未实现**：`POST /api/graph/import`、`POST /api/docs/upload`、
   `DELETE /api/session/{session_id}`。
   - 事实：这三条**不属于任何里程碑的交付/验收条目**（M5 验收只含前端四项；M4 验收不含它们），
     故本轮未擅自实现，`app/main.py` 文档字符串已明确标注为「尚未挂载」。
   - 影响：**不影响 M5 验收**，也不影响前端（前端只用 `/api/chat` 与 `/api/health`）。
   - 建议归属（请裁定）：`POST /api/graph/import`（幂等导入，与 `scripts/init_graph.py` 同逻辑）
     与 `DELETE /api/session/{id}`（清 checkpointer 会话）实现成本低，可并入 **M6**；
     `POST /api/docs/upload`（multipart + metadata + 切分入库）会牵动「上传语料是否进向量库」的
     数据层口径与版权声明，建议放到 **M7** 或独立小任务，避免影响 M6 评测的可复现性。

4. **【待补】推送 private 仓库**：仓库尚未配置 remote，`gh` CLI 本机不可用。
   请提供 **private 仓库地址**（或确认由谁创建），我再配置 remote 并推送；
   推送前会确认仓库可见性为 **private**，并把 remote 地址回报。

---

## 5. 下一步（M6 评测）

**M5 交付完成，待审核通过后进入 M6。** 规格书仍为 **v1.5**。M6 交付项（含 M4 二审裁定的三条）：

| 来源 | M6 交付项 |
| --- | --- |
| 规格书 §M6 | `tests/eval/cases.yaml`（≥30 条）、评测脚本、`eval_report.md`；报告含 4.4 全部指标实测值（含未达标项如实记录） |
| 规格书 8.1 | 用例分布含「混合类 5 条」（复合意图）、多轮追问 4 条、拒答/越界 4 条 |
| 裁定 A | 给出**复合问题在真实问句中的占比估算**，据此裁决**多意图合并**做不做（低 → 永久不做并写进 README 已知局限） |
| 裁定 B-3 | **guard on/off 的 A/B 对比**，量化对「答案有据率」的实际影响 |
| M3 遗留 | 裁决 **LLM 意图路径（`route_llm`）去留**（启用或删除，不得无限期挂着） |
| M2/M3 遗留 | 意图路由自由口语抽样 80% 的 4 条盲区（「能克制」「走一路」「用什么英雄」「拿X我选谁」）纳入评测 |

> M6 评测脚本将用 `/api/chat/sync`（5.2 明确其存在的理由）批量跑分，避免解析 SSE。
> 前端已就绪，M6 亦可人工抽检 SSE 路径。
