from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import JSONResponse

from real_estate_crm.admin.service import (
    AdminService,
    InquiryFilters,
    InquiryNotFound,
    InvalidCursor,
    InvalidInquiryMutation,
    StaleInquiryVersion,
)
from real_estate_crm.auth.routes import require_csrf_roles, require_roles
from real_estate_crm.auth.service import AuthenticatedSession
from real_estate_crm.observability import safe_event

router = APIRouter(prefix="/api/v1", tags=["crm"])
CRM_ROLES = ("admin", "agent")
Status = Literal["new", "contacted", "qualified", "viewing", "won", "lost", "closed"]


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=lambda value: value.split("_")[0] + "".join(part.title() for part in value.split("_")[1:]),
        populate_by_name=True,
        extra="forbid",
    )


class ContactResponse(ApiModel):
    full_name: str
    email: str | None
    phone: str | None


class PropertySummary(ApiModel):
    id: uuid.UUID
    title: str


class UserSummary(ApiModel):
    id: uuid.UUID
    display_name: str


class InquirySummary(ApiModel):
    id: uuid.UUID
    reference: str
    status: Status
    version: int
    source_platform: Literal["facebook", "instagram", "tiktok", "x", "direct", "unknown"]
    intent: Literal["buy", "rent", "sell", "information"] | None
    submitted_at: datetime
    contact: ContactResponse
    property: PropertySummary
    assignee: UserSummary | None


class ConsentSummary(ApiModel):
    notice_version: str
    requested_contact: bool
    marketing: bool
    ad_measurement: bool
    recorded_at: datetime


class HistoryActor(ApiModel):
    id: uuid.UUID
    display_name: str


class StatusHistoryItem(ApiModel):
    id: uuid.UUID
    from_status: Status
    to_status: Status
    created_at: datetime
    actor: HistoryActor


class InquiryDetail(InquirySummary):
    capture_surface: Literal["website"]
    form_version: str
    budget_band: str | None
    timeframe: str | None
    preferred_contact_method: Literal["email", "phone", "whatsapp", "no_preference"] | None
    message: str | None
    dedupe_state: Literal["clear", "review"]
    updated_at: datetime
    consent: ConsentSummary | None
    status_history: list[StatusHistoryItem]


class InquiryPageResponse(ApiModel):
    items: list[InquirySummary]
    next_cursor: str | None


class AssigneeChoice(UserSummary):
    role: Literal["admin", "agent"]


class StatusMutation(ApiModel):
    status: Status
    expected_version: int = Field(ge=1)


class AssignmentMutation(ApiModel):
    assigned_user_id: uuid.UUID | None
    expected_version: int = Field(ge=1)


def _service(request: Request) -> AdminService:
    return request.app.state.admin_service  # type: ignore[no-any-return]


def _failure(request: Request, status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message}, "requestId": request.state.request_id},
        status_code=status,
        headers={"Cache-Control": "private, no-store"},
    )


async def _detail_or_error(request: Request, call: object, *args: object, **kwargs: object) -> InquiryDetail | JSONResponse:
    try:
        result: Any = await run_in_threadpool(call, *args, **kwargs)  # type: ignore[arg-type]
        return InquiryDetail.model_validate(result)
    except InquiryNotFound:
        return _failure(request, 404, "inquiry_not_found", "Inquiry not found")
    except StaleInquiryVersion:
        request.app.state.metrics.observe_stale_version()
        return _failure(request, 409, "stale_version", "Inquiry was changed by another user")
    except InvalidInquiryMutation as exc:
        return _failure(request, 422, "invalid_mutation", str(exc))


@router.get(
    "/inquiries",
    operation_id="listInquiries",
    response_model=InquiryPageResponse,
    responses={401: {"description": "Authentication required"}, 403: {"description": "Role denied"}},
)
async def list_inquiries(
    request: Request,
    session: Annotated[AuthenticatedSession | JSONResponse, Depends(require_roles(*CRM_ROLES))],
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query(min_length=1, max_length=256)] = None,
    status: Annotated[Status | None, Query()] = None,
    property_id: Annotated[uuid.UUID | None, Query(alias="propertyId")] = None,
    assigned_user_id: Annotated[uuid.UUID | None, Query(alias="assignedUserId")] = None,
) -> InquiryPageResponse | JSONResponse:
    if isinstance(session, JSONResponse):
        return session
    try:
        page = await run_in_threadpool(
            _service(request).list_inquiries,
            page_size=page_size,
            cursor=cursor,
            filters=InquiryFilters(status, property_id, assigned_user_id),
        )
    except InvalidCursor:
        return _failure(request, 422, "invalid_cursor", "Cursor is invalid")
    return InquiryPageResponse.model_validate({"items": page.items, "nextCursor": page.next_cursor})


