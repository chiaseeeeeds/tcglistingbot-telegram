"""Game adapter contracts for Pokémon and One Piece card handling."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class CardMatchHint:
    """Normalized OCR hint payload passed into game-specific match logic."""

    raw_text: str
    game: str | None = None
    language: str | None = None


class GameAdapter(Protocol):
    """Protocol implemented by each supported card game adapter."""

    game: str

    def identify(self, hint: CardMatchHint) -> dict:
        """Return a best-effort canonical card match payload from OCR-derived input."""


class PokemonAdapter:
    """Basic adapter shell for Pokémon-specific OCR and identity normalization."""

    game = "pokemon"

    def identify(self, hint: CardMatchHint) -> dict:
        """Return a placeholder structure for future Pokémon identification logic."""

        return {"game": self.game, "matched": False, "raw_text": hint.raw_text}


class OnePieceAdapter:
    """Basic adapter shell for One Piece-specific OCR and identity normalization."""

    game = "onepiece"

    def identify(self, hint: CardMatchHint) -> dict:
        """Return a placeholder structure for future One Piece identification logic."""

        return {"game": self.game, "matched": False, "raw_text": hint.raw_text}
