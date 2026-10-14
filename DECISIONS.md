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

## 2026-10-14（M2 检索层）

- `2026-10-14 | 意图路由默认走确定性关键词规则路径（route_rules），LLM 路径（route_llm，Ollama 结构化输出）为可选增强且任何异常回落规则路径 | 规格书 4.2 步骤[1]写的是「意图识别（LLM）」，但意图枚举封闭（4.4 明确不得新增）、且输入已带实体链接结果（4.3），关键词覆盖足够；确定性 = 可单测、零延迟、离线可跑，契合 M2 验收全为确定性断言。LLM 路径保留以对接 4.11 的 qwen2.5:3b，M6 若意图准确率不足可切换 | 影响 app/retrieval/intent.py（route(use_llm=False) 为默认）；**此为对规格书 4.2 的有意偏离，M2 报告已单列请需求方确认**`
- `2026-10-14 | 实体链接模糊匹配用「拼音音节序列编辑距离」而非「整串字符编辑距离」，编辑距离→置信度映射 {0:1.0, 1:0.8, 2:0.6}，距离 ≤2 是必要非充分条件，最终由 ENTITY_CONFIDENCE_THRESHOLD(0.7) 把关 | 中文输入错误集中在同音/近音字（凯→铠、貂禅→貂蝉、后一→后羿），音节序列能把同音错字直接归零，比字符编辑距离更贴合错误分布；映射让「距离 2」落到 0.6 < 0.7 被拒，避免过度宽松 | 影响 app/retrieval/entity_linking.py 的 _fuzzy/_lev；M2 实体链接单测覆盖 5 个 fuzzy 用例`
- `2026-10-14 | normalize 增加 ASCII 大小写归一（s.lower()），使分路口语的英文缩写 AD/ADC/AP/SUP/JUNGLE 可命中 | 规格书 4.3 第 2 级点名要求覆盖「AD」等分路口语，但 NFKC 只做全半角、不转小写，而 LANE_ALIASES 的键是小写；不归一即漏命中。英雄/装备/铭文名均为中文，转小写不影响 | 影响 app/retrieval/entity_linking.py 的 normalize；已由单测 test_link_single_entity[AD]/[adc] 固化`
- `2026-10-14 | load_embedding_function() 加进程内缓存（@lru_cache），缓存的是同一个 EF 实例 | bge-large-zh-v1.5 约 1.2GB，每次 get_collection() 都新建 SentenceTransformer 会让单次检索耗时以十秒计（M2 每条查询都取 collection）；缓存不改变「必须显式传入 EF」这一契约 | 影响 app/utils/chroma.py；EF 重启回归测试仍成立（测试自行新建 PersistentClient + 显式传 EF）`
- `2026-10-14 | Neo4j 封装 run_template 的首个形参命名 template（而非 name） | HERO_BY_NAME 模板的 Cypher 参数是 `$name`，若首参叫 name 则 `run_template("HERO_BY_NAME", name="东皇太一")` 抛 "got multiple values for argument 'name'"；改名后模板参数与函数形参不再冲突 | 影响 app/retrieval/neo4j_client.py 的 run_template/query_evidence 签名；已由单测 test_hero_by_name_and_role_templates 固化`
- `2026-10-14 | 别名表 data/hero_aliases.json 由 M1a 的 5 个样例英雄扩展到 38 个英雄（覆盖简称/俗称、同音错字、昵称/梗） | M1b 遗留项：全量入库时其余 128 英雄 aliases 暂空，实体链接层按需补齐；38 个含全部演示点名英雄（亚瑟/貂蝉/东皇太一）+ 高频单字英雄（铠/瑶）+ 高频错字对（凯/貂禅/兰凌王/后裔/安其拉） | 影响 build_graph_data.py 产出的 heroes.json aliases 与 M2 实体链接单测语料`
- `2026-10-14 | M2 目录落地：新增 app/retrieval/（neo4j_client/cypher_templates/chroma_client/bm25/entity_linking/intent）与 app/schemas/、tests/unit/；app/agent/nodes 属 M3 交付物，M2 不创建 | 附录 A 的目录结构中 M2 实际需要的是 retrieval 与 schemas；tests/unit 承载实体链接/模板/方向性测试（附录 A 明示）。agent 编排层为 M3，提前建空目录无内容可放 | 影响仓库结构与附录 A 落地进度；M2 报告已说明 agent/nodes 的归属`

## 2026-10-15（M2 审核后：条件落实 + M3 前置）

