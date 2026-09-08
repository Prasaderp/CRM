from __future__ import annotations

import math
import re
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Header, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, ValidationError
from starlette.responses import JSONResponse

from real_estate_crm.leads.normalization import normalize_lead
from real_estate_crm.leads.schemas import LeadAccepted, LeadBodyTooLarge, MalformedLeadBody, parse_lead_request
from real_estate_crm.leads.service import IdempotencyConflict, LeadService, PropertyNotFound

router = APIRouter(prefix="/api/v1", tags=["public"])
_SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,78}[a-z0-9])?$")


class PropertyResponse(BaseModel):
    model_config = ConfigDict(
        alias_generator=lambda value: value.split("_")[0] + "".join(p.title() for p in value.split("_")[1:]),
        extra="forbid",
        from_attributes=True,
        populate_by_name=True,
    )

    slug: str
    title: str
    summary: str
    locality: str
    price_label: str | None
    project_registration_number: str | None
    registration_authority_url: str | None


@dataclass(slots=True)
class _Bucket:
    tokens: float
    updated_at: float
    last_seen_at: float

    def available(self, now: float, *, capacity: float, refill_per_second: float) -> float:
        return min(capacity, self.tokens + max(0.0, now - self.updated_at) * refill_per_second)


class LeadRateLimiter:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic, max_peers: int = 10_000) -> None:
        self._clock = clock
        self._max_peers = max_peers
        now = clock()
        self._global = _Bucket(60.0, now, now)
        self._peers: OrderedDict[str, _Bucket] = OrderedDict()
        self._lock = threading.Lock()
        self.fast_completion_count = 0

    def consume(self, peer: str) -> tuple[bool, int]:
        now = self._clock()
        with self._lock:
            self._expire_peers(now)
            bucket = self._peers.get(peer)
            if bucket is None:
                if len(self._peers) >= self._max_peers:
                    self._peers.popitem(last=False)
                bucket = _Bucket(5.0, now, now)
                self._peers[peer] = bucket
            peer_tokens = bucket.available(now, capacity=5.0, refill_per_second=1 / 60)
            global_tokens = self._global.available(now, capacity=60.0, refill_per_second=1.0)
            bucket.tokens, bucket.updated_at, bucket.last_seen_at = peer_tokens, now, now
            self._global.tokens, self._global.updated_at, self._global.last_seen_at = global_tokens, now, now
            self._peers.move_to_end(peer)
            if peer_tokens >= 1 and global_tokens >= 1:
                bucket.tokens -= 1
                self._global.tokens -= 1
                return True, 0
            waits = []
            if peer_tokens < 1:
                waits.append((1 - peer_tokens) * 60)
            if global_tokens < 1:
                waits.append(1 - global_tokens)
            return False, max(1, min(60, math.ceil(max(waits))))

    def record_fast_completion(self) -> None:
        with self._lock:
            self.fast_completion_count += 1

    def _expire_peers(self, now: float) -> None:
        while self._peers:
            peer, bucket = next(iter(self._peers.items()))
            if now - bucket.last_seen_at < 900:
                break
            del self._peers[peer]


def _error(request: Request, status: int, code: str, message: str, *, retry_after: int | None = None) -> JSONResponse:
    headers = {"Cache-Control": "private, no-store"}
    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)
    return JSONResponse(
        {"error": {"code": code, "message": message}, "requestId": request.state.request_id},
        status_code=status,
        headers=headers,
    )


def _service(request: Request) -> LeadService:
    return request.app.state.lead_service  # type: ignore[no-any-return]


@router.get(
    "/properties/{slug}",
    operation_id="getProperty",
    response_model=PropertyResponse,
    response_model_by_alias=True,
)
async def get_property(slug: str, request: Request) -> PropertyResponse | JSONResponse:
    if not _SLUG.fullmatch(slug):
        return _error(request, 404, "property_not_found", "Property not found")
    row = await run_in_threadpool(_service(request).get_property, slug)
    if row is None:
        return _error(request, 404, "property_not_found", "Property not found")
    return PropertyResponse.model_validate(row)


@router.post(
    "/leads",
    operation_id="createLead",
    status_code=201,
    response_model=LeadAccepted,
    response_model_by_alias=True,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/LeadRequest"}}},
        }
    },
)
async def create_lead(
    request: Request,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    started_at = time.monotonic()
    limiter: LeadRateLimiter = request.app.state.lead_rate_limiter
    peer = request.client.host if request.client else "unknown"
    allowed, retry_after = limiter.consume(peer)
    if not allowed:
        return _error(request, 429, "rate_limited", "Request rate limit exceeded", retry_after=retry_after)
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        return _error(request, 415, "unsupported_media_type", "Content-Type must be application/json")
    try:
        key = uuid.UUID(idempotency_key) if idempotency_key is not None else None
        if key is None or key.version != 4 or key.variant != uuid.RFC_4122:
            raise ValueError
    except (ValueError, AttributeError):
        return _error(request, 400, "invalid_idempotency_key", "Idempotency-Key must be a UUIDv4")
    try:
        parsed_length = int(request.headers["content-length"]) if "content-length" in request.headers else None
        if parsed_length is not None and parsed_length < 0:
            raise ValueError
    except ValueError:
        return _error(request, 400, "malformed_request", "Malformed Content-Length")
    max_bytes = request.app.state.settings.max_request_body_size_bytes
    if parsed_length is not None and parsed_length > max_bytes:
        return _error(request, 413, "body_too_large", "Request body exceeds the allowed size")
    try:
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > max_bytes:
                raise LeadBodyTooLarge
        lead_input = parse_lead_request(bytes(raw), max_bytes=max_bytes)
        if lead_input.website:
            return _error(request, 422, "validation_failed", "Request validation failed")
        lead = normalize_lead(lead_input)
    except LeadBodyTooLarge:
        return _error(request, 413, "body_too_large", "Request body exceeds the allowed size")
    except MalformedLeadBody:
        return _error(request, 400, "malformed_json", "Request body must be valid JSON")
    except (ValidationError, ValueError):
        return _error(request, 422, "validation_failed", "Request validation failed")
    try:
        accepted, _replayed = await run_in_threadpool(_service(request).accept, lead, key)
    except IdempotencyConflict:
        return _error(request, 409, "idempotency_conflict", "Idempotency-Key was already used for another request")
    except PropertyNotFound:
        return _error(request, 404, "property_not_found", "Property not found")
    if time.monotonic() - started_at < 1:
        limiter.record_fast_completion()
    return JSONResponse(
        accepted.model_dump(mode="json", by_alias=True),
        status_code=201,
        headers={"Cache-Control": "private, no-store"},
    )
