# CasePilot

CasePilot is a local portfolio application for investigating fictional board-game support cases. Checkpoint 1 is a fixture-driven walkthrough of the support desk. The interface shows a request, order facts, policy excerpts and an exact-action preview. The Stage 1 goal is a reviewer-controlled sandbox with verified receipts.

See [progress and verification](docs/PROGRESS.md) for the current checkpoint. This code was generated with Codex and is being reviewed in slices by the product owner.

## Windows setup

Use PowerShell, Git, Node.js 24 LTS with npm, and Python 3.14. The demo runs on loopback ports 3000 (Next.js) and 8000 (FastAPI). It uses SQLite bundled with Python.

```powershell
Set-Location -LiteralPath 'E:\casepilot'
python -m venv .venv
& '.\.venv\Scripts\python.exe' -m pip install -r '.\backend\requirements-dev.txt'
& '.\.venv\Scripts\python.exe' -m backend.seed --reset
npm --prefix '.\frontend' ci

$demoToken = & '.\.venv\Scripts\python.exe' -c 'import secrets; print(secrets.token_urlsafe(32))'
"CASEPILOT_DEMO_TOKEN=$demoToken" | Set-Content -LiteralPath '.\frontend\.env.local' -Encoding ascii
```

Generate the token once during setup. The ignored `.env.local` file is shared by the two server processes. [The safe example](frontend/.env.example) lists the variable name. The browser receives the fictional case data. Next.js adds the bearer token on the server when it calls FastAPI. FastAPI uses a fixed support persona scoped to C100. Both servers bind to `127.0.0.1` for the local demo.

### Start each service in its own PowerShell window

Backend:

```powershell
Set-Location -LiteralPath 'E:\casepilot'
$env:CASEPILOT_DEMO_TOKEN = (Get-Content -LiteralPath '.\frontend\.env.local' | Where-Object { $_ -like 'CASEPILOT_DEMO_TOKEN=*' }) -replace '^CASEPILOT_DEMO_TOKEN=', ''
& '.\.venv\Scripts\python.exe' -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

Frontend:

```powershell
Set-Location -LiteralPath 'E:\casepilot'
npm --prefix '.\frontend' run dev
```

Open [the local support desk](http://127.0.0.1:3000). Start with **Refund for a received return**, then try the damaged-game and late-delivery cases.

### Reset fixtures and run checks

The reset replaces the local sandbox records and restores the fixture clock to `2026-11-18 12:00 UTC`.

```powershell
Set-Location -LiteralPath 'E:\casepilot'
& '.\.venv\Scripts\python.exe' -m backend.seed --reset
& '.\.venv\Scripts\python.exe' -m unittest discover -s backend/tests -v
npm --prefix '.\frontend' run build
```

## Technology choices

The slice pins Next.js 16.4.6 and React 19.3.1. Next.js 16 is on the active support line, and React 19.3 is a stable release. [Next.js support policy](https://nextjs.org/support-policy), [React release notes](https://react.dev/blog/2026/09/09/react-19-3).

FastAPI 0.164.0 provides a typed response for the workspace. Uvicorn 0.54.0 serves it on loopback. SQLite keeps the fixtures and local ledger in one resettable file. [FastAPI releases](https://fastapi.tiangolo.com/release-notes/), [Uvicorn release notes](https://github.com/Kludex/uvicorn/blob/main/docs/release-notes.md).
