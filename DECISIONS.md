# DECISIONS.md — 技术决策记录

> 规格书 0.1 铁律 2：**遇到规格书未定义的决策，先写入本文件（一行：决策 + 理由 + 影响面），再实现。禁止静默决定。**
> 格式：`日期 | 决策 | 理由 | 影响面`

## 2026-10-14（M0 前，需求方确认单已逐条裁定）

- `2026-10-14 | Q6：意图识别模型先用本机 qwen2.5:3b（规格书默认 7b），M6 评测若意图路由准确率 < 85% 再换 7b | 需求方裁定：3b 大概率够用（意图是封闭枚举 + 输入已带实体链接结果）；避免一开始下载 4.7GB | 影响 config.INTENT_MODEL 默认值；M6 评测报告需含意图路由准确率 |
- `2026-10-14 | Q7：答案生成默认走云端 API；key 到位前按 LLM_MODE=local 实现并保证可切换，local 不算验收状态 | 需求方裁定：生成质量是演示门面，3b 中文游戏领域表达不足 | 影响 config.LLM_MODE / CLOUD_* 键；M4 验收前需提供 key 或明确记录降级 |
- `2026-10-14 | Q5：Neo4j 部署首选 Docker（docker-compose.yml）；Docker 守护进程不可用时改 Neo4j Desktop 本机直装；明确不用 Aura Free | 需求方裁定：Aura 要注册 + 网络，演示时不可控 | 影响环境依赖与 README 启动说明 |
- `2026-10-14 | Q8：项目根目录固定为 D:\javaProgram\honor-graphrag | 需求方裁定：不放 Trae 沙箱深处（路径深、可能随沙箱清理） | 影响所有相对/绝对路径约定 |
- `2026-10-14 | B：ML 重依赖（torch / sentence-transformers）单独放入 requirements-ml.txt，M1a 阶段安装；下载失败先试用镜像源再记录 | 需求方裁定：Windows 上 GB 级下载，先确认网络 | 影响安装流程，M0 不被重依赖阻塞 |
- `2026-10-14 | weight 字段改为可选，官方数据统一填 1.0（语义=官方认定关系存在，不代表强度）；禁止 LLM 编造权重 | 需求方裁定（A 条）：官方不提供权重，给确定性数据加注虚假精度是更坏的做法；4.9 低置信判定改为"图谱仅命中 1 条关系且无文本证据交叉印证" | 影响 4.5 关系模型、4.9 置信度判定、M2 模板实现 |
- `2026-10-14 | 依赖清单拆分为 requirements.txt（核心，M0 可全装）与 requirements-ml.txt（ML，M1a 装） | M0 需快速验证骨架，避免被 torch 下载阻塞；规格书 4.12 Python 3.12 已核实 | 影响安装流程与 README 启动步骤 |

- `2026-10-14 | pip 源改用清华镜像（配置写入 .venv/pip.ini，仅影响本项目 venv，不动全局 pip 配置） | 实测官方 PyPI 源约 29KB/s，kubernetes-37.0.1(7.5MB) 下载停滞数分钟；清华镜像约 114KB/s（快约 4 倍）。用户 B 条已预授权"下载失败走镜像并记 DECISIONS.md" | 影响依赖安装来源；README 启动步骤需注明镜像配置；若某包镜像未同步则临时回退官方源 |

## 2026-10-14（M1a 数据层）

