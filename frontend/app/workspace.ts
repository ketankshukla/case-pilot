export type CaseState = "investigating" | "awaiting_information" | "awaiting_review";

export interface DemoCase {
  case_id: string;
  scenario_id: string;
  title: string;
  state: CaseState;
  request: string;
  order: {
    order_id: string;
    version: number;
    paid_cents: number;
    currency: "USD";
    facts: { label: string; value: string }[];
  } | null;
  missing_information: string[];
  evidence: {
    source_id: string;
    title: string;
    version: number;
    effective_date: string;
    excerpt: string;
  }[];
  proposal: {
    revision: number;
    remedy: "full_refund";
    amount_cents: number;
    currency: "USD";
    order_version: number;
    policy_ids: string[];
    validation_summary: string;
  } | null;
  history: { at_utc: string; title: string; detail: string }[];
}

export interface WorkspaceSnapshot {
  fixture_version: string;
  clock_utc: string;
  persona: { display_name: string; customer_id: string };
  cases: DemoCase[];
}

export async function readWorkspace(): Promise<WorkspaceSnapshot | null> {
  const token = process.env.CASEPILOT_DEMO_TOKEN;
  const backendUrl = process.env.CASEPILOT_BACKEND_URL
    ?? (process.env.VERCEL ? undefined : "http://127.0.0.1:8000");
  if (!token || !backendUrl) return null;

  try {
    const response = await fetch(new URL("/demo/workspace", backendUrl), {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(5000),
    });
    return response.ok ? ((await response.json()) as WorkspaceSnapshot) : null;
  } catch {
    return null;
  }
}
