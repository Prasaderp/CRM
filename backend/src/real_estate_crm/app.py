from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

import sqlalchemy as sa
from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from sqlalchemy.orm import Session, sessionmaker
from starlette.responses import Response
from starlette.responses import JSONResponse

from real_estate_crm.admin.routes import router as admin_router
from real_estate_crm.admin.service import AdminService
from real_estate_crm.auth.routes import router as auth_router
from real_estate_crm.auth.service import AuthService
from real_estate_crm.config import Settings, get_settings
from real_estate_crm.db import DatabaseError, get_session_factory
from real_estate_crm.leads.routes import LeadRateLimiter, router as lead_router
from real_estate_crm.leads.schemas import LeadRequest
from real_estate_crm.leads.service import IdempotencyStateError, LeadService
from real_estate_crm.observability import (
    Metrics,
    ReadinessProbe,
    alembic_heads,
    configure_logging,
    is_loopback,
    request_id,
    route_template,
    safe_event,
)


def create_app(
    *,
    settings: Settings | None = None,
    session_factory: sessionmaker[Session] | None = None,
    rate_limiter: LeadRateLimiter | None = None,
    service_factory: Callable[[sessionmaker[Session], Settings], LeadService] = LeadService,
    auth_service_factory: Callable[[sessionmaker[Session]], AuthService] = AuthService,
    admin_service_factory: Callable[[sessionmaker[Session]], AdminService] = AdminService,
    readiness_probe: Callable[[], tuple[bool, str]] | None = None,
    metrics: Metrics | None = None,
) -> FastAPI:
    cfg = settings or get_settings()
    sessions = session_factory or get_session_factory()
    app = FastAPI(title="Real-Estate Lead Capture CRM", version="0.1.0")
    app.state.settings = cfg
    app.state.lead_service = service_factory(sessions, cfg)
    app.state.auth_service = auth_service_factory(sessions)
    app.state.admin_service = admin_service_factory(sessions)
    app.state.lead_rate_limiter = rate_limiter or LeadRateLimiter()
    app.state.metrics = metrics or Metrics.create()
    app.state.readiness_probe = readiness_probe or ReadinessProbe(sessions, alembic_heads())
    configure_logging()

    @app.middleware("http")
    async def request_boundary(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        started_at = time.monotonic()
        request.state.request_id = request_id(request.headers.get("X-Request-ID"))
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        if request.url.path.startswith("/api/v1/"):
            response.headers["Cache-Control"] = "private, no-store"
        template = route_template(request.scope)
        duration = time.monotonic() - started_at
        app.state.metrics.observe_request(template, request.method, response.status_code, duration)
        safe_event(
            "http.request.completed",
            request_id=request.state.request_id,
            route=template,
            method=request.method,
            status=response.status_code,
            duration_ms=round(duration * 1000, 3),
        )
        return response

    @app.exception_handler(DatabaseError)
    async def database_unavailable(request: Request, _exc: Exception) -> JSONResponse:
        return _failure(request, 503, "service_unavailable", "Service temporarily unavailable")

    app.add_exception_handler(sa.exc.OperationalError, database_unavailable)

    @app.exception_handler(RequestValidationError)
    async def request_validation_failed(request: Request, _exc: RequestValidationError) -> JSONResponse:
        return _failure(request, 422, "validation_failed", "Request validation failed")

    @app.exception_handler(sa.exc.IntegrityError)
    async def persistence_failure(request: Request, _exc: Exception) -> JSONResponse:
        return _failure(request, 500, "internal_error", "An internal error occurred")

    app.add_exception_handler(IdempotencyStateError, persistence_failure)

    @app.exception_handler(Exception)
    async def unhandled_failure(request: Request, _exc: Exception) -> JSONResponse:
        return _failure(request, 500, "internal_error", "An internal error occurred")

    app.include_router(lead_router)
    app.include_router(auth_router)
    app.include_router(admin_router)

    @app.get("/health/live", include_in_schema=False)
    async def health_live() -> JSONResponse:
        return JSONResponse({"status": "live"}, headers={"Cache-Control": "no-store"})

    @app.get("/health/ready", include_in_schema=False)
    async def health_ready() -> JSONResponse:
        ready, reason = await run_in_threadpool(app.state.readiness_probe)
        return JSONResponse(
            {"status": "ready" if ready else "not_ready", "reason": reason},
            status_code=200 if ready else 503,
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/metrics", include_in_schema=False)
    async def prometheus_metrics(request: Request) -> Response:
        if not is_loopback(request.client.host if request.client else None):
            return Response(status_code=404, headers={"Cache-Control": "no-store"})
        return Response(
            app.state.metrics.render(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
            headers={"Cache-Control": "no-store"},
        )

    def public_openapi() -> dict[str, object]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
        lead_schema = LeadRequest.model_json_schema(by_alias=True, ref_template="#/components/schemas/{model}")
        definitions = lead_schema.pop("$defs", {})
        schemas = schema.setdefault("components", {}).setdefault("schemas", {})
        schemas.update(definitions)
        schemas["LeadRequest"] = lead_schema
        documented_headers = {
            "Cache-Control": {"description": "Sensitive API responses are private and not stored", "schema": {"type": "string"}},
            "X-Request-ID": {"description": "Opaque request correlation identifier", "schema": {"type": "string", "format": "uuid"}},
        }
        for path, path_item in schema.get("paths", {}).items():
            if not path.startswith("/api/v1/"):
                continue
            for method, operation in path_item.items():
                if method not in {"get", "post", "put", "patch", "delete"}:
                    continue
                for response in operation.get("responses", {}).values():
                    response.setdefault("headers", documented_headers)
        app.openapi_schema = schema
        return schema

    app.openapi = public_openapi  # type: ignore[method-assign]
    return app


def _failure(request: Request, status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message}, "requestId": request.state.request_id},
        status_code=status,
        headers={"Cache-Control": "private, no-store"},
    )


app = create_app()
