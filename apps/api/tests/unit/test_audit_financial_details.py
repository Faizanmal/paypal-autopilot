from app.audit.service import financial_details
from app.modules.office.service import _paypal_operation, _policy_evaluated, _proposed_by_ai, _result


def test_financial_details_keeps_audit_fields_explicit():
    details = financial_details(
        status="submitted",
        proposed_by_ai=True,
        approval_id="appr-1",
        approver_id="user-1",
        policy_evaluated="exact_action_approval",
        paypal_operation="payouts.create_batch:BATCH-1",
        amount="10.00",
    )
    assert details["status"] == "submitted"
    assert details["proposed_by_ai"] is True
    assert details["approval_id"] == "appr-1"
    assert details["approver_id"] == "user-1"
    assert details["policy_evaluated"] == "exact_action_approval"
    assert details["paypal_operation"] == "payouts.create_batch:BATCH-1"
    assert details["amount"] == "10.00"


def test_office_audit_mapping_derives_paypal_policy_and_result():
    details = {
        "paypal_invoice_id": "INV2-1",
        "provider_status": "SENT",
        "action_hash": "abc",
        "approval_id": "appr-9",
    }
    assert _paypal_operation("invoice.paypal_sent", details) == "invoicing.send:INV2-1"
    assert _policy_evaluated("payout.approved", details) == "exact_action_approval"
    assert _result("invoice.paypal_sent", details) == "SENT"
    assert _proposed_by_ai("agent.step_succeeded", {}) is True
    assert _proposed_by_ai("payout.intent_created", {"proposed_by_ai": True}) is True
    assert _proposed_by_ai("payout.intent_created", {"proposed_by_ai": False}) is False
