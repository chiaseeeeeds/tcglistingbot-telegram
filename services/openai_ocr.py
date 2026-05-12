"""OpenAI-backed OCR helpers using the Responses API."""

from __future__ import annotations

import base64
import io
import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx
from PIL import Image

from config import get_config

logger = logging.getLogger(__name__)
_RESPONSES_API_URL = 'https://api.openai.com/v1/responses'


class OpenAIOCRError(RuntimeError):
    """Base error for OpenAI OCR failures."""


class OpenAIOCRRequestError(OpenAIOCRError):
    """Raised when the OpenAI request fails or returns no usable payload."""


class OpenAIOCRSchemaError(OpenAIOCRError):
    """Raised when the OpenAI response does not match the expected schema."""


@dataclass(frozen=True)
class OpenAIOCRRegion:
    label: str
    identifier_text: str
    ratio_text: str
    set_code: str
    name_en: str
    name_jp: str
    raw_text: str


@dataclass(frozen=True)
class OpenAIOCRBatchResult:
    regions: list[OpenAIOCRRegion]
    best_guess: OpenAIOCRRegion
    warnings: list[str]


@dataclass(frozen=True)
class OpenAIGameDetectionResult:
    game: str
    confidence: float
    reason: str
    tokens_seen: list[str]


def _image_to_data_url(image: Image.Image) -> str:
    prepared = image.convert('RGB')
    max_side = 1400
    if max(prepared.size) > max_side:
        prepared = prepared.copy()
        prepared.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    prepared.save(buffer, format='JPEG', quality=85, optimize=True)
    encoded = base64.b64encode(buffer.getvalue()).decode('ascii')
    return f'data:image/jpeg;base64,{encoded}'


OCR_RESPONSE_SCHEMA: dict[str, Any] = {
    'type': 'object',
    'additionalProperties': False,
    'properties': {
        'regions': {
            'type': 'array',
            'items': {
                'type': 'object',
                'additionalProperties': False,
                'properties': {
                    'label': {'type': 'string'},
                    'identifier_text': {'type': 'string'},
                    'ratio_text': {'type': 'string'},
                    'set_code': {'type': 'string'},
                    'name_en': {'type': 'string'},
                    'name_jp': {'type': 'string'},
                    'raw_text': {'type': 'string'},
                },
                'required': [
                    'label',
                    'identifier_text',
                    'ratio_text',
                    'set_code',
                    'name_en',
                    'name_jp',
                    'raw_text',
                ],
            },
        },
        'best_guess': {
            'type': 'object',
            'additionalProperties': False,
            'properties': {
                'label': {'type': 'string'},
                'identifier_text': {'type': 'string'},
                'ratio_text': {'type': 'string'},
                'set_code': {'type': 'string'},
                'name_en': {'type': 'string'},
                'name_jp': {'type': 'string'},
                'raw_text': {'type': 'string'},
            },
            'required': [
                'label',
                'identifier_text',
                'ratio_text',
                'set_code',
                'name_en',
                'name_jp',
                'raw_text',
            ],
        },
        'warnings': {
            'type': 'array',
            'items': {'type': 'string'},
        },
    },
    'required': ['regions', 'best_guess', 'warnings'],
}

GAME_DETECTION_SCHEMA: dict[str, Any] = {
    'type': 'object',
    'additionalProperties': False,
    'properties': {
        'game': {
            'type': 'string',
            'enum': ['pokemon', 'onepiece', 'unknown'],
        },
        'confidence': {'type': 'number'},
        'reason': {'type': 'string'},
        'tokens_seen': {
            'type': 'array',
            'items': {'type': 'string'},
        },
    },
    'required': ['game', 'confidence', 'reason', 'tokens_seen'],
}


def _build_content(
    *,
    prompt: str,
    regions: list[tuple[str, Image.Image]],
) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [{'type': 'input_text', 'text': prompt}]
    for label, image in regions:
        content.append({'type': 'input_text', 'text': f'Region label: {label}'})
        content.append(
            {
                'type': 'input_image',
                'image_url': _image_to_data_url(image),
                'detail': 'high',
            }
        )
    return content


