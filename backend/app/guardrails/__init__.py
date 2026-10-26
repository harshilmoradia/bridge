"""Guardrails applied to bank and GL text before it reaches any prompt.

- `pii.mask_pii`: PII masking (B-08 slice 1).
- `injection`: injection flagging and `<untrusted>` delimiting (B-08 slice 2).
"""

from app.guardrails.pii import mask_pii

__all__ = ["mask_pii"]
