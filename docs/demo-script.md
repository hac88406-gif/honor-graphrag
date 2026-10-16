# 演示脚本（规格书 8.1 / M7）

> **用途**：把「跑起来之后打什么、应看到什么」固化成可复制的清单。M7 验收要求「陌生人按 README
> 15 分钟跑起来」——光有启动步骤不够，复核者还需要一份**可复跑的对照表**，否则无法判断「跑对了没有」。
>
> **清单与期望值取自 [`tests/eval/cases.yaml`](../tests/eval/cases.yaml)**（同一份人工标注），
> 避免演示清单与评测集出现两套口径。**问句、期望意图、期望响应类型均不因演示而调整。**

## 一、前置条件

1. 按 [README「快速开始」](../README.md#快速开始陌生人-15-分钟跑起来) 完成第 0~3 步
   （`.env` / venv / 下载 embedding 模型 / 重建数据层 / 起 Neo4j）。
2. 起 API：`.\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`
3. `.env` 里 `GENERATION_MODE=llm`（走真实生产路径，才能看到 LLM 生成与 guard 行为）。
4. 三项组件必须全绿：`curl http://127.0.0.1:8000/api/health` → `neo4j/chroma/llm` 均 `ok=true`。
   任一不 ok 时下面的结果需按降级路径解读（脚本会打 `[WARN]`）。

## 二、复跑方式

```powershell
# 默认打到 127.0.0.1:8000，产物写入 docs/milestones/M7-demo-output.txt
.\.venv\Scripts\python scripts\run_demo.py

# 换地址 / 换产物路径
.\.venv\Scripts\python scripts\run_demo.py --base-url http://127.0.0.1:8000 --out docs/milestones/M7-demo-output.txt
```

脚本行为要点：`/api/health` 先跑并 **fail-fast**（组件不全绿时后面的结果不可信）；
用 `httpx.Client(trust_env=False)` —— 本机若配了 `HTTP(S)_PROXY`，打 `127.0.0.1` 会走代理而连不上；
每条用例用独立 `session_id`（多轮链共用同一个，用于验证指代消解）。

## 三、演示问题清单（8.1 八类场景，15 个 turn）

| # | 用例 | 8.1 场景 | 问句 | 期望意图 / 期望类型 |
| --- | --- | --- | --- | --- |
| 01 | G-01 | 图谱-克制/被克制 | 铠被谁克制 | `COUNTER_BY` / `answer` |
| 02 | G-05 | 图谱-克制/被克制 | 貂蝉克制谁 | `COUNTER_OF` / `answer` |
| 03 | B-02 | 图谱-出装 | 亚瑟怎么出装 | `ITEM_BUILD` / `answer` |
| 04 | B-03 | 图谱-铭文 | 貂蝉的铭文怎么搭配 | `INSCRIPTION` / `answer` |
| 05 | S-01 | 图谱-搭档 | 谁和鲁班七号配合好 | `SYNERGY` / `answer` |
| 06 | T-01 | 文本-打法 | 貂蝉对线思路 | `GAMEPLAY` / `answer` |
| 07 | T-07 | 文本-版本 | 这个版本谁强 | `TIER_META` / `low_confidence` |
| 08 | H-01 | 混合-对位 | 我玩铠怎么打吕布 | `MATCHUP` / `answer` |
| 09 | H-04 | 混合-对位 | 怎么打东皇太一 | `MATCHUP` / `clarify` |
| 10 | M-01 | 多轮追问 | 铠被谁克制（第 1 轮） | `COUNTER_BY` / `answer` |
| 11 | M-01 | 多轮追问 | 那铭文呢（第 2 轮，继承「铠」） | `INSCRIPTION` / `answer` |
| 12 | R-01 | 拒答-越界 | 今天天气怎么样 | `OUT_OF_SCOPE` / `reject` |
| 13 | R-05 | 拒答-知识库未收录 | 铭文怎么分解 | `INSCRIPTION` / `reject` |
| 14 | E-01 | 实体异常（同音错别字） | 凯被谁克制 | `COUNTER_BY` / `answer` |
| 15 | E-03 | 实体异常（纯昵称） | 猴子怕谁 | `COUNTER_BY` / `answer` |

## 四、实测结果（2026-10-16 17:55，真实 HTTP，非桩数据）

环境：`neo4j=True chroma=True llm=True`，`model=deepseek-v4-pro`。
完整逐条输出（含答案全文与来源卡片）见 [`docs/milestones/M7-demo-output.txt`](milestones/M7-demo-output.txt)。

| # | 实测意图 / 类型 | 置信度 | 实体链接 | 依据（图谱/向量） | 耗时 | 与期望一致 |
| --- | --- | --- | --- | --- | --- | --- |
| 01 | `COUNTER_BY` / `answer` | 0.850 | 铠→铠(193, exact) | 4 / 0 | 2.58s | ✅ |
| 02 | `COUNTER_OF` / `answer` | 0.850 | 貂蝉→貂蝉(141, exact) | 10 / 0 | 3.18s | ✅ |
| 03 | `ITEM_BUILD` / `answer` | 0.724 | 亚瑟→亚瑟(166, exact) | 10 / 4 | 7.82s | ✅ |
| 04 | `INSCRIPTION` / `answer` | 0.850 | 貂蝉→貂蝉(141, exact) | 6 / 0 | 2.95s | ✅（另命中 `SYNERGY`，留痕） |
| 05 | `SYNERGY` / `answer` | 0.750 | 鲁班七号→鲁班七号(112, exact) | 2 / 0 | 2.17s | ✅ |
| 06 | `GAMEPLAY` / `answer` | 0.737 | 貂蝉→貂蝉(141, exact) | 0 / 5 | 12.50s | ✅（另命中 `MATCHUP`，留痕） |
| 07 | `TIER_META` / `low_confidence` | 0.516 | （无） | 0 / 5 | 5.37s | ✅ |
| 08 | `MATCHUP` / `answer` | 0.621 | 铠(193) / 吕布(123) | 9 / 5 | 3.21s | ✅（正文见下方观察 3） |
| 09 | `MATCHUP` / `clarify` | 0.000 | 东皇太一→东皇太一(187, exact) | 0 / 0 | 0.02s | ✅ |
| 10 | `COUNTER_BY` / `answer` | 0.850 | 铠→铠(193, exact) | 4 / 0 | 2.91s | ✅ |
| 11 | `INSCRIPTION` / `answer` | 0.850 | 铠→铠(193, exact) | 6 / 0 | 4.85s | ✅（指代消解「那铭文呢」→「铠铭文呢」） |
| 12 | `OUT_OF_SCOPE` / `reject` | 0.000 | （无） | 0 / 0 | 0.02s | ✅ |
| 13 | `INSCRIPTION` / `reject` | 0.000 | （无） | 0 / 0 | 0.02s | ✅ |
| 14 | `COUNTER_BY` / `answer` | 0.850 | 凯→铠(193, **alias**) | 4 / 0 | 3.13s | ✅ |
| 15 | `COUNTER_BY` / `answer` | 0.850 | 猴子→孙悟空(167, **alias**) | 7 / 0 | 3.34s | ✅ |

**15/15 个 turn 的意图与响应类型均与人工标注一致。**

> 注：#14 的链接方式是 `alias` 而非 `fuzzy` —— 「凯」在别名表里有登记（含常见同音错字），
> 故未走到拼音模糊兜底。要看 `fuzzy` 兜底需用别名表未收录的错字，本条只覆盖「同音错字可被链接」。

### 值得注意的实测现象（如实记录）

1. **拒答 / 澄清路径首响应极快（0.02s）且 `citations=[]`。** 第 09/12/13 条都是 0.02s 返回，
   无来源卡片 —— 符合 4.9「拒答 / 澄清明确返回空来源」，不是缺数据。
2. **多意图在回答里被显式告知。** 第 04 条正文首句「（本次只回答了「铭文」；您还提到了「搭档搭配」，
   可以继续追问。）」、第 06 条同理 —— 这正是「只答一个 + 留痕告知」的裁定行为（README 已知局限）。
3. **第 08 条走 `answer` 但正文是「资料不足。」** —— 这是**模型自己**的诚实回退
   （`app/llm/prompts.py` 第 4 条约束「资料不足以回答时直接说明资料不足」），不是空答案、也不是拒答。
   归因：`MATCHUP` 意图把「我玩铠怎么打吕布」拆成我方 + 敌方两个槽位，检索到的是
   **「谁克制吕布」这类通用事实（9 条图谱边）**，而库里**没有「铠对吕布」的逐对位打法文本**，
   模型据此判定证据不足以回答「怎么打」，如实说资料不足。
   **这是检索粒度局限**：图谱只有英雄间克制关系，没有任意两英雄对的打法指导；已登记为已知局限。
4. **延迟分布与 README 已知偏差一致**：模板 / 澄清 / 拒答路径 0.02s；LLM 生成路径 2.17~12.50s，
   差异主因是推理模型的思考前置（`deepseek-v4-pro` 先出 `reasoning_content` 再吐正文），
   详见 README「首 token 延迟」与 [`docs/eval_report.md`](eval_report.md) §2.5。
