"""Photo quality assessment helpers for OCR-bound card images."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np


@dataclass(frozen=True)
class PhotoQualityAssessment:
    """Normalized quality signals used before OCR and card matching."""

    width: int
    height: int
    sharpness: float
    brightness: float
    contrast: float
    glare_ratio: float
    dark_ratio: float
    score: float
    acceptable: bool
    warnings: list[str]

    def as_dict(self) -> dict[str, Any]:
        """Serialize the assessment for Telegram context/user data."""

        return asdict(self)



def _clamp(value: float, *, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))



def _score_resolution(width: int, height: int) -> float:
    min_side = min(width, height)
    return _clamp((min_side - 480.0) / 720.0)



def _score_sharpness(sharpness: float) -> float:
    return _clamp((sharpness - 25.0) / 155.0)



def _score_brightness(brightness: float) -> float:
    distance = abs(brightness - 150.0)
    return _clamp(1.0 - (distance / 105.0))



def _score_contrast(contrast: float) -> float:
    return _clamp((contrast - 22.0) / 58.0)



def _score_glare(glare_ratio: float) -> float:
    return _clamp(1.0 - (glare_ratio / 0.16))



def _score_darkness(dark_ratio: float) -> float:
    return _clamp(1.0 - (dark_ratio / 0.30))



def assess_photo_quality(image_path: str | Path) -> PhotoQualityAssessment:
    """Estimate whether a photo is likely usable for OCR and matching."""

    image = cv2.imread(str(image_path))
    if image is None:
        raise ValueError(f'Could not read image for quality assessment: {image_path}')

    height, width = image.shape[:2]
    grayscale = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    sharpness = float(cv2.Laplacian(grayscale, cv2.CV_64F).var())
    brightness = float(np.mean(grayscale))
    contrast = float(np.std(grayscale))
    glare_ratio = float(np.mean(grayscale >= 245))
    dark_ratio = float(np.mean(grayscale <= 22))

    component_scores = [
        _score_resolution(width, height),
        _score_sharpness(sharpness),
        _score_brightness(brightness),
        _score_contrast(contrast),
        _score_glare(glare_ratio),
        _score_darkness(dark_ratio),
    ]
    score = round(sum(component_scores) / len(component_scores), 3)

    warnings: list[str] = []
    if min(width, height) < 700:
        warnings.append('The selected front photo is low-resolution, so OCR may miss the printed identifier.')
    if sharpness < 22:
        warnings.append('The selected front photo looks blurry. A steadier, tighter crop should improve OCR.')
    elif sharpness < 45:
        warnings.append('The selected front photo is slightly soft, so small printed text may be less reliable.')
    if brightness < 60:
        warnings.append('The selected front photo looks quite dark. Better lighting should improve OCR.')
    elif brightness > 220:
        warnings.append('The selected front photo looks overexposed. Reducing glare should improve OCR.')
    if contrast < 24:
        warnings.append('The selected front photo has weak contrast, so card text may blend into the background.')
    if glare_ratio > 0.08:
        warnings.append('There is noticeable glare on the selected front photo, which can wash out text.')
    if dark_ratio > 0.22:
        warnings.append('Large dark regions are hiding detail in the selected front photo.')

    acceptable = True
    if min(width, height) < 520:
        acceptable = False
    if sharpness < 12:
        acceptable = False
    if brightness < 35 or brightness > 240:
        acceptable = False
    if glare_ratio > 0.18:
        acceptable = False
    if score < 0.27:
        acceptable = False

    return PhotoQualityAssessment(
        width=width,
        height=height,
        sharpness=round(sharpness, 2),
        brightness=round(brightness, 2),
        contrast=round(contrast, 2),
        glare_ratio=round(glare_ratio, 4),
        dark_ratio=round(dark_ratio, 4),
        score=score,
        acceptable=acceptable,
        warnings=warnings,
    )



def assessment_from_payload(payload: dict[str, Any] | None) -> PhotoQualityAssessment | None:
    """Rebuild an assessment from a context payload when present."""

    if not payload:
        return None
    try:
        return PhotoQualityAssessment(
            width=int(payload.get('width') or 0),
            height=int(payload.get('height') or 0),
            sharpness=float(payload.get('sharpness') or 0.0),
            brightness=float(payload.get('brightness') or 0.0),
            contrast=float(payload.get('contrast') or 0.0),
            glare_ratio=float(payload.get('glare_ratio') or 0.0),
            dark_ratio=float(payload.get('dark_ratio') or 0.0),
            score=float(payload.get('score') or 0.0),
            acceptable=bool(payload.get('acceptable')),
            warnings=[str(item) for item in list(payload.get('warnings') or []) if str(item).strip()],
        )
    except Exception:
        return None



def format_quality_summary(assessment: PhotoQualityAssessment | None) -> str:
    """Return a compact human-readable summary for a quality assessment."""

    if assessment is None:
        return 'not assessed'
    rating = 'good' if assessment.score >= 0.7 else 'fair' if assessment.score >= 0.45 else 'weak'
    return (
        f'{rating} quality — score {assessment.score:.2f}, '
        f'{assessment.width}x{assessment.height}, sharpness {assessment.sharpness:.0f}'
    )