@router.get(
    "/inquiries/{inquiry_id}",
    operation_id="getInquiry",
    response_model=InquiryDetail,
    responses={401: {"description": "Authentication required"}, 403: {"description": "Role denied"}, 404: {"description": "Inquiry not found"}},
)
async def get_inquiry(
    inquiry_id: uuid.UUID,
    request: Request,
    session: Annotated[AuthenticatedSession | JSONResponse, Depends(require_roles(*CRM_ROLES))],
) -> InquiryDetail | JSONResponse:
    if isinstance(session, JSONResponse):
        return session
    return await _detail_or_error(request, _service(request).get_inquiry, inquiry_id)


@router.get(
    "/users",
    operation_id="listAssignees",
    response_model=list[AssigneeChoice],
    responses={401: {"description": "Authentication required"}, 403: {"description": "Role denied"}},
)
async def list_users(
    request: Request,
    session: Annotated[AuthenticatedSession | JSONResponse, Depends(require_roles(*CRM_ROLES))],
) -> list[AssigneeChoice] | JSONResponse:
    if isinstance(session, JSONResponse):
        return session
    users = await run_in_threadpool(_service(request).list_active_users)
    return [AssigneeChoice.model_validate(user) for user in users]


@router.patch(
    "/inquiries/{inquiry_id}/status",
    operation_id="updateInquiryStatus",
    response_model=InquiryDetail,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Role or CSRF denied"},
        404: {"description": "Inquiry not found"},
        409: {"description": "Stale inquiry version"},
    },
)
async def update_status(
    inquiry_id: uuid.UUID,
    payload: StatusMutation,
    request: Request,
    session: Annotated[AuthenticatedSession | JSONResponse, Depends(require_csrf_roles(*CRM_ROLES))],
) -> InquiryDetail | JSONResponse:
    if isinstance(session, JSONResponse):
        return session
    result = await _detail_or_error(
        request,
        _service(request).update_status,
        inquiry_id,
        status=payload.status,
        expected_version=payload.expected_version,
        actor_user_id=session.user_id,
        request_id=uuid.UUID(request.state.request_id),
    )
    if isinstance(result, InquiryDetail):
        safe_event(
            "admin.inquiry.changed",
            request_id=request.state.request_id,
            actor_id=str(session.user_id),
            inquiry_id=str(inquiry_id),
            action="status",
            new_status=payload.status,
        )
    return result


@router.patch(
    "/inquiries/{inquiry_id}/assignment",
    operation_id="updateInquiryAssignment",
    response_model=InquiryDetail,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Role or CSRF denied"},
        404: {"description": "Inquiry not found"},
        409: {"description": "Stale inquiry version"},
    },
)
async def update_assignment(
    inquiry_id: uuid.UUID,
    payload: AssignmentMutation,
    request: Request,
    session: Annotated[AuthenticatedSession | JSONResponse, Depends(require_csrf_roles(*CRM_ROLES))],
) -> InquiryDetail | JSONResponse:
    if isinstance(session, JSONResponse):
        return session
    result = await _detail_or_error(
        request,
        _service(request).update_assignment,
        inquiry_id,
        assigned_user_id=payload.assigned_user_id,
        expected_version=payload.expected_version,
        actor_user_id=session.user_id,
        request_id=uuid.UUID(request.state.request_id),
    )
    if isinstance(result, InquiryDetail):
        safe_event(
            "admin.inquiry.changed",
            request_id=request.state.request_id,
            actor_id=str(session.user_id),
            inquiry_id=str(inquiry_id),
            action="assignment",
        )
    return result


__all__ = ["router"]
