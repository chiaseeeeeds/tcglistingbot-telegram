"""Structured OCR signal models for card identification."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class OCRSignal:
    """One structured OCR signal extracted from a card image."""

    kind: str
    value: str
    confidence: float
    source: str
    region: str
    extras: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            'kind': self.kind,
            'value': self.value,
            'confidence': round(self.confidence, 4),
            'source': self.source,
            'region': self.region,
            'extras': dict(self.extras),
        }


@dataclass(frozen=True)
class OCRStructuredResult:
    """Structured OCR output emitted before catalog matching."""

    layout_family: str
    selected_source: str
    signals: list[OCRSignal]
    raw_regions: list[dict[str, str]] = field(default_factory=list)
    raw_chunks: dict[str, list[str]] = field(default_factory=dict)

    def top_signal(self, kind: str) -> OCRSignal | None:
        matches = [signal for signal in self.signals if signal.kind == kind and signal.value]
        if not matches:
            return None
        return max(matches, key=lambda signal: signal.confidence)

    def top_value(self, kind: str) -> str:
        signal = self.top_signal(kind)
        return signal.value if signal is not None else ''

    def as_dict(self) -> dict[str, object]:
        return {
            'layout_family': self.layout_family,
            'selected_source': self.selected_source,
            'signals': [signal.as_dict() for signal in self.signals],
            'raw_regions': [dict(item) for item in self.raw_regions],
            'raw_chunks': {key: list(values) for key, values in self.raw_chunks.items()},
        }


def render_legacy_ocr_text(result: OCRStructuredResult) -> str:
    """Render structured OCR signals into the current legacy merged text format."""

    chunks: list[str] = []
    identifier = result.top_value('identifier')
    if identifier:
        chunks.append(f'IDENTIFIER: {identifier}')
    name_en = result.top_value('name_en')
    if name_en:
        chunks.append(f'NAME_EN: {name_en}')
    else:
        name_jp = result.top_value('name_jp')
        if name_jp:
            chunks.append(f'NAME_JP: {name_jp}')
    return ' | '.join(chunk for chunk in chunks if chunk)
