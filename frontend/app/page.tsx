import { cookies, headers } from "next/headers";

import { CaseDesk, DeskHeader } from "./case-desk";
import { localSandboxEnabled, reviewerCookie, reviewerKey, validReviewerSession, type ReviewerAccess } from "./reviewer-session";
import { readInvestigation, readReview, readWorkspace } from "./workspace";

export const dynamic = "force-dynamic";

export default async function Home({ searchParams }: {
  searchParams: Promise<{ case?: string | string[]; review_notice?: string | string[] }>;
}) {
  const [workspace, params, requestHeaders] = await Promise.all([readWorkspace(), searchParams, headers()]);

  if (!workspace) {
    return (
      <>
        <DeskHeader />
        <main className="page-shell" id="main-content" tabIndex={-1}>
          <section className="panel setup-panel">
            <h1>Case desk unavailable</h1>
            <p>Check the Python service and the shared demo token. The project README covers local setup and the protected Vercel preview.</p>
            <a className="retry-link" href="/">Reload case desk</a>
          </section>
        </main>
      </>
    );
  }

  const selectedCase = workspace.cases.find((item) => item.case_id === params.case)
    ?? workspace.cases.find((item) => item.scenario_id === "SC01")
    ?? workspace.cases[0];
  const local = localSandboxEnabled(requestHeaders.get("host"));
  const key = local ? reviewerKey() : null;
  const [investigation, review, cookieJar] = await Promise.all([
    selectedCase ? readInvestigation(selectedCase.case_id) : null,
    local && selectedCase ? readReview(selectedCase.case_id) : null,
    key ? cookies() : null,
  ]);
  const signedIn = key && validReviewerSession(cookieJar?.get(reviewerCookie)?.value, key);
  const access: ReviewerAccess = !local ? "hosted" : !key ? "setup" : signedIn ? "signed-in" : "signed-out";
  const notice = typeof params.review_notice === "string" ? params.review_notice : undefined;

  return <CaseDesk workspace={workspace} selectedCase={selectedCase} investigation={investigation} review={review} access={access} notice={notice} />;
}
