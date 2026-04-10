"""Card detection and perspective rectification helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

TARGET_CARD_WIDTH = 744
TARGET_CARD_HEIGHT = 1039
_CARD_RATIO = TARGET_CARD_HEIGHT / TARGET_CARD_WIDTH


@dataclass(frozen=True)
class CardDetectionResult:
    """Detected and rectified card image metadata."""

    image: Image.Image
    detected: bool
    method: str
    confidence: float


def _order_points(points: np.ndarray) -> np.ndarray:
    ordered = np.zeros((4, 2), dtype='float32')
    sums = points.sum(axis=1)
    diffs = np.diff(points, axis=1)
    ordered[0] = points[np.argmin(sums)]
    ordered[2] = points[np.argmax(sums)]
    ordered[1] = points[np.argmin(diffs)]
    ordered[3] = points[np.argmax(diffs)]
    return ordered


def _rectified_dimensions(points: np.ndarray) -> tuple[float, float]:
    top_left, top_right, bottom_right, bottom_left = points
    width_top = np.linalg.norm(top_right - top_left)
    width_bottom = np.linalg.norm(bottom_right - bottom_left)
    height_left = np.linalg.norm(bottom_left - top_left)
    height_right = np.linalg.norm(bottom_right - top_right)
    return max(width_top, width_bottom), max(height_left, height_right)


def _warp_card(image: np.ndarray, points: np.ndarray) -> Image.Image:
    ordered = _order_points(points.astype('float32'))
    destination = np.array(
        [
            [0, 0],
            [TARGET_CARD_WIDTH - 1, 0],
            [TARGET_CARD_WIDTH - 1, TARGET_CARD_HEIGHT - 1],
            [0, TARGET_CARD_HEIGHT - 1],
        ],
        dtype='float32',
    )
    matrix = cv2.getPerspectiveTransform(ordered, destination)
    warped = cv2.warpPerspective(image, matrix, (TARGET_CARD_WIDTH, TARGET_CARD_HEIGHT))
    rgb = cv2.cvtColor(warped, cv2.COLOR_BGR2RGB)
    return Image.fromarray(rgb)


def _score_quad(points: np.ndarray, image_area: float) -> float:
    area = cv2.contourArea(points.astype('float32'))
    if area <= 0:
        return -1.0
    width, height = _rectified_dimensions(_order_points(points.astype('float32')))
    if width <= 0 or height <= 0:
        return -1.0
    ratio = max(width, height) / max(min(width, height), 1e-6)
    ratio_error = abs(ratio - _CARD_RATIO)
    if ratio_error > 0.45:
        return -1.0
    area_score = min(area / max(image_area, 1.0), 1.0)
    ratio_score = max(0.0, 1.0 - ratio_error)
    return area_score * 0.7 + ratio_score * 0.3


def _find_best_quadrilateral(image: np.ndarray) -> tuple[np.ndarray | None, str, float]:
    image_area = float(image.shape[0] * image.shape[1])
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)

    preprocessors = [
        ('canny', cv2.Canny(blurred, 50, 150)),
        (
            'adaptive',
            cv2.adaptiveThreshold(
                blurred,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY,
                11,
                2,
            ),
        ),
    ]

    best_points: np.ndarray | None = None
    best_method = 'fallback'
    best_score = -1.0

    kernel = np.ones((5, 5), np.uint8)
    for method_name, processed in preprocessors:
        morphed = cv2.morphologyEx(processed, cv2.MORPH_CLOSE, kernel, iterations=2)
        contours, _ = cv2.findContours(morphed, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < image_area * 0.12:
                continue
            perimeter = cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, 0.02 * perimeter, True)
            if len(approx) != 4:
                continue
            points = approx.reshape(4, 2)
            score = _score_quad(points, image_area)
            if score > best_score:
                best_points = points
                best_method = method_name
                best_score = score

    if best_points is not None:
        return best_points, best_method, best_score

    contours, _ = cv2.findContours(cv2.Canny(blurred, 30, 120), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    for contour in sorted(contours, key=cv2.contourArea, reverse=True):
        area = cv2.contourArea(contour)
        if area < image_area * 0.12:
            continue
        rect = cv2.minAreaRect(contour)
        box = cv2.boxPoints(rect)
        score = _score_quad(box, image_area)
        if score > best_score:
            best_points = box
            best_method = 'min_area_rect'
            best_score = score
            break

    return best_points, best_method, best_score


def detect_and_rectify_card(image_path: str | Path) -> CardDetectionResult:
    """Detect the primary card in a photo and rectify it to a normalized portrait image."""

    image = cv2.imread(str(image_path))
    if image is None:
        raise FileNotFoundError(f'Card image not found: {image_path}')

    points, method, confidence = _find_best_quadrilateral(image)
    if points is None:
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        return CardDetectionResult(
            image=Image.fromarray(rgb),
            detected=False,
            method='none',
            confidence=0.0,
        )

    rectified = _warp_card(image, points)
    return CardDetectionResult(
        image=rectified,
        detected=True,
        method=method,
        confidence=round(float(confidence), 3),
    )
