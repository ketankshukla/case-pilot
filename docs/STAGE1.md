# CasePilot Stage 1 specification

CasePilot is a fictional support desk for board-game orders. A support representative opens a seeded customer case, checks the order facts and policy evidence, and sees an exact proposal or an explanation of what is missing. An authenticated local reviewer controls approval, denial, editing, and execution.

Stage 1 uses deterministic replay with zero model-provider calls. Codex generated the implementation from requirements supplied and reviewed by the product owner. The public repository contains the source and fictional fixtures. The hosted desk requires Vercel Authentication and serves read-only replay. Reviewer decisions, sandbox writes, and retained audit records belong to the local desk.

## Workspace and data flow

| Area | What the representative can inspect |
| --- | --- |
| Case inbox | Seeded request titles and scenario IDs within the session's customer scope |
| Case workspace | The request, versioned order facts, and questions to resolve missing information |
| Policy evidence | Applicable passages with source ID, title, version, effective date, and approval status |
| Exact-action review | The remedy, amount or quantity, validation outcome, saved revision, reviewer decision, execution status, and receipt |
| Run history and audit | Current replay tool outcomes and decisions, plus saved local investigations and sandbox events |

Next.js delivers the desk and handles the local reviewer session. FastAPI derives customer scope and role on the server and exposes typed operations for order, line, refund, shipment, and policy facts. On the local desk, a reviewer signs in with a separate configured key. The frontend checks the browser origin and keeps a signed, HTTP-only, one-hour session cookie. FastAPI checks the reviewer credential again at the mutation endpoint.

Replay retrieves evidence from SQLite full-text search using a bounded set of case intents. Product, region, approval status, and effective dates determine applicability. A deterministic validation step checks eligibility, facts, and citation support before creating a candidate. Customer messages and document excerpts are treated as data. The replay uses at most six read attempts, retries a timed-out read once, and applies a two-second read limit, a twenty-second investigation limit, and a 4,000-character request cap.

The local SQLite database retains reviewed revisions, decisions, executions, and audit events. The executor reserves or writes within an atomic transaction and verifies the persisted result in a separate readback. The record is a refund ledger entry, a replacement request, or an outbox draft. All three are fictional. [Architecture and decision diagrams](FLOWS.md)

## Fictional policies

The fixed eligibility clock is **November 18, 2026 at 12:00 UTC**. Amounts use integer US cents, including taxes and shipping in fixture prices. Ordinary fixtures and adversarial fixtures are kept separate.

| Policy | Rule |
| --- | --- |
| KB01 v1 · Returned orders | An unused order is within the window through day 30 after delivery. The return must be received before a refund. Day 31 is outside the window. Used items escalate. |
| KB02 v1 · Damaged items | Within 14 days of delivery, a damaged line with a completed declaration can qualify for a replacement or a refund within the net paid line amount. A unit can receive only one remedy. |
| KB03 v1 · Delays | At least seven calendar days after the promised date, a status draft uses the known shipment facts. Replacement requires a checked shipment and eligible stock and remedy history. Unknown status leaves the delivery date unverified. A changed shipment can invalidate a proposal. |
| KB04 v1 · Refund balances | The maximum is the settled paid amount less verified refunds and pending reservations. Both the order and line limits apply. An uncertain write reserves its amount until reconciliation. |
| KB05 v1 · Evidence | Current approved evidence must match the order's product and region. A gap or conflict in applicable evidence requires escalation. |

The base examples are C100's $80 unused return O100, the $40 and $60 lines on O200, and the late shipment O300. O900 belongs to C200 and tests the customer boundary. Scenario variants use explicitly identified fixtures or isolated test databases so the base examples remain reproducible.

## Review and execution states

