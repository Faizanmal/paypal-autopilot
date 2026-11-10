"""Planning and execution.

The language adapter returns a plan. It does not receive PayPal credentials
and it cannot call PayPal. Confirmed steps run through the TrustFlow,
Autopilot, and SpendPilot services. Payout tools prepare an approval and
never call payout execution.
"""
