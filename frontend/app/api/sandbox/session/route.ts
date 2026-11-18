import { NextResponse } from "next/server";

import {
  issueReviewerSession,
  localSandboxEnabled,
  matchesReviewerKey,
  readSmallForm,
  requestOrigin,
  reviewerCookie,
  reviewerCookieOptions,
  reviewerKey,
  reviewReturnUrl,
} from "../../../reviewer-session";

export async function POST(request: Request) {
  if (!localSandboxEnabled(request.headers.get("host"))) return new Response(null, { status: 404 });
  const origin = requestOrigin(request);
  if (!origin) return new Response(null, { status: 403 });

  const form = await readSmallForm(request);
  const caseId = form?.get("case_id") ?? null;
  const redirect = (notice?: string) => NextResponse.redirect(reviewReturnUrl(origin, caseId, notice), 303);
  const action = form?.get("action");
  if (action === "logout") {
    const response = redirect();
    response.cookies.set(reviewerCookie, "", { ...reviewerCookieOptions, maxAge: 0 });
    return response;
  }

  const key = reviewerKey();
  const supplied = form?.get("reviewer_key");
  if (!key || action !== "login" || !supplied || !matchesReviewerKey(supplied, key)) return redirect("sign-in");

  const response = redirect();
  response.cookies.set(reviewerCookie, issueReviewerSession(key), reviewerCookieOptions);
  return response;
}
