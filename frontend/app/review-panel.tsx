import type { ReactNode } from "react";

import type { ReviewerAccess } from "./reviewer-session";
import type { DemoCase, ReviewSnapshot, ReviewState, VerifiedReceipt } from "./workspace";

type SavedReview = NonNullable<ReviewSnapshot["proposal"]>;

const reviewLabels: Record<ReviewState, string> = {
  awaiting_review: "Awaiting review",
  approved: "Approved · ready to execute",
  denied: "Denied",
  executing: "Executing",
  completed: "Completed",
  failed: "Failed",
  uncertain: "Uncertain · verify operation",
  invalidated: "Invalidated · prepare for review again",
};

export const remedyLabels = {
  full_refund: "Full refund",
  partial_refund: "Partial refund",
  replacement: "Replacement request",
  delay_update: "Customer update draft",
} as const;

const reviewNotices: Record<string, string> = {
  "sign-in": "Sign in with the configured local reviewer key.",
  invalid: "Check the form fields. Refund amounts must be positive whole cents.",
  conflict: "The latest proposal or order facts prevented this action. Check the current revision and review history.",
  "check-state": "The request could not be confirmed. Reload and check the latest review state before attempting it again.",
  invalid_edit: "Choose a refund amount within the current eligible balance.",
  stale_revision: "The selected revision has changed. Review the latest revision before continuing.",
  invalid_proposal: "Correct this proposal before approving it.",
  approval_required: "Approve this exact revision before executing it.",
  idempotency_conflict: "This operation ID is already bound to a different request.",
};

const dollars = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
const utcDateTime = new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "medium", timeZone: "UTC" });

export function SavedReviewStatus({ state }: { state: ReviewState }) {
  return <span className={`status review-${state}`}>{reviewLabels[state]}</span>;
}

function ReviewForm({ caseId, action, revision, children }: {
  caseId: string;
  action: string;
  revision?: number;
  children: ReactNode;
}) {
  return (
    <form className="review-form" method="post" action={`/api/sandbox/review/${caseId}`}>
      <input type="hidden" name="action" value={action} />
      {revision === undefined ? null : <input type="hidden" name="revision" value={revision} />}
      {children}
    </form>
  );
}

function ReviewActions({ item, saved }: { item: DemoCase; saved: SavedReview }) {
  const { state, revision, execution, payload, idempotency_key } = saved;
  return (
    <div className="review-actions">
      {state === "awaiting_review" ? (
        <>
          <ReviewForm caseId={item.case_id} action="approve" revision={revision}>
            <button className="review-primary" type="submit" disabled={payload.validation_status === "invalid"}>Approve revision {revision}</button>
          </ReviewForm>
          <details className="review-detail">
            <summary>Deny this revision</summary>
            <ReviewForm caseId={item.case_id} action="deny" revision={revision}>
              <label htmlFor="denial-reason">Reason for denial</label>
              <textarea id="denial-reason" name="reason" rows={2} maxLength={280} required />
              <button type="submit">Deny revision {revision}</button>
            </ReviewForm>
          </details>
        </>
      ) : null}

      {(state === "awaiting_review" || state === "approved") && payload.amount_cents !== null ? (
        <details className="review-detail">
          <summary>Edit refund amount</summary>
          <ReviewForm caseId={item.case_id} action="edit" revision={revision}>
            <label htmlFor="refund-cents">Refund amount in cents</label>
            <input id="refund-cents" name="amount_cents" inputMode="numeric" pattern="[1-9][0-9]*" maxLength={10} defaultValue={payload.amount_cents} required />
            <p className="muted">The new revision will need its own approval.</p>
            <button type="submit">Save new revision</button>
          </ReviewForm>
        </details>
      ) : null}

      {state === "approved" ? (
        <ReviewForm caseId={item.case_id} action="execute" revision={revision}>
          <input type="hidden" name="idempotency_key" value={idempotency_key} />
          {item.scenario_id === "SC13" ? (
            <>
              <label htmlFor="execution-simulation">Simulation</label>
              <select id="execution-simulation" name="simulation" defaultValue="normal">
                <option value="normal">Normal execution</option>
                <option value="reject_before_commit">Reject before commit</option>
                <option value="timeout_after_commit">Timeout after commit</option>
                <option value="unresolved">Unresolved operation</option>
              </select>
            </>
          ) : <input type="hidden" name="simulation" value="normal" />}
          <button className="review-primary" type="submit">Execute approved action</button>
        </ReviewForm>
      ) : null}

      {(state === "uncertain" || state === "executing") && execution ? (
        <ReviewForm caseId={item.case_id} action="reconcile">
          <input type="hidden" name="execution_id" value={execution.execution_id} />
          <button className="review-primary" type="submit">Reconcile operation</button>
        </ReviewForm>
      ) : null}
    </div>
  );
}

