import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../api/client";
import { captureAttribution, PropertyPage } from "./PropertyPage";

const { createLeadMock, getPropertyMock } = vi.hoisted(() => ({
  createLeadMock: vi.fn(),
  getPropertyMock: vi.fn(),
}));
vi.mock("../../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../api/client")>()),
  createLead: createLeadMock,
  getProperty: getPropertyMock,
}));

const property = {
  slug: "approved-home",
  title: "Courtyard Residence",
  summary: "A calm two-bedroom home near transit and daily services.",
  locality: "Pune",
  priceLabel: "₹35 lakh onwards",
  projectRegistrationNumber: "P52100000001",
  registrationAuthorityUrl: "https://authority.example/project/P52100000001",
};
const accepted = {
  inquiryId: "b3c4e1a0-dc8d-4f9e-b786-d70a672195ca",
  reference: "RE-ABC1234567",
  status: "new" as const,
  submittedAt: "2026-07-31T08:00:00Z",
};

function renderPage(
  path: string,
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } }),
) {
  const view = render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/p/:propertySlug" element={<PropertyPage />} />
          <Route path="/confirmation" element={<h1>Confirmation</h1>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { ...view, client };
}

function fillAndSubmit(): void {
  fireEvent.change(screen.getByLabelText(/full name/i), { target: { value: "Test Person" } });
  fireEvent.change(screen.getByLabelText(/^email/i), { target: { value: "test@example.com" } });
  fireEvent.click(screen.getByLabelText(/requesting a response/i));
  fireEvent.click(screen.getByRole("button", { name: /send property enquiry/i }));
}

beforeEach(() => {
  getPropertyMock.mockReset();
  createLeadMock.mockReset();
  sessionStorage.clear();
});

afterEach(cleanup);

describe("PropertyPage", () => {
  it("renders approved fields, disclosure, registration, and a wired form", async () => {
    getPropertyMock.mockResolvedValue(property);
    createLeadMock.mockResolvedValue(accepted);
    renderPage("/p/approved-home?utm_source=instagram");

    expect(screen.getByRole("status")).toHaveTextContent(/loading current property/i);
    expect(await screen.findByRole("heading", { level: 1, name: property.title })).toBeTruthy();
    expect(screen.getByText(property.priceLabel)).toBeTruthy();
    expect(screen.getByText(property.projectRegistrationNumber)).toBeTruthy();
    expect(screen.getByLabelText("Property disclosure")).toHaveTextContent(/no scarcity/i);
    expect(screen.getByRole("link", { name: /verify registration/i })).toHaveAttribute(
      "href",
      property.registrationAuthorityUrl,
    );

    fillAndSubmit();
    expect(await screen.findByRole("heading", { name: "Confirmation" })).toBeTruthy();
    expect(createLeadMock).toHaveBeenCalledTimes(1);
    expect(createLeadMock.mock.calls[0]?.[0]).toMatchObject({ propertySlug: "approved-home" });
  });

  it.each(["missing-home", "inactive-home"])(
    "renders %s as non-submittable on 404",
    async (slug) => {
      getPropertyMock.mockRejectedValue(new ApiError(404, "property_not_found", "hidden"));
      renderPage(`/p/${slug}`);
      expect(
        await screen.findByRole("heading", { name: /isn’t accepting enquiries/i }),
      ).toBeTruthy();
      expect(screen.queryByRole("button", { name: /send property enquiry/i })).toBeNull();
    },
  );

  it("keeps loading stable and allows an explicit retry after a bounded failure", async () => {
    let reject!: (error: unknown) => void;
    getPropertyMock
      .mockReturnValueOnce(new Promise((_resolve, fail) => (reject = fail)))
      .mockResolvedValueOnce(property);
    renderPage("/p/approved-home");
    expect(screen.getByRole("main")).toHaveAttribute("aria-busy", "true");
    reject(new ApiError(503, "service_unavailable", "database secret"));

    const retry = await screen.findByRole("button", { name: "Try again" });
    expect(document.body.textContent).not.toContain("database secret");
    fireEvent.click(retry);
    expect(await screen.findByRole("heading", { name: property.title })).toBeTruthy();
    expect(getPropertyMock).toHaveBeenCalledTimes(2);
  });

  it("bounds hostile attribution without allowing it to select the property or headers", async () => {
    getPropertyMock.mockResolvedValue({
      ...property,
      registrationAuthorityUrl: "javascript:alert(1)",
    });
    createLeadMock.mockResolvedValue(accepted);
    const campaign = "c".repeat(260);
    const click = "z".repeat(700);
    renderPage(
      `/p/approved-home?utm_source=%00instagram&utm_campaign=${campaign}&fbclid=${click}&propertySlug=attacker&name=pii`,
    );
    await screen.findByRole("heading", { name: property.title });
    expect(screen.queryByRole("link", { name: /verify registration/i })).toBeNull();
    fillAndSubmit();
    await waitFor(() => expect(createLeadMock).toHaveBeenCalled());

    const payload = createLeadMock.mock.calls[0]?.[0];
    expect(getPropertyMock).toHaveBeenCalledWith("approved-home", expect.any(AbortSignal));
    expect(payload.propertySlug).toBe("approved-home");
    expect(payload.attribution.utmSource).toBe("instagram");
    expect(payload.attribution.utmCampaign).toHaveLength(200);
    expect(payload.attribution.clickIdKind).toBe("fbclid");
    expect(payload.attribution.clickIdValue).toHaveLength(512);
    expect(payload.attribution.landingUrl).not.toContain("?");
    expect(JSON.stringify(payload)).not.toContain("attacker");
    expect(JSON.stringify(payload)).not.toContain("pii");
  });

  it("uses a direct source fallback and keeps measurement identifiers paired", () => {
    expect(captureAttribution("?ttclid=opaque&twclid=ignored")).toMatchObject({
      utmSource: "direct",
      clickIdKind: "ttclid",
      clickIdValue: "opaque",
    });
    expect(captureAttribution("?fbclid=%00")).toMatchObject({
      clickIdKind: null,
      clickIdValue: null,
    });
  });

  it("reuses the in-memory property cache within the 60-second stale window", async () => {
    getPropertyMock.mockResolvedValue(property);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const first = renderPage("/p/approved-home", client);
    await screen.findByRole("heading", { name: property.title });
    first.unmount();
    renderPage("/p/approved-home", client);
    await screen.findByRole("heading", { name: property.title });
    expect(getPropertyMock).toHaveBeenCalledTimes(1);
  });
});
