# CasePilot build progress

Update this file after each working slice. Record the demonstrated scope, checks actually run, limitations and the decision for the next checkpoint. Git history tracks the source for each slice.

## 2026-11-18 · Planning approved

- Confirmed `E:\casepilot` as the project folder. Existing planning and personal materials stay outside Git.
- Chose a Next.js and React frontend, FastAPI backend and SQLite for the resettable local sandbox.
- Agreed to commit verified slices and push them privately. Public source publication follows the Stage 1 acceptance and publication review.

## 2026-11-18 · Checkpoint 1, fixture-driven support desk

The browser opens a seeded case. Next.js reads the fixture workspace from FastAPI using a server-side demo token. FastAPI serves only C100's scoped cases from SQLite. The screen displays prewritten policy links, a proposal preview and sample run history.

```mermaid
flowchart LR
    Browser[Browser support desk] --> Next[Next.js page]
    Next -->|Authenticated workspace read| Api[FastAPI demo persona]
    Api -->|Scoped read| Db[(SQLite fictional fixtures)]
```

### Rules shown

- **SC01** shows O100 v3, the received unused return and a proposed $80.00 refund with KB01 and KB04 v1. Viewing it leaves the ledger empty.
- **SC05** shows a request that needs an order ID. The screen pauses with no selected order or proposal.
- **SC18** shows an order eight days past its promised date and unknown shipment status. The fixture shows no delivery estimate or replacement proposal.
- The workspace API uses the server's customer scope. All five demo policy records and four base orders are in the versioned `stage1-v1` fixture.

### Verification

- **Passing** · Four backend tests cover SC01, SC05, SC06 and SC18 fixture behavior, including a zero-row ledger after repeated reads and exclusion of C200 records. These checks cover the fixture-view portions of those scenarios.
- **Passing** · `npm run build` compiled the Next.js page and checked TypeScript.
- **Passing** · Edge smoke check loaded the real local workspace, followed a citation and opened a case by keyboard, checked the late shipment, and found no horizontal overflow at 390 pixels or runtime page errors. Reviewed desktop and mobile screenshots.
- Full Stage 1 acceptance testing is pending. In particular, AT01 still requires an approved and verified execution.

### Known limitations and next decision

The evidence, proposal and run history are predefined. The only API in use is the scoped workspace read. Model calls, policy search, reviewer controls, execution, real audit events and acceptance variants are scheduled for later checkpoints.

Next decision after review: approve Checkpoint 2 with free deterministic replay so its evidence and missing-information paths can be checked without a model account.

## 2026-11-18 · Vercel compatibility and GitHub push workflow

