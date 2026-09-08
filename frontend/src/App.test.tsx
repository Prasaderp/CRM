import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { Component, type ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App, ApplicationErrorBoundary } from "./App";
import { ApiError } from "./api/client";

const getPropertyMock = vi.hoisted(() => vi.fn());
const getSessionMock = vi.hoisted(() => vi.fn());
vi.mock("./api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api/client")>()),
  getProperty: getPropertyMock,
  getSession: getSessionMock,
}));

function renderRoute(path: string, state?: unknown): void {
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter initialEntries={[{ pathname: path, state }]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  getPropertyMock.mockReset();
});

beforeEach(() => {
  getSessionMock.mockRejectedValue(
    new ApiError(401, "authentication_required", "Authentication required"),
  );
});

describe("application routes", () => {
  it.each([
    ["/login", "Team sign in"],
    ["/missing", "This link doesn’t match an available page."],
  ])("renders %s with an accessible main heading", async (path, heading) => {
    renderRoute(path);
    expect(await screen.findByRole("heading", { level: 1, name: heading })).toBeTruthy();
    expect(screen.getByRole("main")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Skip to content" }).getAttribute("href")).toBe(
      "#main-content",
    );
  });

  it("binds the property route to the loaded public contract", async () => {
    getPropertyMock.mockResolvedValue({
      slug: "approved-home",
      title: "Approved Home",
      summary: "Summary",
      locality: "Pune",
      priceLabel: null,
      projectRegistrationNumber: null,
      registrationAuthorityUrl: null,
    });
    renderRoute("/p/approved-home");
    expect(await screen.findByRole("heading", { level: 1, name: "Approved Home" })).toBeTruthy();
  });

  it("renders confirmation only from an accepted submission state", () => {
    renderRoute("/confirmation", {
      accepted: {
        inquiryId: "b3c4e1a0-dc8d-4f9e-b786-d70a672195ca",
        reference: "RE-ABC1234567",
        status: "new",
        submittedAt: "2026-07-31T08:00:00Z",
      },
      propertyTitle: "Approved Home",
    });
    expect(screen.getByRole("heading", { name: "Thank you." })).toBeTruthy();
    expect(screen.getByText(/RE-ABC1234567/)).toBeTruthy();
  });

  it("keeps the unauthenticated CRM boundary out of browser history", async () => {
    renderRoute("/crm/inquiries?filter=private");
    expect(await screen.findByRole("heading", { level: 1, name: "Team sign in" })).toBeTruthy();
  });
});

class ThrowingChild extends Component {
  override render(): ReactNode {
    throw new Error("synthetic secret that must not render");
  }
}

describe("application failure boundary", () => {
  it("shows a sanitized recovery state and reload action", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    render(
      <ApplicationErrorBoundary>
        <ThrowingChild />
      </ApplicationErrorBoundary>,
    );
    expect(screen.getByRole("heading", { name: "We couldn’t display this page." })).toBeTruthy();
    expect(document.body.textContent).not.toContain("synthetic secret");
    expect(screen.getByRole("button", { name: "Refresh page" })).toBeTruthy();
  });
});
