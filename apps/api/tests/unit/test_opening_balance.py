from decimal import Decimal

import pytest

from app.core.errors import ValidationFailedError
from app.modules.finance.service import _parse_opening


def test_opening_balance_rejects_negative_and_oversize_values():
    with pytest.raises(ValidationFailedError, match="negative"):
        _parse_opening("-1.00")
    with pytest.raises(ValidationFailedError, match="maximum"):
        _parse_opening("100000000.01")
    assert _parse_opening("0.00") == Decimal("0.00")
    assert _parse_opening("100000000.00") == Decimal("100000000.00")
