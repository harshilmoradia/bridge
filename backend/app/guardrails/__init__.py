"""Guardrails applied to bank and GL text before it reaches any prompt.

- `pii.mask_pii`: PII masking (B-08 slice 1).
- `injection.detect_injection`: injection flagging (B-08 slice 2).
- `untrusted`: `prepare_untrusted`, `prompt_row` and the shared system-prompt rules,
  the one path by which bank and GL text enters a prompt (B-08 slice 2).
"""

from app.guardrails.injection import InjectionResult, detect_injection
from app.guardrails.pii import mask_pii
from app.guardrails.untrusted import (
    UNTRUSTED_SYSTEM_RULES,
    PreparedText,
    prepare_untrusted,
    prompt_row,
    with_untrusted_rules,
)

__all__ = [
    "UNTRUSTED_SYSTEM_RULES",
    "InjectionResult",
    "PreparedText",
    "detect_injection",
    "mask_pii",
    "prepare_untrusted",
    "prompt_row",
    "with_untrusted_rules",
]
