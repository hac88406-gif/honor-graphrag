"""图谱复位脚本（补丁 P1 §4）——把数据层从「被写脏」拉回 `data/graph/*.json` 基线。

**为什么必须有这个脚本**：`scripts/init_graph.py` 是**纯 MERGE**，它只会写、不会删。
于是 P1-3 写入的每条关系都**留在图里**，重跑 `init_graph.py` 也修不回来：
MERGE 认的是「起点+类型+终点+patch」这个唯一键，脏关系只要键不同就永远匹配不到，
自然也不会被覆盖掉。而数据层基线（341 节点 / 3165 关系 / COUNTERS 527）是写进 README
并被 `scripts/verify_data_layer.py` 断言的 —— 项目二每演示一次写入，就污染项目一一次，
且基线断言会开始失败。

**语义（照契约 §4 原文）**：`MATCH ()-[r]->() DELETE r` 删掉**全部关系**，再复用
`scripts/init_graph.py` 的 `import_all(session)` 从 `data/graph/*.json` 全量重建。

**只删关系、不删节点**：P1-3 唯一能改的就是关系（它连节点都要求必须已存在，§5-2），
所以关系就是污染面。节点保持不动有两个好处：一是省掉 341 次重建，二是约束/索引
不会被短暂拆掉（`import_all` 建约束用的是 IF NOT EXISTS，节点留着就不会有并发窗口）。

用法：
  python scripts/reset_graph.py      # 复位并打印前后计数
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
for _p in (PROJECT_ROOT, PROJECT_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from neo4j import GraphDatabase  # noqa: E402

from app.config import settings  # noqa: E402

import init_graph  # noqa: E402  # scripts/ 与项目根同在 sys.path

# 删关系不删节点：见模块 docstring。整句是常量，无参数拼接（9.1-4）。
DELETE_ALL_RELATIONSHIPS = "MATCH ()-[r]->() DELETE r"


def _open_driver():
    return GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
        connection_timeout=settings.NEO4J_CONNECT_TIMEOUT,
    )


def reset(session) -> dict:
    """在给定会话上执行「删全部关系 -> 全量重建」，返回 before/after/summary。

    计数口径复用 `init_graph.node_counts` / `rel_counts`（不另写统计语句），
    保证与 `verify_data_layer.py` 看到的是同一套数字。
    """
    before = {
        "nodes": init_graph.node_counts(session),
        "rels": init_graph.rel_counts(session),
    }
    session.run(DELETE_ALL_RELATIONSHIPS)
    summary = init_graph.import_all(session)
    after = {
        "nodes": init_graph.node_counts(session),
        "rels": init_graph.rel_counts(session),
    }
    return {"before": before, "after": after, "summary": summary}


def reset_all() -> dict:
    """自开会话执行复位（CLI 与测试共用的唯一入口，避免各自管理驱动）。"""
    driver = _open_driver()
    try:
        # 不可达必须**响亮地失败**：复位没跑成却静默返回，会让人以为图谱已经干净了
        driver.verify_connectivity()
        with driver.session() as session:
            return reset(session)
    finally:
        driver.close()


def graph_counts() -> dict:
    """当前图谱计数（按 label / 按 type + 合计）。用于交付报告里的「改动前/后/复位后」。"""
    driver = _open_driver()
    try:
        driver.verify_connectivity()
        with driver.session() as session:
            nodes = init_graph.node_counts(session)
            rels = init_graph.rel_counts(session)
    finally:
        driver.close()
    return {
        "nodes": nodes,
        "rels": rels,
        "total_nodes": sum(nodes.values()),
        "total_rels": sum(rels.values()),
    }


def main() -> int:
    result = reset_all()
    print("[reset] 复位前节点：", result["before"]["nodes"])
    print("[reset] 复位前关系：", result["before"]["rels"])
    print("[reset] 本次写入：", result["summary"])
    print("[reset] 复位后节点：", result["after"]["nodes"])
    print("[reset] 复位后关系：", result["after"]["rels"])
    print(
        "[reset] 基线核对请以 scripts/verify_data_layer.py 为准"
        "（README 声明口径：341 节点 / 3165 关系 / COUNTERS 527）"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
