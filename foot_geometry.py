"""Uncalibrated top-view NT$10 coin scale experiment, not a shoe-size classifier."""
from __future__ import annotations

from pathlib import Path
import math

import cv2
import numpy as np

COIN_DIAMETER_MM = 26.0
MIN_COIN_PIXELS = 30.0


def read_image(path):
    data = np.frombuffer(Path(path).read_bytes(), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("無法解碼照片，請選擇 JPEG 或 PNG。")
    return image


def write_png(path, image):
    success, encoded = cv2.imencode(".png", image)
    if not success:
        raise ValueError("PNG 編碼失敗")
    Path(path).write_bytes(encoded.tobytes())


def _point(point, image):
    x, y = map(float, point)
    h, w = image.shape[:2]
    if not (math.isfinite(x) and math.isfinite(y) and 0 <= x < w and 0 <= y < h):
        raise ValueError("標記點必須在影像範圍內。")
    return np.array([x, y], dtype=np.float64)


def make_result(mode, coin_pixels, coin_points, foot_pixels, foot_points, width_pixels=None,
                coin_diameter_mm=COIN_DIAMETER_MM, reference="assumed_NTD10"):
    if not math.isfinite(coin_pixels) or coin_pixels < MIN_COIN_PIXELS:
        raise ValueError("硬幣直徑不足 30 像素，請靠近或提高解析度後重拍。")
    if not math.isfinite(foot_pixels) or foot_pixels < 2 * coin_pixels:
        raise ValueError("腳長端點／輪廓不合理，請重新選取。")
    if not math.isfinite(coin_diameter_mm) or coin_diameter_mm <= 0:
        raise ValueError("硬幣實際直徑必須是正數。")
    scale = coin_diameter_mm / coin_pixels
    warnings = ["尚未校正鏡頭畸變、透視及腳部高度，這是比例估計值。",
                "硬幣面額由偵測模型判斷，但請確認硬幣與腳在同一平面。"]
    if coin_pixels < 60:
        warnings.append("硬幣少於 60 像素，尺度對邊緣誤差較敏感，建議拍近一點。")
    if mode == "manual":
        warnings.append("手動模式依點選端點計算；硬幣兩點必須通過圓心。")
    return {
        "schema_version": 1, "mode": mode, "reference": reference,
        "coin_diameter_mm": float(coin_diameter_mm), "coin_diameter_px": float(coin_pixels),
        "mm_per_pixel": float(scale), "foot_length_px": float(foot_pixels),
        "foot_length_mm": float(foot_pixels * scale),
        "silhouette_width_mm": None if width_pixels is None else float(width_pixels * scale),
        "coin_diameter_points": np.asarray(coin_points).tolist(),
        "foot_length_points": np.asarray(foot_points).tolist(),
        "coin_1px_error_effect_mm_approx": float(foot_pixels * scale / coin_pixels),
        "warnings": warnings,
        "shoe_size": None,
    }


def measure_manual(image, points, coin_diameter_mm=COIN_DIAMETER_MM, reference="assumed_NTD10"):
    """Four original-image points: coin rim/rim through center, heel, longest toe."""
    if len(points) != 4:
        raise ValueError("需要四個點：硬幣直徑兩端、腳跟、最長腳趾。")
    p = [_point(point, image) for point in points]
    return make_result("manual", float(np.linalg.norm(p[1] - p[0])), p[:2],
                       float(np.linalg.norm(p[3] - p[2])), p[2:],
                       coin_diameter_mm=coin_diameter_mm, reference=reference)


def measure_ai_assisted(image, coin_detection, foot_detection, coin_diameter_mm, reference):
    """Calculate length from a detected coin circle and socked-foot mask.

    A detection box only locates the coin.  The scale itself is taken from a
    fitted circle inside that box, while the length comes from the principal
    axis of the segmentation mask.  This keeps the measurement independent of
    detector-box padding and exposes a safe manual fallback when the coin edge
    cannot be fitted.
    """
    if not coin_detection or not foot_detection:
        raise ValueError("需要同時辨識硬幣與襪子腳才能自動計算")
    h, w = image.shape[:2]
    x1, y1, x2, y2 = (float(v) for v in coin_detection["xyxy"])
    pad = max(8, round(min(x2 - x1, y2 - y1) * .18))
    left, top = max(0, round(x1) - pad), max(0, round(y1) - pad)
    right, bottom = min(w, round(x2) + pad), min(h, round(y2) + pad)
    roi = image[top:bottom, left:right]
    if roi.size == 0:
        raise ValueError("硬幣辨識範圍無效，請重新凍結畫面")

    expected_radius = min(x2 - x1, y2 - y1) / 2
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    gray = cv2.medianBlur(gray, 5)
    circles = cv2.HoughCircles(gray, cv2.HOUGH_GRADIENT, dp=1.2,
                               minDist=max(12, int(expected_radius)), param1=100,
                               param2=18,
                               minRadius=max(8, int(expected_radius * .45)),
                               maxRadius=max(10, int(expected_radius * 1.18)))
    if circles is None:
        raise ValueError("無法精確找到硬幣圓邊，請讓硬幣完整入鏡、避免反光，或改用四點修正")
    candidates = np.asarray(circles[0], dtype=np.float64)
    target = np.array([(right - left) / 2, (bottom - top) / 2, expected_radius])
    # Prefer the circle closest to the detection centre and expected radius.
    score = np.linalg.norm((candidates - target) / np.maximum(target, 1), axis=1)
    cx, cy, radius = candidates[int(np.argmin(score))]
    cx, cy = cx + left, cy + top
    coin_pixels = float(radius * 2)

    polygon = np.round(np.asarray(foot_detection["polygon"])).astype(np.int32).reshape(-1, 1, 2)
    mask = np.zeros((h, w), dtype=np.uint8)
    cv2.fillPoly(mask, [polygon], 255)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        raise ValueError("襪子腳遮罩無法轉為量測輪廓，請重新凍結畫面")
    contour = max(contours, key=cv2.contourArea)
    points = contour[:, 0, :].astype(np.float64)
    if len(points) < 5:
        raise ValueError("襪子腳遮罩點數不足，請重新凍結畫面")
    foot_start, ankle_point, length, width, ankle_score = _toe_to_ankle_axis(mask, contour)
    result = make_result("ai_assisted", coin_pixels,
                         [[cx - radius, cy], [cx + radius, cy]], length,
                         [foot_start, ankle_point], width,
                         coin_diameter_mm=coin_diameter_mm, reference=reference)
    result["foot_contour"] = contour[:, 0, :].tolist()
    result["coin_circle"] = [float(cx), float(cy), float(radius)]
    result["ankle_cut_score"] = float(ankle_score)
    result["warnings"].append("自動量測會從襪子腳遮罩的腳踝收窄處截掉襪筒或小腿，請確認硬幣與腳位於同一平面")
    return result


def _toe_to_ankle_axis(mask, contour):
    """Return a toe-to-ankle axis rather than the full sock/calf axis.

    The segmentation class can include a sock cuff.  Along the foot's main
    axis a genuine foot normally has: narrow toe → wide forefoot → narrow
    ankle.  We search that width profile from both ends and retain the side
    that has this characteristic shape.  A weak profile is rejected instead
    of silently reporting a calf-inclusive length.
    """
    points = contour[:, 0, :].astype(np.float64)
    center = points.mean(axis=0)
    _, vectors = np.linalg.eigh(np.cov((points - center).T))
    axis = vectors[:, -1]
    coords = np.column_stack(np.nonzero(mask > 0))[:, ::-1].astype(np.float64)
    along = (coords - center) @ axis
    across = (coords - center) @ np.array([-axis[1], axis[0]])
    lo, hi = float(along.min()), float(along.max())
    bins = 96
    edges = np.linspace(lo, hi, bins + 1)
    indices = np.clip(np.digitize(along, edges) - 1, 0, bins - 1)
    widths = np.zeros(bins, dtype=np.float64)
    for index in range(bins):
        values = across[indices == index]
        if len(values) >= 5:
            widths[index] = np.percentile(values, 95) - np.percentile(values, 5)
    valid = widths > 0
    if valid.sum() < 40:
        raise ValueError("襪子腳遮罩過小，無法自動判斷腳踝")
    # Interpolate small empty edge bins, then smooth the cross-section width.
    positions = np.arange(bins)
    widths = np.interp(positions, positions[valid], widths[valid])
    widths = cv2.GaussianBlur(widths.reshape(1, -1), (1, 9), 0).ravel()
    centers = (edges[:-1] + edges[1:]) / 2

    def candidate(reverse):
        profile = widths[::-1] if reverse else widths
        locations = centers[::-1] if reverse else centers
        start = max(2, round(bins * .08))
        search_from, search_to = round(bins * .38), round(bins * .92)
        neck_index = search_from + int(np.argmin(profile[search_from:search_to]))
        if neck_index < round(bins * .48):
            return None
        forefoot = float(np.max(profile[start:neck_index]))
        toe_width = float(np.median(profile[:start]))
        ankle_width = float(profile[neck_index])
        if forefoot <= 1:
            return None
        narrowing = (forefoot - ankle_width) / forefoot
        toe_taper = (forefoot - toe_width) / forefoot
        # Toe must taper, and the ankle must be visibly narrower than the
        # forefoot.  These gates reject masks that are mostly lower leg.
        if narrowing < .14 or toe_taper < .08:
            return None
        score = narrowing * .72 + toe_taper * .28
        toe_value, ankle_value = float(locations[0]), float(locations[neck_index])
        toe_point = center + axis * toe_value
        ankle_point = center + axis * ankle_value
        return score, toe_point, ankle_point, abs(ankle_value - toe_value), ankle_width

    candidates = [item for item in (candidate(False), candidate(True)) if item is not None]
    if not candidates:
        raise ValueError("無法從遮罩找到可靠腳踝，請讓整隻腳與腳踝完整入鏡後重新量測")
    score, toe_point, ankle_point, length, ankle_width = max(candidates, key=lambda item: item[0])
    return toe_point, ankle_point, float(length), float(ankle_width), float(score)


def foreground_mask(image, threshold=40.0):
    """Estimate a uniform mat color from the image border, then separate foreground."""
    if not 10 <= threshold <= 150:
        raise ValueError("背景差異門檻需介於 10 和 150。")
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB).astype(np.float32)
    border = np.concatenate((lab[0], lab[-1], lab[:, 0], lab[:, -1]))
    background = np.median(border, axis=0)
    border_distance = np.linalg.norm(border - background, axis=1)
    if np.mean(border_distance < threshold) < 0.85:
        raise ValueError("影像邊緣背景不夠一致；請讓純色墊子填滿畫面，或使用手動模式。")
    mask = (np.linalg.norm(lab - background, axis=2) > threshold).astype(np.uint8) * 255
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)


