"""LangGraph checkpointer 封装（规格书 4.8-4）。

**为什么用 checkpointer 而不是手写 Redis**（2.3/2.4 已裁定）：
  1. 「最简依赖」是项目目标——Redis 会引入第三个中间件，而本项目真正的外部依赖只有 Neo4j 一个；
  2. 多轮状态的并发写入、序列化、恢复是框架原生能力，手写 Redis 等于把这些重造一遍；
  3. 单机演示场景下 SQLite 文件足够，且可随项目目录一起清理重建（已进 .gitignore）。

**为什么是 AsyncSqliteSaver 而不是 SqliteSaver**（实测结论）：
4.8-6 要求用 `astream_events` 输出节点级事件。`astream_events` 是异步接口，内部会调用
checkpointer 的 `aget_tuple`；同步的 `SqliteSaver` 未实现这些异步方法，会在流式路径上抛
`NotImplementedError: The SqliteSaver does not support async methods`。
因此编排层统一走**异步** checkpointer + 异步调用（`ainvoke` / `astream_events`），
避免出现「同步能跑、流式报错」的一半可用状态。

**SQLite 线程约束**：LangGraph 在工作线程池里执行节点，`sqlite3` 默认禁止跨线程复用连接。
`aiosqlite` 在内部线程执行 sqlite，本身规避了该限制；但若直接传 `sqlite3.connect(...)` 建立的
连接，必须带 `check_same_thread=False`（实测会抛 `ProgrammingError`，见 DECISIONS.md 2026-10-15 M3 条）。
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.config import settings

logger = logging.getLogger(__name__)

# app/memory/checkpointer.py -> app/memory -> app -> 项目根
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# 进程级单例（FastAPI 全生命周期共用；测试用 open_checkpointer 各自建独立的）
_saver: AsyncSqliteSaver | None = None


def db_path() -> str:
    """checkpointer 数据库绝对路径（相对路径按项目根解析，避免随 cwd 漂移）。"""
    p = Path(settings.CHECKPOINT_DB)
    return str(p if p.is_absolute() else PROJECT_ROOT / p)


@asynccontextmanager
async def open_checkpointer(path: str | None = None) -> AsyncIterator[AsyncSqliteSaver]:
    """按需打开一个 checkpointer 上下文。

    测试用 `:memory:` 或临时文件，避免污染真实会话库；退出时关闭连接。
    """
    target = path or db_path()
    if target != ":memory:":
        Path(target).parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(target)
    try:
        yield AsyncSqliteSaver(conn)
    finally:
        await conn.close()


async def get_checkpointer() -> AsyncSqliteSaver:
    """进程级单例。FastAPI 各请求共用同一连接（aiosqlite 内部串行化写操作）。"""
    global _saver
    if _saver is None:
        target = db_path()
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        conn = await aiosqlite.connect(target)
        _saver = AsyncSqliteSaver(conn)
        logger.info("checkpointer 已就绪：%s", target)
    return _saver


async def reset_checkpointer() -> None:
    """丢弃单例（测试或配置变更后调用）。"""
    global _saver
    if _saver is not None:
        try:
            await _saver.conn.close()
        except Exception as e:  # noqa: BLE001 - 清理失败不应影响调用方
            logger.warning("关闭 checkpointer 连接失败：%s", e)
        _saver = None
