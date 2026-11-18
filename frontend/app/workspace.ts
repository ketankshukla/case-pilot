export type CaseState = "investigating" | "awaiting_information" | "awaiting_review" | "escalated";

export interface CaseSummary {
  case_id: string;
  scenario_id: string;
  title: string;
}

export interface PolicyVersion {
  source_id: string;
  version: number;
}

export type Remedy = "full_refund" | "partial_refund" | "replacement" | "delay_update";

export interface Proposal {
  revision: number;
  remedy: Remedy;
  amount_cents: number | null;
  quantity: number | null;
  draft: string | null;
  validation_status: "valid" | "invalid";
  currency: "USD" | null;
  customer_id: string;
  order_id: string;
  line_id: string | null;
  order_version: number;
  policy_versions: PolicyVersion[];
  validation_summary: string;
}

export type ReviewState = "awaiting_review" | "approved" | "denied" | "executing" | "completed" | "failed" | "uncertain" | "invalidated";

export interface VerifiedReceipt {
  execution_id: string;
  record_id: string;
  remedy: Remedy;
  order_id: string;
  line_id: string | null;
  amount_cents: number | null;
  quantity: number | null;
  currency: "USD" | null;
  verified_at: string;
}

export interface ToolEvent {
  at_utc: string;
  title: string;
  detail: string;
  operation: string;
  status: "ok" | "paused" | "error";
  attempt: number;
  latency_ms: number | null;
}

export interface SavedInvestigation extends Pick<DemoCase, "case_id" | "scenario_id" | "state" | "evidence_status" | "decision_summary"> {
  run_id: string;
  actor: string;
  at_utc: string;
  fixture_version: string;
  mode: "replay";
  order_version: number | null;
  proposal_revision: number | null;
  evidence: PolicyVersion[];
  tools: ToolEvent[];
  latency_ms: number;
  provider_calls: 0;
}

export interface ReviewSnapshot {
  case_id: string;
  scenario_id: string;
  proposal: {
    revision: number;
    state: ReviewState;
    payload: Proposal;
    review: {
      decision: "approved" | "denied";
      reviewer_id: string;
      reason: string | null;
      at_utc: string;
    } | null;
    execution: {
      execution_id: string;
      status: "executing" | "completed" | "failed" | "uncertain";
      message: string;
      receipt: VerifiedReceipt | null;
    } | null;
    idempotency_key: string;
  } | null;
  events: {
    event_id: number;
    revision: number;
    at_utc: string;
    actor: string;
    operation: string;
    detail: string;
    before_state: ReviewState | null;
    after_state: ReviewState;
    execution_id: string | null;
    idempotency_identity: string | null;
  }[];
  runs: SavedInvestigation[];
}

export interface DemoCase extends CaseSummary {
  state: CaseState;
  request: string;
  decision_summary: string;
  order: {
    order_id: string;
    version: number;
    paid_cents: number;
    currency: "USD";
    facts: { label: string; value: string }[];
  } | null;
  missing_information: string[];
  candidate_order_ids: string[];
  evidence_status: "available" | "missing" | "conflicting" | "not_checked";
  evidence: (PolicyVersion & {
    title: string;
    effective_date: string;
    approval_status: string;
    source_kind?: "adversarial_fixture" | "policy";
    excerpt: string;
  })[];
  proposal: Proposal | null;
  draft: string | null;
  history: ToolEvent[];
}

export interface WorkspaceSnapshot {
  fixture_version: string;
  clock_utc: string;
  persona: { display_name: string; customer_id: string };
  cases: CaseSummary[];
}

async function readDemo<T>(path: string, timeoutMs: number): Promise<T | null> {
  const token = process.env.CASEPILOT_DEMO_TOKEN;
  const backendUrl = process.env.CASEPILOT_BACKEND_URL
    ?? (process.env.VERCEL ? undefined : "http://127.0.0.1:8000");
  if (!token || !backendUrl) return null;

  try {
    const response = await fetch(new URL(path, backendUrl), {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(timeoutMs),
    });
    return response.ok ? ((await response.json()) as T) : null;
  } catch {
    return null;
  }
}

export function readWorkspace() {
  return readDemo<WorkspaceSnapshot>("/demo/workspace", 5_000);
}

export function readInvestigation(caseId: string) {
  return readDemo<DemoCase>(`/demo/cases/${encodeURIComponent(caseId)}/investigation`, 25_000);
}

export function readReview(caseId: string) {
  return readDemo<ReviewSnapshot>(`/demo/cases/${encodeURIComponent(caseId)}/review`, 5_000);
}
