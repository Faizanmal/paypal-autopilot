export type User = {
  id: string;
  email: string;
  full_name: string;
};

export type Workspace = {
  id: string;
  name: string;
  slug: string;
  role: string;
};

export type AuthSession = {
  user: User;
  workspace: Workspace;
};

export type Customer = {
  id: string;
  name: string;
  email: string;
  company_name: string | null;
  billing_email: string | null;
  billing_address: string | null;
  notes: string | null;
  archived_at: string | null;
};

export type Contractor = {
  id: string;
  name: string;
  email: string;
  paypal_email: string | null;
  notes: string | null;
};

export type Project = {
  id: string;
  customer_id: string | null;
  name: string;
  description: string | null;
  currency_code: string;
  total_amount: string;
  status: string;
  starts_on: string | null;
  ends_on: string | null;
};

export type Milestone = {
  id: string;
  project_id: string;
  sequence: number;
  name: string;
  currency_code: string;
  amount: string;
  trigger_kind: string;
  status: string;
  due_on: string | null;
  acceptance_condition: string | null;
  invoice_id?: string | null;
  paypal_invoice_id?: string | null;
};

export type BillingProgress = {
  currency_code: string;
  project_total: string;
  invoiced_amount: string;
  paid_amount: string;
  remaining_amount: string;
  milestone_count: number;
};

export type ProjectDetail = Project & {
  milestones: Milestone[];
  progress: BillingProgress;
};

export type ContractRecord = {
  id: string;
  filename: string;
  content_type: string;
  status: string;
  customer_id: string | null;
  project_id: string | null;
  provider_label: string;
  legally_verified: boolean;
  disclaimer: string;
  extraction: {
    parties?: string[];
    scope?: string | null;
    deliverables?: string | null;
    acceptance_conditions?: string | null;
    contractor_obligations?: string | null;
    total_amount?: string | null;
    currency_code?: string | null;
    milestones?: Array<{
      name: string;
      amount: string;
      currency_code: string;
      due_on: string;
      trigger_kind?: string;
    }>;
  };
  findings: string[];
};

export type ItemList<T> = {
  items: T[];
};

export type ApiErrorBody = {
  error?: {
    code?: string;
    message?: string;
  };
};

export type CapabilityCheck = {
  name: string;
  status: string;
  detail: string;
};

export type CapabilityReport = {
  paypal_env: string;
  base_url: string;
  credentials_configured: boolean;
  payouts_execution_enabled: boolean;
  limitation: string | null;
  checks: CapabilityCheck[];
};

export type PayoutCapability = {
  execution_enabled: boolean;
  reason: string;
  credentials_configured: boolean;
  scope_present: boolean | null;
};

export type PayoutRequest = {
  id: string;
  contractor_id: string;
  recipient_email: string | null;
  currency_code: string;
  amount: string;
  status: string;
  provider_status: string | null;
  paypal_payout_batch_id: string | null;
  sender_batch_id: string | null;
  last_provider_error: string | null;
  decision_reason: string | null;
};

export type FinancialPolicy = {
  autonomy_level: number;
  require_payout_approval: boolean;
  currency_code: string;
  approval_threshold_amount: string | null;
  per_transaction_limit: string | null;
  daily_limit: string | null;
  monthly_limit: string | null;
  workspace_spending_limit: string | null;
  allowed_currencies: string[];
  approved_recipients: string[];
  restricted_action_types: string[];
  paused_at: string | null;
};

export type Invoice = {
  id: string;
  customer_id: string | null;
  project_id: string | null;
  milestone_id: string | null;
  currency_code: string;
  amount: string;
  status: string;
  paypal_invoice_id: string | null;
  provider_status: string | null;
  hosted_url: string | null;
  due_at: string | null;
  last_synced_at: string | null;
  last_provider_error: string | null;
  reminders_sent: number;
};

export type PaymentRecord = {
  id: string;
  invoice_id: string;
  currency_code: string;
  amount: string;
  source: string;
  external_id: string;
  received_at: string;
};

export type AuditEntry = {
  id: string;
  created_at: string;
  actor_name: string | null;
  actor_email: string | null;
  action: string;
  entity_type: string;
  entity_id: string | null;
  result: string;
  provider_reference: string | null;
  approval_id: string | null;
  proposed_by_ai: boolean;
  policy_evaluated: string | null;
  paypal_operation: string | null;
};

export type WorkflowStepRecord = {
  sequence: number;
  step_type: string;
  status: string;
  condition: string | null;
  waiting_for: string | null;
  attempts: number;
  provider_reference: string | null;
  error: string | null;
};

export type WorkflowRecord = {
  id: string;
  status: string;
  agent_run_id: string | null;
  project_id: string | null;
  confirmed_at: string | null;
  steps: WorkflowStepRecord[];
};

export type ScheduledAction = {
  id: string;
  job_type: string;
  status: string;
  run_after: string;
  attempts: number;
  last_error: string | null;
  related_entity_type: string | null;
  related_entity_id: string | null;
};

export type WorkspaceMember = {
  user_id: string;
  full_name: string;
  email: string;
  role: string;
};

export type FinanceAlert = {
  kind: string;
  message: string;
  amount: string | null;
};

export type FinanceProjectionEntry = {
  on: string | null;
  direction: string;
  amount: string;
  label: string;
  included: boolean;
  reason: string;
};

export type FinanceInsight = {
  kind: string;
  message: string;
  figures: Record<string, string>;
};

export type FinanceSnapshot = {
  currency: string;
  horizon_days: number;
  total_invoiced: string;
  total_paid: string;
  outstanding_receivables: string;
  overdue_receivables: string;
  upcoming_expected_payments: string;
  pending_contractor_obligations: string;
  completed_payouts: string;
  net_cash_flow_estimate: string | null;
  confirmed_payments: string;
  expected_payments: string;
  undated_expected_payments: string;
  planned_expenses: string;
  in_flight_expenses: string;
  executed_expenses: string;
  refunds_reversed: string;
  paypal_balance_available: boolean;
  paypal_balance_amount: string | null;
  paypal_balance_reason: string;
  projected_available: string | null;
  opening_balance: string | null;
  opening_as_of: string | null;
  pending_approval_count: number;
  duplicate_payment_events: number;
  excluded_by_currency: Record<string, number>;
  insights: FinanceInsight[];
  alerts: FinanceAlert[];
  assumptions: string[];
  uncertainty: string[];
  projection: FinanceProjectionEntry[];
};

export type WorkspaceRuntime = {
  paypal_env: string;
  paypal_configured: boolean;
  payouts_execution_enabled: boolean;
  ai_provider: string;
  ai_credentials_configured: boolean;
};

export type AgentStep = {
  sequence: number;
  action_type: string;
  status: string;
  summary: string;
  arguments: Record<string, unknown>;
  result: Record<string, unknown> | null;
  provider_reference: string | null;
  error: string | null;
  attempts: number;
  requires_approval: boolean;
  preconditions: string[];
  depends_on: number[];
};

export type AgentRun = {
  id: string;
  instruction: string;
  status: string;
  provider: string;
  provider_label: string;
  explanation: string | null;
  error_code: string | null;
  clarifications: string[];
  steps: AgentStep[];
};
