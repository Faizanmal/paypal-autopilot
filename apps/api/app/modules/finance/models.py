"""User-supplied cash assumptions. Payment records remain the source of received cash."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Numeric, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.columns import CURRENCY


class CashAssumption(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "cash_assumptions"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    currency_code: Mapped[str] = mapped_column(CURRENCY, nullable=False, default="USD", server_default="USD")
    opening_balance: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    as_of: Mapped[date | None] = mapped_column(Date, nullable=True)
