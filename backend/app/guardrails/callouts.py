"""The guardrail callout the read API shows beside a bank or GL row.

It uses `screen_text`, the same NFKC -> mask -> detect pass `prepare_untrusted` runs for the
agents' prompts, and the person-payee rule of `prompt_row`. `sent_to_model` is that masked text
before `<untrusted>` tag escaping (`&` -> `&amp;`), which is plumbing the reader need not see.
"""

from app.guardrails.pii import PERSON
from app.guardrails.screen import screen_text
from app.schemas.reads import Guardrail


def bank_guardrail(description: str) -> Guardrail:
    screened = screen_text(description or "")
    return Guardrail(
        injection_flagged=screened.injection.flagged,
        pii_masked=screened.pii_masked,
        sent_to_model=screened.text,
    )


def gl_guardrail(description: str, counterparty: str | None) -> Guardrail:
    screened = screen_text(description or "")
    sent_counterparty = None
    counterparty_masked = False
    counterparty_flagged = False
    if counterparty is not None:
        counter = screen_text(counterparty)
        counterparty_flagged = counter.injection.flagged
        person_payee = PERSON in screened.text  # a bare person name is invisible to mask_pii alone
        sent_counterparty = PERSON if person_payee else counter.text
        counterparty_masked = person_payee or counter.pii_masked
    return Guardrail(
        injection_flagged=screened.injection.flagged or counterparty_flagged,
        pii_masked=screened.pii_masked or counterparty_masked,
        sent_to_model=screened.text,
        sent_counterparty=sent_counterparty,
    )
