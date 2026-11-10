"""Deterministic language understanding. This replaces an LLM only for planning."""

from __future__ import annotations

import re
from decimal import Decimal

from app.core.config import SUPPORTED_CURRENCIES
from app.modules.ai.schemas import (
    ActionType,
    EntityMention,
    PlanStepDraft,
    WorkflowPlanDraft,
    WorkflowPlanningContext,
    WorkflowPlanResult,
)
from app.modules.ai.security import injection_rejection

FALLBACK_LABEL = "Fallback parser (no AI provider configured)"
DEFAULT_PROJECT_NAME = "Payment milestones"

_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "thirty": 30,
}
_MONEY = (
    r"(?:\$\s*(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
    r"|[A-Za-z]{3}\s*(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
    r"|(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\s*[A-Za-z]{3}"
    r"|(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)"
)
_INVOICE = re.compile(
    rf"^invoice\s+(?P<customer>.+?)\s+(?P<money>{_MONEY})(?:\s+for\s+(?P<description>.+))?$",
    re.IGNORECASE,
)
_INVOICE_BARE = re.compile(
    r"^invoice\s+(?P<customer>.+?)(?:\s+for\s+(?P<description>.+))?$",
    re.IGNORECASE,
)
_REMIND = re.compile(
    r"^remind\s+(?P<customer>.+?)\s+in\s+(?P<days>[a-z0-9-]+)\s+days?\b(?P<rest>.*)$",
    re.IGNORECASE,
)
_PROJECT = re.compile(
    rf"^create\s+(?:a\s+|an\s+)?(?:(?P<money>{_MONEY})\s+)?project\b(?P<rest>.*)$",
    re.IGNORECASE,
)
_PAY = re.compile(
    rf"^pay\s+(?:my\s+)?(?P<recipient>.+?)\s+(?P<money>{_MONEY})(?P<rest>.*)$",
    re.IGNORECASE,
)
_PREPARE_PAYOUT = re.compile(
    rf"^(?:prepare|create|draft)\s+(?:a\s+|an\s+)?"
    rf"(?:(?P<money>{_MONEY})\s+)?(?:contractor\s+)?payout\s+"
    rf"(?:of\s+(?P<money2>{_MONEY})\s+)?"
    rf"to\s+(?:my\s+)?(?P<recipient>.+)$",
    re.IGNORECASE,
)
_OVERDUE = re.compile(
    r"\b(?:show|list|find|get)\b.*\boverdue\b.*?(?P<days>\d+|[a-zA-Z-]+)\s+days?\b",
    re.IGNORECASE,
)
_SUMMARY = re.compile(r"\b(?:financial\s+summary|summarize(?:\s+my)?\s+finances)\b", re.IGNORECASE)
_LOOKUP = re.compile(r"^(?:look\s+up|find|show)\s+customer\s+(?P<name>.+)$", re.IGNORECASE)
_ANALYZE = re.compile(r"^analyze\s+the\s+contract\s+(?P<name>.+)$", re.IGNORECASE)
_FROM_CONTRACT = re.compile(r"^create\s+milestones\s+from\s+the\s+contract\s+(?P<name>.+)$", re.IGNORECASE)
_PROJECT_STATUS = re.compile(r"^show\s+the\s+status\s+of\s+project\s+(?P<name>.+)$", re.IGNORECASE)
_MILESTONE_INVOICE = re.compile(
    r"^prepare\s+an\s+invoice\s+for\s+the\s+accepted\s+milestone\s+(?P<milestone>.+?)\s+on\s+(?P<project>.+)$",
    re.IGNORECASE,
)
_EXPLAIN = re.compile(
    rf"^(?:explain why|why is)\s+(?:a\s+)?(?P<money>{_MONEY})\s+payout\s+to\s+(?P<recipient>.+?)(?:\s+is\s+blocked)?$",
    re.IGNORECASE,
)
_SAFER = re.compile(
    rf"^suggest\s+a\s+safer\s+(?:alternative|payout)\s+(?:than\s+)?(?:a\s+|an\s+)?(?P<money>{_MONEY})"
    rf"(?:\s+payout)?\s+to\s+(?P<recipient>.+)$",
    re.IGNORECASE,
)
_RESUME = re.compile(
    r"^resume\s+the\s+payout(?:\s+workflow)?(?:\s+to\s+(?P<recipient>.+?))?(?:\s+after\s+approval)?$",
    re.IGNORECASE,
)