- `2026-10-14 | 分路编码 -> 分路名映射：1=对抗路 2=打野 3=中路 4=发育路 5=游走（ROLE_CODE_TO_LANE） | 规格书 6.1 未给出编码含义，由实测反查：拿 herolist.json 的 roles 与官方英雄页分路图标交叉验证得出 | 影响 fetch_official.py 的 roles 解析与 DATA_SCOPE 分路统计；M2 的 HEROES_BY_ROLE 模板依赖同一映射`
- `2026-10-14 | 装备 item_type -> 分类名映射：1=攻击 2=法术 3=防御 4=移动 5=打野 7=游走（ITEM_TYPE_TO_CATEGORY） | 规格书 6.1 标"待实现方验证"，实测 115 件装备的 item_type 取值只出现 {1,2,3,4,5,7}，**不存在 6**；分类名按官方装备页分组标题归纳 | 影响 fetch_official.py 装备结构化；未命中类型会落为 "未知(N)" 而非静默丢弃`
- `2026-10-14 | 铭文 ming_type -> 颜色映射：red=红 yellow=黄 blue=蓝（MING_TYPE_TO_COLOR） | 规格书 6.1b 写的 "green" 与实测不符——实测 93 个铭文的 ming_type 只有 red/yellow/blue 三值，无 green | 影响 fetch_official.py 铭文解析；若官方后续引入绿色系铭文需补映射`
- `2026-10-14 | 5 个样例英雄（阶段一入库）选定为：亚瑟(166) / 兰陵王(153) / 貂蝉(141) / 后羿(169) / 东皇太一(187) | 规格书 6.4 只规定"5 个英雄"，未指定名单。选取依据：①五路各一（对抗/打野/中路/发育/游走）；②覆盖规格书 8.1 演示脚本点名的三个英雄（亚瑟、貂蝉、东皇太一），保证"亚瑟怎么出装""貂蝉铭文""怎么打东皇"三类 demo 问题在阶段一即可跑通；③含 2 个新手最常问（亚瑟/后羿）+ 3 个高讨论度（貂蝉/东皇太一/兰陵王） | 影响 data/graph/*.json、hero_aliases.json、guides/*.md、REVIEW.md 的覆盖面；**名单在 M1a 审核时需求方可直接改**`
- `2026-10-14 | Neo4j 入库范围：5 个全量 Hero 节点 + 被这 5 英雄关系引用到的"邻居英雄"桩节点（仅 id/name/patch/source/data_source=official，无 aliases/roles） | 规格书 4.5 要求"入库 5 个英雄的完整数据（含其关系）"，但关系边的终点必须存在节点才能建边；官方关系指向的英雄绝大多数不在这 5 个之内。若只建 5 个节点，则几乎所有 COUNTERS/SYNERGIZES 边都无处落，demo 的"图谱召回"链路直接失效 | 影响 init_graph.py 的节点集与 M1a 验收的节点计数口径（报告需区分"全量英雄"与"桩节点"）；M1b 全量入库时桩节点会被真实数据覆盖为全量节点`
- `2026-10-14 | 阶段一语料构成：C1（官方聚合，data_source=real）5 篇 + C2（LLM 生成，data_source=llm_assisted）5 篇 = 10 篇，每英雄各一篇 | 规格书 6.2 裁定"C1+C2 为主，C3 不用"；C1 用官方详情页的克制/搭档理由 + 技能描述 + 铭文说明 + 出装说明按英雄聚合，文本全部取自抓取快照、不经改写，故与图谱关系同源；C2 基于同一批官方事实撰写"对线/打法思路"，事实源仍是官方故内容自洽。C1 由 scripts/build_guides.py 从快照自动生成（保证不掺入人工改写），C2 人工撰写、在 REVIEW.md 中单列待审 | 影响 data/guides/*.md 的篇目与 metadata、init_chroma.py 的导入、M6 评测对"模板腔"的检查`
- `2026-10-14 | C2 语料的 metadata 取 source_type="official" + data_source="llm_assisted" | 规格书 4.6 的 source_type 枚举只有 official/guide_site/ugc，无"生成"一档；C2 的事实来源是官方页面（故 source_type=official），但文本是生成而非原文（故 data_source=llm_assisted）。两字段语义分工：source_type 记事实出处，data_source 记文本是否真实 | 影响 init_chroma.py 的 metadata 写入与 REVIEW.md 的 llm_assisted 单列口径`
- `2026-10-14 | 推荐出装中 4 个装备 ID（1722/1223/1225/91040）在 item.json 全量清单中不存在，对应 RECOMMENDS_ITEM 边暂不建立并记入 REVIEW.md | 实测 133 英雄共 1594 条出装引用、72 个不同装备，其中上述 4 个 ID 在 item.json(115 件) 中查无；规格书 3.4 要求装备节点恰为 115，故不为其造桩节点 | 影响 init_graph.py 的出装边计数与 REVIEW.md 的不确定项；待官方 item.json 补齐后可重跑`
- `2026-10-14 | Embedding 模型 bge-large-zh-v1.5 的下载源改用 ModelScope（魔搭）镜像，落盘 models/bge-large-zh-v1.5，规格书 1.3 选型不变 | 实测 hf-mirror.com 对该模型静态资源返回 403 无法下载；ModelScope 可访问且实测约 1~5 MB/s，可断点续跑 | 影响 scripts/download_embedding_model.py（BASE 固定为 modelscope.cn 的 resolve 地址）、config.EMBEDDING_MODEL_DIR（本地目录优先加载，避免运行时联网）；模型目录已加入 .gitignore（约 1.24GB，不入库）`
- `2026-10-14 | Chroma 每次运行先删同名 collection 再重建（幂等），而非"存在则跳过" | 重复执行导入时若跳过，切分参数或语料变动会留下脏数据导致 count 漂移；删除重建保证任意次运行结果一致 | 影响 scripts/init_chroma.py 的建库流程；代价是每次重跑需重新 embedding（10 篇语料、24 chunk，本机 CPU 秒级完成）`
- `2026-10-14 | 列表型 hero_ids 的过滤算子：实测 chromadb 1.5.9 下 `{"hero_ids": {"$in": [...]}}` 对列表字段**返回空**（$in 只匹配标量等值），`$contains` 才是列表成员匹配的正确算子；故保留 hero_ids 为 [String]（规格书 4.6），但 M2 检索层的 hero 过滤必须用 `$contains`（多英雄用 `$and` 叠加），**不采用规格书 4.6 示例中的 `$in`** | 规格书 4.6 的 metadata 定义（hero_ids: [String]）与它自己的过滤示例（$in）在本机 chromadb 版本下不可同时成立；$in 静默返回空会导致"按英雄过滤"看起来生效实则失效（正是规格书 4.6 警告的静默失败） | 影响 init_chroma.py 的抽查语句（已改为 $contains）与 M2 向量检索的 where 构造；**此为规格书 4.6 示例算子与库行为的冲突点，已在 M1a 报告中显式列出待需求方确认**`
- `2026-10-14 | 重新打开 collection 时必须显式传入 bge embedding function（`get_collection(name, embedding_function=...)`），不可用 `get_collection(name)` 裸取 | 实测裸取会回退到 chromadb 默认的 ONNXMiniLM_L6_V2，该默认 EF 会联网下载 ONNX 模型（本机握手超时→查询报 ConnectTimeout）；即入库用 bge、查询用另一模型，向量空间不一致且依赖联网 | 影响 M2 向量检索的 collection 获取方式；M1a 的 /api/health 未触发此路径（只做 heartbeat），故 M1a 验收不受影响`

