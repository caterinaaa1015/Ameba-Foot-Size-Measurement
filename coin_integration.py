"""Small, testable helpers for the live NT$1/NT$5 coin detector overlay."""
from __future__ import annotations

import re

import cv2


def denomination_from_label(label):
    """Return an integer denomination for labels such as ``coin_5``."""
    match = re.fullmatch(r"coin_(\d+)", str(label))
    return int(match.group(1)) if match else None


def detect_coins(model, image, confidence=0.5, imgsz=416):
    """Run YOLO and return JSON-safe, confidence-sorted detections."""
    result = model.predict(image, imgsz=imgsz, conf=confidence, device="cpu", verbose=False)[0]
    names = result.names
    boxes = result.boxes.xyxy.cpu().numpy()
    classes = result.boxes.cls.cpu().numpy().astype(int)
    scores = result.boxes.conf.cpu().numpy()
    detections = []
    for box, class_id, score in zip(boxes, classes, scores):
        label = str(names[int(class_id)])
        detections.append({
            "label": label,
            "denomination": denomination_from_label(label),
            "confidence": float(score),
            "xyxy": [float(value) for value in box],
        })
    return sorted(detections, key=lambda item: item["confidence"], reverse=True)


def score_known_coin(denomination, detections):
    """Score one saved frame against its user-supplied denomination.

    The collector captures a single known coin, so the strongest prediction is
    the classification decision. Extra boxes are retained as a separate count.
    """
    if not detections:
        return "missed", 0
    status = "correct" if detections[0]["denomination"] == int(denomination) else "wrong_class"
    return status, max(0, len(detections) - 1)


def render_detections(image, detections):
    """Render a display-only overlay; the stored capture remains unchanged."""
    rendered = image.copy()
    for detection in detections:
        x1, y1, x2, y2 = (round(value) for value in detection["xyxy"])
        label = detection["label"].replace("coin_", "NT$")
        text = f"{label} {detection['confidence']:.2f}"
        cv2.rectangle(rendered, (x1, y1), (x2, y2), (255, 90, 0), 3)
        cv2.putText(rendered, text, (x1, max(24, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX,
                    0.7, (255, 90, 0), 2, cv2.LINE_AA)
    return rendered
