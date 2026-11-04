"""Train a two-class detector for the deployed NT$10 / NT$50 measurement setup."""
from __future__ import annotations

import os
from pathlib import Path


BASE = Path(__file__).resolve().parent.parent
os.environ.setdefault("YOLO_CONFIG_DIR", str(BASE / ".build" / "yolo_config"))
os.environ.setdefault("YOLO_AUTOINSTALL", "false")


def main() -> None:
    from ultralytics import YOLO, settings

    settings.update({"sync": False})
    model = YOLO(str(BASE / "yolov8n.pt"))
    model.train(
        data=str(BASE / "coin_dataset" / "yolo_10_50_fixed" / "data.yaml"),
        epochs=40,
        imgsz=640,
        batch=8,
        device="cpu",
        workers=0,
        optimizer="AdamW",
        lr0=0.001,
        patience=15,
        seed=42,
        deterministic=True,
        freeze=0,
        degrees=35,
        translate=0.12,
        scale=0.45,
        perspective=0.0008,
        hsv_h=0.015,
        hsv_s=0.45,
        hsv_v=0.35,
        mosaic=0.6,
        close_mosaic=6,
        fliplr=0.5,
        amp=False,
        cache=False,
        project=str(BASE / "output" / "coin_yolo"),
        name="train_10_50_full",
        exist_ok=False,
        save=True,
        plots=True,
    )


if __name__ == "__main__":
    main()
