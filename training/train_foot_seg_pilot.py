"""Run the reproducible pilot fine-tune for socked-foot segmentation."""
from __future__ import annotations

import argparse
from pathlib import Path

from ultralytics import YOLO


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--weights", type=Path, default=Path("yolov8n-seg.pt"))
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--project", type=Path, default=Path("output/foot_seg"))
    parser.add_argument("--name", default="pilot_90_cpu")
    parser.add_argument("--rotation-aug", action="store_true",
                        help="Use right-angle-friendly rotation, flip, scale and perspective augmentation")
    args = parser.parse_args()
    if not args.data.is_file():
        parser.error(f"找不到資料設定：{args.data}")
    if not args.weights.is_file():
        parser.error(f"找不到預訓練權重：{args.weights}")
    options = dict(
        data=str(args.data), epochs=args.epochs, imgsz=640, batch=4,
        device="cpu", workers=0, project=str(args.project), name=args.name,
        patience=10, seed=20261030, deterministic=True, verbose=True,
    )
    if args.rotation_aug:
        # Existing captures become additional plausible camera placements; the
        # corresponding masks are transformed together by Ultralytics.
        options.update(degrees=180.0, fliplr=.5, flipud=.5, translate=.12,
                       scale=.35, perspective=.0005, mosaic=.25)
    YOLO(str(args.weights)).train(**options)


if __name__ == "__main__":
    main()
