import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  createLead,
  getInquiry,
  getProperty,
  getSession,
  type LeadRequest,
  listAssignees,
  listInquiries,
  login,
  requestJson,
  updateInquiryAssignment,
  updateInquiryStatus,
} from "./client";

const property = {
  slug: "approved-home",
  title: "Approved Home",
  summary: "A verified listing.",
  locality: "Pune",
  priceLabel: "₹35 lakh",
  projectRegistrationNumber: null,
  registrationAuthorityUrl: null,
};
const accepted = {
  inquiryId: "b3c4e1a0-dc8d-4f9e-b786-d70a672195ca",
  reference: "RE-ABC1234567",
  status: "new",
  submittedAt: "2026-07-31T08:00:00Z",
};
const inquiryDetail = {
  id: "6d33b0aa-ae0a-4fd7-94cb-f80408c765e2",
  reference: "RE-ABC1234567",
  status: "new",
  version: 1,
  sourcePlatform: "instagram",
  captureSurface: "website",
  formVersion: "test-v1",
  intent: "buy",
  budgetBand: null,
  timeframe: null,
  preferredContactMethod: "email",
  message: null,
  dedupeState: "clear",
  submittedAt: "2026-07-31T08:00:00Z",
  updatedAt: "2026-07-31T08:00:00Z",
  contact: { fullName: "Synthetic Customer", email: "synthetic@example.com", phone: null },
  property: {
    id: "4a321748-3fa3-4576-a975-f1135cedfc18",
    title: "Riverside Residence",
  },
  assignee: null,
  consent: {
    noticeVersion: "test-v1",
    requestedContact: true,
    marketing: false,
    adMeasurement: false,
    recordedAt: "2026-07-31T08:00:00Z",
  },
  statusHistory: [],
};
const lead: LeadRequest = {
  propertySlug: "approved-home",
  formVersion: "property-inquiry-test-1.0",
  website: "",
  contact: {
    fullName: "Test Person",
    email: "test@example.com",
    phone: null,
    preferredContactMethod: "email",
  },
  inquiry: { intent: "buy", budgetBand: null, timeframe: null, message: null },
  attribution: {
    utmSource: "x",
    utmMedium: null,
    utmCampaign: null,
    utmContent: null,
    utmTerm: null,
    clickIdKind: "twclid",
    clickIdValue: "opaque",
    landingUrl: "https://example.test/p/approved-home",
    referrerUrl: null,
  },
  consent: {
    privacyNoticeVersion: "TEST-2026-07-31",
    requestedContact: true,
    marketing: false,
    adMeasurement: false,
    locale: "en-IN",
  },
};

