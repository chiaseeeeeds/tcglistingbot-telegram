"""Validation helpers for TCG Listing Bot user inputs."""

from __future__ import annotations

import re

LETTERS_AND_SPACES_RE = re.compile(r'^[A-Za-z ]+$')
DIGITS_ONLY_RE = re.compile(r'^\d+$')


def is_letters_and_spaces(value: str) -> bool:
    """Return `True` when the input contains only English letters and spaces."""

    return bool(value) and bool(LETTERS_AND_SPACES_RE.fullmatch(value.strip()))


def is_digits_only(value: str) -> bool:
    """Return `True` when the input contains only digits."""

    return bool(value) and bool(DIGITS_ONLY_RE.fullmatch(value.strip()))
