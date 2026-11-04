"""Convert reviewed socked-foot binary masks into a YOLO segmentation dataset."""
from __future__ import annotations

import argparse
import random
import shutil
from pathlib import Path

import cv2
import yaml


def polygon_from_mask(mask_path: Path):
    mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
    if mask is None:
        raise ValueError(f"無法讀取遮罩：{mask_path}")
    height, width = mask.shape
    contours, _ = cv2.findContours((mask > 127).astype("uint8"), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    contour = max(contours, key=cv2.contourArea)
    if cv2.contourArea(contour) < 100:
        return None
    epsilon = max(1.0, 0.002 * cv2.arcLength(contour, True))
    polygon = cv2.approxPolyDP(contour, epsilon, True).reshape(-1, 2)
    if len(polygon) < 3:
        return None
    return [(float(x) / width, float(y) / height) for x, y in polygon]


def pairs(mask_root: Path, raw_root: Path):
    records = []
    for mask in sorted(mask_root.glob("*/*.png")):
        image = raw_root / mask.parent.name / mask.name
        if not image.is_file():
            raise ValueError(f"找不到對應原圖：{image}")
        records.append((image, mask))
    if not records:
        raise ValueError(f"找不到遮罩 PNG：{mask_root}")
    return records


def write_sample(image: Path, mask: Path, target: Path):
    polygon = polygon_from_mask(mask)
    # Every capture batch restarts at socked_foot_0001.png.  Keep the batch
    # name in the exported filename so different people/socks never overwrite
    # one another during the train/validation split.
    unique_stem = f"{image.parent.name}__{image.stem}"
    image_out = target / "images" / f"{unique_stem}{image.suffix}"
    label_out = target / "labels" / f"{unique_stem}.txt"
    image_out.parent.mkdir(parents=True, exist_ok=True)
    label_out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(image, image_out)
    if polygon is None:
        label_out.write_text("", encoding="utf-8")
        return False
    coords = " ".join(f"{value:.6f}" for point in polygon for value in point)
    label_out.write_text(f"0 {coords}\n", encoding="utf-8")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--masks", type=Path, default=Path("foot_dataset/masks_sam"))
    parser.add_argument("--raw", type=Path, default=Path("foot_dataset/raw/socked_foot"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--val-fraction", type=float, default=.2)
    parser.add_argument("--seed", type=int, default=20261030)
    args = parser.parse_args()
    if not 0 < args.val_fraction < .5:
        parser.error("--val-fraction 必須介於 0 與 0.5 之間")
    records = pairs(args.masks, args.raw)
    if args.output.exists():
        parser.error(f"輸出資料夾已存在，為避免覆寫請換一個：{args.output}")
    random.Random(args.seed).shuffle(records)
    val_count = max(1, round(len(records) * args.val_fraction))
    splits = {"train": records[val_count:], "val": records[:val_count]}
    counts = {}
    for split, samples in splits.items():
        positives = sum(write_sample(image, mask, args.output / split) for image, mask in samples)
        counts[split] = {"images": len(samples), "positive_masks": positives, "empty_masks": len(samples) - positives}
    config = {"path": str(args.output.resolve()).replace("\\", "/"),
              "train": "train/images", "val": "val/images", "names": {0: "socked_foot"}}
    (args.output / "data.yaml").write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print({"output": str(args.output.resolve()), **counts})


if __name__ == "__main__":
    main()
