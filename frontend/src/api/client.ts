// biome-ignore-all lint/complexity/useLiteralKeys: strict index-signature access is intentional for untrusted JSON.
import type { components } from "./schema";

export type LeadRequest = components["schemas"]["LeadRequest"];
export type LeadAccepted = components["schemas"]["LeadAccepted"];
export type Property = components["schemas"]["PropertyResponse"];
export type LoginRequest = components["schemas"]["LoginRequest"];
export type Session = components["schemas"]["SessionResponse"];
export type Inquiry = components["schemas"]["InquirySummary"];
export type InquiryPage = components["schemas"]["InquiryPageResponse"];
export type InquiryDetailRecord = components["schemas"]["InquiryDetail"];
export type AssigneeChoice = components["schemas"]["AssigneeChoice"];
export type InquiryStatus = Inquiry["status"];

type Method = "GET" | "POST" | "PATCH" | "DELETE";
type RequestOptions = {
  method?: Method;
  body?: unknown;
  headers?: Readonly<Record<string, string>>;
  signal?: AbortSignal;
  authenticatedMutation?: boolean;
  retries?: number;
  query?: URLSearchParams;
};

const TRANSIENT_STATUSES = new Set([408, 425, 429, 500, 502, 503, 504]);
const SAFE_ERROR_CODES = new Set([
  "body_too_large",
  "authentication_failed",
  "authentication_required",
  "csrf_rejected",
  "forbidden",
  "idempotency_conflict",
  "inquiry_not_found",
  "invalid_idempotency_key",
  "invalid_cursor",
  "invalid_mutation",
  "malformed_json",
  "malformed_request",
  "property_not_found",
  "rate_limited",
  "service_unavailable",
  "stale_version",
  "unsupported_media_type",
  "validation_failed",
]);

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | undefined;
  readonly retryable: boolean;

  constructor(status: number, code: string, message: string, requestId?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.requestId = requestId;
    this.retryable = status === 0 || TRANSIENT_STATUSES.has(status);
  }
}

function csrfToken(): string | undefined {
  if (typeof document === "undefined") return undefined;
  const value = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith("csrf_token="))
    ?.slice("csrf_token=".length);
  if (!value) return undefined;
  try {
    return decodeURIComponent(value);
  } catch {
    return undefined;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function safeApiError(status: number, payload: unknown): ApiError {
  const envelope: { error?: unknown; requestId?: unknown } = isRecord(payload) ? payload : {};
  const detail: { code?: unknown } = isRecord(envelope.error) ? envelope.error : {};
  const suppliedCode = typeof detail.code === "string" ? detail.code : "request_failed";
  const code = SAFE_ERROR_CODES.has(suppliedCode) ? suppliedCode : "request_failed";
  const requestId =
    typeof envelope.requestId === "string" ? envelope.requestId.slice(0, 128) : undefined;
  const defaults: Record<number, string> = {
    400: "The request could not be processed.",
    404: "The requested resource was not found.",
    409: "This request conflicts with a previous submission.",
    413: "The submitted information is too large.",
    422: "Please review the submitted information.",
    429: "Too many requests. Please wait before trying again.",
    503: "The service is temporarily unavailable.",
  };
  return new ApiError(status, code, defaults[status] ?? "The request failed.", requestId);
}

async function decodeJson(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type")?.split(";", 1)[0]?.trim().toLowerCase();
  if (contentType !== "application/json") {
    throw response.ok
      ? new ApiError(
          response.status,
          "invalid_response",
          "The server returned an invalid response.",
        )
      : safeApiError(response.status, undefined);
  }
  try {
    return await response.json();
  } catch {
    throw response.ok
      ? new ApiError(
          response.status,
          "invalid_response",
          "The server returned an invalid response.",
        )
      : safeApiError(response.status, undefined);
  }
}

function retryDelay(response: Response | undefined, attempt: number): number {
  const seconds = Number(response?.headers.get("retry-after"));
  return Number.isFinite(seconds) && seconds > 0
    ? Math.min(seconds * 1_000, 5_000)
    : Math.min(150 * 2 ** attempt, 1_200);
}

function wait(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(signal.reason ?? new DOMException("Aborted", "AbortError"));
    const finish = () => {
      signal?.removeEventListener("abort", abort);
      resolve();
    };
    const timeout = window.setTimeout(finish, ms);
    const abort = () => {
      window.clearTimeout(timeout);
      reject(signal?.reason ?? new DOMException("Aborted", "AbortError"));
    };
    signal?.addEventListener("abort", abort, { once: true });
  });
}

