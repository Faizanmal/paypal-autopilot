"""Plan checks that run before any tool. Identity and policy come from the server."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

from pydantic import ValidationError

from app.core.config import SUPPORTED_CURRENCIES
from app.core.errors import ValidationFailedError
from app.core.money import parse_money
from app.modules.ai.milestones import expand_direct_milestones, requested_milestone_count
from app.modules.ai.schemas import (
    ALLOWED_ARGUMENT_KEYS,
    APPROVAL_ACTIONS,
    MONEY_ACTIONS,
    READ_ONLY_ACTIONS,
    ActionType,
    MilestonePlanDraft,
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
    normalization = sanitize_plan_arguments(draft, instruction)
    if not normalization.ok:
        return normalization
    # Some compatible providers return a CREATE_MILESTONE step with its
    # proposed rows nested under ``milestones`` instead of scalar tool fields.
    # Flatten a single row before the ordinary amount/currency validation.
    projects = {step.sequence: step for step in draft.steps if step.action_type is ActionType.CREATE_PROJECT}
    for step in draft.steps:
        rows = step.arguments.get("milestones")
        if step.action_type is not ActionType.CREATE_MILESTONE or not isinstance(rows, list):
            continue
        name = str(step.arguments.get("milestone_name") or "").strip().casefold()
        matches = [
            row
            for row in rows
            if isinstance(row, dict)
            and str(row.get("name") or row.get("milestone_name") or "").strip().casefold() == name
        ]
        if len(matches) != 1:
            return _fail("missing_required", "Each milestone needs one explicit row with an amount.")
        row = matches[0]
        step.arguments["amount"] = row.get("amount")
        step.arguments["currency_code"] = row.get("currency_code") or row.get("currency")
        if not step.arguments["currency_code"]:
            parents = [projects[value] for value in step.depends_on if value in projects]
            if len(parents) == 1:
                step.arguments["currency_code"] = parents[0].arguments.get("currency_code")
        step.arguments.pop("milestones", None)
    try:
        expand_direct_milestones(draft, instruction)
    except (ValidationFailedError, ValidationError) as exc:
        message = exc.message if isinstance(exc, ValidationFailedError) else "The milestone plan is invalid."
        return _fail("missing_required", message)
    return _validate_sanitized_plan(draft, instruction)


def sanitize_plan_arguments(draft: WorkflowPlanDraft, instruction: str) -> ValidationResult:
    """Normalize provider formatting only; identities and policy remain server-owned.

    Scan unknown values for injection before discarding them. Empty identifiers
    are harmless model placeholders; false/zero/nonempty collections are not.
    Date aliases are accepted only for a milestone's allowlisted due_on field.
    """

    def strip_empty_identities(arguments):
        if isinstance(arguments, list):
            return all(strip_empty_identities(value) for value in arguments)
        if not isinstance(arguments, dict):
            return True
        for key, value in list(arguments.items()):
            if forbidden_argument_key(key):
                if value is None or (isinstance(value, str) and not value.strip()):
                    del arguments[key]
                else:
                    return False
            elif not strip_empty_identities(value):
                return False
        return True

    cleaned = draft.model_copy(deep=True)
    for step in cleaned.steps:
        if not strip_empty_identities(step.arguments):
            return _fail("untrusted_argument", "The plan included an identity or secret. Nothing was executed.")
    if contains_injection(instruction) or contains_injection(cleaned.model_dump_json()):
        return _fail(
            "prompt_injection",
            "The plan included instructions to override policy or payment status. Nothing was executed.",
        )
    name_targets = {
        ActionType.CREATE_PROJECT: "project_name",
        ActionType.GET_PROJECT_STATUS: "project_name",
        ActionType.CREATE_MILESTONE: "milestone_name",
        ActionType.LOOKUP_CUSTOMER: "customer_name",
        ActionType.PREPARE_PAYOUT: "recipient_name",
        ActionType.EXPLAIN_POLICY: "recipient_name",
        ActionType.RESUME_PAYOUT: "recipient_name",
        ActionType.ANALYZE_CONTRACT: "contract_name",
    }
    for step in cleaned.steps:
        arguments = step.arguments
        aliases = {"currency": "currency_code"}
        if step.action_type in name_targets:
            aliases["name"] = name_targets[step.action_type]
        if step.action_type is ActionType.CREATE_MILESTONE:
            # Legacy providers often add an unsolicited due_date. Only promote
            # a date alias when it is actually grounded in the instruction.
            aliases.update(
                {
                    key: "due_on"
                    for key in ("date", "due_date")
                    if isinstance(arguments.get(key), str) and arguments[key] in instruction
                }
            )
        for alias, target in aliases.items():
            value = arguments.get(alias)
            if value is None or value == "":
                continue
            existing = arguments.get(target)
            if existing is not None and existing != "" and existing != value:
                return _fail("ambiguous", f"Conflicting {alias} and {target} values need clarification.")
            arguments[target] = value
        step.arguments = {
            key: value
            for key, value in arguments.items()
            if key in ALLOWED_ARGUMENT_KEYS and value is not None and not (key == "milestones" and value == [])
        }
    for original, normalized in zip(draft.steps, cleaned.steps, strict=True):
        original.arguments = normalized.arguments
    return ValidationResult(ok=True)


def _validate_sanitized_plan(draft: WorkflowPlanDraft, instruction: str) -> ValidationResult:
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
        if step.action_type is ActionType.CREATE_MILESTONE:
            parents = [
                by_sequence[value]
                for value in step.depends_on
                if value in by_sequence and by_sequence[value].action_type is ActionType.CREATE_PROJECT
            ]
            if len(parents) != 1:
                return _fail("missing_required", "Each direct milestone must reference exactly one project step.")
            try:
                item = MilestonePlanDraft.model_validate(
                    {
                        "name": step.arguments.get("milestone_name"),
                        "amount": str(step.arguments.get("amount", "")),
                        "currency_code": step.arguments.get("currency_code"),
                        "trigger_kind": step.arguments.get("trigger_kind"),
                        "due_on": step.arguments.get("due_on") or None,
                    }
                )
            except ValidationError:
                return _fail(
                    "missing_required", "Each milestone needs a name, amount, currency, and valid date/trigger."
                )
            step.arguments["trigger_kind"] = item.trigger_kind or "on_event"
            if item.due_on:
                if item.due_on.isoformat() not in instruction:
                    return _fail("missing_required", "State milestone due dates explicitly as ISO dates.")
                step.arguments["due_on"] = item.due_on.isoformat()
            else:
                step.arguments.pop("due_on", None)
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
    for project in draft.steps:
        if project.action_type is not ActionType.CREATE_PROJECT:
            continue
        milestones = [
            step
            for step in draft.steps
            if step.action_type is ActionType.CREATE_MILESTONE and project.sequence in step.depends_on
        ]
        expected = requested_milestone_count(instruction)
        if (
            expected is not None
            and len(milestones) != expected
            and len([s for s in draft.steps if s.action_type is ActionType.CREATE_PROJECT]) == 1
        ):
            return _fail("missing_required", "The plan must explicitly include every requested milestone.")
        names = [str(step.arguments["milestone_name"]).strip().casefold() for step in milestones]
        if len(names) != len(set(names)) or any(not name for name in names):
            return _fail("invalid_plan", "Milestone names must be nonempty and unique within a project.")
        if milestones and (
            any(
                step.arguments["currency_code"].upper() != project.arguments["currency_code"].upper()
                for step in milestones
            )
            or sum(Decimal(step.arguments["amount"]) for step in milestones) != Decimal(project.arguments["amount"])
        ):
            return _fail("invalid_plan", "Milestone amounts must sum to the project total in the same currency.")
    for step in draft.steps:
        if step.action_type in MONEY_ACTIONS and not _amount_grounded(
            draft, instruction, step.sequence, str(step.arguments["amount"])
        ):
            return _fail(
                "ungrounded_amount", "A plan used an amount the instruction did not state. Nothing was executed."
            )
    return ValidationResult(ok=True)


def _amount_grounded(draft: WorkflowPlanDraft, instruction: str, sequence: int, amount: str) -> bool:
    if _mentioned(instruction, amount):
        return True
    step = next(item for item in draft.steps if item.sequence == sequence)
    if step.action_type is not ActionType.CREATE_MILESTONE or not step.depends_on:
        return False
    if requested_milestone_count(instruction) is None:
        return False
    parent = next(
        (
            item
            for item in draft.steps
            if item.sequence in step.depends_on and item.action_type is ActionType.CREATE_PROJECT
        ),
        None,
    )
    if parent is None or parent.action_type is not ActionType.CREATE_PROJECT:
        return False
    total = parent.arguments.get("amount")
    if not isinstance(total, str) or not _mentioned(instruction, total):
        return False
    siblings = [
        item.arguments.get("amount")
        for item in draft.steps
        if item.action_type is ActionType.CREATE_MILESTONE and parent.sequence in item.depends_on
    ]
    if not all(isinstance(item, str) for item in siblings):
        return False
    try:
        return sum(parse_money(str(item), "USD")[0] for item in siblings) == Decimal(total)
    except ValidationFailedError:
        return False
