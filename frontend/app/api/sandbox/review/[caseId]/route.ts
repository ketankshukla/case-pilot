import { NextRequest, NextResponse } from "next/server";

import {
  caseIdPattern,
  localSandboxEnabled,
  readSmallForm,
  requestOrigin,
  reviewerCookie,
  reviewerKey,
  reviewReturnUrl,
  sandboxBackend,
  validReviewerSession,
} from "../../../../reviewer-session";

const simulations = new Set(["normal", "reject_before_commit", "timeout_after_commit", "unresolved"]);
const operationId = /^[A-Za-z0-9_-]{8,80}$/;
const knownConflicts = new Set(["invalid_edit", "stale_revision", "invalid_proposal", "approval_required", "idempotency_conflict"]);

function boundedInteger(value: string | null, maximum: number): number | null {
  if (!value || !/^[1-9][0-9]{0,9}$/.test(value)) return null;
  const number = Number(value);
  return number <= maximum ? number : null;
}

function parseCommand(form: URLSearchParams | null) {
  if (!form) return null;
  const action = form.get("action");
  if (action === "prepare") return { action };
  if (action === "reconcile") {
    const execution_id = form.get("execution_id");
    return execution_id && operationId.test(execution_id) ? { action, execution_id } : null;
  }

  const revision = boundedInteger(form.get("revision"), 2_147_483_647);
  if (revision === null) return null;
  if (action === "approve") return { action, revision };
  if (action === "deny") {
    const reason = form.get("reason")?.trim();
    return reason && reason.length <= 280 ? { action, revision, reason } : null;
  }
  if (action === "edit") {
    const amount_cents = boundedInteger(form.get("amount_cents"), 1_000_000_000);
    return amount_cents === null ? null : { action, revision, amount_cents };
  }
  if (action === "execute") {
    const idempotency_key = form.get("idempotency_key");
    const simulation = form.get("simulation");
    return idempotency_key && operationId.test(idempotency_key) && simulation && simulations.has(simulation)
      ? { action, revision, idempotency_key, simulation }
      : null;
  }
  return null;
}

export async function POST(request: NextRequest, { params }: { params: Promise<{ caseId: string }> }) {
  if (!localSandboxEnabled(request.headers.get("host"))) return new Response(null, { status: 404 });
  const origin = requestOrigin(request);
  if (!origin) return new Response(null, { status: 403 });

  const key = reviewerKey();
  if (!key || !validReviewerSession(request.cookies.get(reviewerCookie)?.value, key)) {
    return new Response("Sign in as the local reviewer before making changes.", { status: 401 });
  }
  const { caseId } = await params;
  if (!caseIdPattern.test(caseId)) return new Response(null, { status: 404 });
  const redirect = (notice?: string) => NextResponse.redirect(reviewReturnUrl(origin, caseId, notice), 303);
  const command = parseCommand(await readSmallForm(request));
  if (!command) return redirect("invalid");

  try {
    const result = await fetch(new URL(`/demo/cases/${caseId}/review`, sandboxBackend), {
      method: "POST",
      headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
      body: JSON.stringify(command),
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(20_000),
    });
    if (result.ok) return redirect();
    if (result.status === 401 || result.status === 403) return redirect("sign-in");
    if (result.status === 400 || result.status === 422) return redirect("invalid");
    if (result.status === 409) {
      const error = await result.json().catch(() => null) as { detail?: { code?: string } } | null;
      const code = error?.detail?.code;
      return redirect(code && knownConflicts.has(code) ? code : "conflict");
    }
    return redirect("check-state");
  } catch {
    return redirect("check-state");
  }
}
