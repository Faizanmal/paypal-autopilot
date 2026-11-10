"""Turn an accepted milestone into one PayPal invoice draft.

The amount and customer come from the milestone and its project. A second call
returns the invoice already linked to that milestone.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import NotFoundError, ValidationFailedError
from app.integrations.paypal.client import PayPalClient
from app.modules.autopilot.models import Invoice
from app.modules.autopilot.schemas import InvoiceCreate
from app.modules.autopilot.service import create_invoice
from app.modules.identity.deps import Principal
from app.modules.trustflow.models import Milestone, Project


async def prepare_milestone_invoice(
    session: AsyncSession,
    principal: Principal,
    milestone_id: uuid.UUID,
    client: PayPalClient,
    settings: Settings,
) -> Invoice:
    milestone = await session.scalar(
        select(Milestone).where(Milestone.id == milestone_id, Milestone.workspace_id == principal.workspace_id)
    )
    if milestone is None:
        raise NotFoundError("Milestone not found.")
    project = await session.scalar(
        select(Project).where(Project.id == milestone.project_id, Project.workspace_id == principal.workspace_id)
    )
    if project is None or project.customer_id is None:
        raise ValidationFailedError("The project has no customer to bill.")
    existing = await session.scalar(select(Invoice).where(Invoice.milestone_id == milestone.id))
    if milestone.status != "accepted":
        if existing is not None and existing.paypal_invoice_id and existing.workspace_id == principal.workspace_id:
            return existing
        raise ValidationFailedError("Only an accepted milestone can generate an invoice draft.")
    return await create_invoice(
        session,
        principal,
        InvoiceCreate(
            customer_id=project.customer_id,
            project_id=project.id,
            milestone_id=milestone.id,
            currency_code=milestone.currency_code,
            amount=milestone.amount,
            description=milestone.name[:200],
            idempotency_key=f"milestone:{milestone.id}",
        ),
        client,
        settings,
    )
