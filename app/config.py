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
    LLM_MAX_TOKENS: int = 512

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
