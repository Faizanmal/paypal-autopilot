from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.ai.schemas import WorkflowPlanDraft
from app.modules.ai.tools import ToolOutcome, execute_tool
from app.modules.ai.validate import validate_plan
from tests.unit.test_planner_normalization import PROJECT, response_plan


def bulk_plan(rows=None, count=None):
    plan = response_plan(True)
    plan["steps"] = plan["steps"][:1] + [
        {
            "sequence": 2,
            "action_type": "create_milestones",
            "summary": "Create three payment milestones.",
            "arguments": {},
            "depends_on": [1],
            "requires_approval": False,
            "read_only": False,
        }
    ]
    if rows is not None:
        plan["steps"][1]["arguments"]["milestones"] = rows
    if count is not None:
        plan["steps"][1]["arguments"]["milestone_count"] = count
    return plan


def milestone_rows():
    return [{"name": f"Milestone {index}", "amount": "1000.00", "currency_code": "USD"} for index in range(1, 4)]


@pytest.mark.parametrize("rows", [None, milestone_rows()])
def test_two_step_live_shape_becomes_explicit_reviewable_milestones(rows):
    draft = WorkflowPlanDraft.model_validate(bulk_plan(rows))
    assert validate_plan(draft, PROJECT).ok
    assert len(draft.steps) == 4
    assert [step.arguments["milestone_name"] for step in draft.steps[1:]] == [f"Milestone {i}" for i in range(1, 4)]
    assert [step.arguments["amount"] for step in draft.steps[1:]] == ["1000.00"] * 3
    assert all(step.depends_on == [1] for step in draft.steps[1:])
    assert all("project_id" not in step.arguments for step in draft.steps)


def test_mismatched_bulk_sum_is_rejected_before_materialization():
    rows = milestone_rows()
    rows[-1]["amount"] = "900.00"
    result = validate_plan(WorkflowPlanDraft.model_validate(bulk_plan(rows)), PROJECT)
    assert not result.ok
    assert result.code == "invalid_plan"
    assert "sum" in result.message


def test_cent_remainder_is_distributed_without_rounding_loss():
    plan = bulk_plan()
    plan["steps"][0]["arguments"]["amount"] = "3000.01"
    draft = WorkflowPlanDraft.model_validate(plan)
    assert validate_plan(draft, PROJECT.replace("$3,000", "$3,000.01")).ok
    assert [step.arguments["amount"] for step in draft.steps[1:]] == ["1000.00", "1000.00", "1000.01"]


def test_no_count_or_missing_requested_steps_requires_clarification():
    assert (
        validate_plan(WorkflowPlanDraft.model_validate(bulk_plan()), "Create a $3,000 project with milestones.").code
        == "missing_required"
    )
    plan = bulk_plan()
    plan["steps"] = plan["steps"][:1]
    assert validate_plan(WorkflowPlanDraft.model_validate(plan), PROJECT).code == "missing_required"


def test_model_cannot_invent_an_equal_split_without_a_user_supplied_count():
    draft = WorkflowPlanDraft.model_validate(bulk_plan(milestone_rows()))
    assert not validate_plan(draft, "Create a $3,000 project with payment milestones.").ok


@pytest.mark.parametrize("change", ["identity", "duplicate", "missing_dependency", "contract_and_direct"])
def test_unsafe_or_ambiguous_bulk_proposals_do_not_execute(change):
    plan = bulk_plan(milestone_rows())
    if change == "identity":
        plan["steps"][1]["arguments"]["project_id"] = str(uuid4())
    elif change == "duplicate":
        plan["steps"][1]["arguments"]["milestones"][1]["name"] = "Milestone 1"
    elif change == "missing_dependency":
        plan["steps"][1]["depends_on"] = [99]
    else:
        plan["steps"][1]["arguments"]["contract_name"] = "agreement.docx"
    assert not validate_plan(WorkflowPlanDraft.model_validate(plan), PROJECT).ok


def test_dependency_output_references_are_remapped_after_expansion():
    plan = bulk_plan()
    plan["steps"].append(
        {
            "sequence": 3,
            "action_type": "get_project_status",
            "summary": "Inspect project",
            "arguments": {},
            "depends_on": [2],
            "read_only": True,
        }
    )
    draft = WorkflowPlanDraft.model_validate(plan)
    assert validate_plan(draft, PROJECT).ok
    assert draft.steps[-1].depends_on == [4]


def test_one_earlier_project_can_supply_an_omitted_dependency():
    plan = bulk_plan()
    plan["steps"][1]["depends_on"] = []
    draft = WorkflowPlanDraft.model_validate(plan)
    assert validate_plan(draft, PROJECT).ok
    assert all(step.depends_on == [1] for step in draft.steps[1:])


def test_unused_empty_milestone_array_does_not_change_contract_path():
    draft = WorkflowPlanDraft.model_validate(
        {
            "intent": "create_milestones",
            "entities": [],
            "steps": [
                {
                    "sequence": 1,
                    "action_type": "create_milestones",
                    "summary": "Apply reviewed contract",
                    "arguments": {"contract_name": "agreement.docx", "milestones": []},
                }
            ],
        }
    )
    assert validate_plan(draft, "Create milestones from the contract agreement.docx").ok
    assert draft.steps[0].arguments == {"contract_name": "agreement.docx"}


def test_optional_due_date_is_preserved_only_when_stated():
    rows = milestone_rows()
    rows[0]["due_on"] = "2026-11-15"
    draft = WorkflowPlanDraft.model_validate(bulk_plan(rows))
    assert not validate_plan(deepcopy(draft), PROJECT).ok
    assert validate_plan(draft, PROJECT + " Milestone 1 is due 2026-11-15.").ok
    assert draft.steps[1].arguments["due_on"] == "2026-11-15"


@pytest.mark.asyncio
async def test_bulk_executor_uses_project_output_without_a_contract(monkeypatch):
    project_id = uuid4()
    monkeypatch.setattr("app.modules.ai.tools.ensure_workflow_enabled", AsyncMock())
    monkeypatch.setattr(
        "app.modules.ai.tools.get_project_detail",
        AsyncMock(return_value=SimpleNamespace(total_amount=Decimal("3000.00"), currency_code="USD")),
    )
    create = AsyncMock(
        side_effect=[ToolOutcome(status="succeeded", result={"milestone_id": str(uuid4())}) for _ in range(3)]
    )
    monkeypatch.setattr("app.modules.ai.tools._milestone", create)
    result = await execute_tool(
        None,
        None,
        run_id=uuid4(),
        sequence=2,
        action_type="create_milestones",
        arguments={"milestones": milestone_rows()},
        trusted={},
        preconditions=[],
        depends_on=[1],
        outputs={1: {"status": "succeeded", "project_id": str(project_id)}},
    )
    assert result.status == "succeeded"
    assert result.result["milestone_count"] == 3
    assert create.await_count == 3
    assert all(call.args[3] == {"project_id": str(project_id)} for call in create.await_args_list)
