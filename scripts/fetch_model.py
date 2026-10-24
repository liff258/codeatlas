"""下载本地 embedding 模型。

为什么走 ModelScope 而不是 HuggingFace：
    huggingface.co 和 hf-mirror.com 在当前网络环境下都不可达（连接直接失败），
    modelscope.cn 可达且实测 3.3 MB/s。这是「10 分钟复现」的现实约束。

为什么用 bge-m3 而不是 small 版：
    contracts/db-schema.sql 把向量维度锁死在 vector(1024)，bge-m3 正好是 1024 维，
    改 schema 会牵连 HNSW 索引和配置。而且 bge-m3 是 XLM-RoBERTa 底座，
    中文语义明显强于 small 版。代价是 2.2GB 下载和 CPU 推理慢一些，可接受。

用法：
    python scripts/fetch_model.py                 # 下载到 data/models/bge-m3
    python scripts/fetch_model.py --model BAAI/bge-small-zh-v1.5
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "models"

API = "https://www.modelscope.cn/api/v1/models/{model}/repo/files?Revision=master"
FILE_API = (
    "https://www.modelscope.cn/api/v1/models/{model}/repo"
    "?FilePath={path}&Revision=master"
)

# 用不到的大文件：ColBERT 多头向量（我们只用 CLS pooling）、稀疏向量、示例图、占位 onnx
SKIP_SUFFIX = (".jpg", ".jpeg", ".png", ".gif", ".md")
SKIP_EXACT = {"colbert_linear.pt", "sparse_linear.pt"}


def _get(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "codeatlas-fetch/1.0"})
    # 显式绕过失效的 HTTP 代理环境变量
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as r:
        return r.read()


def list_files(model: str) -> list[str]:
    import json

    data = json.loads(_get(API.format(model=model)))
    files = data.get("Data", {}).get("Files") or data.get("Data") or []
    if isinstance(files, dict):
        files = [files]
    return [f["Path"] for f in files if isinstance(f, dict) and f.get("Path")]


def download(model: str, dest: Path) -> int:
    paths = list_files(model)
    if not paths:
        print(f"✗ 列不出 {model} 的文件")
        return 1

    wanted = [
        p
        for p in paths
        if p.lower().endswith(SKIP_SUFFIX) is False
        and p.split("/")[-1] not in SKIP_EXACT
        and not p.startswith(("onnx/", "imgs/"))
    ]

    total_bytes = 0
    for i, path in enumerate(wanted, 1):
        target = dest / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.stat().st_size > 0:
            print(f"  [{i}/{len(wanted)}] 已存在，跳过 {path}")
            total_bytes += target.stat().st_size
            continue

        url = FILE_API.format(model=model, path=urllib.parse.quote(path))
        t0 = time.time()
        try:
            data = _get(url, timeout=600)
        except urllib.error.HTTPError as e:
            # 404 说明这一项是目录（ModelScope 的文件列表把目录也列出来了），跳过即可
            if e.code == 404:
                print(f"  [{i}/{len(wanted)}] 跳过（目录）{path}")
                continue
            print(f"  [{i}/{len(wanted)}] ✗ {path}: {e}")
            return 1
        except Exception as e:  # noqa: BLE001
            print(f"  [{i}/{len(wanted)}] ✗ {path}: {e}")
            return 1

        target.write_bytes(data)
        mb = len(data) / 1048576
        total_bytes += len(data)
        print(f"  [{i}/{len(wanted)}] {mb:8.1f} MB  {path}  ({time.time()-t0:.0f}s)")

    print(f"\n✓ {model} 下载完成：{total_bytes/1048576:.0f} MB → {dest}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="BAAI/bge-m3")
    args = ap.parse_args()

    dest = CACHE / args.model.split("/")[-1]
    dest.mkdir(parents=True, exist_ok=True)
    print(f"模型：{args.model}\n目标：{dest}\n")
    return download(args.model, dest)


if __name__ == "__main__":
    sys.exit(main())
