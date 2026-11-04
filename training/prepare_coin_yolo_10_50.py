"""Build a two-class NT$10 / NT$50 dataset from the reviewed fixed-camera labels.

The source photos and original three-class dataset are never changed.  This
creates a separate dataset with class ids remapped to 0=coin_10 and 1=coin_50.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path


BASE = Path(__file__).resolve().parent.parent
SOURCE = BASE / "coin_dataset" / "yolo_1_10_50_fixed"
TARGET = BASE / "coin_dataset" / "yolo_10_50_fixed"
CLASS_MAP = {1: 0, 2: 1}
NAMES = {0: "coin_10", 1: "coin_50"}


def remap_label(source: Path, target: Path) -> bool:
    lines = []
    for line in source.read_text(encoding="ascii").splitlines():
        parts = line.split()
        if not parts or int(parts[0]) not in CLASS_MAP:
            continue
        parts[0] = str(CLASS_MAP[int(parts[0])])
        lines.append(" ".join(parts))
    if not lines:
        return False
    target.write_text("\n".join(lines) + "\n", encoding="ascii")
    return True


def main() -> None:
    if TARGET.exists():
        shutil.rmtree(TARGET)
    counts = {name: 0 for name in NAMES.values()}
    for split in ("train", "val"):
        image_dir = SOURCE / "images" / split
        label_dir = SOURCE / "labels" / split
        out_images = TARGET / "images" / split
        out_labels = TARGET / "labels" / split
        out_images.mkdir(parents=True, exist_ok=True)
        out_labels.mkdir(parents=True, exist_ok=True)
        for label in sorted(label_dir.glob("*.txt")):
            remapped = out_labels / label.name
            if not remap_label(label, remapped):
                continue
            image = image_dir / f"{label.stem}.png"
            shutil.copy2(image, out_images / image.name)
            cls = int(remapped.read_text(encoding="ascii").split()[0])
            counts[NAMES[cls]] += 1
    data = "\n".join((
        f"path: {TARGET.as_posix()}",
        "train: images/train",
        "val: images/val",
        "names:",
        "  0: coin_10",
        "  1: coin_50",
        "",
    ))
    (TARGET / "data.yaml").write_text(data, encoding="utf-8")
    (TARGET / "dataset_report.json").write_text(json.dumps(counts, indent=2), encoding="utf-8")
    print(json.dumps(counts, ensure_ascii=False))


if __name__ == "__main__":
    main()
