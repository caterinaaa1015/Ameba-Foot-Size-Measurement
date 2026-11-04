"""AI helpers for the combined coin + socked-foot measurement interface.

The segmentation model identifies the socked-foot region.  It does *not*
identify anatomical heel/toe keypoints, so final length still requires the
operator to click heel and longest toe on a frozen frame.
"""
from __future__ import annotations

import cv2
import numpy as np


# Diameters in millimetres for the denominations supported by the local coin
# model.  A denomination prediction chooses this known reference diameter;
# the user still marks a true edge-to-edge diameter for the scale.
COIN_DIAMETERS_MM = {1: 20.0, 10: 26.0, 50: 28.0}


def _restore_rotation(polygon, rotation, original_shape):
    """Map a right-angle-rotated polygon back to original-image pixels."""
    height, width = original_shape[:2]
    points = np.asarray(polygon, dtype=np.float32)
    x, y = points[:, 0], points[:, 1]
    if rotation == "cw":
        restored = np.column_stack((y, height - 1 - x))
    elif rotation == "180":
        restored = np.column_stack((width - 1 - x, height - 1 - y))
    elif rotation == "ccw":
        restored = np.column_stack((width - 1 - y, x))
    else:
        restored = points
    restored[:, 0] = np.clip(restored[:, 0], 0, width - 1)
    restored[:, 1] = np.clip(restored[:, 1], 0, height - 1)
    return restored


def _with_original_coordinates(detections, rotation, original_shape):
    restored = []
    for detection in detections:
        polygon = _restore_rotation(detection["polygon"], rotation, original_shape)
        x1, y1 = polygon.min(axis=0)
        x2, y2 = polygon.max(axis=0)
        restored.append({"confidence": detection["confidence"],
                         "xyxy": [float(x1), float(y1), float(x2), float(y2)],
                         "polygon": polygon.tolist(),
                         "rotation": rotation})
    return restored


def detect_socked_feet(model, image, confidence=.25, imgsz=640):
    """Return one best original-image mask, retrying uncommon foot rotations.

    Training data is often dominated by one placement direction.  If that
    primary view is weak, run three right-angle views and map their masks back
    before choosing the strongest result.  This improves orientation tolerance
    without pretending that a new model was trained on unseen viewpoints.
    """
    def predict(frame):
        result = model.predict(frame, imgsz=imgsz, conf=confidence, device="cpu", verbose=False)[0]
        if result.boxes is None or result.masks is None:
            return []
        boxes = result.boxes.xyxy.cpu().numpy()
        scores = result.boxes.conf.cpu().numpy()
        polygons = result.masks.xy
        detections = []
        for box, score, polygon in zip(boxes, scores, polygons):
            polygon = np.asarray(polygon, dtype=np.float32)
            if len(polygon) >= 3:
                detections.append({"confidence": float(score),
                                   "xyxy": [float(value) for value in box],
                                   "polygon": polygon.tolist()})
        return detections

    detections = _with_original_coordinates(predict(image), "none", image.shape)
    if detections and max(item["confidence"] for item in detections) >= .55:
        return [max(detections, key=lambda item: item["confidence"])]

    rotations = (("cw", cv2.ROTATE_90_CLOCKWISE), ("180", cv2.ROTATE_180),
                 ("ccw", cv2.ROTATE_90_COUNTERCLOCKWISE))
    for name, code in rotations:
        detections.extend(_with_original_coordinates(predict(cv2.rotate(image, code)), name, image.shape))
    return [max(detections, key=lambda item: item["confidence"])] if detections else []


def best_known_coin(detections):
    """Use the strongest recognized supported denomination, if available."""
    for detection in detections:
        denomination = detection.get("denomination")
        if denomination in COIN_DIAMETERS_MM:
            return detection
    return None


def render_combined_detections(image, coin_detections, foot_detections):
    """Render display-only overlays without mutating the camera frame."""
    output = image.copy()
    overlay = output.copy()
    for detection in foot_detections:
        polygon = np.round(np.asarray(detection["polygon"])).astype(np.int32).reshape(-1, 1, 2)
        cv2.fillPoly(overlay, [polygon], (80, 205, 75))
        cv2.polylines(output, [polygon], True, (50, 230, 50), 2)
        x1, y1, x2, y2 = (round(value) for value in detection["xyxy"])
        cv2.rectangle(output, (x1, y1), (x2, y2), (50, 230, 50), 2)
        cv2.putText(output, f"socked foot {detection['confidence']:.2f}", (x1, max(25, y1 - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, .65, (50, 230, 50), 2, cv2.LINE_AA)
    output = cv2.addWeighted(overlay, .32, output, .68, 0)
    for detection in coin_detections:
        x1, y1, x2, y2 = (round(value) for value in detection["xyxy"])
        denomination = detection.get("denomination")
        text = f"NT${denomination} {detection['confidence']:.2f}" if denomination else "coin"
        cv2.rectangle(output, (x1, y1), (x2, y2), (255, 165, 0), 3)
        cv2.putText(output, text, (x1, max(25, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX,
                    .7, (255, 165, 0), 2, cv2.LINE_AA)
    return output


def rasterize_mask(image_shape, detection):
    """Make a full-size binary mask for saving alongside a frozen capture."""
    mask = np.zeros(image_shape[:2], dtype=np.uint8)
    polygon = np.round(np.asarray(detection["polygon"])).astype(np.int32).reshape(-1, 1, 2)
    cv2.fillPoly(mask, [polygon], 255)
    return mask
