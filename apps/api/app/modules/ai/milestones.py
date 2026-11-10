"""Turn direct bulk milestone proposals into explicit, reviewable workflow steps."""

from __future__ import annotations

import re
from decimal import Decimal

from pydantic import ValidationError

from app.core.errors import ValidationFailedError
from app.core.money import money_to_api, parse_money
from app.modules.ai.schemas import ActionType, MilestonePlanDraft, PlanStepDraft, WorkflowPlanDraft

_COUNTS = {
    word: index
    for index, word in enumerate(
        ("one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve"), 1
    )
}


def requested_milestone_count(instruction: str) -> int | None:
    matches = re.findall(
        r"\b(\d+|" + "|".join(_COUNTS) + r")\s+(?:payment\s+)?milestones?\b", instruction, re.IGNORECASE
    )
    counts = {int(value) if value.isdigit() else _COUNTS[value.lower()] for value in matches}
    return counts.pop() if len(counts) == 1 else None


def expand_direct_milestones(draft: WorkflowPlanDraft, instruction: str) -> None:
    """No database identities enter this conversion. Dependencies remain step numbers."""
    sequences = [step.sequence for step in draft.steps]
    if len(sequences) != len(set(sequences)):
        raise ValidationFailedError("The plan repeats a step number.")
    if sequences != sorted(sequences):
        raise ValidationFailedError("Plan steps must be in sequence order.")
    for step in draft.steps:
        if any(dependency not in sequences or dependency >= step.sequence for dependency in step.depends_on):
            raise ValidationFailedError("A step depends on a missing earlier step.")
    expected = requested_milestone_count(instruction)
    projects = [step for step in draft.steps if step.action_type is ActionType.CREATE_PROJECT]
    expanded: list[PlanStepDraft] = []
    references: dict[int, int] = {}
    for step in draft.steps:
        dependencies = [references.get(value, value) for value in step.depends_on]
        if step.action_type is not ActionType.CREATE_MILESTONES or step.arguments.get("contract_name"):
            if step.action_type is ActionType.CREATE_MILESTONES and step.arguments.get("milestones"):
                raise ValidationFailedError("Choose contract-derived milestones or direct plan milestones, not both.")
            copied = step.model_copy(deep=True)
            copied.sequence = len(expanded) + 1
            copied.depends_on = dependencies
            expanded.append(copied)
            references[step.sequence] = copied.sequence
            continue
        parents = [project for project in projects if project.sequence in step.depends_on]
        if not parents:
            parents = [project for project in projects if project.sequence < step.sequence]
        if len(parents) != 1:
            raise ValidationFailedError("Direct milestones need one unambiguous earlier project step.")
        parent = parents[0]
        if parent.sequence >= step.sequence:
            raise ValidationFailedError("Milestones must depend on an earlier project step.")
        total, currency = parse_money(
            str(parent.arguments.get("amount", "")), str(parent.arguments.get("currency_code", ""))
        )
        raw = step.arguments.get("milestones")
        if raw is None or raw == []:
            count = step.arguments.get("milestone_count", expected)
            if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 12 or count != expected:
                raise ValidationFailedError("Provide the milestone names and amounts, or state a count from 1 to 12.")
            cents, remainder = divmod(int(total * 100), count)
            raw = [
                {
                    "name": f"Milestone {index + 1}",
                    "amount": money_to_api(Decimal(cents + (1 if index >= count - remainder else 0)) / 100),
                    "currency_code": currency,
                }
                for index in range(count)
            ]
        if not isinstance(raw, list) or not raw or len(raw) > 12:
            raise ValidationFailedError("Provide between 1 and 12 explicit milestones.")
        try:
            items = [MilestonePlanDraft.model_validate(item) for item in raw]
        except ValidationError as exc:
            raise ValidationFailedError(
                "Each milestone needs a name, decimal amount, currency, and valid optional date/trigger."
            ) from exc
        # Explicit rows become the same primitive tool steps used by the fallback planner.
        for item in items:
            copied = PlanStepDraft(
                sequence=len(expanded) + 1,
                action_type=ActionType.CREATE_MILESTONE,
                summary=f"Add {item.name} for {item.currency_code} {item.amount}.",
                arguments={
                    "milestone_name": item.name,
                    "amount": item.amount,
                    "currency_code": item.currency_code,
                    "trigger_kind": item.trigger_kind or "on_event",
                    **({"due_on": item.due_on.isoformat()} if item.due_on else {}),
                },
                depends_on=list(dict.fromkeys([references[parent.sequence], *dependencies])),
                preconditions=list(step.preconditions),
                requires_approval=step.requires_approval,
                read_only=step.read_only,
            )
            expanded.append(copied)
        references[step.sequence] = expanded[-1].sequence
    if len(expanded) > 50:
        raise ValidationFailedError("The expanded plan exceeds 50 steps.")
    draft.steps = expanded