export async function requestJson(path: string, options: RequestOptions = {}): Promise<unknown> {
  if (!path.startsWith("/api/") || path.includes("?")) {
    throw new TypeError("API paths must be fixed same-origin paths without query strings");
  }
  const method = options.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json", ...options.headers };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (options.authenticatedMutation) {
    if (method === "GET") throw new TypeError("CSRF is only valid for mutations");
    const token = csrfToken();
    if (!token) throw new ApiError(0, "csrf_unavailable", "Your session could not be verified.");
    headers["X-CSRF-Token"] = token;
  }
  const retries = method === "GET" ? Math.min(Math.max(options.retries ?? 2, 0), 2) : 0;
  for (let attempt = 0; ; attempt += 1) {
    let response: Response | undefined;
    try {
      const url = options.query?.size ? `${path}?${options.query}` : path;
      response = await fetch(url, {
        method,
        credentials: "same-origin",
        headers,
        ...(options.body === undefined ? {} : { body: JSON.stringify(options.body) }),
        ...(options.signal ? { signal: options.signal } : {}),
      });
      if (response.ok) return response.status === 204 ? undefined : await decodeJson(response);
      if (attempt < retries && TRANSIENT_STATUSES.has(response.status)) {
        await wait(retryDelay(response, attempt), options.signal);
        continue;
      }
      throw safeApiError(response.status, await decodeJson(response).catch(() => undefined));
    } catch (error) {
      if (error instanceof ApiError || options.signal?.aborted || !(error instanceof TypeError))
        throw error;
      if (attempt >= retries) {
        throw new ApiError(0, "network_error", "The server could not be reached.");
      }
      await wait(retryDelay(response, attempt), options.signal);
    }
  }
}

function requireDate(record: Record<string, unknown>, key: string): string {
  const value = requireString(record, key, false, 64) as string;
  if (!Number.isFinite(Date.parse(value)))
    throw new ApiError(200, "invalid_response", "The server returned an invalid response.");
  return value;
}

function requireUuid(record: Record<string, unknown>, key: string): string {
  const value = requireString(record, key, false, 36) as string;
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value))
    throw new ApiError(200, "invalid_response", "The server returned an invalid response.");
  return value;
}

function validUuid(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
}

function inquiryPath(id: string, suffix = ""): string {
  if (!validUuid(id)) throw new TypeError("Inquiry ID must be a UUID");
  return `/api/v1/inquiries/${id}${suffix}`;
}

function parseSession(payload: unknown): Session {
  if (!isRecord(payload))
    throw new ApiError(200, "invalid_response", "The server returned an invalid response.");
  const role = requireString(payload, "role", false, 16);
  if (role !== "admin" && role !== "agent")
    throw new ApiError(200, "invalid_response", "The server returned an invalid response.");
  return {
    userId: requireUuid(payload, "userId"),
    displayName: requireString(payload, "displayName", false, 120) as string,
    role,
    idleExpiresAt: requireDate(payload, "idleExpiresAt"),
    absoluteExpiresAt: requireDate(payload, "absoluteExpiresAt"),
  };
}

export async function getSession(signal?: AbortSignal): Promise<Session> {
  return parseSession(
    await requestJson("/api/v1/auth/session", { retries: 0, ...(signal ? { signal } : {}) }),
  );
}

