"""Read-only workspace for the private Vercel service binding."""

from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import Request, Response

from .app import create_app
from .database import reset_fixture_database


# Seed a private, disposable copy from the bundled fictional fixture.
_fixture_directory = TemporaryDirectory(prefix="casepilot-preview-")
_fixture_database = Path(_fixture_directory.name) / "demo.sqlite3"
reset_fixture_database(_fixture_database)

# Vercel generates a binding URL per deployment. Every read still requires the token.
app = create_app(_fixture_database, allow_binding_hosts=True, sandbox_actions=False)


@app.middleware("http")
async def reject_write_methods(request: Request, call_next):
    if request.method not in {"GET", "HEAD"}:
        return Response(status_code=405, headers={"Allow": "GET, HEAD"})
    return await call_next(request)
