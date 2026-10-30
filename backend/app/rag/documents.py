"""Build deterministic, allowlisted search text from source transaction rows."""

from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
from typing import Any, Literal

from app.guardrails import screen_text
from app.guardrails.pii import PERSON

SourceType = Literal["bank_transaction", "gl_entry"]


@dataclass(frozen=True)
class SearchDocument:
    dataset: str
    source_type: SourceType
    source_id: str
    search_text: str
    content_hash: str


def _text(value: object) -> str:
    if isinstance(value, float):
        raise TypeError("money and searchable values must not use float")
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return str(value)
    return str(value).strip()


def _screen(value: object) -> str:
    return screen_text(_text(value)).text


def build_search_document(
    dataset: str,
    source_type: SourceType,
    source_id: str,
    row: dict[str, Any],
) -> SearchDocument:
    """Screen free text and compose a stable allowlist; never embed arbitrary row JSON."""
    if source_type == "bank_transaction":
        description = screen_text(_text(row.get("description")))
        fields = (
            ("transaction", source_id),
            ("date", _text(row.get("posted_date"))),
            ("amount", _text(row.get("amount"))),
            ("type", _screen(row.get("type"))),
            ("check", _screen(row.get("check_number"))),
            ("description", description.text),
        )
    else:
        description = screen_text(_text(row.get("description")))
        raw_counterparty = _text(row.get("counterparty"))
        # A bare person payee is not recognizable without the description's contextual mask.
        counterparty = PERSON if PERSON in description.text else screen_text(raw_counterparty).text
        fields = (
            ("ledger entry", source_id),
            ("date", _text(row.get("date"))),
            ("amount", _text(row.get("amount"))),
            ("method", _screen(row.get("method"))),
            ("check", _screen(row.get("check_number"))),
            ("account", _screen(row.get("account"))),
            ("counter account", _screen(row.get("counter_account"))),
            ("description", description.text),
            ("counterparty", counterparty),
        )
    searchable = " ".join(f"{label}: {value}" for label, value in fields if value)
    digest = sha256(searchable.encode("utf-8")).hexdigest()
    return SearchDocument(dataset, source_type, source_id, searchable, digest)
