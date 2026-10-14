"""7 个参数化 Cypher 模板注册表（规格书 4.7）。

**不用自由 Text2Cypher**（4.7 已裁定）：本项目 schema 只有 4 类节点、4 类关系，意图是封闭枚举。
自由生成 Cypher 在窄 schema 上是「用不可靠的手段解决确定性问题」，收益为零、风险非零：
  - 可靠性：意图枚举封闭，模板可穷举；
  - 安全性：参数化从根本上消除注入面（9.1-4：禁止字符串拼接）；
  - 可测试性：每个模板可单测，给定槽位断言返回结构；
  - 可缓存：同一槽位组合的结果可缓存。

**方向性是本文件最容易写错的地方**（规格书 4.4 点名）：
  - COUNTERS_BY_HERO（X 被谁克制）= **入边** `(x)-[r:COUNTERS]->(k)`，x 是压制者；
  - COUNTERS_OF_HERO（X 克制谁）  = **出边** `(k)-[r:COUNTERS]->(x)`，x 是被压制者。
方向写反时查询**会返回结果而不是报错**（静默错误），故 M2 必须为两者各写断言测试。

patch 过滤统一用 `r.patch IN $patches`（标量字段），窗口来自 config.PATCH_WINDOW（规格书 1.9）。
"""
from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------- 模板定义

# 谁克制 X（入边）。返回压制者 x 与目标 k 两侧名字，供 Evidence 组装完整关系描述。
COUNTERS_BY_HERO: Final[str] = """
MATCH (x:Hero)-[r:COUNTERS]->(k:Hero {id: $hero_id})
WHERE r.patch IN $patches
RETURN x.id AS counter_id, x.name AS counter_name,
       k.id AS target_id, k.name AS target_name,
       r.reason AS reason, r.weight AS weight, r.patch AS patch, r.source AS source
ORDER BY r.weight DESC, x.name
LIMIT $limit
"""

# X 克制谁（出边）。
COUNTERS_OF_HERO: Final[str] = """
MATCH (k:Hero {id: $hero_id})-[r:COUNTERS]->(x:Hero)
WHERE r.patch IN $patches
RETURN k.id AS subject_id, k.name AS subject_name,
       x.id AS target_id, x.name AS target_name,
       r.reason AS reason, r.weight AS weight, r.patch AS patch, r.source AS source
ORDER BY r.weight DESC, x.name
LIMIT $limit
"""

# X 的搭档（出边：官方「最佳搭档」区块记的是本英雄的搭档，故只取本英雄的出边）。
SYNERGY_BY_HERO: Final[str] = """
MATCH (k:Hero {id: $hero_id})-[r:SYNERGIZES]->(x:Hero)
WHERE r.patch IN $patches
RETURN k.id AS subject_id, k.name AS subject_name,
       x.id AS target_id, x.name AS target_name,
       r.reason AS reason, r.weight AS weight, r.patch AS patch, r.source AS source
ORDER BY r.weight DESC, x.name
LIMIT $limit
"""

# X 的出装（两套，用 build_index 区分；order 为 1~6 的装备顺序）。
ITEMS_BY_HERO: Final[str] = """
MATCH (h:Hero {id: $hero_id})-[r:RECOMMENDS_ITEM]->(i:Item)
WHERE r.patch IN $patches
RETURN h.id AS hero_id, h.name AS hero_name,
       r.build_index AS build_index, r.order AS order,
       i.id AS item_id, i.name AS item_name,
       r.patch AS patch, r.source AS source
ORDER BY r.build_index, r.order
LIMIT $limit
"""

# X 的铭文搭配（一套 3 个：红/蓝/绿各一）。
INSCRIPTIONS_BY_HERO: Final[str] = """
MATCH (h:Hero {id: $hero_id})-[r:RECOMMENDS_INSCRIPTION]->(n:Inscription)
WHERE r.patch IN $patches
RETURN h.id AS hero_id, h.name AS hero_name,
       r.build_index AS build_index, n.id AS inscription_id, n.name AS inscription_name,
       n.color AS color, n.level AS level,
       r.patch AS patch, r.source AS source
ORDER BY r.build_index, n.color
LIMIT $limit
"""

# 实体解析（按规范名或别名反查节点）。
HERO_BY_NAME: Final[str] = """
MATCH (h:Hero)
WHERE h.name = $name OR $name IN h.aliases
RETURN h.id AS id, h.name AS name, h.roles AS roles, h.patch AS patch, h.source AS source
LIMIT 1
"""

# 按分路列英雄（澄清反问用：给出候选让用户挑）。
HEROES_BY_ROLE: Final[str] = """
MATCH (h:Hero)
WHERE $role IN h.roles
RETURN h.id AS id, h.name AS name, h.roles AS roles, h.source AS source
ORDER BY h.name
LIMIT $limit
"""

# 模板名 -> Cypher 语句。键名与规格书 4.7 表格一致。
TEMPLATES: Final[dict[str, str]] = {
    "COUNTERS_BY_HERO": COUNTERS_BY_HERO,
    "COUNTERS_OF_HERO": COUNTERS_OF_HERO,
    "SYNERGY_BY_HERO": SYNERGY_BY_HERO,
    "ITEMS_BY_HERO": ITEMS_BY_HERO,
    "INSCRIPTIONS_BY_HERO": INSCRIPTIONS_BY_HERO,
    "HERO_BY_NAME": HERO_BY_NAME,
    "HEROES_BY_ROLE": HEROES_BY_ROLE,
}

# 意图 -> 模板（规格书 4.4 的「主路径」列）。MATCHUP 是混合意图，由 M3 编排层组合。
INTENT_TO_TEMPLATE: Final[dict[str, str]] = {
    "COUNTER_BY": "COUNTERS_BY_HERO",
    "COUNTER_OF": "COUNTERS_OF_HERO",
    "SYNERGY": "SYNERGY_BY_HERO",
    "ITEM_BUILD": "ITEMS_BY_HERO",
    "INSCRIPTION": "INSCRIPTIONS_BY_HERO",
}


def render(name: str) -> str:
    """取模板语句。名字不存在即抛错——避免静默路由到空查询。"""
    if name not in TEMPLATES:
        raise KeyError(f"未知 Cypher 模板：{name}")
    return TEMPLATES[name]
