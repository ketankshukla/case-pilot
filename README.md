# CasePilot

CasePilot is a portfolio application for investigating fictional board-game support cases. Deterministic replay uses a fixed case request and clock to read scoped facts, retrieve relevant policy passages, and propose a resolution. Checkpoint 3 adds reviewer decisions and verified execution in the local SQLite sandbox. Replay makes zero model-provider calls.

See [progress and verification](docs/PROGRESS.md) for the current checkpoint. This code was generated with Codex and is being reviewed in slices by the product owner.

## Windows setup

Use PowerShell, Git, Node.js 24 LTS with npm, and Python 3.14. The demo runs on loopback ports 3000 (Next.js) and 8000 (FastAPI). It uses SQLite bundled with Python.

```powershell
Set-Location -LiteralPath 'E:\casepilot'
python -m venv .venv
& '.\.venv\Scripts\python.exe' -m pip install -r '.\backend\requirements-dev.txt'
npm --prefix '.\frontend' ci
Push-Location -LiteralPath '.\backend'
& '..\.venv\Scripts\python.exe' -m casepilot.seed --reset
Pop-Location

$demoToken = & '.\.venv\Scripts\python.exe' -c 'import secrets; print(secrets.token_urlsafe(32))'
$reviewerToken = & '.\.venv\Scripts\python.exe' -c 'import secrets; print(secrets.token_urlsafe(32))'
@("CASEPILOT_DEMO_TOKEN=$demoToken", "CASEPILOT_REVIEWER_TOKEN=$reviewerToken") |
    Set-Content -LiteralPath '.\frontend\.env.local' -Encoding ascii
```

Generate the keys once during setup. The ignored `.env.local` file is shared by the two server processes. [The safe example](frontend/.env.example) lists the variable names. Both servers bind to `127.0.0.1`. If you already have a local demo token, generate and append only the reviewer entry to that file.

### Start each service in its own PowerShell window

Backend:

```powershell
Set-Location -LiteralPath 'E:\casepilot\backend'
$env:CASEPILOT_DEMO_TOKEN = (Get-Content -LiteralPath '..\frontend\.env.local' | Where-Object { $_ -like 'CASEPILOT_DEMO_TOKEN=*' }) -replace '^CASEPILOT_DEMO_TOKEN=', ''
$env:CASEPILOT_REVIEWER_TOKEN = (Get-Content -LiteralPath '..\frontend\.env.local' | Where-Object { $_ -like 'CASEPILOT_REVIEWER_TOKEN=*' }) -replace '^CASEPILOT_REVIEWER_TOKEN=', ''
& '..\.venv\Scripts\python.exe' -m uvicorn casepilot.app:app --host 127.0.0.1 --port 8000
```

Frontend:

```powershell
Set-Location -LiteralPath 'E:\casepilot'
npm --prefix '.\frontend' run dev
```

Open [the local support desk](http://127.0.0.1:3000). Start with **Refund for a received return**, follow a policy citation, then try the cases with missing information, missing evidence, or conflicting rules.

### Reset fixtures and run checks

After updating from Checkpoint 2, run the reset to install `stage1-v3`. The reset replaces local sandbox records, review history, and receipts and restores the fixture clock to `2026-11-18 12:00 UTC`.

```powershell
Set-Location -LiteralPath 'E:\casepilot\backend'
& '..\.venv\Scripts\python.exe' -m casepilot.seed --reset

Set-Location -LiteralPath 'E:\casepilot'
& '.\scripts\check-before-push.ps1'
```

## Checkpoint 2 reads

The Next.js server fetches the inbox with `GET /demo/workspace`, then requests one replay with `GET /demo/cases/{case_id}/investigation`. The replay uses the same scoped operations as these bearer-protected API routes.

| Route | Result |
| --- | --- |
| `GET /demo/orders/{order_id}` | Versioned order facts |
| `GET /demo/orders/{order_id}/lines/{line_id}` | Paid amount, quantity, and damage declaration for the line |
| `GET /demo/orders/{order_id}/refunds` | Prior, reserved, and remaining cents, with optional `line_id` |
| `GET /demo/orders/{order_id}/shipment` | Shipment status and recorded dates |
| `GET /demo/cases/{case_id}/policies` | Applicable approved passages and evidence status |

SQLite full-text search finds passages using the seeded case intent. The service checks approval status, product, region, and effective dates, then checks the required policy rules and verifies the proposed amount and citations against the facts. When evidence is missing or conflicts, the replay escalates the case. Investigation results are regenerated on each case view.

## Local reviewer walkthrough

1. Open the [local support desk](http://127.0.0.1:3000) and sign in as reviewer with the `CASEPILOT_REVIEWER_TOKEN` value from the ignored `frontend/.env.local` file. Keep that key local.
2. Open **SC01**, prepare the $80 proposal, and approve the saved revision. Check the approved state, then select **Execute approved action** to verify a sandbox receipt.
3. Open **SC03**, prepare the proposal, and deny it with a reason. Open **SC04**, prepare the invalid $100 draft, and save a new revision for `4000` cents. Review and approve the new revision before execution.
4. Open **SC13**, prepare and approve the proposal, then select **Timeout after commit** before execution. The case stays uncertain until **Reconcile operation** reads back the original operation and verifies a receipt.
5. **SC17** records a replacement request and **SC18** saves an honest draft in the local outbox. Both follow the same approval and verification steps.

Next.js checks the local browser origin on each review submission and keeps a signed, one-hour, HTTP-only reviewer session. FastAPI verifies a distinct reviewer bearer and keeps the reviewer scoped to C100. Review actions are disabled in the hosted app. Refunds are local ledger entries, replacements are local requests, and delay updates are local drafts.

## GitHub and Vercel

Run the pre-push script for every GitHub push. It checks the Python service and builds the Next.js production bundle. Once the Vercel project is linked, also run `vercel build` locally with the matching project settings for Vercel configuration or runtime changes. Push the verified commit to GitHub and check that commit's deployment status in Vercel. [Local Vercel builds](https://vercel.com/docs/cli/build).

The [root Vercel configuration](vercel.json) uses Services (Beta) to build `frontend/` and `backend/` together. When connecting the GitHub repository, use the **Services** framework preset with the repository root as the project root. Enable **Vercel Authentication → All Deployments** for the Stage 1 review and set a fresh `CASEPILOT_DEMO_TOKEN` for the protected environment. Vercel supplies `CASEPILOT_BACKEND_URL` automatically as a private binding from Next.js to FastAPI. [Vercel Services](https://vercel.com/docs/services), [Deployment Protection](https://vercel.com/changelog/protect-production-deployments-for-free-on-every-plan).

The hosted entry point seeds a temporary SQLite snapshot from the bundled fictional records and serves the read-only workspace. Reviewer sign-in and writes run only in the local demo. Hosted approval, execution, and receipt persistence would require shared durable storage. [Vercel filesystem support](https://vercel.com/docs/functions/runtimes#file-system-support).

## Technology choices

The slice pins Next.js 16.4.6 and React 19.3.1. Next.js 16 is on the active support line, and React 19.3 is a stable release. [Next.js support policy](https://nextjs.org/support-policy), [React release notes](https://react.dev/blog/2026/09/09/react-19-3).

FastAPI 0.164.0 provides a typed response for the workspace. Uvicorn 0.54.0 serves it on loopback. SQLite keeps the fixtures and local ledger in one resettable file. [FastAPI releases](https://fastapi.tiangolo.com/release-notes/), [Uvicorn release notes](https://github.com/Kludex/uvicorn/blob/main/docs/release-notes.md).