function ReceiptDetails({ receipt }: { receipt: VerifiedReceipt }) {
  return (
    <section className="verified-receipt" aria-labelledby="receipt-heading">
      <h3 id="receipt-heading">Verified sandbox receipt</h3>
      <dl className="action-facts">
        <div><dt>Record</dt><dd className="review-id">{receipt.record_id}</dd></div>
        <div><dt>Operation</dt><dd className="review-id">{receipt.execution_id}</dd></div>
        <div><dt>Remedy</dt><dd>{remedyLabels[receipt.remedy]}</dd></div>
        <div><dt>Order</dt><dd>{receipt.order_id}{receipt.line_id ? ` · Line ${receipt.line_id}` : ""}</dd></div>
        {receipt.amount_cents === null ? null : <div><dt>Amount</dt><dd>{dollars.format(receipt.amount_cents / 100)} {receipt.currency}</dd></div>}
        {receipt.quantity === null ? null : <div><dt>Quantity</dt><dd>{receipt.quantity}</dd></div>}
        <div><dt>Verified</dt><dd><time dateTime={receipt.verified_at}>{utcDateTime.format(new Date(receipt.verified_at))} UTC</time></dd></div>
      </dl>
    </section>
  );
}

export function LocalReview({ item, review, access, notice }: {
  item: DemoCase;
  review: ReviewSnapshot | null;
  access: Exclude<ReviewerAccess, "hosted">;
  notice?: string;
}) {
  const saved = review?.proposal;
  const execution = saved?.execution;
  const receipt = execution?.status === "completed" ? execution.receipt : null;
  const noticeText = notice && Object.hasOwn(reviewNotices, notice) ? reviewNotices[notice] : null;
  const canPrepare = (item.proposal || item.draft) && (!saved || ["denied", "invalidated", "failed"].includes(saved.state));
  return (
    <div className="local-review" id="local-review" tabIndex={-1}>
      <div className="review-heading">
        <h3>Local reviewer</h3>
        {access === "signed-in" ? (
          <form method="post" action="/api/sandbox/session">
            <input type="hidden" name="action" value="logout" />
            <input type="hidden" name="case_id" value={item.case_id} />
            <button className="review-sign-out" type="submit">Sign out</button>
          </form>
        ) : null}
      </div>

      {noticeText ? <p role="alert" className="review-error">{noticeText}</p> : null}
      {saved?.review?.reason ? <p className="muted">Denial reason · {saved.review.reason}</p> : null}
      {execution && !receipt ? (
        <div className="review-outcome">
          <p>{execution.message}</p>
          <p className="muted">Operation ID · <span className="review-id">{execution.execution_id}</span></p>
        </div>
      ) : null}
      {receipt ? <ReceiptDetails receipt={receipt} /> : null}

      {access === "setup" ? <p className="muted">Configure a separate reviewer key for both local services using the README.</p> : null}
      {access === "signed-out" ? (
        <form className="review-form" method="post" action="/api/sandbox/session">
          <input type="hidden" name="action" value="login" />
          <input type="hidden" name="case_id" value={item.case_id} />
          <label htmlFor="reviewer-key">Reviewer key</label>
          <input id="reviewer-key" type="password" name="reviewer_key" maxLength={256} autoComplete="off" required />
          <button type="submit">Sign in as reviewer</button>
        </form>
      ) : null}
      {access === "signed-in" && !review ? <p className="muted">The review log is unavailable. Check the local backend and reload.</p> : null}
      {access === "signed-in" && review && canPrepare ? (
        <ReviewForm caseId={item.case_id} action="prepare">
          <button className="review-primary" type="submit">{saved ? "Prepare new revision" : "Prepare for review"}</button>
        </ReviewForm>
      ) : null}
      {access === "signed-in" && saved ? <ReviewActions item={item} saved={saved} /> : null}
    </div>
  );
}
