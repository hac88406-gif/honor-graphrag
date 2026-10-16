"""语料切分的**唯一实现**（规格书 4.6：按语义段落切分，目标 300~500 字、重叠 100 字）。

为什么单独成模块：`scripts/init_chroma.py`（从 `data/guides/` 重建全库）与
`POST /api/docs/upload`（接口入库单篇）**必须用同一套切分**。若各写一套，同一篇文本
「重建出来的 chunk」与「接口写进去的 chunk」就会不同，检索结果随入库路径漂移 ——
这正是本项目反复踩的「同一件事两个口径」类问题，故这里只留一份实现，两边 import。

切分策略（非自定，来自 4.6）：**按语义段落切**（标题 / 列表项 / 段落为语义单元），
不按固定 token 硬切；单元超上限时按句末标点二次切分；打包超出上限时以尾部重叠续接，
保证跨 chunk 的语义不断裂。
"""
from __future__ import annotations

import re

# 切分参数（规格书 4.6：目标 300~500 字，重叠 100 字）
CHUNK_MAX = 500
CHUNK_MIN = 300
OVERLAP = 100


def split_atoms(body: str) -> list[str]:
    """把正文拆成语义单元：每个标题行、每个列表项（含其续行）各为一个单元，段落为多行单元。"""
    atoms: list[str] = []
    cur: list[str] = []

    def flush() -> None:
        text = "\n".join(cur).strip()
        if text:
            atoms.append(text)
        cur.clear()

    for raw in body.split("\n"):
        s = raw.strip()
        if not s:
            flush()
            continue
        if s.startswith("#") or s.startswith("- "):
            flush()
            cur.append(s)
        else:
            cur.append(s)
    flush()
    return atoms


def split_long(text: str) -> list[str]:
    """单个语义单元超过 CHUNK_MAX 时，按句末标点切成不超过 CHUNK_MAX 的片段。"""
    sentences = re.split(r"(?<=[。！？；])", text)
    pieces: list[str] = []
    buf = ""
    for sent in sentences:
        if not sent:
            continue
        if len(buf) + len(sent) <= CHUNK_MAX:
            buf += sent
        else:
            if buf:
                pieces.append(buf)
            buf = sent
    if buf:
        pieces.append(buf)
    return pieces


def pack(atoms: list[str]) -> list[str]:
    """把语义单元贪心打包成 chunk，超出上限时以尾部 OVERLAP 字重叠续接。"""
    chunks: list[str] = []
    cur = ""

    def emit() -> None:
        nonlocal cur
        if cur.strip():
            chunks.append(cur.strip())
        tail = cur[-OVERLAP:] if len(cur) > OVERLAP else cur
        cur = tail

    for atom in atoms:
        parts = split_long(atom) if len(atom) > CHUNK_MAX else [atom]
        for part in parts:
            if not cur.strip():
                cur = part
            elif len(cur) + 1 + len(part) <= CHUNK_MAX:
                cur += "\n" + part
            else:
                emit()
                cur = cur + "\n" + part if cur.strip() else part
    if cur.strip():
        chunks.append(cur.strip())
    return chunks


def split_document(body: str) -> list[str]:
    """正文 -> chunk 列表。**入库侧的唯一入口**，调用方不要再自行组合上面三个函数。"""
    return pack(split_atoms(body))
