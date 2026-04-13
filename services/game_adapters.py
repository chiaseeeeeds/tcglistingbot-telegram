"""Game adapter contracts for Pokémon and One Piece card handling."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from services.card_identifier import identify_card_from_text
from services.ocr_signals import OCRStructuredResult


@dataclass(frozen=True)
class CardMatchHint:
    """Normalized OCR hint payload passed into game-specific match logic."""

    raw_text: str
    game: str | None = None
    language: str | None = None
    structured: OCRStructuredResult | None = None


class GameAdapter(Protocol):
    """Protocol implemented by each supported card game adapter."""

    game: str

    def identify(self, hint: CardMatchHint) -> dict[str, Any]:
        """Return a best-effort canonical card match payload from OCR-derived input."""


class PokemonAdapter:
    """Pokémon-specific identity normalization wrapper."""

    game = 'pokemon'

    def identify(self, hint: CardMatchHint) -> dict[str, Any]:
        result = identify_card_from_text(
            raw_text=hint.raw_text,
            game=self.game,
            structured=hint.structured,
        )
        return {
            'game': self.game,
            'matched': result.matched,
            'card_id': result.card_id,
            'display_name': result.display_name,
            'confidence': result.confidence,
            'match_reasons': list(result.match_reasons),
            'metadata': dict(result.metadata),
            'raw_text': hint.raw_text,
            'language': hint.language,
        }


class OnePieceAdapter:
    """One Piece-specific identity normalization wrapper."""

    game = 'onepiece'

    def identify(self, hint: CardMatchHint) -> dict[str, Any]:
        result = identify_card_from_text(
            raw_text=hint.raw_text,
            game=self.game,
            structured=hint.structured,
        )
        return {
            'game': self.game,
            'matched': result.matched,
            'card_id': result.card_id,
            'display_name': result.display_name,
            'confidence': result.confidence,
            'match_reasons': list(result.match_reasons),
            'metadata': dict(result.metadata),
            'raw_text': hint.raw_text,
            'language': hint.language,
        }
