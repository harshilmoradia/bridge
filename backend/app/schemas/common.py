"""Types shared by every v1 contract. Money is a Decimal in Python and a decimal string in JSON."""

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, PlainSerializer, WithJsonSchema

CENT = Decimal("0.01")

Money = Annotated[
    Decimal,
    PlainSerializer(lambda d: str(d.quantize(CENT)), return_type=str, when_used="json"),
    WithJsonSchema({"type": "string", "pattern": r"^-?\d+\.\d{2}$", "examples": ["864.09"]}),
]

# Every bank or GL row has exactly one of these. `unmatched` means no item in the latest run covers it.
ReconStatus = Literal[
    "matched", "auto_resolved", "reconciling_item", "needs_approval", "approved", "rejected", "unmatched"
]
ItemStatus = Literal["matched", "auto_resolved", "reconciling_item", "needs_approval", "approved", "rejected"]


class ApiError(BaseModel):
    code: str
    message: str
