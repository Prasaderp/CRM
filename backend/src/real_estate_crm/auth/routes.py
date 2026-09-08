from __future__ import annotations

import hmac
from collections.abc import Awaitable, Callable
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Cookie, Depends, Header, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import JSONResponse, Response

from real_estate_crm.auth.service import (
    AuthenticatedSession,
    AuthenticationRejected,
    AuthService,
    InactiveUser,
)
from real_estate_crm.observability import safe_event

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])
SESSION_COOKIE_PATH = "/"


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class SessionResponse(BaseModel):
    model_config = ConfigDict(alias_generator=lambda value: value.split("_")[0] + "".join(
        part.title() for part in value.split("_")[1:]
    ), populate_by_name=True, extra="forbid")

    user_id: str
    display_name: str
    role: Literal["admin", "agent"]
    idle_expires_at: str
    absolute_expires_at: str


def auth_service(request: Request) -> AuthService:
    return request.app.state.auth_service  # type: ignore[no-any-return]


def _failure(request: Request, status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message}, "requestId": request.state.request_id},
        status_code=status,
        headers={"Cache-Control": "private, no-store"},
    )


def _origin_allowed(request: Request) -> bool:
    origin = request.headers.get("origin")
    if not origin:
        return False
    settings = request.app.state.settings
    allowed = {str(settings.public_origin).rstrip("/"), *(value.rstrip("/") for value in settings.trusted_origins)}
    return origin.rstrip("/") in allowed


async def current_session(
    request: Request,
    token: Annotated[str | None, Cookie(alias="session_id")] = None,
) -> AuthenticatedSession | JSONResponse:
    cookie_name = request.app.state.settings.session_cookie_name
    token = request.cookies.get(cookie_name) if cookie_name != "session_id" else token
    current = await run_in_threadpool(auth_service(request).lookup_session, token or "")
    return current or _failure(request, 401, "authentication_required", "Authentication required")


def require_roles(*roles: str) -> Callable[..., Awaitable[AuthenticatedSession | JSONResponse]]:
    allowed = frozenset(roles)

    async def dependency(
        request: Request,
        session: Annotated[AuthenticatedSession | JSONResponse, Depends(current_session)],
    ) -> AuthenticatedSession | JSONResponse:
        if isinstance(session, JSONResponse):
            return session
        if session.role not in allowed:
            return _failure(request, 403, "forbidden", "Access denied")
        return session

    return dependency


async def require_csrf(
    request: Request,
    session: Annotated[AuthenticatedSession | JSONResponse, Depends(current_session)],
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> AuthenticatedSession | JSONResponse:
    if isinstance(session, JSONResponse):
        return session
    cookie = request.cookies.get(request.app.state.settings.csrf_cookie_name)
    if (
        not _origin_allowed(request)
        or not cookie
        or not csrf_header
        or not hmac.compare_digest(cookie, csrf_header)
        or not auth_service(request).verify_csrf(session, csrf_header)
    ):
        return _failure(request, 403, "csrf_rejected", "Request could not be verified")
    return session


def require_csrf_roles(*roles: str) -> Callable[..., Awaitable[AuthenticatedSession | JSONResponse]]:
    allowed = frozenset(roles)

    async def dependency(
        request: Request,
        session: Annotated[AuthenticatedSession | JSONResponse, Depends(require_csrf)],
    ) -> AuthenticatedSession | JSONResponse:
        if isinstance(session, JSONResponse):
            return session
        if session.role not in allowed:
            return _failure(request, 403, "forbidden", "Access denied")
        return session

    return dependency


def _session_response(session: AuthenticatedSession) -> SessionResponse:
    if session.role not in {"admin", "agent"}:
        raise ValueError("unsupported authenticated role")
    return SessionResponse(
        user_id=str(session.user_id),
        display_name=session.display_name,
        role=cast(Literal["admin", "agent"], session.role),
        idle_expires_at=session.idle_expires_at.isoformat(),
        absolute_expires_at=session.absolute_expires_at.isoformat(),
    )


def _set_cookies(response: JSONResponse, request: Request, token: str, csrf_token: str) -> None:
    settings = request.app.state.settings
    secure = settings.environment != "local"
    common = {"secure": secure, "samesite": "lax", "path": SESSION_COOKIE_PATH}
    response.set_cookie(settings.session_cookie_name, token, httponly=True, **common)
    response.set_cookie(settings.csrf_cookie_name, csrf_token, httponly=False, **common)


def _clear_cookies(response: Response, request: Request) -> None:
    settings = request.app.state.settings
    secure = settings.environment != "local"
    response.delete_cookie(
        settings.session_cookie_name, path=SESSION_COOKIE_PATH, secure=secure, httponly=True, samesite="lax"
    )
    response.delete_cookie(
        settings.csrf_cookie_name, path=SESSION_COOKIE_PATH, secure=secure, httponly=False, samesite="lax"
    )


@router.post("/login", operation_id="login", response_model=SessionResponse)
async def login(payload: LoginRequest, request: Request) -> SessionResponse | JSONResponse:
    if not _origin_allowed(request):
        return _failure(request, 403, "origin_rejected", "Request could not be verified")
    source_ip = request.client.host if request.client else "unknown"
    service = auth_service(request)
    try:
        user = await run_in_threadpool(service.authenticate, str(payload.email), payload.password, source_ip)
        issued = await run_in_threadpool(service.issue_session, user.id)
        current = await run_in_threadpool(service.lookup_session, issued.token, refresh=False)
    except (AuthenticationRejected, InactiveUser):
        request.app.state.metrics.observe_login_failure("invalid_credentials")
        safe_event(
            "auth.login.failed",
            request_id=request.state.request_id,
            reason="invalid_credentials",
        )
        return _failure(request, 401, "authentication_failed", "Invalid credentials")
    if current is None:
        return _failure(request, 401, "authentication_failed", "Invalid credentials")
    response = JSONResponse(_session_response(current).model_dump(by_alias=True))
    _set_cookies(response, request, issued.token, issued.csrf_token)
    return response


@router.get("/session", operation_id="getSession", response_model=SessionResponse)
async def get_session(
    session: Annotated[AuthenticatedSession | JSONResponse, Depends(current_session)],
) -> SessionResponse | JSONResponse:
    return session if isinstance(session, JSONResponse) else _session_response(session)


@router.post("/logout", operation_id="logout", status_code=204)
async def logout(
    request: Request,
    session: Annotated[AuthenticatedSession | JSONResponse, Depends(require_csrf)],
) -> Response:
    if isinstance(session, JSONResponse):
        return session
    token = request.cookies.get(request.app.state.settings.session_cookie_name, "")
    await run_in_threadpool(auth_service(request).revoke_session, token)
    response = Response(status_code=204)
    _clear_cookies(response, request)
    return response


__all__ = [
    "SessionResponse",
    "auth_service",
    "current_session",
    "require_csrf",
    "require_csrf_roles",
    "require_roles",
    "router",
]
