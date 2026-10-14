"""M0 冒烟测试：应用可导入、/api/health 可达且返回三项组件状态字段。

规格书 7 节 M0 验收：pytest 能跑通（1~2 个占位测试即可）。
注意：本测试只断言状态字段结构存在，不要求组件全绿——
neo4j 是否连通取决于 Docker 是否启动，由 /api/health 返回真实值。
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_app_root():
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "honor-graphrag"


def test_health_returns_three_component_status():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    # 三项状态字段必须存在，且每项都有 ok/detail 两个子字段
    for comp in ("neo4j", "chroma", "llm"):
        assert comp in body, f"missing component status: {comp}"
        assert "ok" in body[comp]
        assert "detail" in body[comp]
