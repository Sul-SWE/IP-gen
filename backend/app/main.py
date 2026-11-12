"""Application factory: API, security headers, error format, static frontend."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.engine import Engine
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import auth
from .api import router
from .config import FRONTEND_DIR, Settings, load_settings
from .db import make_engine, make_session_factory, transaction
from .errors import ApiError
from .services import rules

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; "
       "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")


def create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    settings = settings or load_settings()
    engine = engine or make_engine(settings.database_url)
    factory = make_session_factory(engine)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        with transaction(factory) as db:      # first run: default rules and the admin account
            rules.seed_defaults(db)
            auth.ensure_admin(db, settings)
        yield

    app = FastAPI(title="IP Generator", version="1.0", lifespan=lifespan, docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = factory
    app.state.limiter = auth.LoginLimiter(settings.login_max_fails, settings.login_window_minutes)

    if settings.allowed_origins:   # locked down: same-origin only unless origins are listed explicitly
        app.add_middleware(CORSMiddleware, allow_origins=list(settings.allowed_origins), allow_credentials=True,
                           allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["Content-Type", "X-CSRF-Token"])

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("Content-Security-Policy", CSP)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        if request.url.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        else:
            resp.headers.setdefault("Cache-Control", "no-cache")
        return resp

    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError):
        resp = JSONResponse(exc.body(), status_code=exc.status)
        if exc.code == "session_replaced":
            resp.delete_cookie(auth.COOKIE, path="/")
        return resp

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        details = [f"{'.'.join(str(p) for p in e['loc'][1:]) or 'request'}: {e['msg']}" for e in exc.errors()]
        return JSONResponse({"error": "validation", "message": "Some values are missing or not valid.", "details": details}, status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"error": "http", "message": str(exc.detail), "details": []}, status_code=exc.status_code)
        return JSONResponse({"error": "not_found", "message": "Page not found.", "details": []}, status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def server_error(_: Request, exc: Exception):   # never leak internals
        return JSONResponse({"error": "server", "message": "Something went wrong on the server. Nothing was changed.", "details": []}, status_code=500)

    app.include_router(router)
    if FRONTEND_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
    return app
