"""下载 Embedding 模型（规格书 1.3 选型：BAAI/bge-large-zh-v1.5，本地 CPU 可跑）。

为什么不走 HuggingFace：实测 hf-mirror.com 对该模型的静态资源返回 403/极慢（<10KB/s），
而 ModelScope（魔搭，国内镜像）实测约 1.0MB/s。模型本身仍是规格书裁定的 bge-large-zh-v1.5，
此处仅替换**下载来源**，不改选型。见 DECISIONS.md（M1a 数据层）。

落盘位置：models/bge-large-zh-v1.5/，供 sentence-transformers 直接按本地目录加载。
可重跑：已存在且字节数一致的 file 跳过；不一致则重下。
"""
from __future__ import annotations

import sys
import time
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TARGET_DIR = PROJECT_ROOT / "models" / "bge-large-zh-v1.5"

REPO = "BAAI/bge-large-zh-v1.5"
BASE = f"https://modelscope.cn/models/{REPO}/resolve/master/"

# sentence-transformers 加载所需的最小文件集（含 Pooling 配置，缺它只会得到未池化向量）
FILES = [
    "config.json",
    "config_sentence_transformers.json",
    "modules.json",
    "sentence_bert_config.json",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.txt",
    "1_Pooling/config.json",
    "pytorch_model.bin",
]


def human(n: int) -> str:
    return f"{n / 1024 / 1024:.1f}MB"


def fetch(rel: str) -> None:
    dst = TARGET_DIR / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    url = BASE + rel
    req = urllib.request.Request(url, headers={"User-Agent": "honor-graphrag-fetch/1.0"})

    # 断点续跑：先探 Content-Length，本地文件大小一致则跳过
    with urllib.request.urlopen(req, timeout=30) as r:
        total = int(r.headers.get("Content-Length") or 0)
        if dst.exists() and dst.stat().st_size == total and total > 0:
            print(f"[skip] {rel} 已存在（{human(total)}）")
            return
        t0 = time.time()
        got = 0
        tmp = dst.with_suffix(dst.suffix + ".part")
        with tmp.open("wb") as f:
            while True:
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                if total and got % (1 << 20) < (1 << 16):  # 每 ~1MB 打印一次
                    dt = time.time() - t0
                    pct = got / total * 100
                    print(f"  {rel}: {pct:5.1f}% {human(got)}/{human(total)} "
                          f"{got / 1024 / 1024 / max(dt, 0.001):.2f}MB/s", flush=True)
        tmp.replace(dst)
    print(f"[done] {rel} {human(dst.stat().st_size)}")


def main() -> int:
    print(f"[dl] 目标目录：{TARGET_DIR}")
    print(f"[dl] 来源：ModelScope {REPO}（规格书 1.3 选型不变，仅换下载源）")
    for rel in FILES:
        try:
            fetch(rel)
        except Exception as e:  # 失败即报错，不静默
            print(f"[ERR] {rel} 下载失败：{type(e).__name__} {e}", file=sys.stderr)
            return 1
    print("[dl] 全部文件就绪")
    return 0


if __name__ == "__main__":
    sys.exit(main())
