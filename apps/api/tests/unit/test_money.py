from decimal import Decimal

import pytest

from app.core.errors import ValidationFailedError
from app.core.money import parse_money


def test_parses_usd_decimal_string():
    amount, currency = parse_money("10.10", "usd")
    assert amount == Decimal("10.10")
    assert currency == "USD"
    assert isinstance(amount, Decimal)


def test_rejects_binary_float():
    with pytest.raises(ValidationFailedError, match="binary float"):
        parse_money(10.1, "USD")


def test_rejects_extra_precision():
    with pytest.raises(ValidationFailedError, match="2 decimal"):
        parse_money("10.001", "USD")


def test_rejects_non_positive_and_unsupported_currency():
    with pytest.raises(ValidationFailedError, match="greater than zero"):
        parse_money("0.00", "USD")
    with pytest.raises(ValidationFailedError, match="not supported"):
        parse_money("1.00", "JPY")


@pytest.mark.parametrize("amount", ["NaN", "sNaN", "Infinity", "-Infinity", "1e100000", "1000000000000"])
def test_rejects_non_finite_and_database_overflow(amount):
    with pytest.raises(ValidationFailedError):
        parse_money(amount, "USD")


def test_accepts_largest_database_amount():
    assert parse_money("999999999999.99", "USD")[0] == Decimal("999999999999.99")
