"""补丁 P1 新增端点的共享契约口径（错误响应形状 / patches 校验 / 英雄消歧）。

**为什么单独一个模块、而不是在两个 router 里各写一份**：P1-1 与 P1-2 都要校验 `patches`、
都要把「英雄名 -> 唯一英雄」的消歧失败转成 404、错误响应形状也必须一致。若各写一份，
两处必然各自漂移 —— 这正是本项目反复踩的「同一件事两个口径」。故这三件事收敛在此，
`app/api/graph.py` 与 `app/api/retrieval.py` 只做各自的字段校验与调用。

错误响应形状（P1 §1 通用约定）：`{"error": "<机器可读码>", "detail": "<人类可读说明>"}`，
需要时追加结构化字段（如 404 的 `candidates`）。

**与既有 `/api/docs/upload` 的差异是有意的**：后者沿用 FastAPI 默认的 `{"detail": ...}`，
而 P1 §2-1 要求「不得修改既有端点的既有行为」，所以**不改它**；新端点一律用本模块的
`{error, detail}`。差异已记入 DECISIONS.md，避免后来者以为漏改。

错误码分工（沿用项目既有口径 + P1 §1）：
  - `422` = 请求体**形状/类型**不合法（FastAPI 对 `BaseModel` 的标准行为，如 weight 传了字符串）；
  - `400` = 字段**取值**不合法（relation 非枚举 / limit 越界 / patches 格式错 / patch 越窗 …）；
  - `404` = 找不到（英雄无法消歧 / 节点不存在）；
  - `500` = 写入成功但回读不到（P1 §5-2 的静默失败：请求本身没错，是内部状态与预期不一致）；
  - `503` = 依赖不可用（Neo4j / Chroma）。
"""
from __future__ import annotations

import re
from typing import Final

from fastapi.responses import JSONResponse

from app.retrieval.entity_linking import link_heroes
from app.schemas.entity import LinkedEntity

# 版本形如 YYYY-MM（与 app/api/docs.py 的 PATCH_RE 同口径）
PATCH_RE: Final[re.Pattern[str]] = re.compile(r"^\d{4}-\d{2}$")
# ename：数字字符串（英雄在图谱中的规范 ID）
ID_RE: Final[re.Pattern[str]] = re.compile(r"^\d+$")


class ContractError(Exception):
    """契约级错误（400 / 404 / 503）的统一载体。

    校验放在端点体外、用异常往外抛，是为了让「校验」与「主流程」分开：
    同一个校验（如 patches）会出现在多个端点，异常比层层传返回值更干净。
    """
    def __init__(self, response: JSONResponse) -> None:
        super().__init__("contract error")
        self.response = response


def err(status: int, code: str, detail: str, **extra) -> JSONResponse:
    """构造 `{error, detail}` 形状的错误响应（P1 §1 通用约定）。"""
    return JSONResponse(status_code=status, content={"error": code, "detail": detail, **extra})


def bad(code: str, detail: str) -> ContractError:
    return ContractError(err(400, code, detail))


def not_found(code: str, detail: str, **extra) -> ContractError:
    return ContractError(err(404, code, detail, **extra))


def unavailable(code: str, detail: str) -> ContractError:
    return ContractError(err(503, code, detail))


def server_error(code: str, detail: str) -> ContractError:
    """500：请求合法但内部状态与预期不一致（P1-3 写入成功却回读不到）。

    与 400/404 的区别必须守住：那两个是「调用方给的东西有问题」，这个是
    「我们答应了却没做到」。把它混成 400 会让调用方去改一个本来就对的请求。
    """
    return ContractError(err(500, code, detail))


def validate_patches(patches: list[str] | None) -> list[str] | None:
    """校验 patches：None 表示「用 config 默认窗口」，给了就必须是非空 YYYY-MM 数组。"""
    if patches is None:
        return None
    if not patches or not all(isinstance(p, str) and PATCH_RE.match(p) for p in patches):
        raise bad("patches_invalid", "patches 必须是非空的 YYYY-MM 字符串数组，如 [\"2026-10\"]")
    return list(patches)


def validate_int_range(value: int | None, lo: int, hi: int, field: str) -> int | None:
    """区间校验：越界一律 400，**不做静默截断**（P1 §1：截断会让调用方以为参数生效了）。"""
    if value is None:
        return None
    if not (lo <= value <= hi):
        raise bad(
            f"{field}_out_of_range",
            f"{field} 必须在 {lo}~{hi} 之间，收到：{value}（越界不静默截断）",
        )
    return value


def link_one_hero(name: str) -> LinkedEntity:
    """把英雄名消歧为**唯一**英雄，走 `entity_linking.link_heroes`（P1 §2-2 强制项）。

    无法消歧（0 个或 >1 个候选）一律 404 并带上 `candidates`，供调用方澄清 ——
    「猜一个最像的」正是本项目在防的静默错误。
    """
    candidates = [e for e in link_heroes(name) if e.canonical_id]
    if len(candidates) == 1:
        return candidates[0]
    dump = [e.model_dump() for e in candidates]
    if not candidates:
        detail = f"未能把 {name!r} 识别为任何英雄（别名表与模糊匹配均未命中）"
    else:
        names = " / ".join(f"{e.canonical_name}({e.canonical_id})" for e in candidates)
        detail = f"{name!r} 对应多个英雄，无法消歧：{names}"
    raise not_found("hero_not_found", detail, candidates=dump)
