"""Shared column types for money and identifiers."""

from __future__ import annotations

from sqlalchemy import Numeric, String

MONEY = Numeric(14, 2)
CURRENCY = String(3)
