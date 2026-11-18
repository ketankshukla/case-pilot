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