- Added Vercel Services (Beta) configuration for Next.js and FastAPI in one project. Public routing reaches the frontend. A private binding carries the token-authenticated workspace read to the packaged Python service.
- The hosted checkpoint serves a read-only snapshot seeded on startup from the same fictional records. The local demo uses a resettable SQLite file. Hosted writes and reconciled receipts require shared durable storage and a separate review.
- Added the required pre-push script and recorded GitHub as the deployment trigger in `AGENTS.md`.
- **Passing** · Five backend tests and the Next.js production build. The hosted-entry test checks the packaged seed, bearer authentication, and rejection of writes.
- **Passing** · `vercel dev --local` loaded SC01 and its $80 proposal through the service binding. A request through the frontend URL to `/demo/workspace` returned 404.
- **Pending** · Vercel account inspection found no project connected to the GitHub repository. `vercel build` reported that linked project settings were required. The Git-triggered cloud build is pending that connection. See the [README](../README.md#github-and-vercel) for the Services preset and protection settings.

## 2026-11-18 · First Vercel production deployment

- The first deployment built Next.js and FastAPI successfully. An authenticated request showed **Case desk unavailable** because the production demo token was missing.
- Enabled Vercel Authentication for all deployments. Confirmed the production address required sign-in before adding `CASEPILOT_DEMO_TOKEN` as a production-only Vercel Secret.
- Five backend tests and the Next.js production build passed before push. Local `vercel build --prod` compiled Next.js and hit a Windows symlink permission error during packaging. Vercel's first cloud build packaged both services successfully.
- A fresh GitHub-triggered build picks up the secret. Check the deployed page for the SC01 fixture and its $80 proposal after Vercel reports Ready.

## 2026-11-18 · Repository privacy

- Checked the three existing commits and confirmed GitHub had only the matching `main` branch. The review found no personal documents, ZIP archives, or matches for local secrets and common credential formats.
- Added repository-wide ignore rules for Word and PDF documents, ZIP archives, and common private-key files. Recorded the pre-push review and stop rule in `AGENTS.md`.

## 2026-11-18 · Checkpoint 2, direct reads and deterministic replay

Opening a case now runs an investigation against `stage1-v2` instead of displaying canned evidence and proposals. Existing installations need one fixture reset. The source repository is public by the product owner's request. Vercel Authentication protects the hosted desk.

```mermaid
flowchart LR
    Desk[Case desk] -->|Select case| Web[Next.js server]
    Web -->|Scoped request| API[FastAPI replay]
    API -->|Order and balance reads| Facts[(SQLite fixtures)]
    API -->|Full-text policy search| Policies[(Versioned passages)]
    API -->|Facts and evidence| Rules[Validate and decide]
    Rules -->|Proposal, question, or escalation| Desk
```

In **SC01**, the server uses the demo session to find O100 v3, retrieves KB01 and KB04, and checks that the unused return was received within 30 days. The refund read finds 8,000 cents available. Replay validates the amount and citation versions and returns a proposal for review. The ledger stays empty.

### Rules and verification

| Scenario | Checkpoint 2 behavior verified |
| --- | --- |
| SC01, SC02 | Repeatable $80 proposal with versioned citations, inclusive day 30, rejection of day 31, future and malformed dates |
| SC05, SC06 | Clarification for a missing order ID and generic errors for orders outside the session's scope |
| SC07 | Missing, conflicting and expired evidence trigger escalation |
| SC09, SC11 | $20 remaining on the balance variant and rejection of malformed proposals |
| SC10, SC18 | One retry after a read timeout and a delay draft without an invented delivery date |

- **Passing** · Eleven backend tests and the Next.js production build. This covers the read and replay portion of the listed scenarios. Full Stage 1 acceptance remains pending.
- **Passing** · Edge opened the built app, navigated cases and citations by keyboard, and checked the refund, missing-order, missing and conflicting evidence, line balance, and delay paths. The page fit at 390 pixels and reported no runtime page errors.
- **Host limitation** · Local `vercel build --prod` compiled Next.js, then Windows refused a symlink during Vercel packaging.
- Replay uses seeded intent, up to six read attempts, one retry per timed-out read, a two-second read timeout, a 20-second run limit, and a 4,000-character request cap. The run history shows observed tool outcomes. It is regenerated for each view and makes zero model-provider calls.

### Review

Open SC01 and follow KB01 v1 from the $80 proposal. Open SC05 and check the order ID prompt. Compare the missing and conflicting SC07 cases. Review the unknown-status draft in SC18.

This slice serves read-only proposals and drafts. The next decision is whether to approve Checkpoint 3 for exact-revision reviewer controls and local sandbox execution.

## 2026-11-18 · Checkpoint 3, reviewer decisions and local execution

The local reviewer can prepare a proposal, approve or deny its exact saved revision, or edit a refund amount to create a new revision. A separate execution request rechecks the current facts, policy and reviewer decision before writing. The hosted desk displays read-only replay.

```mermaid
flowchart LR
    Prep[Save proposal] --> Review{Reviewer decision}
    Review -->|Edit| Prep
    Review -->|Deny| Denied[Denial recorded]
    Review -->|Approve| Approved[Exact revision approved]
    Approved --> Recheck[Recheck in executor]
    Recheck -->|Stale| Invalidated[Approval invalidated]
    Recheck -->|Eligible| Write[Sandbox transaction]
    Write -->|Rejected| Failed[Confirmed failure]
    Write -->|Committed| Read[Read back original ID]
    Write -->|Outcome unknown| Uncertain[Uncertain balance reserved]
    Uncertain --> Read
    Read -->|Match| Receipt[Verified receipt]
    Read -->|Unconfirmed| Uncertain
```

The executor can produce one local refund ledger entry, replacement request or outbox draft. An idempotency key ties retries to the same operation. Reconciliation checks the original operation ID against the stored result. Unconfirmed refunds reserve their amounts.

### Rules and verification

| Scenario | Checkpoint 3 behavior verified |
| --- | --- |
| SC01, SC03 | Approval leaves the ledger empty before execution. Execution verifies one $80 entry. Denial records the reviewer's reason. |
| SC04, SC09 | The invalid $100 line draft needs a corrected revision and fresh approval. Invalid and over-limit cents are rejected. |
| SC06, SC08 | Reviewer authorization and customer scope are enforced on the backend. A stale approval or racing request cannot overspend. |
| SC11–SC13 | Mismatched readback cannot produce a receipt. Duplicate requests keep one execution ID. Failed and uncertain outcomes are distinct. |
| SC17, SC18 | Stock and delivery changes invalidate approvals as appropriate. The verified replacement and delay actions create local records. |

- **Passing** · 29 backend tests and the Next.js production build.
- **Passing** · Edge exercised local sign-in, approval and execution, denial, edit and reapproval, and original-ID reconciliation after a timed-out write. Cross-origin submissions were rejected and reviewer text rendered as text. The verified receipt survived refresh and the page fit at mobile width.
- **Host limitation** · Local `vercel build --prod` compiled the app. Windows refused a symlink in Vercel's packaging output.
- The local fixture database is `stage1-v3`. Review activity and sandbox receipts persist there. The hosted application uses a disposable fixture snapshot and disables reviewer routes. No provider calls occur in replay.

### Review

Follow the [local reviewer walkthrough](../README.md#local-reviewer-walkthrough) to approve SC01, deny SC03, edit SC04, and reconcile SC13. The next decision is whether to proceed to Checkpoint 4 for the audit views, failure coverage, and full Stage 1 evaluation.

### Reviewer sign-in follow-up

Reproduced the missing setup guidance on signed-out SC01. The sign-in form now shows the exact PowerShell command to open the local key file, a copy button for the command, and the line to look for. The form continues to verify the locally configured reviewer key.

All 29 backend tests and the production build passed. Edge verified the command, clipboard feedback, mobile layout, and sign-in. The credential stayed out of the rendered page.

## 2026-11-18 · Checkpoint 4, audit and Stage 1 evaluation

- **Run history → Saved audit trail** shows saved replay decisions and tool results alongside reviewer decisions, state transitions, operation IDs, and hashed retry identities. Preparing a proposal saves the replay used for that revision. A reviewer can also save a blocked or incomplete investigation without preparing an action.
- Added separate adversarial fixtures and tests for the missing Stage 1 branches. The actual `stage1-v3` database upgraded to `stage1-v4` with its prior reviews, actions, receipts, and audit records preserved.
- **Passing** · 43 backend tests across all 31 required acceptance checks, plus the Next.js production build. The [evaluation matrix](EVALUATION.md) records each test and the deferred checks.
- **Passing** · Edge verified scoped candidate selection prompts, saved audit records after refresh, reviewer request protection, safe text rendering, reconciliation of the original operation ID, and mobile fit.
- Both [architecture and decision flows](FLOWS.md) parsed and rendered locally. The [Stage 1 guide](STAGE1.md) includes the specification, decisions, and five-minute walkthrough.

### Review

1. Open **SC05** and its two-candidate variant. Check that the desk asks for clarification.
2. Open **SC07** and save the missing-evidence investigation. Expand it in **Saved audit trail** and check the policy status and tool results.
3. Run **SC13** with **Timeout after commit**. Reconcile it and compare the operation ID in the audit and receipt.
4. Review the scenario matrix and flow diagrams against the behavior you observed.

The hosted desk remains read-only. Replay uses zero model-provider calls. The next decision is whether to accept Stage 1 after reviewing the local walkthrough and test evidence.

## 2026-11-21 · Stage 2 evaluation setup

- Reused eight fictional Stage 1 cases and rewrote their requests in everyday language. The [Stage 2 evaluation setup](STAGE2_EVALUATION.md) defines decision, evidence, and customer-reply points, plus a separate hard-fail gate.
- Verified that all eight requests map to their source fixtures and scoring rows. The 43 Stage 1 backend tests and the production build passed.
- Setup cost was $0 in model API spend. Model calls and scores are pending. Review the cases and scoring rules before agreeing on a provider and spending cap.

## 2026-11-21 · Stage 2 first Codex evaluation

- Ran all eight approved cases once using GPT-6.1 Terra with low reasoning effort through the local Codex CLI signed in to ChatGPT Pro. Each case used a fresh, read-only session with scoped fictional fixture evidence. Model API spend was $0.
- Scored **19/24** under the agreed rubric, with **6/8 decisions**, **8/8 evidence points**, **5/8 customer replies**, and **zero hard failures**. The run missed the pilot gate. E02 missed the direct order-choice question. E05 gave a $20 ceiling without committing to that amount in its recommendation.
- The [run record](STAGE2_EVALUATION.md#first-run--2026-11-21) includes the eight first answers, scores, scoped reads, and token usage. This run evaluated recommendations and drafts. CasePilot's runtime integration and the model's own retrieval choices remain unevaluated.
- Verified the eight saved answers against the Codex output and checked the scoring totals. All 43 backend tests and the Next.js production build passed.
- **Review checkpoint** · Review the deductions before deciding whether to revise the output instructions and run a second evaluation.

## 2026-11-21 · Stage 2 revised-prompt evaluation

- Added shared prompt instructions to make the model ask about the specific matching orders, propose a single exact refund amount, explain conflicting guidance in the reply, and decline requests for unscoped orders. The [second run record](STAGE2_EVALUATION.md#second-run--2026-11-21) contains the exact additions, scores, first answers, and usage.
- Ran all eight cases once through GPT-6.1 Terra on the ChatGPT Pro sign-in. Verified the request and evidence payloads and response schema matched the first run. No paid API calls, tool calls, or retries occurred.
- Scored **22/24**, with **7/8 decisions**, **8/8 evidence points**, **7/8 customer replies**, and **zero hard failures**. E02, E04, E05, and E07 recovered all five missed points. E06 lost two points because the answer omitted the outstanding shipment check in both the decision and reply. The gate still requires eight correct decisions.
- Verified the eight saved answers and scoring totals. All 43 backend tests and the Next.js production build passed.
- **Review checkpoint** · Review the E06 deduction and the revised prompt. This run repeated the eight pilot cases after tuning on their results. Performance on new cases and a live CasePilot integration remains unevaluated.
