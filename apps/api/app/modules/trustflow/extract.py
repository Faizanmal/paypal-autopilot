"""Deterministic contract reading.

The uploaded text is data. Amounts, parties, and dates are patterns in that
text. Nothing in the document is executed, and the result is not a legal opinion.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from app.core.money import parse_money
from app.modules.ai.security import contains_injection

NOT_LEGALLY_VERIFIED = "This extraction is not legally verified. Review it before creating a project or invoice."
PARSER_LABEL = "Deterministic contract parser (no AI provider configured)"

_HEADINGS = {
    "scope of work": "scope",
    "deliverables": "deliverables",
    "acceptance": "acceptance_conditions",
    "contractor obligations": "contractor_obligations",
}
_PARTY = re.compile(r"(?im)^agreement between\s+(.+?)\s+and\s+(.+?)\.\s*$")
_AMOUNT = r"(?:\$[0-9,]+(?:\.[0-9]{1,2})?|[A-Za-z]{3}\s+[0-9,]+(?:\.[0-9]{1,2})?)"
_TOTAL = re.compile(rf"(?im)^total contract value:\s*({_AMOUNT})\s*$")
_MILESTONE = re.compile(
    rf"(?im)^milestone\s+\d+\s*:\s*(?P<name>.+?)\s+[-—]\s*(?P<money>{_AMOUNT})\s+due\s+(?P<due>\d{{4}}-\d{{2}}-\d{{2}})\s*$"
)


class ExtractedMilestone(BaseModel):
    name: str
    amount: str
    currency_code: str
    due_on: date
    acceptance_condition: str | None = None
    trigger_kind: str


class ContractExtractionDraft(BaseModel):
    parties: list[str] = Field(default_factory=list)
    scope: str | None = None
    deliverables: str | None = None
    acceptance_conditions: str | None = None
    contractor_obligations: str | None = None
    currency_code: str | None = None
    total_amount: str | None = None
    milestones: list[ExtractedMilestone] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)
    legally_verified: bool = False
    disclaimer: str = NOT_LEGALLY_VERIFIED

    def apply_blocked(self) -> bool:
        blocked = (
            "prompt_injection",
            "ambiguous_parties",
            "ambiguous_total",
            "missing_total",
            "missing_milestones",
            "total_mismatch",
            "unsupported_currency",
            "invalid_amount",
        )
        return any(any(item.startswith(code) for code in blocked) for item in self.findings)


def _money(token: str) -> tuple[str, str] | str:
    raw = token.strip()
    currency: str | None = None
    if raw.startswith("$"):
        currency = "USD"
        raw = raw[1:]
    else:
        coded = re.fullmatch(r"([A-Za-z]{3})\s+(.+)", raw)
        if coded:
            currency = coded.group(1).upper()
            raw = coded.group(2)
    number = raw.replace(",", "")
    if currency is None:
        return "missing_currency"
    try:
        amount, code = parse_money(number, currency)
    except Exception:
        if currency != "USD":
            return f"unsupported_currency:{currency}"
        return "invalid_amount"
    return format(amount, "f"), code


def _sections(text: str) -> dict[str, str]:
    found: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        label = line.strip().rstrip(":").lower()
        if label in _HEADINGS:
            current = _HEADINGS[label]
            found.setdefault(current, [])
            continue
        if label.startswith(("total contract value", "milestone ", "agreement between")):
            current = None
            continue
        if current is not None and line.strip():
            found[current].append(line.strip())
    return {key: " ".join(value).strip() for key, value in found.items() if value}


def extract_contract_text(text: str) -> ContractExtractionDraft:
    findings: list[str] = []
    if contains_injection(text):
        findings.append("prompt_injection: The contract contains instructions and they were not followed.")
    parties = [f"{match.group(1).strip()} and {match.group(2).strip()}" for match in _PARTY.finditer(text)]
    if len(parties) == 0:
        findings.append("missing_parties: The contract does not name both parties.")
    elif len(parties) > 1:
        findings.append("ambiguous_parties: The contract names more than one pair of parties.")
    totals: list[tuple[str, str]] = []
    for match in _TOTAL.finditer(text):
        parsed = _money(match.group(1))
        if isinstance(parsed, str):
            findings.append(parsed if ":" in parsed else f"{parsed}: A contract total could not be read.")
        else:
            totals.append(parsed)
    distinct = {(amount, currency) for amount, currency in totals}
    total_amount: str | None = None
    currency_code: str | None = None
    if len(distinct) == 1:
        total_amount, currency_code = totals[0]
    elif len(distinct) == 0 and not any(
        item.startswith("unsupported_currency") or item.startswith("invalid_amount") for item in findings
    ):
        findings.append("missing_total: The contract does not state one total contract value.")
    elif len(distinct) > 1:
        findings.append("ambiguous_total: The contract states more than one total.")
    milestones: list[ExtractedMilestone] = []
    for index, match in enumerate(_MILESTONE.finditer(text), start=1):
        parsed = _money(match.group("money"))
        if isinstance(parsed, str):
            findings.append(f"{parsed}: Milestone {index} has an amount that cannot be used.")
            continue
        amount, currency = parsed
        if currency_code and currency != currency_code:
            findings.append("unsupported_currency: A milestone currency does not match the contract total.")
        try:
            due_on = date.fromisoformat(match.group("due"))
        except ValueError:
            findings.append(f"invalid_date: Milestone {index} does not have an ISO due date.")
            continue
        count_guess = len(list(_MILESTONE.finditer(text)))
        if index == 1:
            trigger = "upfront"
        elif index == count_guess:
            trigger = "on_delivery"
        else:
            trigger = "on_event"
        milestones.append(
            ExtractedMilestone(
                name=match.group("name").strip()[:200],
                amount=amount,
                currency_code=currency,
                due_on=due_on,
                trigger_kind=trigger,
            )
        )
    if not milestones:
        findings.append("missing_milestones: The contract does not list readable payment milestones.")
    if total_amount and milestones and currency_code:
        total = Decimal(total_amount)
        summed = sum((Decimal(item.amount) for item in milestones), Decimal("0"))
        if summed != total:
            findings.append(
                f"total_mismatch: Milestone amounts sum to {summed} {currency_code}, not the contract total {total}."
            )
    sections = _sections(text)
    cleaned: dict[str, str | None] = {}
    for key in ("scope", "deliverables", "acceptance_conditions", "contractor_obligations"):
        value = sections.get(key)
        if value and contains_injection(value):
            findings.append(
                f"untrusted_text: The {key.replace('_', ' ')} section contained instructions and was omitted."
            )
            cleaned[key] = None
        else:
            cleaned[key] = value
    safe_parties = [] if any(item.startswith("prompt_injection") for item in findings) else parties[:1]
    return ContractExtractionDraft(
        parties=safe_parties,
        scope=cleaned["scope"],
        deliverables=cleaned["deliverables"],
        acceptance_conditions=cleaned["acceptance_conditions"],
        contractor_obligations=cleaned["contractor_obligations"],
        currency_code=None if any(item.startswith("prompt_injection") for item in findings) else currency_code,
        total_amount=None if any(item.startswith("prompt_injection") for item in findings) else total_amount,
        milestones=[] if any(item.startswith("prompt_injection") for item in findings) else milestones,
        findings=findings,
        legally_verified=False,
    )
