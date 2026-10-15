"""Cypher 模板注册表 + COUNTER_BY / COUNTER_OF 方向断言（规格书 4.7 / M2 验收）。

规格书 4.4 点名：**方向写反时查询会返回结果而不是报错**（静默错误），故必须为两条查询各写断言。
本文件把「方向性」拆成两层断言：
  1. 静态：模板文本里 MATCH 模式的箭头方向正确（离线可跑）；
  2. 动态：真实 Neo4j 上，COUNTERS_OF_HERO 返回的 subject 恒为被查英雄、COUNTERS_BY_HERO
     返回的 target 恒为被查英雄，并用一条已知边（兰陵王→李白）做正反交叉验证。

Neo4j 不可达时相关用例走 `require_neo4j` 门禁（见 tests/conftest.py）：
开发模式跳过（视为「未执行」），**验收模式（REQUIRE_SERVICES=1）下 fail**——
方向性动态断言是防静默方向错误的核心保护，不允许在验收时静默跳过。
静态用例始终离线运行。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import settings
from app.retrieval import cypher_templates as ct
from app.retrieval import neo4j_client

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RELATIONS_FILE = PROJECT_ROOT / "data" / "graph" / "relations.json"

LANLINGWANG = "153"   # 兰陵王
LIBAI = "131"         # 李白
# 已知单向边（源数据层 relations.json 中 兰陵王 克制 李白，且无 李白→兰陵王 反向边）
KNOWN_FROM, KNOWN_TO = LANLINGWANG, LIBAI


def _load_relations() -> list[dict]:
    return json.loads(RELATIONS_FILE.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 静态（离线）

def test_registry_has_exactly_seven_templates():
    """规格书 4.7：模板注册表恰有 7 个模板，键名与规格书一致。"""
    expected = {
        "COUNTERS_BY_HERO", "COUNTERS_OF_HERO", "SYNERGY_BY_HERO",
        "ITEMS_BY_HERO", "INSCRIPTIONS_BY_HERO", "HERO_BY_NAME", "HEROES_BY_ROLE",
    }
    assert set(ct.TEMPLATES) == expected


def test_render_unknown_template_raises():
    """未知模板名必须抛错，避免静默路由到空查询。"""
    with pytest.raises(KeyError):
        ct.render("NO_SUCH_TEMPLATE")


def test_intent_to_template_is_closed():
    """意图 -> 模板映射封闭：键 ⊆ 意图枚举、值 ⊆ 模板表。"""
    from app.retrieval.intent import INTENTS

    assert set(ct.INTENT_TO_TEMPLATE) <= set(INTENTS)
    assert set(ct.INTENT_TO_TEMPLATE.values()) <= set(ct.TEMPLATES)


def test_direction_arrows_in_template_text():
    """静态方向断言：被谁克制 = 入边，克制谁 = 出边（写反即失败）。"""
    assert "(x:Hero)-[r:COUNTERS]->(k:Hero {id: $hero_id})" in ct.COUNTERS_BY_HERO
    assert "(k:Hero {id: $hero_id})-[r:COUNTERS]->(x:Hero)" in ct.COUNTERS_OF_HERO


def test_templates_are_parameterized_not_concatenated():
    """9.1-4：所有 Cypher 必须参数化（$param），不得字符串拼接。

    模板是纯字符串常量：不应出现 Python 侧的插值痕迹（%s / .format(），
    一切变量只能经 `$param` 交给驱动绑定。
    """
    for name, cypher in ct.TEMPLATES.items():
        assert "$" in cypher, f"{name} 未见参数占位符"
        assert "%s" not in cypher and ".format(" not in cypher, f"{name} 出现字符串拼接痕迹"
    for name in ("COUNTERS_BY_HERO", "COUNTERS_OF_HERO", "SYNERGY_BY_HERO",
                 "ITEMS_BY_HERO", "INSCRIPTIONS_BY_HERO"):
        assert "$hero_id" in ct.TEMPLATES[name]
        assert "$patches" in ct.TEMPLATES[name]
        assert "$limit" in ct.TEMPLATES[name]


def test_graph_templates_filter_by_patch():
    """版本过滤在模板层以 `r.patch IN $patches` 实现（1.9 统一口径）。"""
    for name in ("COUNTERS_BY_HERO", "COUNTERS_OF_HERO", "SYNERGY_BY_HERO",
                 "ITEMS_BY_HERO", "INSCRIPTIONS_BY_HERO"):
        assert "r.patch IN $patches" in ct.TEMPLATES[name]


# ---------------------------------------------------------------- 动态（Neo4j）

def test_counters_of_hero_rows_subject_is_queried_hero(require_neo4j):
    """COUNTERS_OF_HERO（X 克制谁，出边）：每行的 subject 必须是被查英雄本身。

    若方向写反（查成入边），subject 会变成对方英雄，此断言立即失败。
    """
    require_neo4j()
    rows = neo4j_client.run_template("COUNTERS_OF_HERO", hero_id=LANLINGWANG, limit=100)
    assert rows, "兰陵王应有出边 COUNTERS（克制谁）"
    assert all(r["subject_id"] == LANLINGWANG for r in rows), "subject 不是被查英雄，方向可能写反"


def test_counters_by_hero_rows_target_is_queried_hero(require_neo4j):
    """COUNTERS_BY_HERO（X 被谁克制，入边）：每行的 target 必须是被查英雄本身。"""
    require_neo4j()
    rows = neo4j_client.run_template("COUNTERS_BY_HERO", hero_id=LANLINGWANG, limit=100)
    assert rows, "兰陵王应有入边 COUNTERS（被谁克制）"
    assert all(r["target_id"] == LANLINGWANG for r in rows), "target 不是被查英雄，方向可能写反"


def test_counter_edge_cross_consistency_known_pair(require_neo4j):
    """用已知单向边 兰陵王→李白 做正反交叉验证（同一事实从两个方向查得到）。"""
    require_neo4j()
    of_targets = {
        r["target_id"]
        for r in neo4j_client.run_template("COUNTERS_OF_HERO", hero_id=KNOWN_FROM, limit=100)
    }
    assert KNOWN_TO in of_targets, "兰陵王 应克制 李白（出边缺失）"

    by_counters = {
        r["counter_id"]
        for r in neo4j_client.run_template("COUNTERS_BY_HERO", hero_id=KNOWN_TO, limit=100)
    }
    assert KNOWN_FROM in by_counters, "李白 应被 兰陵王 克制（入边缺失）"

    # 反向不存在：兰陵王 被谁克制 不应包含 李白（否则方向被写反/多写了反向边）
    by_llw = {
        r["counter_id"]
        for r in neo4j_client.run_template("COUNTERS_BY_HERO", hero_id=KNOWN_FROM, limit=100)
    }
    assert KNOWN_TO not in by_llw, "李白 不应出现在 兰陵王 的『被谁克制』里（方向写反）"


def test_counter_out_degree_dedup_caliber(require_neo4j):
    """出度对账：入库后（去重）出度 == 源数据层出度按 (起点,类型,终点) 去重后的条数。

    兰陵王 源数据层出边 24 条，其中 兰陵王→鲁班七号 被两处官方页各述一次，
    MERGE（唯一键含 patch）后合并为 1 条 -> 入库后 23 条。这正是「三层计数口径」的落点。
    """
    require_neo4j()
    src_out = [
        r["to_id"]
        for r in _load_relations()
        if r["type"] == "COUNTERS" and r["from_id"] == LANLINGWANG
    ]
    assert len(src_out) == 24, "源数据层兰陵王出度应为 24"
    assert len(set(src_out)) == 23, "去重后（按终点）应为 23"

    rows = neo4j_client.run_template("COUNTERS_OF_HERO", hero_id=LANLINGWANG, limit=100)
    assert len(rows) == len(set(src_out)) == 23, "入库后出度应等于去重后条数"

    duplicated = sorted({t for t in src_out if src_out.count(t) > 1})
    assert duplicated == ["112"], f"唯一被合并的边应是 兰陵王→鲁班七号，实际 {duplicated}"


def test_graph_version_filter_returns_no_rows_for_old_patch(require_neo4j):
    """图谱侧版本过滤：窗口外的 patch 不应召回任何行（实际召回结果，非 count）。"""
    require_neo4j()
    rows = neo4j_client.run_template(
        "COUNTERS_OF_HERO", hero_id=LANLINGWANG, limit=100, patches=["1999-01"]
    )
    assert rows == []
    # 默认窗口（config.PATCH_WINDOW）应正常召回
    assert neo4j_client.run_template("COUNTERS_OF_HERO", hero_id=LANLINGWANG, limit=100)


def test_query_evidence_structure_matches_5_1(require_neo4j):
    """图谱 Evidence 结构符合 5.1：kind=graph、relation/source/source_url/patch 齐备、score=None。"""
    require_neo4j()
    ev = neo4j_client.query_evidence("COUNTERS_OF_HERO", hero_id=LANLINGWANG, limit=3)
    assert ev
    e = ev[0]
    assert e.kind == "graph"
    assert e.relation == "COUNTERS"
    assert e.source == "official"
    assert e.source_url and e.source_url.startswith("http")
    assert e.patch in settings.PATCH_WINDOW
    assert e.score is None
    assert "克制" in e.content
    assert len(e.hero_ids) == 2 and e.hero_ids[0] == KNOWN_FROM


def test_items_and_inscriptions_templates(require_neo4j):
    """出装 / 铭文模板可查且 hero_id 恒为被查英雄。"""
    require_neo4j()
    items = neo4j_client.run_template("ITEMS_BY_HERO", hero_id="166", limit=20)  # 亚瑟
    assert items and all(r["hero_id"] == "166" for r in items)

    ins = neo4j_client.run_template("INSCRIPTIONS_BY_HERO", hero_id="141", limit=20)  # 貂蝉
    assert ins and all(r["hero_id"] == "141" for r in ins)


def test_hero_by_name_and_role_templates(require_neo4j):
    """按规范名/别名反查英雄；按分路列英雄。"""
    require_neo4j()
    by_name = neo4j_client.run_template("HERO_BY_NAME", name="东皇太一")
    assert by_name and by_name[0]["id"] == "187"

    by_alias = neo4j_client.run_template("HERO_BY_NAME", name="东皇")
    assert by_alias and by_alias[0]["id"] == "187"

    by_role = neo4j_client.run_template("HEROES_BY_ROLE", role="游走", limit=50)
    assert by_role and all("游走" in r["roles"] for r in by_role)
