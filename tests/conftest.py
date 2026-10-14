"""pytest 全局配置：把项目根与 scripts/ 加入 sys.path。

测试需要直接 import scripts/ 下的脚本模块（init_graph / fetch_official 等），
而 scripts 不是包，故把该目录也加入路径。
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

for _p in (PROJECT_ROOT, PROJECT_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
