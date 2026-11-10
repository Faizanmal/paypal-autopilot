from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from sqlalchemy.dialects import postgresql

from app.core.errors import AppError
from app.modules.workflows.engine import reconcile_open_invoices


@pytest.mark.asyncio
async def test_reconciliation_reaches_later_batches_despite_payment_and_provider_failure(monkeypatch):
    rows = [SimpleNamespace(id=UUID(int=i), status="sent") for i in range(1, 28)]
    queries = []

    async def scalars(query):
        queries.append(query.compile(dialect=postgresql.dialect()).params)
        return [rows[:25], rows[25:], []][len(queries) - 1]

    session = SimpleNamespace(scalars=scalars, commit=AsyncMock())
    synced = []

    async def sync(_session, invoice, _client):
        synced.append(invoice.id)
        if invoice.id.int == 1:
            raise AppError("Provider temporarily unavailable")
        invoice.status = "paid"
        return True

    paid = AsyncMock()
    monkeypatch.setattr("app.modules.workflows.engine.get_settings", lambda: SimpleNamespace(paypal_configured=True))
    monkeypatch.setattr("app.modules.workflows.engine.get_paypal_client", lambda: object())
    monkeypatch.setattr("app.modules.autopilot.service.sync_invoice_from_provider", sync)
    monkeypatch.setattr("app.modules.workflows.engine.on_invoice_paid", paid)

    assert await reconcile_open_invoices(session) == {"checked": 27, "paid": 26, "unavailable": 1}
    assert synced == [row.id for row in rows]
    assert paid.await_count == 26
    assert rows[24].id in queries[1].values()
    assert rows[-1].id in queries[2].values()
