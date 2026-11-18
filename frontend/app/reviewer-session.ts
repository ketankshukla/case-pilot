import { createHash, createHmac, randomBytes, timingSafeEqual } from "node:crypto";

const sessionSeconds = 60 * 60;
const maxFormBytes = 4_096;
export const sandboxBackend = "http://127.0.0.1:8000";
export const reviewerCookie = "casepilot_reviewer";
export const reviewerCookieOptions = { httpOnly: true, sameSite: "strict", path: "/", maxAge: sessionSeconds } as const;
export const caseIdPattern = /^CP-[0-9]{4}(?:-[A-Z])?$/;

export type ReviewerAccess = "hosted" | "setup" | "signed-out" | "signed-in";

function loopbackOrigin(host: string | null): string | null {
  if (!host || !/^(127\.0\.0\.1|localhost)(?::[1-9][0-9]{0,4})?$/.test(host)) return null;
  try {
    return new URL(`http://${host}`).origin;
  } catch {
    return null;
  }
}

export function localSandboxEnabled(host: string | null): boolean {
  const backend = process.env.CASEPILOT_BACKEND_URL;
  return !process.env.VERCEL && (!backend || backend === sandboxBackend) && loopbackOrigin(host) !== null;
}

export function requestOrigin(request: Request): string | null {
  const origin = loopbackOrigin(request.headers.get("host"));
  return origin !== null && request.headers.get("origin") === origin ? origin : null;
}

const hash = (value: string) => createHash("sha256").update(value).digest();

export function reviewerKey(): string | null {
  const value = process.env.CASEPILOT_REVIEWER_TOKEN;
  const demo = process.env.CASEPILOT_DEMO_TOKEN;
  if (!value || Array.from(value).length < 32 || value.length > 256 || !demo || timingSafeEqual(hash(value), hash(demo))) return null;
  return value;
}

export function matchesReviewerKey(provided: string, key: string): boolean {
  return provided.length <= 256 && timingSafeEqual(hash(provided), hash(key));
}

function signature(key: string, signedValue: string): Buffer {
  return createHmac("sha256", key).update(`casepilot-local-reviewer:${signedValue}`).digest();
}

export function issueReviewerSession(key: string): string {
  const expiry = Math.floor(Date.now() / 1000) + sessionSeconds;
  const signedValue = `${expiry}.${randomBytes(16).toString("hex")}`;
  return `${signedValue}.${signature(key, signedValue).toString("hex")}`;
}

export function validReviewerSession(session: string | undefined, key: string): boolean {
  const match = session && /^(\d{10,12})\.([a-f0-9]{32})\.([a-f0-9]{64})$/.exec(session);
  if (!match) return false;
  const now = Math.floor(Date.now() / 1000);
  const expiry = Number(match[1]);
  return expiry > now && expiry <= now + sessionSeconds
    && timingSafeEqual(signature(key, `${match[1]}.${match[2]}`), Buffer.from(match[3], "hex"));
}

export async function readSmallForm(request: Request): Promise<URLSearchParams | null> {
  const mediaType = request.headers.get("content-type")?.split(";")[0]?.trim().toLowerCase();
  const length = request.headers.get("content-length");
  if (mediaType !== "application/x-www-form-urlencoded" || !request.body) return null;
  if (length !== null && (!/^\d+$/.test(length) || Number(length) > maxFormBytes)) return null;

  const reader = request.body.getReader();
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let size = 0;
  let result = "";
  try {
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) return new URLSearchParams(result + decoder.decode());
      size += chunk.value.byteLength;
      if (size > maxFormBytes) {
        await reader.cancel();
        return null;
      }
      result += decoder.decode(chunk.value, { stream: true });
    }
  } catch {
    return null;
  } finally {
    reader.releaseLock();
  }
}

export function reviewReturnUrl(origin: string, caseId: string | null, notice?: string): URL {
  const result = new URL("/", origin);
  if (caseId && caseIdPattern.test(caseId)) result.searchParams.set("case", caseId);
  if (notice) result.searchParams.set("review_notice", notice);
  result.hash = "local-review";
  return result;
}
