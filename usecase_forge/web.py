"""HTTP API.

On Vercel, steps run in the queue worker (`usecase_forge.worker`) and state lives in
Vercel Blob. Locally (no VERCEL env), steps run in a background thread and state is
kept in memory, so `uvicorn usecase_forge.web:app` works with no cloud setup.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from usecase_forge.config import load_settings
from usecase_forge.graph import default_dependencies
from usecase_forge.keyvault import KeyVault
from usecase_forge.runs import InputError, QuotaExceeded, RunService, TransientError
from usecase_forge.store import BlobRunStore, MemoryRunStore

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("usecase_forge")

TOPIC = "usecase-runs"
ON_VERCEL = os.getenv("VERCEL") == "1"


class ConfigError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def get_service() -> RunService:
    settings = load_settings()
    if os.getenv("BLOB_READ_WRITE_TOKEN"):
        store = BlobRunStore()
    elif ON_VERCEL:
        raise ConfigError("Storage is not configured: connect a Vercel Blob store to this project.")
    else:
        store = MemoryRunStore()

    secret = os.getenv("RUN_SECRET")
    vault = KeyVault(secret) if secret else (None if ON_VERCEL else KeyVault.ephemeral())

    if os.getenv("DEMO_MODE") == "1":
        from usecase_forge.demo import demo_dependencies

        deps_factory, has_key = demo_dependencies, True
    else:
        deps_factory = lambda api_key: default_dependencies(settings, api_key=api_key)  # noqa: E731
        has_key = bool(settings.google_api_key)

    return RunService(
        store=store,
        vault=vault,
        deps_factory=deps_factory,
        server_key_available=has_key,
        daily_limit=int(os.getenv("DAILY_RUN_LIMIT", "3")),
    )


# --- dispatching ------------------------------------------------------------

_local_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="run")


def _run_locally(message: dict | None) -> None:
    """Local stand-in for the queue: run steps back to back, retrying transient errors."""
    service, attempt = get_service(), 1
    while message:
        try:
            message, attempt = service.execute(message, attempt), 1
        except TransientError as exc:
            attempt += 1
            time.sleep(exc.delay)


async def dispatch(message: dict) -> None:
    if ON_VERCEL:
        from vercel.queue import send

        await send(TOPIC, message)
    else:
        _local_pool.submit(_run_locally, message)


# --- rate limiting (per instance; a cheap first line of defence) ---------------

_hits: dict[str, deque] = defaultdict(deque)
_hits_lock = threading.Lock()
RATE_LIMIT, RATE_WINDOW = 5, 60.0


def _rate_limited(client: str) -> bool:
    now = time.monotonic()
    with _hits_lock:
        q = _hits[client]
        while q and now - q[0] > RATE_WINDOW:
            q.popleft()
        if len(q) >= RATE_LIMIT:
            return True
        q.append(now)
        return False


# --- API ----------------------------------------------------------------------

# Swagger UI loads scripts from a CDN, which the production CSP blocks; keep it local-only.
app = FastAPI(
    title="UseCaseForge API",
    docs_url=None if ON_VERCEL else "/api/docs",
    openapi_url="/api/openapi.json",
)


SECURITY_HEADERS = {
    # Mirrors vercel.json so local and Docker runs enforce the same policy.
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
                               "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}


@app.middleware("http")
async def headers(request: Request, call_next):
    response = await call_next(request)
    for key, value in SECURITY_HEADERS.items():
        response.headers.setdefault(key, value)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(ConfigError)
async def config_error(_: Request, exc: ConfigError):
    return JSONResponse({"detail": str(exc)}, status_code=503)


class RunRequest(BaseModel):
    url: str = Field(min_length=3, max_length=500)
    extra_urls: list[str] = Field(default_factory=list, max_length=3)
    api_key: str | None = Field(default=None, max_length=200)


@app.get("/api/status")
def status():
    service = get_service()
    settings = load_settings()
    return {
        "ok": True,
        "model": settings.chat_model,
        "shared_key": service.server_key_available,
        "own_key_supported": service.vault is not None,
        "daily_limit": service.daily_limit,
        "runs_left_today": service.runs_left_today(),
    }


@app.post("/api/runs", status_code=202)
async def create_run(body: RunRequest, request: Request):
    client = request.headers.get("x-forwarded-for", request.client.host if request.client else "?").split(",")[0]
    if _rate_limited(client):
        raise HTTPException(429, "Too many requests. Please wait a minute and try again.")
    service = get_service()
    try:
        snapshot, message = service.create(body.url, body.extra_urls, body.api_key)
    except InputError as exc:
        raise HTTPException(400, str(exc)) from exc
    except QuotaExceeded as exc:
        raise HTTPException(429, str(exc)) from exc
    await dispatch(message)
    log.info("Run %s queued for %s", snapshot["id"], snapshot["state"]["url"])
    return {"id": snapshot["id"]}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    run = get_service().get(run_id)
    if run is None:
        raise HTTPException(404, "Run not found.")
    return run


@app.get("/api/runs/{run_id}/report.md", response_class=PlainTextResponse)
def get_report(run_id: str):
    run = get_service().get(run_id)
    if run is None or not run.get("report"):
        raise HTTPException(404, "Report not ready.")
    return PlainTextResponse(
        run["report"],
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="usecaseforge-{run_id[:8]}.md"'},
    )


if ON_VERCEL:
    from fastapi.responses import RedirectResponse

    @app.get("/", include_in_schema=False)
    def root():
        # The CDN normally serves public/index.html at "/" before this function runs.
        return RedirectResponse("/index.html", status_code=307)
else:
    # On Vercel, public/ is served by the CDN. Locally, serve it from here.
    from fastapi.staticfiles import StaticFiles

    public = Path(__file__).resolve().parent.parent / "public"
    if public.is_dir():
        app.mount("/", StaticFiles(directory=public, html=True), name="public")