- `2026-10-15 | 意图路由测试作为 M3 第一项交付，先于 M3 编排层落地 | 需求方 2026-10-15 裁定：M3 的条件边完全按 intent 分发，intent 有误会让 M3 调试变成噩梦；「规则优先」决定的全部风险都在覆盖率上，M2 交付时零测试不可接受 | 影响 tests/unit/test_intent_routing.py（79 用例）；M3 编排层开工前置条件`
- `2026-10-15 | 规则路径初步准确率：覆盖契约集 43/43 = 100%；规格书 8.1 自带示例问句 11/11；**自由口语抽样 16/20 = 80%** | 条件二要求给出前置信号。前两组 100% 有共同开发（规则与用例同源）导致的虚高，**以自由口语抽样 80% 作为更可信的泛化估计**；低于 85% 的部分即 M6 待补清单 | 影响 M6 评测基线；4 条口语盲区（「能克制」「走一路」「用什么英雄」「拿X我选谁」）已列入 M6 待补`
- `2026-10-15 | IntentResult 增加 matched_intents 字段，命中多个词表时全部记录（按优先级序），并在日志 warning 留痕 | 条件三：当前「先命中先返回」会让「铠的出装和铭文」只返回一个意图、丢掉另一个且无记录——用户拿到半个答案而系统不知道，属静默失败。需求方明确「不要求现在就做多意图合并，但必须看得见」 | 影响 app/retrieval/intent.py 的 route_rules/_RULES；M6 归因「答案不全」时据此判断是否只取了一个意图；已由 test_multi_intent_hit_is_traced 固化`
- `2026-10-15 | 裁定「谁能针对 X」→ COUNTER_BY、「怎么针对 X」→ MATCHUP | 需求方点名的跨意图误判风险：「谁能针对铠」要的是一份压制者名单（同 COUNTER_BY），「怎么针对铠」要的是应对方法（同 MATCHUP）。两者都含「针对」，靠优先级裁决——把「谁能针对/谁针对/谁能克/谁能压制」加入 _COUNTER_BY，_COUNTER_BY 先于 _MATCHUP | 影响 app/retrieval/intent.py 的 _COUNTER_BY；已由 test_who_counters_kai_ruling 固化（并断言该问句 matched_intents 同时含两者）`
- `2026-10-15 | 移除分路口语的单字别名「上」「中」（保留「上单/中单」等双字形式） | 单字别名会在「上海」「中国」这类与王者无关的词里误命中分路，把 OUT_OF_SCOPE 问句抬成 ENTITY_UNKNOWN（走澄清而非拒答）——是意图路由的静默误判源。规格书 4.3 点名要求覆盖的是「上单/中单」 | 影响 app/retrieval/entity_linking.py 的 LANE_ALIASES；已由 test_intent_routing 的「北京到上海多远」用例固化；test_entity_linking.py 不依赖单字别名`
- `2026-10-15 | LLM 意图路径（route_llm）设去留期限：**M6 评测后必须决定「启用」或「删除」，不得无限期挂着** | 需求方记录性要求：一个永远不执行的代码路径 = 未测试代码 = 隐患。当前 route(use_llm=False) 为默认，LLM 路径仅实现未启用 | 影响 app/retrieval/intent.py 的 route_llm/_LLM_SYSTEM；M6 评测报告须给出该路径的裁决（若意图准确率 < 85% 则切换启用并复测，否则删除）`
- `2026-10-15 | Chroma 弃用警告登记：测试输出出现 DeprecationWarning「legacy embedding function config: 'BgeEmbeddingFunction' object has no attribute 'is_legacy'」，说明 EF 走的是兼容路径，未来 Chroma 版本可能移除 | 需求方记录性要求：这正是 EF 重启回归测试存在的理由。**升级 Chroma 版本时必须复跑 tests/unit/test_retrieval_chroma.py::test_ef_restart_regression**，确认 EF 契约未被破坏 | 影响 chromadb 版本升级流程与 README 升级说明；该用例断言写入→重启→重取 collection→同句结果一致`

## 后续里程碑待补

- M2：BM25 中文分词配置、实体链接候选策略细节 → **已于 2026-10-14 M2 落实**（见上节）

- M2 验收补充（需求方 2026-10-14 要求）：M2 完成后复跑一次同类数据层校验（节点/关系计数 + `source/patch/reason` 完整性），确认检索层未破坏数据；M2 交付报告需附该校验真实输出
- M3：LangGraph checkpointer 路径、并行分支实现细节
- M6：评测阈值校准结果回写
