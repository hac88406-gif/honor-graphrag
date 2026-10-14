"""实体链接层单测（规格书 4.3 / M2 验收「实体链接单测通过（含 20+ 别名/错别字用例）」）。

覆盖维度（对齐规格书 4.3 第 2 级「别名表匹配」必须覆盖的四类 + 归一化 + 模糊匹配）：
  - 精确匹配（规范名）
  - 简称 / 俗称
  - 同音错字
  - 昵称 / 梗
  - 位置 / 分路口语（含 ASCII 缩写 AD / ADC）
  - 繁体 / 全半角归一
  - 模糊匹配（拼音音节编辑距离，仅前两级全失败时启用）

全部为确定性断言，不调用大模型、不依赖 Neo4j / Chroma，可离线跑。
"""
from __future__ import annotations

import pytest

from app.retrieval.entity_linking import link, link_heroes

# (用户原文, 期望规范名, 期望 entity_type, 期望 method)
CASES: list[tuple[str, str, str, str]] = [
    # --- 精确匹配：规范名 ---
    ("貂蝉", "貂蝉", "hero", "exact"),
    ("兰陵王", "兰陵王", "hero", "exact"),
    ("鲁班七号", "鲁班七号", "hero", "exact"),
    ("东皇太一", "东皇太一", "hero", "exact"),
    ("孙悟空", "孙悟空", "hero", "exact"),
    ("百里守约", "百里守约", "hero", "exact"),
    ("铠", "铠", "hero", "exact"),
    # --- 别名表：简称 / 俗称 ---
    ("东皇", "东皇太一", "hero", "alias"),
    ("太一", "东皇太一", "hero", "alias"),
    ("猴子", "孙悟空", "hero", "alias"),
    ("鲁班", "鲁班七号", "hero", "alias"),
    ("大小姐", "孙尚香", "hero", "alias"),
    ("奶妈", "蔡文姬", "hero", "alias"),
    ("守约", "百里守约", "hero", "alias"),
    ("玄策", "百里玄策", "hero", "alias"),
    # --- 别名表：同音错字 ---
    ("凯", "铠", "hero", "alias"),
    ("貂禅", "貂蝉", "hero", "alias"),
    ("貂婵", "貂蝉", "hero", "alias"),
    ("刁蝉", "貂蝉", "hero", "alias"),
    ("兰凌王", "兰陵王", "hero", "alias"),
    ("蓝陵王", "兰陵王", "hero", "alias"),
    ("后裔", "后羿", "hero", "alias"),
    ("后弈", "后羿", "hero", "alias"),
    ("安其拉", "安琪拉", "hero", "alias"),
    ("大桥", "大乔", "hero", "alias"),
    # --- 别名表：昵称 / 梗 ---
    ("铠爹", "铠", "hero", "alias"),
    ("铠皇", "铠", "hero", "alias"),
    ("凯爹", "铠", "hero", "alias"),
    ("猴哥", "孙悟空", "hero", "alias"),
    ("小鹿", "瑶", "hero", "alias"),
    ("六耳", "心魔六耳", "hero", "alias"),
    ("小短腿", "鲁班七号", "hero", "alias"),
    ("诗仙", "李白", "hero", "alias"),
    # --- 分路口语（含 ASCII 缩写） ---
    ("射手", "发育路", "role", "alias"),
    ("AD", "发育路", "role", "alias"),
    ("adc", "发育路", "role", "alias"),
    ("打野", "打野", "role", "alias"),
    ("中单", "中路", "role", "alias"),
    ("辅助", "游走", "role", "alias"),
    ("上单", "对抗路", "role", "alias"),
    ("边路", "对抗路", "role", "alias"),
    # --- 繁体 / 全半角归一 ---
    ("鎧", "铠", "hero", "exact"),
    ("蘭陵王", "兰陵王", "hero", "exact"),
    ("貂蟬", "貂蝉", "hero", "exact"),
    ("鲁班７号", "鲁班七号", "hero", "alias"),
    ("东皇太１", "东皇太一", "hero", "alias"),
    # --- 模糊匹配（拼音音节编辑距离） ---
    ("李柏", "李白", "hero", "fuzzy"),
    ("后亿", "后羿", "hero", "fuzzy"),
    ("兰菱王", "兰陵王", "hero", "fuzzy"),
    ("廉坡", "廉颇", "hero", "fuzzy"),
    ("貂蚕", "貂蝉", "hero", "fuzzy"),
]


def test_case_count_meets_acceptance():
    """规格书 M2 验收：别名/错别字用例 ≥ 20。"""
    assert len(CASES) >= 20, f"用例数 {len(CASES)} 少于验收要求的 20"


@pytest.mark.parametrize("text, name, etype, method", CASES, ids=[c[0] for c in CASES])
def test_link_single_entity(text, name, etype, method):
    """每个用例都应链接到期望规范实体，且 method 与期望一致。"""
    res = link(text)
    matched = [
        e for e in res.entities if e.canonical_name == name and e.entity_type == etype
    ]
    assert matched, f"{text!r} 未链接到 {name}（返回：{[(e.canonical_name, e.method) for e in res.entities]}）"
    assert matched[0].method == method, f"{text!r} 期望 method={method}，实际 {matched[0].method}"
    assert matched[0].confidence > 0.0
    assert matched[0].raw  # raw 回填用户原文（归一化后）


def test_link_exact_confidence_is_one_alias_is_090():
    """精确匹配置信度 1.0；别名表命中 0.9（区分两级，供 4.9 置信度判定使用）。"""
    assert link("貂蝉").entities[0].confidence == 1.0
    assert link("东皇").entities[0].confidence == 0.9


def test_link_multi_entity_in_one_sentence():
    """一句话含多个英雄：应一次抽出全部（最长匹配扫描）。"""
    names = {e.canonical_name for e in link("亚瑟和兰陵王谁厉害").entities}
    assert {"亚瑟", "兰陵王"} <= names

    names2 = {e.canonical_name for e in link("铠和吕布谁厉害").entities}
    assert {"铠", "吕布"} <= names2


def test_link_hero_plus_role():
    """英雄 + 分路口语混合：两类实体都能识别。"""
    res = link("铠适合打野吗")
    types = {e.entity_type for e in res.entities}
    assert "hero" in types and "role" in types
    assert "铠" in {e.canonical_name for e in res.entities}


def test_link_heroes_filters_out_roles():
    """link_heroes 只保留英雄类实体（意图路由/模板查询用）。"""
    assert link_heroes("射手怎么出装") == []
    heroes = link_heroes("铠和吕布谁厉害")
    assert {e.canonical_name for e in heroes} == {"铠", "吕布"}


def test_link_unrecognized_has_no_entities():
    """域外问题不应链接出任何实体（交给意图层判 OUT_OF_SCOPE）。"""
    assert link("今天天气怎么样").entities == []


def test_link_empty_input():
    res = link("   ")
    assert res.entities == [] and res.unrecognized == []