export async function login(credentials: LoginRequest, signal?: AbortSignal): Promise<Session> {
  return parseSession(
    await requestJson("/api/v1/auth/login", {
      method: "POST",
      body: credentials,
      ...(signal ? { signal } : {}),
    }),
  );
}

export async function logout(signal?: AbortSignal): Promise<void> {
  await requestJson("/api/v1/auth/logout", {
    method: "POST",
    authenticatedMutation: true,
    ...(signal ? { signal } : {}),
  });
}

const INQUIRY_STATUSES = new Set<InquiryStatus>([
  "new",
  "contacted",
  "qualified",
  "viewing",
  "won",
  "lost",
  "closed",
]);

function parseInquiry(payload: unknown): Inquiry {
  if (!isRecord(payload) || !isRecord(payload["contact"]) || !isRecord(payload["property"]))
    throw new ApiError(200, "invalid_response", "The server returned an invalid response.");
  const status = requireString(payload, "status", false, 16) as InquiryStatus;
  const sourcePlatform = requireString(
    payload,
    "sourcePlatform",
    false,
    16,
  ) as Inquiry["sourcePlatform"];
  const intent = payload["intent"];
  const assignee = payload["assignee"];
  if (
    !INQUIRY_STATUSES.has(status) ||
    !["facebook", "instagram", "tiktok", "x", "direct", "unknown"].includes(sourcePlatform) ||
    !(intent === null || ["buy", "rent", "sell", "information"].includes(String(intent))) ||
    !(assignee === null || isRecord(assignee)) ||
    !Number.isInteger(payload["version"]) ||
    Number(payload["version"]) < 1
  )
    throw new ApiError(200, "invalid_response", "The server returned an invalid response.");
  return {
    id: requireUuid(payload, "id"),
    reference: requireString(payload, "reference", false, 32) as string,
    status,
    version: payload["version"] as number,
    sourcePlatform,
    intent: intent as Inquiry["intent"],
    submittedAt: requireDate(payload, "submittedAt"),
    contact: {
      fullName: requireString(payload["contact"], "fullName", false, 120) as string,
      email: requireString(payload["contact"], "email", true, 254),
      phone: requireString(payload["contact"], "phone", true, 16),
    },
    property: {
      id: requireUuid(payload["property"], "id"),
      title: requireString(payload["property"], "title", false, 160) as string,
    },
    assignee:
      assignee === null
        ? null
        : {
            id: requireUuid(assignee, "id"),
            displayName: requireString(assignee, "displayName", false, 120) as string,
          },
  };
}

