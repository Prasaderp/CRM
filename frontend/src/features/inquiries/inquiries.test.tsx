import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  type AssigneeChoice,
  type InquiryDetailRecord,
  type InquiryStatus,
} from "../../api/client";
import { INQUIRY_DETAIL_STALE_MS, InquiryDetail } from "./InquiryDetail";

const api = vi.hoisted(() => ({
  getInquiry: vi.fn(),
  listAssignees: vi.fn(),
  updateInquiryAssignment: vi.fn(),
  updateInquiryStatus: vi.fn(),
}));
vi.mock("../../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../api/client")>()),
  ...api,
}));

const inquiryId = "6d33b0aa-ae0a-4fd7-94cb-f80408c765e2";
const owner: AssigneeChoice = {
  id: "3e95c44a-5c7a-4cac-8e65-12c3652c5169",
  displayName: "Asha Rao",
  role: "agent",
};
const detail: InquiryDetailRecord = {
  id: inquiryId,
  reference: "RE-ABC1234567",
  status: "new",
  version: 1,
  sourcePlatform: "instagram",
  captureSurface: "website",
  formVersion: "test-v1",
  intent: "buy",
  budgetBand: "300000-400000",
  timeframe: "1-3-months",
  preferredContactMethod: "email",
  message: "Synthetic request only.",
  dedupeState: "clear",
  submittedAt: "2026-07-31T08:00:00Z",
  updatedAt: "2026-07-31T08:00:00Z",
  contact: {
    fullName: "Synthetic Customer",
    email: "synthetic@example.test",
    phone: "+919876543210",
  },
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

function renderDetail(
  client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  }),
) {
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/crm/inquiries/${inquiryId}`]}>
        <Routes>
          <Route path="/crm/inquiries/:inquiryId" element={<InquiryDetail />} />
          <Route path="/login" element={<h1>Team sign in</h1>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return client;
}

beforeEach(() => {
  api.getInquiry.mockResolvedValue(detail);
  api.listAssignees.mockResolvedValue([owner]);
  api.updateInquiryStatus.mockResolvedValue({ ...detail, status: "qualified", version: 2 });
  api.updateInquiryAssignment.mockResolvedValue({ ...detail, assignee: owner, version: 2 });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe("inquiry detail", () => {
  it("renders bounded customer context and exposes keyboard-operable mutations", async () => {
    renderDetail();
    expect(await screen.findByRole("heading", { name: "Synthetic Customer" })).toBeTruthy();
    expect(screen.getByText("synthetic@example.test").closest("a")?.getAttribute("href")).toBe(
      "mailto:synthetic@example.test",
    );
    fireEvent.change(screen.getByLabelText("Current stage"), { target: { value: "qualified" } });
    fireEvent.click(screen.getByRole("button", { name: "Save status" }));
    await waitFor(() =>
      expect(api.updateInquiryStatus).toHaveBeenCalledWith(inquiryId, "qualified", 1),
    );
  });

  it("invalidates the detail and every inquiry-list key after a committed mutation", async () => {
    const client = renderDetail();
    const invalidation = vi.spyOn(client, "invalidateQueries");
    await screen.findByRole("heading", { name: "Synthetic Customer" });
    fireEvent.change(screen.getByLabelText("Assigned team member"), {
      target: { value: owner.id },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save owner" }));
    await waitFor(() =>
      expect(api.updateInquiryAssignment).toHaveBeenCalledWith(inquiryId, owner.id, 1),
    );
    await waitFor(() => {
      expect(invalidation).toHaveBeenCalledWith({ queryKey: ["inquiry", inquiryId] });
      expect(invalidation).toHaveBeenCalledWith({ queryKey: ["inquiries"] });
    });
  });

  it("refreshes a stale version while preserving the operator selection for intentional retry", async () => {
    api.getInquiry
      .mockResolvedValueOnce(detail)
      .mockResolvedValue({ ...detail, status: "contacted", version: 2 });
    api.updateInquiryStatus
      .mockRejectedValueOnce(new ApiError(409, "stale_version", "private server detail"))
      .mockResolvedValue({ ...detail, status: "qualified", version: 3 });
    renderDetail();
    await screen.findByRole("heading", { name: "Synthetic Customer" });
    const select = screen.getByLabelText("Current stage") as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "qualified" satisfies InquiryStatus } });
    fireEvent.click(screen.getByRole("button", { name: "Save status" }));
    expect(await screen.findByText("This inquiry changed in another session.")).toBeTruthy();
    expect(select.value).toBe("qualified");
    fireEvent.click(screen.getByRole("button", { name: "Save status" }));
    await waitFor(() =>
      expect(api.updateInquiryStatus).toHaveBeenLastCalledWith(inquiryId, "qualified", 2),
    );
  });

  it("clears all sensitive memory state and redirects when detail authorization expires", async () => {
    api.getInquiry.mockRejectedValue(new ApiError(401, "authentication_required", "token detail"));
    const client = renderDetail();
    client.setQueryData(["inquiries", {}], { items: [detail] });
    expect(await screen.findByRole("heading", { name: "Team sign in" })).toBeTruthy();
    await waitFor(() => expect(client.getQueryData(["inquiries", {}])).toBeUndefined());
    expect(document.body.textContent).not.toContain("token detail");
  });

  it("uses the mandated five-second memory cache without persistent browser storage", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-31T08:00:00Z"));
    const client = new QueryClient();
    const fetcher = vi.fn().mockResolvedValue(detail);
    const options = {
      queryKey: ["inquiry", inquiryId] as const,
      queryFn: fetcher,
      staleTime: INQUIRY_DETAIL_STALE_MS,
    };
    await client.fetchQuery(options);
    vi.setSystemTime(new Date("2026-07-31T08:00:04.999Z"));
    await client.fetchQuery(options);
    expect(fetcher).toHaveBeenCalledTimes(1);
    vi.setSystemTime(new Date("2026-07-31T08:00:05.001Z"));
    await client.fetchQuery(options);
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it("sanitizes server and contract failures instead of rendering sensitive details", async () => {
    api.getInquiry.mockRejectedValue(
      new ApiError(404, "inquiry_not_found", "database host secret@example.test"),
    );
    renderDetail();
    expect(await screen.findByRole("heading", { name: "Inquiry not found" })).toBeTruthy();
    expect(document.body.textContent).not.toContain("secret@example.test");
  });
});