| State | How it advances |
| --- | --- |
| Investigating | A bounded replay reads authorized facts and searches for applicable evidence. |
| Awaiting information | Ask for an order ID, confirmation of a candidate, or a missing shipment fact. The representative resolves the gap before proceeding. |
| Escalated | Missing or conflicting evidence, failed eligibility, or unverified tool data goes to human review. |
| Awaiting review | A prepared proposal saves an exact revision. A valid revision can be approved or denied. An edit creates a new revision for review. |
| Denied | The reviewer decision and reason are recorded. A later reconsideration needs a new revision. |
| Approved | A reviewer has approved the exact revision. A separate execution request still has to pass the server's current checks. |
| Invalidated | Stale facts, policy, or balance invalidate the review basis. Re-evaluate and seek fresh approval. |
| Executing | The server starts one operation tied to the approved revision and idempotency key. Matching retries reuse the operation. |
| Failed | A confirmed rejection leaves the remedy incomplete and requires a fresh review attempt. |
| Uncertain | An unresolved write reserves the amount or eligible unit where applicable. Reconciliation checks the same operation ID. |
| Completed | A verified readback matches the saved action and produces a receipt. |

Open **Saved audit trail** under **Run history** to connect a saved investigation to its case and scenario. **Saved investigations** records the actor, fixture and policy versions, order version, tool outcomes, decision, duration, and provider usage. **Review and execution** shows revisions, state transitions, operation IDs, and an idempotency fingerprint where available. The receipt shows the verified record after readback. Preparing a proposal saves its replay. Use **Save investigation to audit** to retain a run when the case pauses or escalates. [Scenario coverage and evaluation](EVALUATION.md)

## Decision log

| Decision | Reason and tradeoff |
| --- | --- |
| Next.js and FastAPI with narrow APIs | The browser stays focused on the workflow. The backend owns typed facts, authorization, and mutations. |
| SQLite for the local demo | A single resettable database supports consistent reads, transactions, and an inspectable ledger. The hosted fixture database is temporary and serves replay only. |
| Full-text policy search with structured checks | The evidence search is small and explainable. Policy versions and applicability are visible, and the server independently checks eligibility and financial limits. |
| Deterministic replay with no provider calls | Local demo credentials are sufficient to repeat the seeded scenarios. Live-model behavior would require separate approval and evaluation. |
| Review the saved revision | Approval has a precise payload. An edit, stale fact, or balance change can invalidate that authorization rather than silently changing the approved action. |
| Reconcile the original operation | A repeated click or lost response must lead back to the same record, with reservations protecting the balance while the result is unconfirmed. |
| Keep the hosted desk read-only | The reviewer credential, durable SQLite data, and local write routes stay with the local demo. GitHub triggers the hosted build. |

## Five-minute portfolio walkthrough

Use the [local setup and reviewer sign-in](../README.md#local-reviewer-walkthrough) and a fresh set of walkthrough cases. The fixed fixture clock makes the examples reproducible.

| Time | Show | Say |
| --- | --- | --- |
| 0:00–0:45 | Stage 1 overview diagram and Demo banner | “I specified a support workflow with an evidence-backed proposal and human-controlled execution. I used Codex to implement it, then worked through the cases by checkpoint.” |
| 0:45–1:45 | [SC01](http://127.0.0.1:3000/?case=CP-0100), O100 facts and KB01 and KB04 links | “This case ties the $80 proposal to the delivered order, the recorded return, the policy versions, and the verified balance. The replay is deterministic.” |
| 1:45–2:45 | Prepare, approve and execute SC01 | “Approval saves the review decision for one revision. Execution checks current facts and reads the matching ledger entry back before presenting the receipt.” |
| 2:45–4:15 | [SC13](http://127.0.0.1:3000/?case=CP-0113) with **Timeout after commit** | “The result is uncertain, so the balance remains reserved. I reconcile the original operation ID and inspect the one verified entry and its audit events.” |
| 4:15–5:00 | Decision flow and scenario evaluation | “The test matrix maps boundaries, customer scope, edits, retry behavior, stale approvals, and discrepancies to explicit cases. Hosted replay is read-only. Local results are sandbox records.” |

## Future roadmap

- Consider a paid live model only after agreeing on provider setup, an evaluation baseline, and a usage budget.
- Evaluate PostgreSQL if shared durable storage and concurrent reviewers become necessary.
- Consider MCP for a future tool integration boundary and A2A for future specialist advisory handoffs. Both belong to later designs.
- Review identity, tenant isolation, secrets, rate limits, abuse, billing, and operations before deciding whether to release a public interactive service.