function parseInquiryDetail(payload: unknown): InquiryDetailRecord {
  if (!isRecord(payload)) {
    throw new ApiError(200, "invalid_response", "The server returned an invalid response.");
  }
  const summary = parseInquiry(payload);
  const consent = payload["consent"];
  const history = payload["statusHistory"];
  const captureSurface = requireString(payload, "captureSurface", false, 16);
  const preferred = requireString(payload, "preferredContactMethod", true, 32);
  const dedupeState = requireString(payload, "dedupeState", false, 16);
  if (
    captureSurface !== "website" ||
    !["email", "phone", "whatsapp", "no_preference", null].includes(preferred) ||
    !["clear", "review"].includes(String(dedupeState)) ||
    !(consent === null || isRecord(consent)) ||
    !Array.isArray(history) ||
    history.length > 1_000
  ) {
    throw new ApiError(200, "invalid_response", "The server returned an invalid response.");
  }
  const statusHistory = history.map((item) => {
    if (!isRecord(item) || !isRecord(item["actor"])) {
      throw new ApiError(200, "invalid_response", "The server returned an invalid response.");
    }
    const fromStatus = requireString(item, "fromStatus", false, 16) as InquiryStatus;
    const toStatus = requireString(item, "toStatus", false, 16) as InquiryStatus;
    if (
      !INQUIRY_STATUSES.has(fromStatus) ||
      !INQUIRY_STATUSES.has(toStatus) ||
      fromStatus === toStatus
    ) {
      throw new ApiError(200, "invalid_response", "The server returned an invalid response.");
    }
    return {
      id: requireUuid(item, "id"),
      fromStatus,
      toStatus,
      createdAt: requireDate(item, "createdAt"),
      actor: {
        id: requireUuid(item["actor"], "id"),
        displayName: requireString(item["actor"], "displayName", false, 120) as string,
      },
    };
  });
  return {
    ...summary,
    captureSurface: "website",
    formVersion: requireString(payload, "formVersion", false, 40) as string,
    budgetBand: requireString(payload, "budgetBand", true, 40),
    timeframe: requireString(payload, "timeframe", true, 40),
    preferredContactMethod: preferred as InquiryDetailRecord["preferredContactMethod"],
    message: requireString(payload, "message", true, 2_000),
    dedupeState: dedupeState as InquiryDetailRecord["dedupeState"],
    updatedAt: requireDate(payload, "updatedAt"),
    consent:
      consent === null
        ? null
        : {
            noticeVersion: requireString(consent, "noticeVersion", false, 40) as string,
            requestedContact: requireBoolean(consent, "requestedContact"),
            marketing: requireBoolean(consent, "marketing"),
            adMeasurement: requireBoolean(consent, "adMeasurement"),
            recordedAt: requireDate(consent, "recordedAt"),
          },
    statusHistory,
  };
}

export type InquiryFilters = Readonly<{ status?: InquiryStatus }>;

export async function listInquiries(
  filters: InquiryFilters,
  cursor?: string,
  signal?: AbortSignal,
): Promise<InquiryPage> {
  const query = new URLSearchParams({ pageSize: "25" });
  if (filters.status && INQUIRY_STATUSES.has(filters.status)) query.set("status", filters.status);
  if (cursor) {
    if (cursor.length > 256) throw new TypeError("Cursor exceeds its contract bound");
    query.set("cursor", cursor);
  }
  const payload = await requestJson("/api/v1/inquiries", { query, ...(signal ? { signal } : {}) });
  if (!isRecord(payload) || !Array.isArray(payload["items"]) || payload["items"].length > 100)
    throw new ApiError(200, "invalid_response", "The server returned an invalid response.");
  const nextCursor = payload["nextCursor"];
  if (!(nextCursor === null || (typeof nextCursor === "string" && nextCursor.length <= 256)))
    throw new ApiError(200, "invalid_response", "The server returned an invalid response.");
  return { items: payload["items"].map(parseInquiry), nextCursor };
}

export async function getInquiry(id: string, signal?: AbortSignal): Promise<InquiryDetailRecord> {
  return parseInquiryDetail(await requestJson(inquiryPath(id), { ...(signal ? { signal } : {}) }));
}

export async function listAssignees(signal?: AbortSignal): Promise<AssigneeChoice[]> {
  const payload = await requestJson("/api/v1/users", { ...(signal ? { signal } : {}) });
  if (!Array.isArray(payload) || payload.length > 1_000) {
    throw new ApiError(200, "invalid_response", "The server returned an invalid response.");
  }
  return payload.map((item) => {
    if (!isRecord(item)) {
      throw new ApiError(200, "invalid_response", "The server returned an invalid response.");
    }
    const role = requireString(item, "role", false, 16);
    if (role !== "admin" && role !== "agent") {
      throw new ApiError(200, "invalid_response", "The server returned an invalid response.");
    }
    return {
      id: requireUuid(item, "id"),
      displayName: requireString(item, "displayName", false, 120) as string,
      role,
    };
  });
}

export async function updateInquiryStatus(
  id: string,
  status: InquiryStatus,
  expectedVersion: number,
  signal?: AbortSignal,
): Promise<InquiryDetailRecord> {
  if (
    !INQUIRY_STATUSES.has(status) ||
    !Number.isSafeInteger(expectedVersion) ||
    expectedVersion < 1
  ) {
    throw new TypeError("Status mutation violates the API contract");
  }
  return parseInquiryDetail(
    await requestJson(inquiryPath(id, "/status"), {
      method: "PATCH",
      body: { status, expectedVersion },
      authenticatedMutation: true,
      ...(signal ? { signal } : {}),
    }),
  );
}