def _extract_output_text(payload: dict[str, Any]) -> str:
    output_text = payload.get('output_text')
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    for item in payload.get('output', []):
        if not isinstance(item, dict):
            continue
        for content_item in item.get('content', []):
            if not isinstance(content_item, dict):
                continue
            for key in ('text', 'output_text'):
                value = content_item.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            value = content_item.get('json')
            if isinstance(value, dict):
                return json.dumps(value)
    return ''


def _validate_region(raw_region: dict[str, Any]) -> OpenAIOCRRegion:
    expected_keys = {
        'label',
        'identifier_text',
        'ratio_text',
        'set_code',
        'name_en',
        'name_jp',
        'raw_text',
    }
    if set(raw_region.keys()) != expected_keys:
        raise OpenAIOCRSchemaError('OpenAI OCR region schema mismatch.')
    values: dict[str, str] = {}
    for key in expected_keys:
        value = raw_region.get(key, '')
        if not isinstance(value, str):
            raise OpenAIOCRSchemaError(f'OpenAI OCR field {key!r} must be a string.')
        values[key] = ' '.join(value.split())
    return OpenAIOCRRegion(**values)


def _validate_ocr_payload(payload: dict[str, Any]) -> OpenAIOCRBatchResult:
    if set(payload.keys()) != {'regions', 'best_guess', 'warnings'}:
        raise OpenAIOCRSchemaError('OpenAI OCR payload schema mismatch.')
    raw_regions = payload.get('regions')
    raw_best_guess = payload.get('best_guess')
    raw_warnings = payload.get('warnings')
    if not isinstance(raw_regions, list) or not isinstance(raw_best_guess, dict) or not isinstance(raw_warnings, list):
        raise OpenAIOCRSchemaError('OpenAI OCR payload contains invalid field types.')
    regions = [_validate_region(item) for item in raw_regions if isinstance(item, dict)]
    if len(regions) != len(raw_regions):
        raise OpenAIOCRSchemaError('OpenAI OCR payload contains non-object regions.')
    warnings: list[str] = []
    for warning in raw_warnings:
        if not isinstance(warning, str):
            raise OpenAIOCRSchemaError('OpenAI OCR warnings must be strings.')
        warnings.append(' '.join(warning.split()))
    return OpenAIOCRBatchResult(
        regions=regions,
        best_guess=_validate_region(raw_best_guess),
        warnings=warnings,
    )


def _validate_game_payload(payload: dict[str, Any]) -> OpenAIGameDetectionResult:
    if set(payload.keys()) != {'game', 'confidence', 'reason', 'tokens_seen'}:
        raise OpenAIOCRSchemaError('OpenAI game-detection payload schema mismatch.')
    game = payload.get('game')
    confidence = payload.get('confidence')
    reason = payload.get('reason')
    tokens_seen = payload.get('tokens_seen')
    if game not in {'pokemon', 'onepiece', 'unknown'}:
        raise OpenAIOCRSchemaError('OpenAI game-detection game value is invalid.')
    if not isinstance(confidence, (int, float)):
        raise OpenAIOCRSchemaError('OpenAI game-detection confidence must be numeric.')
    if not isinstance(reason, str):
        raise OpenAIOCRSchemaError('OpenAI game-detection reason must be a string.')
    if not isinstance(tokens_seen, list) or any(not isinstance(item, str) for item in tokens_seen):
        raise OpenAIOCRSchemaError('OpenAI game-detection tokens_seen must be string arrays.')
    normalized_tokens = [' '.join(item.split()) for item in tokens_seen if item.strip()]
    return OpenAIGameDetectionResult(
        game=game,
        confidence=max(0.0, min(float(confidence), 1.0)),
        reason=' '.join(reason.split()),
        tokens_seen=normalized_tokens,
    )


