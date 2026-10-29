"""`screen_text`: the one NFKC -> `mask_pii` -> `detect_injection` pass over a bank or GL text.

Every caller that needs to know whether a text holds PII or reads as an injection uses this, so
the order (normalise first, so fullwidth text cannot slip past either check) lives in one place.
"""

import unicodedata
from dataclasses import dataclass

from app.guardrails.injection import InjectionResult, detect_injection
from app.guardrails.pii import mask_pii


@dataclass(frozen=True)
class ScreenedText:
    text: str  # normalised and PII-masked
    pii_masked: bool  # masking changed the normalised text
    injection: InjectionResult


def screen_text(text: str) -> ScreenedText:
    norm = unicodedata.normalize("NFKC", text)
    masked = mask_pii(norm)
    return ScreenedText(text=masked, pii_masked=masked != norm, injection=detect_injection(masked))
