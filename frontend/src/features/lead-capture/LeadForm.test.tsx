import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../api/client";
import { FORM_VERSION, LeadForm, PRIVACY_NOTICE_VERSION } from "./LeadForm";

const createLeadMock = vi.hoisted(() => vi.fn());
vi.mock("../../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../api/client")>()),
  createLead: createLeadMock,
}));

const attribution = {
  utmSource: "instagram",
  utmMedium: "paid_social",
  utmCampaign: null,
  utmContent: null,
  utmTerm: null,
  clickIdKind: "fbclid" as const,
  clickIdValue: "opaque-click",
  landingUrl: "https://example.test/p/approved-home",
  referrerUrl: null,
};
const result = {
  inquiryId: "b3c4e1a0-dc8d-4f9e-b786-d70a672195ca",
  reference: "RE-ABC1234567",
  status: "new" as const,
  submittedAt: "2026-07-31T08:00:00Z",
};

function renderForm(onAccepted = vi.fn()) {
  render(
    <LeadForm propertySlug="approved-home" attribution={attribution} onAccepted={onAccepted} />,
  );
  return onAccepted;
}

function fillRequired(): void {
  fireEvent.change(screen.getByLabelText(/full name/i), { target: { value: "  Test Person  " } });
  fireEvent.change(screen.getByLabelText(/^email/i), { target: { value: "test@example.com" } });
  fireEvent.click(screen.getByLabelText(/requesting a response/i));
}

function submit(): void {
  const form = screen.getByRole("button", { name: /send property enquiry/i }).closest("form");
  if (!form) throw new Error("Lead form is missing");
  fireEvent.submit(form);
}

beforeEach(() => {
  sessionStorage.clear();
  createLeadMock.mockReset();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("LeadForm", () => {
  it("provides accessible labels, separated choices, and focuses the first invalid field", async () => {
    renderForm();
    expect(screen.getByText(/local test notice — not approved for publication/i)).toBeTruthy();
    expect(screen.getByLabelText(/other properties/i)).not.toBeChecked();
    expect(screen.getByLabelText(/advertising measurement/i)).not.toBeChecked();

    submit();
    await screen.findByText("Review the highlighted fields.");
    expect(screen.getByLabelText(/full name/i)).toHaveFocus();
    expect(screen.getByText("Enter your full name.")).toBeTruthy();
    expect(createLeadMock).not.toHaveBeenCalled();
  });

  it("enforces contact compatibility and field bounds before submission", async () => {
    renderForm();
    fireEvent.change(screen.getByLabelText(/full name/i), { target: { value: "x".repeat(121) } });
    fireEvent.change(screen.getByLabelText(/preferred contact/i), {
      target: { value: "whatsapp" },
    });
    fireEvent.click(screen.getByLabelText(/requesting a response/i));
    submit();

    expect(await screen.findByText("Use 120 characters or fewer.")).toBeTruthy();
    expect(screen.getByText("Add the contact detail for your preferred method.")).toBeTruthy();
    expect(createLeadMock).not.toHaveBeenCalled();
  });

  it("submits once under duplicate clicks and emits only server-contract fields", async () => {
    let resolve!: (value: typeof result) => void;
    createLeadMock.mockReturnValue(new Promise((done) => (resolve = done)));
    const onAccepted = renderForm();
    fillRequired();
    const button = screen.getByRole("button", { name: /send property enquiry/i });
    fireEvent.click(button);
    fireEvent.click(button);

    await waitFor(() => expect(createLeadMock).toHaveBeenCalledTimes(1));
    const call = createLeadMock.mock.calls[0];
    if (!call) throw new Error("Expected lead request");
    const [payload, key] = call;
    expect(key).toMatch(/^[0-9a-f-]{36}$/i);
    expect(payload).toMatchObject({
      propertySlug: "approved-home",
      formVersion: FORM_VERSION,
      contact: { fullName: "Test Person", email: "test@example.com" },
      consent: {
        privacyNoticeVersion: PRIVACY_NOTICE_VERSION,
        requestedContact: true,
        marketing: false,
        adMeasurement: false,
      },
      attribution,
    });
    expect(JSON.stringify(payload)).not.toMatch(/elapsed|started|noticeText|clientTime/i);
    expect(button).toBeDisabled();

    resolve(result);
    await waitFor(() => expect(onAccepted).toHaveBeenCalledWith(result));
    expect(sessionStorage.getItem("lead-attempt:approved-home")).toBeNull();
  });

  it("reuses a key after response loss but rotates it when the ambiguous payload changes", async () => {
    const keys = ["3b8816b2-6950-4487-b004-65a5e65d19d2", "04d613af-1eae-4c29-9e21-9e32d63a4e47"];
    vi.spyOn(crypto, "randomUUID")
      .mockReturnValueOnce(keys[0] as `${string}-${string}-${string}-${string}-${string}`)
      .mockReturnValueOnce(keys[1] as `${string}-${string}-${string}-${string}-${string}`);
    createLeadMock
      .mockRejectedValueOnce(new ApiError(0, "network_error", "lost"))
      .mockRejectedValueOnce(new ApiError(0, "network_error", "lost again"))
      .mockResolvedValueOnce(result);
    renderForm();
    fillRequired();

    submit();
    await screen.findByText(/could not confirm whether your enquiry was received/i);
    submit();
    await waitFor(() => expect(createLeadMock).toHaveBeenCalledTimes(2));
    expect(createLeadMock.mock.calls[0]?.[1]).toBe(keys[0]);
    expect(createLeadMock.mock.calls[1]?.[1]).toBe(keys[0]);

    fireEvent.change(screen.getByLabelText(/question or context/i), {
      target: { value: "Arrange a visit" },
    });
    submit();
    await waitFor(() => expect(createLeadMock).toHaveBeenCalledTimes(3));
    expect(createLeadMock.mock.calls[2]?.[1]).toBe(keys[1]);
  });

  it.each([
    [422, "validation_failed", /details were not accepted/i],
    [404, "property_not_found", /no longer accepting enquiries/i],
    [409, "idempotency_conflict", /changed after an earlier attempt/i],
  ])("maps server status %i to a safe recovery message", async (status, code, message) => {
    createLeadMock.mockRejectedValue(new ApiError(status, code, "raw internal detail"));
    renderForm();
    fillRequired();
    submit();
    expect(await screen.findByText(message)).toBeTruthy();
    expect(document.body.textContent).not.toContain("raw internal detail");
  });

  it("keeps marketing and measurement independent in the submitted consent snapshot", async () => {
    createLeadMock.mockResolvedValue(result);
    renderForm();
    fillRequired();
    fireEvent.click(screen.getByLabelText(/other properties/i));
    submit();
    await waitFor(() => expect(createLeadMock).toHaveBeenCalled());
    expect(createLeadMock.mock.calls[0]?.[0].consent).toMatchObject({
      marketing: true,
      adMeasurement: false,
    });
  });
});
