"""全局配置（规格书 9.1-2：所有配置集中于此 + .env，禁止硬编码）。

全部配置项从环境变量读取，未设置的走默认值（与 .env.example 对应）。
新增配置项时：config.py 定义 -> .env.example 补充 -> DECISIONS.md 记录影响面。
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # 允许 .env 中残留与本类无关的键，不报错
    )

    # ---------- 服务 ----------
    APP_HOST: str = "127.0.0.1"
    APP_PORT: int = 8000
    DEBUG: bool = False

    # ---------- Neo4j（规格书 4.12：外部依赖仅此一个） ----------
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    # 演示项目弱口令：README 数据声明中必须注明"仅本地演示，勿用于生产"
    NEO4J_PASSWORD: str = "honor-graphrag"
    NEO4J_CONNECT_TIMEOUT: float = 5.0   # 秒

    # ---------- Chroma（嵌入式 PersistentClient，零外部依赖） ----------
    CHROMA_PERSIST_DIR: str = "data/chroma"

    # ---------- LLM ----------
    # LLM_MODE: local=全本地（Ollama）；cloud=全部云端；hybrid=意图本地/生成云端
    LLM_MODE: str = "local"
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    # 意图识别模型（Q6 裁定：先用 qwen2.5:3b 走通链路，M6 评测不达标再换 7b）
    INTENT_MODEL: str = "qwen2.5:3b"
    # 答案生成：云端 API 参数（Q7 裁定：key 到位前 LLM_MODE=local 可跑但不算验收状态）
    CLOUD_API_KEY: str = ""
    CLOUD_BASE_URL: str = ""
    CLOUD_CHAT_MODEL: str = ""
    LLM_TIMEOUT: float = 30.0            # 秒
    # 推理模型（deepseek-v4-pro / flash）的 completion_tokens **含思考**，实测思考可吃 250~290。
    # 512 会给正文只留 220~260，重问题直接触发 finish_reason=length + 空答案（实测复现）。
    LLM_MAX_TOKENS: int = 2048
    # M6 评测判官（scripts/eval_judge.py）单独一份预算，**不复用生成用的 LLM_MAX_TOKENS**。
    # 原因：判官要「先读完资料再逐条比对」，资料越长思考越长——实测 5/78 条判官
    # 因 2048 全被思考吃掉而返回空答案（finish_reason=length），答案有据率的分母被迫缩小。
    # 判官的产出只是一小段 JSON，正文不需要空间，缺的是思考空间，故给到 2 倍。
    JUDGE_MAX_TOKENS: int = 4096
    # 答案生成方式：llm=云端生成 + 生成后校验；template=确定性证据组装（M3 行为，离线可测）。
    # 测试默认 template（离线、确定性）；M4 生成用例显式置 llm。
    GENERATION_MODE: str = "template"
    # 生成后校验（4.9 生成约束补强）：光靠 prompt 挡不住「把资料里的解释当类别」的越界归纳。
    GUARD_ENABLED: bool = True

    # ---------- Embedding（规格书 1.3 默认裁定） ----------
    EMBEDDING_MODEL: str = "BAAI/bge-large-zh-v1.5"
    # 本地模型目录（由 scripts/download_embedding_model.py 从 ModelScope 拉取）。
    # 存在时优先按本地目录加载，避免运行时联网；不存在则回退到 EMBEDDING_MODEL 走 HF。
    EMBEDDING_MODEL_DIR: str = "models/bge-large-zh-v1.5"
    EMBEDDING_DEVICE: str = "cpu"

    # ---------- 版本（规格书 1.9 统一口径：最近 3 个 patch） ----------
    CURRENT_PATCH: str = "2026-10"
    PATCH_WINDOW: list[str] = ["2026-10", "2026-09", "2026-08"]

    # ---------- 置信度阈值（规格书 4.9；M6 阶段评测校准后回写） ----------
    CONF_LOW: float = 0.45
    CONF_HIGH: float = 0.60
    # 图谱单路的 confidence 映射（4.9 v1.5「按关系条数」；M6 校准）。≥1 条即正常回答，不降级。
    CONF_GRAPH_1: float = 0.60   # 1 条官方关系
    CONF_GRAPH_2: float = 0.75   # 2 条（官方页面模板的常规条数）
    CONF_GRAPH_3: float = 0.85   # ≥3 条互相印证
    # 实体链接采纳阈值（规格书 4.3：< 0.7 走澄清反问）
    ENTITY_CONFIDENCE_THRESHOLD: float = 0.7

    # ---------- 检索 ----------
    GRAPH_TOP_K: int = 10                # 图谱模板查询 LIMIT（规格书 4.4 示例为 10）
    VECTOR_TOP_K: int = 5                # 向量检索返回条数
    BM25_TOP_K: int = 5                  # BM25 混合检索返回条数
    RRF_K: int = 60                      # RRF 融合常数
    USE_BM25: bool = True                # 规格书 10 号裁定：v1 加上 BM25

    # ---------- LangGraph checkpointer（规格书 4.8-4：SqliteSaver，thread_id = session_id） ----------
    # 多轮记忆落本地 SQLite 文件（替代手写 Redis，2.3/2.4 已裁定）；文件可重建，不入库
    CHECKPOINT_DB: str = "data/checkpoints.sqlite"
    # 指代消解视为「简短追问」的长度上限（规格书 4.10 规则 2：长度 < 8 字）
    COREF_SHORT_LEN: int = 8


settings = Settings()
