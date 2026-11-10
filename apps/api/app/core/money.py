"""Currency-aware decimal money.

Monetary values are `decimal.Decimal` in Python and `NUMERIC(14, 2)` in
PostgreSQL. Binary floats are rejected. MVP accepts USD only.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from app.core.config import MONEY_QUANTIZE, SUPPORTED_CURRENCIES
from app.core.errors import ValidationFailedError


def parse_money(amount: Decimal | str | int, currency_code: str) -> tuple[Decimal, str]:
    """Return a quantized positive amount and a normalized currency code."""
    if isinstance(amount, float):
        raise ValidationFailedError("Amount must not be a binary float.")
    currency = currency_code.strip().upper()
    if currency not in SUPPORTED_CURRENCIES:
        raise ValidationFailedError(
            f"Currency {currency} is not supported.",
            details={"currency_code": currency, "supported": sorted(SUPPORTED_CURRENCIES)},
        )
    try:
        value = amount if isinstance(amount, Decimal) else Decimal(str(amount))
    except (InvalidOperation, ValueError) as exc:
        raise ValidationFailedError("Amount is not a decimal value.") from exc
    if value.is_nan() or value.is_infinite() or not value.is_finite():
        raise ValidationFailedError("Amount must be a finite decimal.")
    if value <= 0 or value >= Decimal("1000000000000"):
        raise ValidationFailedError("Amount must be greater than zero and less than 1,000,000,000,000.")
    if value != value.quantize(MONEY_QUANTIZE):
        raise ValidationFailedError("Amount must have at most 2 decimal places.")
    quantized = value.quantize(MONEY_QUANTIZE)
    if quantized <= 0:
        raise ValidationFailedError("Amount must be greater than zero.")
    return quantized, currency


def money_to_api(amount: Decimal) -> str:
    """PayPal amount values are decimal strings, never binary floats."""
    return format(amount.quantize(MONEY_QUANTIZE), "f")