class _ParseStop(Exception):
    def __init__(self, code: str, message: str, clarifications: list[str] | None = None) -> None:
        self.code = code
        self.message = message
        self.clarifications = clarifications or []


def _count(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    return _WORDS.get(token.lower())


def _money(token: str) -> tuple[str, str]:
    raw = token.strip()
    currency: str | None = None
    if raw.startswith("$"):
        currency = "USD"
        raw = raw[1:].strip()
    coded = re.fullmatch(r"([A-Za-z]{3})\s+(.+)", raw)
    if coded:
        currency = coded.group(1).upper()
        raw = coded.group(2).strip()
    else:
        trailed = re.fullmatch(r"(.+?)\s+([A-Za-z]{3})", raw)
        if trailed:
            raw = trailed.group(1).strip()
            currency = trailed.group(2).upper()
    number = raw.replace(",", "")
    if not re.fullmatch(r"\d+(?:\.\d+)?", number):
        raise _ParseStop(
            "invalid_amount",
            "The amount is not a decimal value.",
            ["Enter the amount in dollars and cents."],
        )
    value = Decimal(number)
    if value != value.quantize(Decimal("0.01")) or value <= 0:
        raise _ParseStop(
            "invalid_amount",
            "The amount must be a positive value with at most 2 decimal places.",
            ["Enter a positive amount with at most 2 decimal places."],
        )
    if currency is None:
        raise _ParseStop(
            "missing_currency",
            "The instruction states an amount without a currency.",
            ["Which currency should this use? This workspace accepts USD."],
        )
    if currency not in SUPPORTED_CURRENCIES:
        raise _ParseStop(
            "unsupported_currency",
            f"Currency {currency} is not supported. This workspace accepts USD.",
        )
    return format(value.quantize(Decimal("0.01")), "f"), currency


def _sentences(instruction: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", instruction.strip())
    return [part.strip(" .") for part in parts if part.strip(" .")]


def _add(steps: list[PlanStepDraft], **kwargs: object) -> PlanStepDraft:
    step = PlanStepDraft.model_validate({"sequence": len(steps) + 1, **kwargs})
    steps.append(step)
    return step


def _invoice(sentence: str, steps: list[PlanStepDraft]) -> None:
    matched = _INVOICE.match(sentence)
    if matched is None:
        bare = _INVOICE_BARE.match(sentence)
        customer = bare.group("customer").strip() if bare else "the customer"
        raise _ParseStop(
            "missing_amount",
            f"The invoice for {customer} has no amount.",
            [f"What amount and currency should the invoice for {customer} use?"],
        )
    amount, currency = _money(matched.group("money"))
    customer = matched.group("customer").strip()
    description = (matched.group("description") or "Services").strip()
    _add(
        steps,
        action_type=ActionType.DRAFT_INVOICE,
        summary=f"Draft a {currency} {amount} invoice for {customer}.",
        arguments={
            "customer_name": customer,
            "amount": amount,
            "currency_code": currency,
            "description": description[:200],
        },
        depends_on=[],
        preconditions=[],
        requires_approval=False,
        read_only=False,
    )


def _remind(sentence: str, steps: list[PlanStepDraft]) -> None:
    matched = _REMIND.match(sentence)
    if matched is None:
        raise _ParseStop(
            "missing_required",
            "The reminder is missing a customer or a number of days.",
            ["Who should be reminded, and in how many days?"],
        )
    days = _count(matched.group("days"))
    if days is None or days < 1 or days > 365:
        raise _ParseStop(
            "missing_required",
            "The reminder needs a number of days between 1 and 365.",
            ["In how many days should the reminder run?"],
        )
    customer = matched.group("customer").strip()
    invoice_steps = [step.sequence for step in steps if step.action_type is ActionType.DRAFT_INVOICE]
    _add(
        steps,
        action_type=ActionType.SCHEDULE_REMINDER,
        summary=f"Schedule a reminder for {customer} in {days} days if the invoice is still unpaid.",
        arguments={"customer_name": customer, "days": days},
        depends_on=invoice_steps[-1:],
        preconditions=["invoice remains unpaid"],
        requires_approval=False,
        read_only=False,
    )


def _split(total: str, count: int) -> list[str]:
    cents = int((Decimal(total) * 100).to_integral_value())
    base, extra = divmod(cents, count)
    amounts = [Decimal(base) / Decimal(100) for _ in range(count)]
    for index in range(extra):
        amounts[count - 1 - index] += Decimal("0.01")
    return [format(amount.quantize(Decimal("0.01")), "f") for amount in amounts]


def _project_customer(rest: str) -> str | None:
    """Pull a customer label from trailing 'for Acme' phrasing without eating amounts."""
    for pattern in (
        r"\bfor\s+customer\s+(.+?)\s*$",
        r"\b(?:with|for)\s+client\s+(.+?)\s*$",
        r"\bfor\s+(.+?)\s*$",
    ):
        matched = re.search(pattern, rest, re.IGNORECASE)
        if matched is None:
            continue
        candidate = matched.group(1).strip(" .,")
        if not candidate:
            continue
        # Amounts / currency tokens are not customer names.
        if re.fullmatch(_MONEY, candidate, re.IGNORECASE):
            continue
        if re.fullmatch(r"[A-Za-z]{3}", candidate):
            continue
        if re.search(r"payment\s+milestones?", candidate, re.IGNORECASE):
            continue
        return candidate[:160]
    return None


def _project(sentence: str, steps: list[PlanStepDraft]) -> None:
    matched = _PROJECT.match(sentence)
    if matched is None or not matched.group("money"):
        raise _ParseStop(
            "missing_amount",
            "The project instruction has no amount.",
            ["What is the project total, and which currency should it use?"],
        )
    amount, currency = _money(matched.group("money"))
    rest = matched.group("rest") or ""
    named = re.search(r"(?:called|named)\s+(.+?)(?:\s+with\b|$)", rest, re.IGNORECASE)
    name = named.group(1).strip(" .") if named else DEFAULT_PROJECT_NAME
    count_match = re.search(r"with\s+([a-z0-9-]+)\s+payment\s+milestones?", rest, re.IGNORECASE)
    customer_name = _project_customer(rest)
    arguments: dict = {
        "project_name": name[:200],
        "amount": amount,
        "currency_code": currency,
        "description": "Created from a confirmed agent plan.",
        "name_is_default": named is None,
    }
    if customer_name:
        arguments["customer_name"] = customer_name
    summary = (
        f"Create project {name} for {currency} {amount}"
        if named
        else f"Create a {currency} {amount} project. The instruction did not name it, so the title is {name}"
    )
    summary = f"{summary} for {customer_name}." if customer_name else f"{summary}."
    project = _add(
        steps,
        action_type=ActionType.CREATE_PROJECT,
        summary=summary,
        arguments=arguments,
        depends_on=[],
        preconditions=[],
        requires_approval=False,
        read_only=False,
    )
    if count_match is None:
        return
    count = _count(count_match.group(1))
    if count is None or count < 1 or count > 12:
        raise _ParseStop(
            "missing_required",
            "The project needs a milestone count between 1 and 12.",
            ["How many payment milestones should this project have?"],
        )
    triggers = [
        "upfront" if index == 0 else "on_delivery" if index == count - 1 else "on_event"
        for index in range(count)
    ]
    for index, (share, trigger) in enumerate(zip(_split(amount, count), triggers, strict=True), start=1):
        _add(
            steps,
            action_type=ActionType.CREATE_MILESTONE,
            summary=f"Add milestone {index} for {currency} {share} ({trigger}).",
            arguments={
                "milestone_name": f"Milestone {index}",
                "amount": share,
                "currency_code": currency,
                "trigger_kind": trigger,
            },
            depends_on=[project.sequence],
            preconditions=["project exists"],
            requires_approval=False,
            read_only=False,
        )


def _explain(money: str, recipient: str, steps: list[PlanStepDraft]) -> None:
    amount, currency = _money(money)
    name = recipient.strip()
    _add(
        steps,
        action_type=ActionType.EXPLAIN_POLICY,
        summary=(
            f"Explain whether a {currency} {amount} payout to {name} is allowed and suggest a safer amount. "
            "This does not change workspace limits or send money."
        ),
        arguments={"recipient_name": name, "amount": amount, "currency_code": currency},
        depends_on=[],
        preconditions=[],
        requires_approval=False,
        read_only=True,
    )


def _resume(recipient: str | None, steps: list[PlanStepDraft]) -> None:
    if not recipient or not recipient.strip():
        raise _ParseStop(
            "missing_required",
            "The resume request needs the payout recipient.",
            ["Which recipient should the payout workflow resume for?"],
        )
    name = recipient.strip()
    _add(
        steps,
        action_type=ActionType.RESUME_PAYOUT,
        summary=(
            f"Check whether the payout to {name} still has a valid approval. "
            "This does not approve the payout or send money."
        ),
        arguments={"recipient_name": name},
        depends_on=[],
        preconditions=[],
        requires_approval=False,
        read_only=True,
    )


def _pay(sentence: str, steps: list[PlanStepDraft]) -> None:
    matched = _PAY.match(sentence) or _PREPARE_PAYOUT.match(sentence)
    if matched is None:
        raise _ParseStop(
            "missing_required",
            "The payout instruction needs a recipient and an amount.",
            ["Who should be paid, how much, and in which currency?"],
        )
    money = matched.groupdict().get("money") or matched.groupdict().get("money2")
    if not money:
        raise _ParseStop(
            "missing_amount",
            "The payout instruction has no amount.",
            ["How much should be paid, and in which currency?"],
        )
    amount, currency = _money(money)
    recipient_raw = matched.group("recipient").strip().rstrip(".")
    rest_match = re.search(
        r"^(?P<name>.+?)(?:\s+(?P<rest>\b(?:after|once|when|if)\b.+))?$",
        recipient_raw,
        re.IGNORECASE,
    )
    recipient = (rest_match.group("name") if rest_match else recipient_raw).strip()
    rest = (rest_match.group("rest") if rest_match else "") or ""
    # _PAY captures rest separately; keep that path working.
    if "rest" in matched.groupdict() and matched.groupdict().get("rest"):
        rest = matched.group("rest") or rest
    recipient = re.sub(r"^(?:my\s+)?(?:contractor\s+)?", "", recipient, flags=re.IGNORECASE).strip()
    if not recipient:
        raise _ParseStop(
            "missing_required",
            "The payout instruction needs a recipient.",
            ["Who should receive the payout?"],
        )
    waits_for_payment = re.search(r"\b(?:after|clears|cleared|verified)\b", rest, re.IGNORECASE)
    preconditions = ["client payment cleared"] if waits_for_payment else []
    invoice_steps = [step.sequence for step in steps if step.action_type is ActionType.DRAFT_INVOICE]
    payout = _add(
        steps,
        action_type=ActionType.PREPARE_PAYOUT,
        summary=(
            f"Prepare a {currency} {amount} payout to {recipient}. "
            "This creates an approval request and does not send money."
        ),
        arguments={
            "recipient_name": recipient,
            "amount": amount,
            "currency_code": currency,
            "note": "Prepared by the finance agent after confirmation.",
        },
        depends_on=invoice_steps[-1:] if waits_for_payment else [],
        preconditions=preconditions,
        requires_approval=True,
        read_only=False,
    )
    _add(
        steps,
        action_type=ActionType.CREATE_APPROVAL,
        summary="Record the pending approval for that payout. The agent cannot approve or send it.",
        arguments={"recipient_name": recipient},
        depends_on=[payout.sequence],
        preconditions=["payout intent exists"],
        requires_approval=True,
        read_only=False,
    )


def _overdue(sentence: str, steps: list[PlanStepDraft]) -> None:
    matched = _OVERDUE.search(sentence)
    if matched is None:
        raise _ParseStop(
            "missing_required",
            "The overdue request needs a number of days.",
            ["How many days overdue should the invoice list use?"],
        )
    days = _count(matched.group("days"))
    if days is None or days < 1 or days > 3650:
        raise _ParseStop(
            "missing_required",
            "The overdue window needs a number of days.",
            ["How many days overdue should the invoice list use?"],
        )
    _add(
        steps,
        action_type=ActionType.LOOKUP_INVOICE_STATUS,
        summary=f"List invoices overdue by more than {days} days.",
        arguments={"min_days_overdue": days},
        depends_on=[],
        preconditions=[],
        requires_approval=False,
        read_only=True,
    )


def _one(sentence: str, steps: list[PlanStepDraft]) -> None:
    lowered = sentence.lower()
    analyzed = _ANALYZE.match(sentence)
    if analyzed:
        name = analyzed.group("name").strip()
        _add(
            steps,
            action_type=ActionType.ANALYZE_CONTRACT,
            summary=f"Read the extracted terms of contract {name}. This is not a legal verification.",
            arguments={"contract_name": name},
            depends_on=[],
            preconditions=[],
            requires_approval=False,
            read_only=True,
        )
        return
    from_contract = _FROM_CONTRACT.match(sentence)
    if from_contract:
        name = from_contract.group("name").strip()
        _add(
            steps,
            action_type=ActionType.CREATE_MILESTONES,
            summary=f"Create draft milestones from the reviewed extraction of {name}.",
            arguments={"contract_name": name},
            depends_on=[],
            preconditions=["contract extraction has no blocking findings"],
            requires_approval=False,
            read_only=False,
        )
        return
    status = _PROJECT_STATUS.match(sentence)
    if status:
        name = status.group("name").strip()
        _add(
            steps,
            action_type=ActionType.GET_PROJECT_STATUS,
            summary=f"Read milestone and billing progress for {name}.",
            arguments={"project_name": name},
            depends_on=[],
            preconditions=[],
            requires_approval=False,
            read_only=True,
        )
        return
    milestone_invoice = _MILESTONE_INVOICE.match(sentence)
    if milestone_invoice:
        milestone = milestone_invoice.group("milestone").strip()
        project = milestone_invoice.group("project").strip()
        _add(
            steps,
            action_type=ActionType.PREPARE_MILESTONE_INVOICE,
            summary=f"Prepare a PayPal invoice draft for accepted milestone {milestone} on {project}.",
            arguments={"milestone_name": milestone, "project_name": project},
            depends_on=[],
            preconditions=["milestone is accepted"],
            requires_approval=False,
            read_only=False,
        )
        return
    explained = _EXPLAIN.match(sentence) or _SAFER.match(sentence)
    if explained:
        _explain(explained.group("money"), explained.group("recipient"), steps)
        return
    resumed = _RESUME.match(sentence)
    if resumed:
        _resume(resumed.group("recipient"), steps)
        return
    if lowered.startswith("invoice "):
        _invoice(sentence, steps)
        return
    if lowered.startswith("remind "):
        _remind(sentence, steps)
        return
    if lowered.startswith("create ") and "project" in lowered:
        _project(sentence, steps)
        return
    if lowered.startswith("pay ") or _PREPARE_PAYOUT.match(sentence):
        _pay(sentence, steps)
        return
    if _OVERDUE.search(sentence):
        _overdue(sentence, steps)
        return
    if _SUMMARY.search(sentence):
        _add(
            steps,
            action_type=ActionType.FINANCIAL_SUMMARY,
            summary="Read the workspace financial summary.",
            arguments={},
            depends_on=[],
            preconditions=[],
            requires_approval=False,
            read_only=True,
        )
        return
    lookup = _LOOKUP.match(sentence)
    if lookup:
        name = lookup.group("name").strip()
        _add(
            steps,
            action_type=ActionType.LOOKUP_CUSTOMER,
            summary=f"Look up customer {name}.",
            arguments={"customer_name": name},
            depends_on=[],
            preconditions=[],
            requires_approval=False,
            read_only=True,
        )
        return
    if re.search(r"\bsend\b", lowered) and steps and steps[-1].action_type is ActionType.DRAFT_INVOICE:
        _add(
            steps,
            action_type=ActionType.SEND_INVOICE,
            summary="Send the drafted invoice.",
            arguments={},
            depends_on=[steps[-1].sequence],
            preconditions=["invoice draft exists in PayPal"],
            requires_approval=False,
            read_only=False,
        )
        return
    raise _ParseStop(
        "unsupported_instruction",
        f"I could not turn this into a financial action: {sentence}",
        [f"Rephrase this as an invoice, reminder, project, payout, or overdue list: {sentence}"],
    )


class RuleBasedFallbackProvider:
    provider = "fallback_rules"
    provider_label = FALLBACK_LABEL

    async def plan_workflow(self, instruction: str, context: WorkflowPlanningContext) -> WorkflowPlanResult:
        del context
        rejected = injection_rejection(instruction)
        if rejected:
            return WorkflowPlanResult(
                provider=self.provider,
                provider_label=self.provider_label,
                failure=self._failure("prompt_injection", rejected),
            )
        steps: list[PlanStepDraft] = []
        try:
            for sentence in _sentences(instruction):
                _one(sentence, steps)
        except _ParseStop as stop:
            return WorkflowPlanResult(
                provider=self.provider,
                provider_label=self.provider_label,
                failure=self._failure(stop.code, stop.message, stop.clarifications),
            )
        if not steps:
            return WorkflowPlanResult(
                provider=self.provider,
                provider_label=self.provider_label,
                failure=self._failure(
                    "missing_required",
                    "Write the financial instruction you want planned.",
                    ["Describe the invoice, project, reminder, payout, or report you want."],
                ),
            )
        kinds = {step.action_type.value for step in steps}
        entities = _entities(steps)
        return WorkflowPlanResult(
            provider=self.provider,
            provider_label=self.provider_label,
            draft=WorkflowPlanDraft(
                intent="compound" if len(kinds) > 1 else next(iter(kinds)),
                entities=entities,
                steps=steps,
            ),
        )

    @staticmethod
    def _failure(code: str, message: str, clarifications: list[str] | None = None):
        from app.modules.ai.schemas import PlanningFailure

        return PlanningFailure(code=code, message=message, clarifications=clarifications or [message])


def _entities(steps: list[PlanStepDraft]) -> list[EntityMention]:
    found: list[EntityMention] = []
    seen: set[tuple[str, str]] = set()
    for step in steps:
        mapping = (
            ("customer", "customer_name"),
            ("contractor", "recipient_name"),
            ("project", "project_name"),
            ("contract", "contract_name"),
        )
        for kind, key in mapping:
            value = step.arguments.get(key)
            if isinstance(value, str) and (kind, value.casefold()) not in seen:
                seen.add((kind, value.casefold()))
                found.append(EntityMention(kind=kind, name=value))
    return found