## 2026-10-14（M1b 数据层 — 全量阶段）

- `2026-10-14 | 全项目只通过统一的 get_collection()（app/utils/chroma.py）获取 collection，内部固定传入 bge-large-zh-v1.5 的 EF；禁止任何地方直接 chroma_client.get_collection("guides") | 规格书 4.6「第二个静默失败陷阱」强制项：裸取 collection 会回退到默认 ONNX 模型（all-MiniLM-L6-v2）并联网下载，导致查询向量与写入向量不同源 → 召回静默失效。把「必须显式传 EF」收敛为唯一入口，调用点无处漏传 | 影响 init_chroma.py（EF 加载与 client 获取改为从该模块 import，删除脚本内的第二份 EF 定义）、M2 检索层的 collection 获取方式、M2 EF 重启回归测试；已由 tests/test_data_pipeline.py 的 EF 回归用例覆盖`
- `2026-10-14 | M1b 入库范围：133 英雄全量（不再是 5 样例 + 邻居桩）；别名 data/hero_aliases.json 仍只覆盖 M1a 的 5 个样例英雄，其余 128 个英雄节点 aliases 取空列表 | 规格书 3.4 目标「英雄节点 133」；桩节点机制随全量入库自然消失（所有关系端点均在这 133 个之内）。别名是实体链接层（M2）的语料，规格书 6.4/1002 只要求覆盖那 5 个样例英雄，全量别名留待 M2 按需补齐 | 影响 build_graph_data.py（取消样例过滤、aliases 允许缺省为空）、init_graph.py（stub 节点数降为 0）、REVIEW.md §4.4 别名表口径`
- `2026-10-14 | 语料构成在 M1b 扩为 C1 133 篇（全量英雄官方聚合）+ C2 5 篇（llm_assisted），C1:C2 ≈ 26:1 | 规格书 M1b 要求语料 ≥100；需求方裁定 M1a 阶段 5:5 只是样例、全量阶段 C1 必须明显主导（≥3:1）。C1 由 build_guides.py 从快照自动生成，C2 保持 M1a 已审的 5 篇不动 | 影响 data/guides/*.md 篇目、init_chroma.py 的 chunk 数（≥100）、REVIEW.md §3 语料清单`
- `2026-10-14 | RECOMMENDS_ITEM 边实测 1574 的构成：源引用 1594 = 133×2×6 − 2（`元流之子(法师)` 官方两套出装各 5 件；266 套中仅此 2 套为 5 件，其 10 个 ID 均有效），再减 20 处缺失装备引用 = 1574 | 需求方核对「133×2×6=1596」与实际 1574 差 22，要求说明余下 2 条来源 | 影响 M1b 报告 §2.1 与 §4 的计数说明；结论：差额与缺失装备无关，是官方该英雄出装本就不足 6 件`
- `2026-10-14 | **统一计数口径（全项目规矩）**：关系计数分三层，任何 COUNTERS / SYNERGIZES 数字必须注明层级——**源数据层**（`data/raw/<snapshot>/parsed/relations_all.json`，798 行 / COUNTERS 532）／**导出层**（`data/graph/relations.json`，798 行 / COUNTERS 532，**未去重**）／**入库后层**（Neo4j 按唯一键 `起点+类型+终点+patch` MERGE 去重，793 边 / COUNTERS 527） | 同一根因已两次造成对账歧义（M1a 报告 COUNTERS 99 vs 100；data_profile 兰陵王出度 24 vs Neo4j 23，后者差的正是合并边 兰陵王→鲁班七号）。需求方 2026-10-14 要求统一口径 | 影响 fetch_report.md / data_profile.md / 各里程碑报告 / README 的全部关系计数表述；`data_profile.md` 主表标注为源数据层并新增「入库后口径对照」小节；「793 / 527」是去重后口径，只在入库时实现`

## 后续里程碑待补

- M2：BM25 中文分词配置、实体链接候选策略细节
- M2 验收补充（需求方 2026-10-14 要求）：M2 完成后复跑一次同类数据层校验（节点/关系计数 + `source/patch/reason` 完整性），确认检索层未破坏数据；M2 交付报告需附该校验真实输出
- M3：LangGraph checkpointer 路径、并行分支实现细节
- M6：评测阈值校准结果回写
