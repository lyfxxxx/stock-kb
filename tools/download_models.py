"""从 Hugging Face 下载模型，支持镜像、多线程加速与断点续传。

用法：
    python tools/download_models.py --model BAAI/bge-m3
    python tools/download_models.py --model BAAI/bge-m3 --mirror https://hf-mirror.com
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="下载 Hugging Face 模型（支持镜像/加速/续传）")
    parser.add_argument("--model", required=True, help="HF 模型 ID，如 BAAI/bge-m3")
    parser.add_argument(
        "--cache-dir",
        default=str(Path(__file__).resolve().parent.parent / "models"),
        help="模型缓存目录",
    )
    parser.add_argument(
        "--mirror",
        default=os.environ.get("HF_ENDPOINT", "https://hf-mirror.com"),
        help="HF 镜像地址，默认 https://hf-mirror.com",
    )
    parser.add_argument("--no-accelerate", action="store_true", help="禁用 hf_transfer 多线程加速")
    args = parser.parse_args()

    if not args.no_accelerate:
        try:
            import hf_transfer  # noqa: F401

            os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "1"
            print("[info] 已启用 hf_transfer 多线程加速")
        except ImportError:
            print("[warn] 未安装 hf_transfer，可执行: pip install hf_transfer")

    os.environ["HF_ENDPOINT"] = args.mirror
    Path(args.cache_dir).mkdir(parents=True, exist_ok=True)

    from huggingface_hub import snapshot_download

    print(f"[info] 下载 {args.model} -> {args.cache_dir} (mirror={args.mirror})")
    path = snapshot_download(args.model, cache_dir=args.cache_dir)
    print(f"[ok] {path}")


if __name__ == "__main__":
    main()
