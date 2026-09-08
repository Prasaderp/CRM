import { useQuery } from "@tanstack/react-query";
import { type ReactNode, useMemo } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";

import { ApiError, getProperty, type LeadAccepted, type LeadRequest } from "../../api/client";
import { LeadForm } from "./LeadForm";

const ATTRIBUTION_LIMITS = {
  utm_source: 100,
  utm_medium: 100,
  utm_campaign: 200,
  utm_content: 200,
  utm_term: 200,
} as const;

function boundedOpaque(value: string | null, maxLength: number): string | null {
  if (value === null) return null;
  const sanitized = Array.from(value)
    .filter((character) => {
      const code = character.charCodeAt(0);
      return code >= 32 && (code < 127 || code > 159);
    })
    .join("")
    .trim()
    .slice(0, maxLength);
  return sanitized || null;
}

function originAndPath(value: string, base?: string): string | null {
  try {
    const url = new URL(value, base);
    if (!/^https?:$/.test(url.protocol)) return null;
    return `${url.origin}${url.pathname}`.slice(0, 2048);
  } catch {
    return null;
  }
}

export function captureAttribution(search: string): NonNullable<LeadRequest["attribution"]> {
  const query = new URLSearchParams(search);
  const values = Object.fromEntries(
    Object.entries(ATTRIBUTION_LIMITS).map(([queryKey, limit]) => [
      queryKey.replace(/_([a-z])/g, (_, letter: string) => letter.toUpperCase()),
      boundedOpaque(query.get(queryKey), limit),
    ]),
  ) as Pick<
    NonNullable<LeadRequest["attribution"]>,
    "utmSource" | "utmMedium" | "utmCampaign" | "utmContent" | "utmTerm"
  >;
  const click = (["fbclid", "ttclid", "twclid"] as const)
    .map((kind) => ({ kind, value: boundedOpaque(query.get(kind), 512) }))
    .find(({ value }) => value !== null);
  return {
    ...values,
    utmSource: values.utmSource ?? "direct",
    clickIdKind: click?.kind ?? null,
    clickIdValue: click?.value ?? null,
    landingUrl:
      typeof window === "undefined"
        ? null
        : originAndPath(window.location.href, window.location.origin),
    referrerUrl:
      typeof document === "undefined" || !document.referrer
        ? null
        : originAndPath(document.referrer, window.location.origin),
  };
}

function safeRegistrationLink(value: string | null): string | undefined {
  if (!value) return undefined;
  try {
    const url = new URL(value);
    return url.protocol === "https:" ? url.href : undefined;
  } catch {
    return undefined;
  }
}

function PropertyUnavailable(): ReactNode {
  return (
    <main className="state-page" id="main-content">
      <p className="eyebrow">Property unavailable</p>
      <h1>This property isn’t accepting enquiries.</h1>
      <p>
        The link may be incomplete, expired, or associated with a listing that is no longer active.
      </p>
      <Link className="button-link" to="/">
        Return home
      </Link>
    </main>
  );
}

export function PropertyPage() {
  const { propertySlug } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const attribution = useMemo(() => captureAttribution(location.search), [location.search]);
  const property = useQuery({
    queryKey: ["property", propertySlug],
    queryFn: ({ signal }) => getProperty(propertySlug ?? "", signal),
    enabled: Boolean(propertySlug),
    staleTime: 60_000,
    gcTime: 5 * 60_000,
    retry: false,
  });

  if (!propertySlug || (property.error instanceof ApiError && property.error.status === 404)) {
    return <PropertyUnavailable />;
  }
  if (property.isPending) {
    return (
      <main className="property-shell" id="main-content" aria-busy="true">
        <section className="property-intro property-skeleton" aria-label="Loading property details">
          <span />
          <span />
          <span />
        </section>
        <aside className="form-shell" aria-label="Loading enquiry form">
          <p role="status">Loading current property details…</p>
        </aside>
      </main>
    );
  }
  if (property.isError) {
    return (
      <main className="state-page" id="main-content">
        <p className="eyebrow">Temporary problem</p>
        <h1>We couldn’t load this property.</h1>
        <p>No information has been submitted. Check your connection, then try again.</p>
        <button type="button" onClick={() => void property.refetch()}>
          Try again
        </button>
      </main>
    );
  }

  const registrationUrl = safeRegistrationLink(property.data.registrationAuthorityUrl);
  const accepted = (result: LeadAccepted) =>
    navigate("/confirmation", {
      replace: true,
      state: { accepted: result, propertyTitle: property.data.title },
    });
  return (
    <main className="property-shell" id="main-content">
      <article className="property-intro" aria-labelledby="property-heading">
        <p className="eyebrow">Property enquiry · {property.data.locality}</p>
        <h1 id="property-heading">{property.data.title}</h1>
        {property.data.priceLabel && <p className="price-label">{property.data.priceLabel}</p>}
        <p className="property-summary">{property.data.summary}</p>
        <dl className="property-facts">
          <div>
            <dt>Location</dt>
            <dd>{property.data.locality}</dd>
          </div>
          {property.data.projectRegistrationNumber && (
            <div>
              <dt>Project registration</dt>
              <dd>{property.data.projectRegistrationNumber}</dd>
            </div>
          )}
        </dl>
        {registrationUrl && (
          <a className="registration-link" href={registrationUrl} rel="noreferrer" target="_blank">
            Verify registration with the authority
          </a>
        )}
        <aside className="disclosure" aria-label="Property disclosure">
          <strong>Before you decide</strong>
          <p>
            Price, fees, specifications, availability, and eligibility must be confirmed with the
            property team. This page makes no scarcity or investment-return promise.
          </p>
        </aside>
      </article>
      <aside className="form-shell" aria-label="Enquiry form">
        <LeadForm
          propertySlug={property.data.slug}
          attribution={attribution}
          onAccepted={accepted}
        />
      </aside>
    </main>
  );
}
