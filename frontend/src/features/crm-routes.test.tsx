import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../App";
import { ApiError, type Inquiry, type Session } from "../api/client";
import { LoginPage } from "./auth/LoginPage";
import { InquiriesPage } from "./inquiries/InquiriesPage";

const api = vi.hoisted(() => ({
  getSession: vi.fn(),
  listInquiries: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
}));
vi.mock("../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/client")>()),
  ...api,
}));

const session: Session = {
  userId: "3e95c44a-5c7a-4cac-8e65-12c3652c5169",
  displayName: "Asha Rao",
  role: "agent",
  idleExpiresAt: "2026-07-31T12:00:00Z",
  absoluteExpiresAt: "2026-07-31T18:00:00Z",
};
const inquiry: Inquiry = {
  id: "6d33b0aa-ae0a-4fd7-94cb-f80408c765e2",
  reference: "RE-ABC1234567",
  status: "new",
  version: 1,
  sourcePlatform: "instagram",
  intent: "buy",
  submittedAt: "2026-07-31T08:00:00Z",
  contact: { fullName: "Synthetic Customer", email: "synthetic@example.test", phone: null },
  property: { id: "4a321748-3fa3-4576-a975-f1135cedfc18", title: "Riverside Residence" },
  assignee: null,
};

function renderWithClient(node: React.ReactNode, path = "/") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>{node}</MemoryRouter>
    </QueryClientProvider>,
  );
  return client;
}

beforeEach(() => {
  api.getSession.mockResolvedValue(session);
  api.listInquiries.mockResolvedValue({ items: [inquiry], nextCursor: null });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("authentication boundary", () => {
  it("submits credentials without persisting them and keeps authentication failures generic", async () => {
    api.login.mockRejectedValue(
      new ApiError(401, "authentication_failed", "internal account detail"),
    );
    renderWithClient(<LoginPage session={undefined} />, "/login");
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "agent@example.test" } });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "correct horse battery staple" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect((await screen.findByRole("alert")).textContent).toContain(
      "Email or password wasn’t recognised",
    );
    expect(document.body.textContent).not.toContain("internal account detail");
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it("clears cached customer data and drops sensitive query parameters when a session expires", async () => {
    api.getSession.mockRejectedValue(new ApiError(401, "authentication_required", "expired"));
    const client = renderWithClient(<App />, "/crm/inquiries?email=private@example.test");
    client.setQueryData(["inquiries", {}], {
      pages: [{ items: [inquiry] }],
      pageParams: [undefined],
    });
    expect(await screen.findByRole("heading", { name: "Team sign in" })).toBeTruthy();
    await waitFor(() => expect(client.getQueryData(["inquiries", {}])).toBeUndefined());
    expect(document.body.textContent).not.toContain("private@example.test");
  });
});

describe("inquiry list", () => {
  it("renders a typed page and advances only with the opaque server cursor", async () => {
    api.listInquiries
      .mockResolvedValueOnce({ items: [inquiry], nextCursor: "opaque-cursor" })
      .mockResolvedValueOnce({
        items: [
          { ...inquiry, id: "0d177641-2732-4da7-9394-507102a98187", reference: "RE-ZYX9876543" },
        ],
        nextCursor: null,
      });
    renderWithClient(<InquiriesPage />);
    expect(await screen.findByText("Synthetic Customer")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    await waitFor(() =>
      expect(api.listInquiries).toHaveBeenLastCalledWith(
        {},
        "opaque-cursor",
        expect.any(AbortSignal),
      ),
    );
    expect(await screen.findByText("RE-ZYX9876543")).toBeTruthy();
  });

  it("normalizes the bounded status filter into the query contract", async () => {
    renderWithClient(<InquiriesPage />);
    await screen.findByText("Synthetic Customer");
    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "qualified" } });
    await waitFor(() =>
      expect(api.listInquiries).toHaveBeenCalledWith(
        { status: "qualified" },
        undefined,
        expect.any(AbortSignal),
      ),
    );
  });
});
