"""Plan checks that run before any tool. Identity and policy come from the server."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

from app.core.config import SUPPORTED_CURRENCIES
from app.core.errors import ValidationFailedError
from app.core.money import parse_money
from app.modules.ai.schemas import (
    ALLOWED_ARGUMENT_KEYS,
    APPROVAL_ACTIONS,
    MONEY_ACTIONS,
    READ_ONLY_ACTIONS,
    ActionType,
    WorkflowPlanDraft,
)
from app.modules.ai.security import contains_injection, forbidden_argument_key


@dataclass
class ValidationResult:
    ok: bool
    code: str | None = None
    message: str | None = None
    clarifications: list[str] = field(default_factory=list)


def _mentioned(instruction: str, amount: str) -> bool:
    text = instruction.replace(",", "")
    value = Decimal(amount)
    tokens = {format(value.quantize(Decimal("0.01")), "f")}
    if value == value.to_integral_value():
        tokens.add(str(int(value)))
    return any(re.search(rf"(?<!\d){re.escape(token)}(?!\d)", text) for token in tokens)


def _fail(code: str, message: str, clarifications: list[str] | None = None) -> ValidationResult:
    return ValidationResult(ok=False, code=code, message=message, clarifications=clarifications or [message])


def validate_plan(draft: WorkflowPlanDraft, instruction: str) -> ValidationResult:
    if contains_injection(instruction) or contains_injection(draft.model_dump_json()):
        return _fail(
            "prompt_injection",
            "The plan included instructions to override policy or payment status. Nothing was executed.",
        )
    sequences = [step.sequence for step in draft.steps]
    if len(sequences) != len(set(sequences)):
        return _fail("invalid_plan", "The plan repeats a step number. Nothing was executed.")
    by_sequence = {step.sequence: step for step in draft.steps}
    for step in draft.steps:
        if step.action_type is ActionType.PREPARE_PAYOUT and not step.requires_approval:
            return _fail(
                "policy_bypass",
                "A payout step tried to skip approval. The approval policy was not changed and nothing was executed.",
            )
        if step.action_type in APPROVAL_ACTIONS and not step.requires_approval:
            return _fail(
                "policy_bypass",
                "An approval step tried to skip the approval policy. Nothing was executed.",
            )
        if step.read_only != (step.action_type in READ_ONLY_ACTIONS):
            return _fail("invalid_plan", "A step was marked with the wrong execution mode. Nothing was executed.")
        for key in step.arguments:
            if forbidden_argument_key(key) or key not in ALLOWED_ARGUMENT_KEYS:
                return _fail(
                    "untrusted_argument",
                    "The plan included an identity, secret, or unsupported field. Nothing was executed.",
                )
        for key, value in step.arguments.items():
            if isinstance(value, str) and contains_injection(value):
                return _fail("prompt_injection", "A plan field included override instructions. Nothing was executed.")
            if isinstance(value, bool):
                if key != "name_is_default":
                    return _fail("invalid_plan", "A plan field had an unsupported value. Nothing was executed.")
                continue
            if not isinstance(value, str | int):
                return _fail("invalid_plan", "A plan field had an unsupported value. Nothing was executed.")
        for dependency in step.depends_on:
            earlier = by_sequence.get(dependency)
            if earlier is None or earlier.sequence >= step.sequence:
                return _fail("invalid_plan", "A step depends on a missing earlier step. Nothing was executed.")
        if step.action_type in MONEY_ACTIONS:
            amount = step.arguments.get("amount")
            currency = step.arguments.get("currency_code")
            if isinstance(amount, bool | float):
                return _fail("invalid_amount", "Amount must be a decimal string. Nothing was executed.")
            if isinstance(amount, int):
                amount = f"{amount}.00"
                step.arguments["amount"] = amount
            if not isinstance(amount, str) or not isinstance(currency, str):
                return _fail(
                    "missing_amount",
                    "A financial step is missing an amount or currency.",
                    ["Provide the amount and currency. This workspace accepts USD."],
                )
            if currency.upper() not in SUPPORTED_CURRENCIES:
                return _fail("unsupported_currency", f"Currency {currency} is not supported. Nothing was executed.")
            try:
                parse_money(amount, currency)
            except ValidationFailedError:
                return _fail("invalid_amount", "A financial step has an invalid amount. Nothing was executed.")
            if currency.upper() == "USD" and "$" not in instruction and not re.search(r"\bUSD\b", instruction):
                return _fail(
                    "missing_currency",
                    "A plan used USD even though the instruction did not state a currency.",
                    ["Which currency should this use? This workspace accepts USD."],
                )
            if not _amount_grounded(draft, instruction, step.sequence, amount):
                return _fail(
                    "ungrounded_amount",
                    "A plan used an amount the instruction did not state. Nothing was executed.",
                )
    for project in draft.steps:
        if project.action_type is not ActionType.CREATE_PROJECT:
            continue
        milestones = [
            step for step in draft.steps
            if step.action_type is ActionType.CREATE_MILESTONE and project.sequence in step.depends_on
        ]
        if milestones and (
            any(step.arguments["currency_code"].upper() != project.arguments["currency_code"].upper()
                for step in milestones)
            or sum(Decimal(step.arguments["amount"]) for step in milestones) != Decimal(project.arguments["amount"])
        ):
            return _fail("invalid_plan", "Milestone amounts must sum to the project total in the same currency.")
    return ValidationResult(ok=True)


def _amount_grounded(draft: WorkflowPlanDraft, instruction: str, sequence: int, amount: str) -> bool:
    if _mentioned(instruction, amount):
        return True
    step = next(item for item in draft.steps if item.sequence == sequence)
    if step.action_type is not ActionType.CREATE_MILESTONE or not step.depends_on:
        return False
    parent = next((item for item in draft.steps if item.sequence == step.depends_on[0]), None)
    if parent is None or parent.action_type is not ActionType.CREATE_PROJECT:
        return False
    total = parent.arguments.get("amount")
    if not isinstance(total, str) or not _mentioned(instruction, total):
        return False
    siblings = [
        item.arguments.get("amount")
        for item in draft.steps
        if item.action_type is ActionType.CREATE_MILESTONE and item.depends_on[:1] == [parent.sequence]
    ]
    if not all(isinstance(item, str) for item in siblings):
        return False
    try:
        return sum(parse_money(str(item), "USD")[0] for item in siblings) == Decimal(total)
    except ValidationFailedError:
        return False
