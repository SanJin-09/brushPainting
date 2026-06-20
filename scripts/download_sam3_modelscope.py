#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "model_runtime"))

from model_runtime.modelscope_loader import download_sam3_snapshot


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="通过 ModelScope SDK 下载 SAM 3")
    parser.add_argument(
        "--model-id",
        default="facebook/sam3",
        help="ModelScope 模型 ID（默认: facebook/sam3）",
    )
    parser.add_argument(
        "--revision",
        default="master",
        help="ModelScope revision（默认: master）",
    )
    parser.add_argument(
        "--local-dir",
        default=str(ROOT / "runtime" / "models" / "sam3"),
        help="模型下载目录",
    )
    parser.add_argument(
        "--checkpoint-filename",
        default="sam3.pt",
        help="项目加载的 checkpoint 文件名（默认: sam3.pt）",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="下载完整模型仓库；默认仅下载项目推理所需的 checkpoint",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    checkpoint = download_sam3_snapshot(
        model_id=args.model_id,
        revision=args.revision,
        local_dir=args.local_dir,
        checkpoint_filename=args.checkpoint_filename,
        full_snapshot=args.full,
    )
    print(f"SAM 3 checkpoint 已就绪: {checkpoint}")


if __name__ == "__main__":
    main()