function json(body: unknown, status = 200, headers?: HeadersInit): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("typed API client", () => {
  it("rejects breached session contracts and never retries login timeouts", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        json({
          userId: crypto.randomUUID(),
          displayName: "Mallory",
          role: "owner",
          idleExpiresAt: "never",
          absoluteExpiresAt: "never",
        }),
      )
      .mockRejectedValueOnce(new TypeError("upstream timeout with secret context"));
    vi.stubGlobal("fetch", fetchMock);
    await expect(getSession()).rejects.toMatchObject({ code: "invalid_response" });
    await expect(
      login({ email: "agent@example.test", password: "not persisted" }),
    ).rejects.toMatchObject({ code: "network_error" });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const loginRequest = fetchMock.mock.calls[1];
    if (!loginRequest) throw new Error("login request was not captured");
    expect(String((loginRequest[1] as RequestInit).body)).toContain("not persisted");
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it("bounds inquiry filters and opaque cursors before building a same-origin query", async () => {
    const fetchMock = vi.fn().mockResolvedValue(json({ items: [], nextCursor: null }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(listInquiries({ status: "qualified" }, "opaque+/cursor=")).resolves.toEqual({
      items: [],
      nextCursor: null,
    });
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "/api/v1/inquiries?pageSize=25&status=qualified&cursor=opaque%2B%2Fcursor%3D",
    );
    await expect(listInquiries({}, "x".repeat(257))).rejects.toBeInstanceOf(TypeError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("constructs a fixed same-origin property URL and maps a valid response", async () => {
    const fetchMock = vi.fn().mockResolvedValue(json(property));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getProperty("approved-home")).resolves.toEqual(property);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/properties/approved-home",
      expect.objectContaining({ method: "GET", credentials: "same-origin" }),
    );
    await expect(getProperty("../../admin?utm_source=evil")).rejects.toMatchObject({ status: 404 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("bounds transient query retries and honors Retry-After without retrying client errors", async () => {
    vi.useFakeTimers();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        json({ error: { code: "service_unavailable" } }, 503, { "retry-after": "1" }),
      )
      .mockResolvedValueOnce(json({ error: { code: "service_unavailable" } }, 503))
      .mockResolvedValueOnce(json(property));
    vi.stubGlobal("fetch", fetchMock);

    const request = getProperty("approved-home");
    await vi.runAllTimersAsync();
    await expect(request).resolves.toEqual(property);
    expect(fetchMock).toHaveBeenCalledTimes(3);

    fetchMock.mockReset().mockResolvedValue(json({ error: { code: "property_not_found" } }, 404));
    await expect(getProperty("approved-home")).rejects.toMatchObject({ status: 404 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("never retries mutations and sends only contract headers/body", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("socket timeout secret"));
    vi.stubGlobal("fetch", fetchMock);

    await expect(createLead(lead, "6ba00c22-1643-4d5b-aa0d-f108dbf5c8ca")).rejects.toMatchObject({
      code: "network_error",
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/leads");
    expect(init.headers).toEqual({
      Accept: "application/json",
      "Content-Type": "application/json",
      "Idempotency-Key": "6ba00c22-1643-4d5b-aa0d-f108dbf5c8ca",
    });
    expect(JSON.parse(String(init.body))).toEqual(lead);
  });

  it("supports abort and does not translate cancellation into a retryable network error", async () => {
    const controller = new AbortController();
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_url: string, init: RequestInit) =>
          new Promise((_resolve, reject) => {
            init.signal?.addEventListener("abort", () =>
              reject(new DOMException("Aborted", "AbortError")),
            );
          }),
      ),
    );
    const request = getProperty("approved-home", controller.signal);
    controller.abort();
    await expect(request).rejects.toMatchObject({ name: "AbortError" });
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("rejects malformed success bodies and sanitizes HTML error responses", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json({ ...property, title: 42 }))
      .mockResolvedValueOnce(
        new Response("<h1>database password: hunter2</h1>", {
          status: 503,
          headers: { "content-type": "text/html" },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);
    await expect(getProperty("approved-home")).rejects.toMatchObject({ code: "invalid_response" });

    await expect(requestJson("/api/v1/failure", { retries: 0 })).rejects.toSatisfy((error) => {
      expect(error).toBeInstanceOf(ApiError);
      expect(String(error)).not.toContain("hunter2");
      return true;
    });
  });

  it("copies a decoded host-only CSRF cookie only for authenticated mutations", async () => {
    vi.spyOn(document, "cookie", "get").mockReturnValue("csrf_token=token%2Bvalue");
    const fetchMock = vi.fn().mockResolvedValue(json(accepted));
    vi.stubGlobal("fetch", fetchMock);
    await requestJson("/api/v1/auth/logout", { method: "POST", authenticatedMutation: true });
    expect(fetchMock.mock.calls[0]?.[1]).toEqual(
      expect.objectContaining({
        headers: expect.objectContaining({ "X-CSRF-Token": "token+value" }),
      }),
    );
    await expect(
      requestJson("/api/v1/properties/approved-home", { authenticatedMutation: true }),
    ).rejects.toBeInstanceOf(TypeError);
  });

  it("validates accepted-lead contracts instead of trusting status 201", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json(accepted, 201))
      .mockResolvedValueOnce(json({ ...accepted, reference: "sequential-1" }, 201));
    vi.stubGlobal("fetch", fetchMock);
    await expect(createLead(lead, crypto.randomUUID())).resolves.toEqual(accepted);
    await expect(createLead(lead, crypto.randomUUID())).rejects.toMatchObject({
      code: "invalid_response",
    });
  });

  it("validates CRM detail, assignees, and optimistic mutation contracts end to end", async () => {
    vi.spyOn(document, "cookie", "get").mockReturnValue("csrf_token=bound-csrf");
    const owner = {
      id: "3e95c44a-5c7a-4cac-8e65-12c3652c5169",
      displayName: "Asha Rao",
      role: "agent",
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json(inquiryDetail))
      .mockResolvedValueOnce(json([owner]))
      .mockResolvedValueOnce(json({ ...inquiryDetail, status: "qualified", version: 2 }))
      .mockResolvedValueOnce(json({ ...inquiryDetail, assignee: owner, version: 2 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getInquiry(inquiryDetail.id)).resolves.toMatchObject(inquiryDetail);
    await expect(listAssignees()).resolves.toEqual([owner]);
    await expect(updateInquiryStatus(inquiryDetail.id, "qualified", 1)).resolves.toMatchObject({
      status: "qualified",
      version: 2,
    });
    await expect(updateInquiryAssignment(inquiryDetail.id, owner.id, 1)).resolves.toMatchObject({
      assignee: { id: owner.id, displayName: owner.displayName },
      version: 2,
    });
    expect(fetchMock.mock.calls.slice(2).map(([, init]) => init)).toEqual([
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({ status: "qualified", expectedVersion: 1 }),
        headers: expect.objectContaining({ "X-CSRF-Token": "bound-csrf" }),
      }),
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({ assignedUserId: owner.id, expectedVersion: 1 }),
        headers: expect.objectContaining({ "X-CSRF-Token": "bound-csrf" }),
      }),
    ]);
    await expect(getInquiry("../../private")).rejects.toBeInstanceOf(TypeError);
    await expect(updateInquiryStatus(inquiryDetail.id, "qualified", 0)).rejects.toBeInstanceOf(
      TypeError,
    );
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });
});
