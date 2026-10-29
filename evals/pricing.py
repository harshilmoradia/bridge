"""Estimated cost per tier for the tier comparison (E-03). USD per 1M tokens, (input, output).

Nano and Super: Nebius Token Factory list prices as shown by third-party aggregators on Oct 29, 2026
(typingmind.com and benchlm.ai list Nemotron 3 Nano 30B-A3B at 0.06 / 0.24 and Nemotron 3 Super
120B-A12B at 0.30 / 0.90). Not checked against tokenfactory.nebius.com.
Ultra: PLACEHOLDER. No published price was found for Nemotron 3 Ultra 550B-A55B; 1.00 / 3.00 is a
guess scaled from Super. Replace it before quoting Ultra's cost.
"""

from decimal import Decimal

PRICES_PER_MILLION: dict[str, tuple[Decimal, Decimal]] = {
    "nano": (Decimal("0.06"), Decimal("0.24")),
    "super": (Decimal("0.30"), Decimal("0.90")),
    "ultra": (Decimal("1.00"), Decimal("3.00")),  # placeholder, see above
}
PLACEHOLDER_TIERS: frozenset[str] = frozenset({"ultra"})  # tiers whose price above is a guess
MILLION = Decimal(1_000_000)
MICRO = Decimal("0.000001")


def estimate_cost(tokens_by_tier: dict[str, tuple[int, int]]) -> Decimal:
    """Total USD for (tokens_in, tokens_out) per tier, to the micro-dollar."""
    total = Decimal(0)
    for tier, (tokens_in, tokens_out) in tokens_by_tier.items():
        price_in, price_out = PRICES_PER_MILLION[tier]
        total += (tokens_in * price_in + tokens_out * price_out) / MILLION
    return total.quantize(MICRO)