export async function updateInquiryAssignment(
  id: string,
  assignedUserId: string | null,
  expectedVersion: number,
  signal?: AbortSignal,
): Promise<InquiryDetailRecord> {
  if (
    (assignedUserId !== null && !validUuid(assignedUserId)) ||
    !Number.isSafeInteger(expectedVersion) ||
    expectedVersion < 1
  ) {
    throw new TypeError("Assignment mutation violates the API contract");
  }
  return parseInquiryDetail(
    await requestJson(inquiryPath(id, "/assignment"), {
      method: "PATCH",
      body: { assignedUserId, expectedVersion },
      authenticatedMutation: true,
      ...(signal ? { signal } : {}),
    }),
  );
}

function requireString(
  record: Record<string, unknown>,
  key: string,
  nullable = false,
  maxLength = Number.POSITIVE_INFINITY,
): string | null {
  const value = record[key];
  if (nullable && value === null) return null;
  if (typeof value !== "string" || value.length > maxLength)
    throw new ApiError(200, "invalid_response", "The server returned an invalid response.");
  return value;
}

function requireBoolean(record: Record<string, unknown>, key: string): boolean {
  const value = record[key];
  if (typeof value !== "boolean") {
    throw new ApiError(200, "invalid_response", "The server returned an invalid response.");
  }
  return value;
}

export async function getProperty(slug: string, signal?: AbortSignal): Promise<Property> {
  if (!/^[a-z0-9](?:[a-z0-9-]{0,78}[a-z0-9])?$/.test(slug)) {
    throw new ApiError(404, "property_not_found", "The requested resource was not found.");
  }
  const payload = await requestJson(`/api/v1/properties/${encodeURIComponent(slug)}`, {
    ...(signal ? { signal } : {}),
  });
  if (!isRecord(payload))
    throw new ApiError(200, "invalid_response", "The server returned an invalid response.");
  const result = {
    slug: requireString(payload, "slug", false, 80) as string,
    title: requireString(payload, "title", false, 200) as string,
    summary: requireString(payload, "summary", false, 5_000) as string,
    locality: requireString(payload, "locality", false, 200) as string,
    priceLabel: requireString(payload, "priceLabel", true, 200),
    projectRegistrationNumber: requireString(payload, "projectRegistrationNumber", true, 200),
    registrationAuthorityUrl: requireString(payload, "registrationAuthorityUrl", true, 2_048),
  };
  if (result.slug !== slug)
    throw new ApiError(200, "invalid_response", "The server returned an invalid response.");
  return result;
}

export async function createLead(
  lead: LeadRequest,
  idempotencyKey: string,
  signal?: AbortSignal,
): Promise<LeadAccepted> {
  const payload = await requestJson("/api/v1/leads", {
    method: "POST",
    body: lead,
    headers: { "Idempotency-Key": idempotencyKey },
    ...(signal ? { signal } : {}),
  });
  if (!isRecord(payload))
    throw new ApiError(201, "invalid_response", "The server returned an invalid response.");
  const accepted = {
    inquiryId: requireString(payload, "inquiryId") as string,
    reference: requireString(payload, "reference") as string,
    status: requireString(payload, "status") as "new",
    submittedAt: requireString(payload, "submittedAt") as string,
  };
  if (
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
      accepted.inquiryId,
    ) ||
    !/^RE-[A-Z0-9]{10}$/.test(accepted.reference) ||
    accepted.status !== "new" ||
    !Number.isFinite(Date.parse(accepted.submittedAt))
  ) {
    throw new ApiError(201, "invalid_response", "The server returned an invalid response.");
  }
  return accepted;
}