def measure_auto(image, threshold=40.0):
    mask = foreground_mask(image, threshold)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    contours = [c for c in contours if cv2.contourArea(c) >= 80]
    h, w = image.shape[:2]
    candidates = []
    for index, contour in enumerate(contours):
        if len(contour) < 5:
            continue
        x, y, cw, ch = cv2.boundingRect(contour)
        if x <= 1 or y <= 1 or x + cw >= w - 1 or y + ch >= h - 1:
            continue
        ellipse = cv2.fitEllipse(contour)
        minor, major = sorted(ellipse[1])
        perimeter = cv2.arcLength(contour, True)
        circularity = 4 * np.pi * cv2.contourArea(contour) / max(perimeter ** 2, 1)
        diameter = (minor + major) / 2
        if (MIN_COIN_PIXELS <= diameter <= min(h, w) * 0.3 and
                minor / max(major, 1) >= 0.90 and circularity >= 0.75):
            candidates.append((index, ellipse, diameter))
    if len(candidates) != 1:
        raise ValueError(f"找到 {len(candidates)} 個可用圓形，無法唯一確認硬幣。請移除其他物件、改善光線或用手動模式。")
    coin_index, ellipse, diameter = candidates[0]
    coin_area = cv2.contourArea(contours[coin_index])
    feet = sorted((c for i, c in enumerate(contours)
                   if i != coin_index and cv2.contourArea(c) > coin_area * 4),
                  key=cv2.contourArea, reverse=True)
    if not feet or (len(feet) > 1 and cv2.contourArea(feet[1]) > cv2.contourArea(feet[0]) * 0.3):
        raise ValueError("無法找到唯一的腳部前景；畫面只留一隻完整裸腳與一枚硬幣。")
    contour = feet[0]
    x, y, cw, ch = cv2.boundingRect(contour)
    if x <= 1 or y <= 1 or x + cw >= w - 1 or y + ch >= h - 1:
        raise ValueError("腳部輪廓碰到畫面邊界，可能包含小腿或截掉腳趾／腳跟，請重拍或使用手動端點。")
    points = contour[:, 0, :].astype(np.float64)
    center = points.mean(axis=0)
    _, vectors = np.linalg.eigh(np.cov((points - center).T))
    axis = vectors[:, -1]
    along = (points - center) @ axis
    across = (points - center) @ np.array([-axis[1], axis[0]])
    length, width = float(np.ptp(along)), float(np.ptp(across))
    if length < width * 1.4:
        raise ValueError("前景不像完整足部長輪廓，請檢查分割結果或改用手動模式。")
    foot_points = [center + axis * along.min(), center + axis * along.max()]
    cx, cy = ellipse[0]
    # Endpoints illustrate the fitted mean diameter; not a detector box width.
    coin_points = [[cx - diameter / 2, cy], [cx + diameter / 2, cy]]
    result = make_result("auto", diameter, coin_points, length, foot_points, width)
    result["coin_ellipse"] = [list(ellipse[0]), list(ellipse[1]), float(ellipse[2])]
    result["coin_axis_ratio"] = min(ellipse[1]) / max(ellipse[1])
    result["background_threshold"] = float(threshold)
    result["foot_contour"] = contour[:, 0, :].tolist()
    result["warnings"].append("自動長度為輪廓主軸投影範圍；前景未經足部神經網路辨識，需人工檢查。")
    return result, mask


def annotate(image, result):
    output = image.copy()
    if "foot_contour" in result:
        contour = np.array(result["foot_contour"], np.int32).reshape(-1, 1, 2)
        cv2.drawContours(output, [contour], -1, (60, 220, 60), 2)
    if "coin_ellipse" in result:
        c, axes, angle = result["coin_ellipse"]
        cv2.ellipse(output, (tuple(c), tuple(axes), angle), (0, 220, 255), 2)
    if "coin_circle" in result:
        cx, cy, radius = result["coin_circle"]
        cv2.circle(output, (round(cx), round(cy)), round(radius), (0, 220, 255), 2)
    for key, color in (("coin_diameter_points", (0, 220, 255)),
                       ("foot_length_points", (70, 220, 70))):
        a, b = [tuple(np.round(p).astype(int)) for p in result[key]]
        cv2.line(output, a, b, color, 2)
        cv2.circle(output, a, 5, color, -1)
        cv2.circle(output, b, 5, color, -1)
    text = f'{result["mode"]}: length {result["foot_length_mm"]:.1f} mm'
    cv2.rectangle(output, (0, 0), (min(output.shape[1], 1000), 40), (20, 20, 20), -1)
    cv2.putText(output, text, (10, 27), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)
    return output