def _request_structured_output(
    *,
    prompt: str,
    schema_name: str,
    schema: dict[str, Any],
    regions: list[tuple[str, Image.Image]],
    max_output_tokens: int,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    if not regions:
        raise OpenAIOCRRequestError('OpenAI OCR request requires at least one region image.')

    config = get_config()
    if not config.openai_api_key:
        raise OpenAIOCRRequestError('OPENAI_API_KEY is not configured for OpenAI OCR.')

    payload = {
        'model': config.openai_ocr_model,
        'input': [
            {
                'role': 'user',
                'content': _build_content(prompt=prompt, regions=regions),
            }
        ],
        'text': {
            'format': {
                'type': 'json_schema',
                'name': schema_name,
                'schema': schema,
                'strict': True,
            }
        },
        'max_output_tokens': max_output_tokens,
    }
    headers = {
        'Authorization': f'Bearer {config.openai_api_key}',
        'Content-Type': 'application/json',
    }

    request_timeout = float(timeout_seconds or config.openai_ocr_timeout_seconds)

    last_error: Exception | None = None
    for attempt in range(2):
        try:
            with httpx.Client(timeout=httpx.Timeout(request_timeout)) as client:
                response = client.post(_RESPONSES_API_URL, headers=headers, json=payload)
                response.raise_for_status()
            break
        except httpx.TimeoutException as exc:
            last_error = exc
            if attempt == 0:
                logger.warning('OpenAI OCR request timed out on attempt %s; retrying once.', attempt + 1)
                continue
            raise OpenAIOCRRequestError('OpenAI OCR request timed out.') from exc
        except httpx.HTTPStatusError as exc:
            last_error = exc
            status_code = exc.response.status_code
            if attempt == 0 and status_code in {408, 409, 429, 500, 502, 503, 504}:
                logger.warning('OpenAI OCR request failed with transient status %s on attempt %s; retrying once.', status_code, attempt + 1)
                continue
            body = exc.response.text[:400]
            raise OpenAIOCRRequestError(
                f'OpenAI OCR request failed with status {status_code}: {body}'
            ) from exc
        except httpx.HTTPError as exc:
            last_error = exc
            if attempt == 0:
                logger.warning('OpenAI OCR transport failed on attempt %s; retrying once.', attempt + 1)
                continue
            raise OpenAIOCRRequestError('OpenAI OCR transport failed.') from exc
    else:
        raise OpenAIOCRRequestError('OpenAI OCR request failed before a response was received.') from last_error

    try:
        response_payload = response.json()
    except ValueError as exc:
        raise OpenAIOCRSchemaError('OpenAI OCR response was not valid JSON.') from exc

    output_text = _extract_output_text(response_payload)
    if not output_text:
        logger.warning('OpenAI OCR response had no output_text keys: %s', list(response_payload.keys()))
        raise OpenAIOCRSchemaError('OpenAI OCR response did not contain structured text output.')

    try:
        parsed = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise OpenAIOCRSchemaError('OpenAI OCR structured output was not valid JSON.') from exc
    if not isinstance(parsed, dict):
        raise OpenAIOCRSchemaError('OpenAI OCR structured output must be a JSON object.')
    return parsed


def extract_card_text_from_regions(
    regions: list[tuple[str, Image.Image]],
) -> OpenAIOCRBatchResult:
    """Extract OCR signals from labeled card ROI images."""

    prompt = (
        'Extract visible printed trading-card text from the provided card image. '
        'Use best-effort OCR and prefer partial text over blank fields. '
        'Preserve Japanese text exactly when visible. Ignore playmats, sleeves, fingers, glare artifacts, '
        'and background noise. Capture identifier text, ratio text, set code, English name, Japanese name, '
        'and raw visible text. When uncertain, keep the uncertain field short but do not hallucinate extra details. '
        'The best_guess object should contain the single most useful combined guess from the image.'
    )
    payload = _request_structured_output(
        prompt=prompt,
        schema_name='tcg_card_ocr_batch',
        schema=OCR_RESPONSE_SCHEMA,
        regions=regions,
        max_output_tokens=220,
        timeout_seconds=min(float(get_config().openai_ocr_timeout_seconds), 12.0),
    )
    return _validate_ocr_payload(payload)


def detect_game_from_regions(
    regions: list[tuple[str, Image.Image]],
) -> OpenAIGameDetectionResult:
    """Detect the likely TCG from labeled ROI images."""

    prompt = (
        'Identify whether the visible trading card text most likely belongs to Pokemon, One Piece, '
        'or is unknown. Use only the cropped images provided. Return short tokens you actually saw, '
        'such as HP, Weakness, DON, Character, Leader, or Trigger. Do not guess beyond the evidence.'
    )
    payload = _request_structured_output(
        prompt=prompt,
        schema_name='tcg_game_detection',
        schema=GAME_DETECTION_SCHEMA,
        regions=regions,
        max_output_tokens=120,
        timeout_seconds=min(float(get_config().openai_ocr_timeout_seconds), 5.0),
    )
    return _validate_game_payload(payload)
