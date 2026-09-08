import { useEffect, useRef, useState } from "react";
import { useForm } from "react-hook-form";

import { ApiError, createLead, type LeadAccepted, type LeadRequest } from "../../api/client";
import "./lead-form.css";

export const FORM_VERSION = "property-inquiry-test-1.0";
export const PRIVACY_NOTICE_VERSION = "TEST-2026-07-31";

type Attribution = NonNullable<LeadRequest["attribution"]>;
type Values = {
  fullName: string;
  email: string;
  phone: string;
  intent: "buy" | "rent" | "sell" | "information";
  preferredContactMethod: "email" | "phone" | "whatsapp" | "no_preference";
  budgetBand: "" | "300000-400000";
  timeframe: "" | "1-3-months";
  message: string;
  requestedContact: boolean;
  marketing: boolean;
  adMeasurement: boolean;
  website: string;
};

type LeadFormProps = {
  propertySlug: string;
  attribution: Attribution;
  onAccepted: (accepted: LeadAccepted) => void;
};

type StoredAttempt = { fingerprint: string; key: string };

function readAttempt(storageKey: string): StoredAttempt | undefined {
  try {
    const parsed: unknown = JSON.parse(sessionStorage.getItem(storageKey) ?? "null");
    if (
      typeof parsed === "object" &&
      parsed !== null &&
      "fingerprint" in parsed &&
      "key" in parsed &&
      typeof parsed.fingerprint === "string" &&
      typeof parsed.key === "string" &&
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(parsed.key)
    ) {
      return parsed as StoredAttempt;
    }
  } catch {
    return undefined;
  }
  return undefined;
}

function payloadFor(values: Values, propertySlug: string, attribution: Attribution): LeadRequest {
  const nullable = (value: string): string | null => value.trim() || null;
  const browserLocale = navigator.language?.slice(0, 20);
  const locale =
    browserLocale && /^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$/.test(browserLocale)
      ? browserLocale
      : "en-IN";
  return {
    propertySlug,
    formVersion: FORM_VERSION,
    website: values.website,
    contact: {
      fullName: values.fullName.trim(),
      email: nullable(values.email),
      phone: nullable(values.phone),
      preferredContactMethod: values.preferredContactMethod,
    },
    inquiry: {
      intent: values.intent,
      budgetBand: values.budgetBand || null,
      timeframe: values.timeframe || null,
      message: nullable(values.message),
    },
    attribution,
    consent: {
      privacyNoticeVersion: PRIVACY_NOTICE_VERSION,
      requestedContact: values.requestedContact,
      marketing: values.marketing,
      adMeasurement: values.adMeasurement,
      locale,
    },
  };
}

export function LeadForm({ propertySlug, attribution, onAccepted }: LeadFormProps) {
  const storageKey = `lead-attempt:${propertySlug}`;
  const startedAt = useRef(performance.now());
  const [elapsedMs, setElapsedMs] = useState(0);
  const [submitError, setSubmitError] = useState<string>();
  const [ambiguousFingerprint, setAmbiguousFingerprint] = useState<string>();
  const {
    register,
    handleSubmit,
    watch,
    setFocus,
    formState: { errors, isSubmitting },
  } = useForm<Values>({
    defaultValues: {
      fullName: "",
      email: "",
      phone: "",
      intent: "information",
      preferredContactMethod: "no_preference",
      budgetBand: "",
      timeframe: "",
      message: "",
      requestedContact: false,
      marketing: false,
      adMeasurement: false,
      website: "",
    },
  });
  const contact = watch(["email", "phone", "preferredContactMethod"]);
  useEffect(() => {
    if (!ambiguousFingerprint) return;
    const subscription = watch((values) => {
      const complete = values as Values;
      if (
        JSON.stringify(payloadFor(complete, propertySlug, attribution)) !== ambiguousFingerprint
      ) {
        sessionStorage.removeItem(storageKey);
        setAmbiguousFingerprint(undefined);
      }
    });
    return () => subscription.unsubscribe();
  }, [ambiguousFingerprint, attribution, propertySlug, storageKey, watch]);

  const onSubmit = handleSubmit(
    async (values) => {
      setSubmitError(undefined);
      setElapsedMs(Math.max(0, Math.round(performance.now() - startedAt.current)));
      const payload = payloadFor(values, propertySlug, attribution);
      const fingerprint = JSON.stringify(payload);
      const stored = readAttempt(storageKey);
      const key = stored?.fingerprint === fingerprint ? stored.key : crypto.randomUUID();
      sessionStorage.setItem(
        storageKey,
        JSON.stringify({ fingerprint, key } satisfies StoredAttempt),
      );
      try {
        const accepted = await createLead(payload, key);
        sessionStorage.removeItem(storageKey);
        setAmbiguousFingerprint(undefined);
        onAccepted(accepted);
      } catch (error) {
        setAmbiguousFingerprint(fingerprint);
        setSubmitError(
          error instanceof ApiError && error.code === "idempotency_conflict"
            ? "This form changed after an earlier attempt. Review it and submit again."
            : error instanceof ApiError && error.status === 422
              ? "Some details were not accepted. Review the fields and try again."
              : error instanceof ApiError && error.status === 404
                ? "This property is no longer accepting enquiries."
                : "We could not confirm whether your enquiry was received. Retry without changing it to safely check.",
        );
      }
    },
    (validationErrors) => {
      setSubmitError("Review the highlighted fields.");
      const first = Object.keys(validationErrors)[0] as keyof Values | undefined;
      if (first) setFocus(first);
    },
  );

  return (
    <form className="lead-form" noValidate onSubmit={onSubmit} data-elapsed-ms={elapsedMs}>
      <div className="form-heading">
        <p className="eyebrow">Private enquiry</p>
        <h2>Request property information</h2>
        <p>Fields marked required help the property team respond to this specific enquiry.</p>
      </div>

      {submitError && (
        <div className="form-alert" role="alert" tabIndex={-1}>
          {submitError}
        </div>
      )}

      <label>
        <span>
          Full name <span aria-hidden="true">*</span>
        </span>
        <input
          autoComplete="name"
          aria-invalid={Boolean(errors.fullName)}
          {...register("fullName", {
            required: "Enter your full name.",
            maxLength: { value: 120, message: "Use 120 characters or fewer." },
            validate: (value) =>
              !Array.from(value).some((character) => {
                const code = character.charCodeAt(0);
                return code < 32 || code === 127;
              }) || "Control characters are not allowed.",
          })}
        />
        {errors.fullName && <span className="field-error">{errors.fullName.message}</span>}
      </label>

      <div className="field-pair">
        <label>
          Email
          <input
            type="email"
            inputMode="email"
            autoComplete="email"
            aria-invalid={Boolean(errors.email)}
            {...register("email", {
              maxLength: { value: 254, message: "Use 254 characters or fewer." },
              pattern: {
                value: /^[^\s@]+@[^\s@]+\.[^\s@]+$/,
                message: "Enter a valid email address.",
              },
              validate: (value) =>
                Boolean(value.trim() || contact[1].trim()) ||
                "Enter an email or international phone number.",
            })}
          />
          {errors.email && <span className="field-error">{errors.email.message}</span>}
        </label>
        <label>
          Phone
          <input
            type="tel"
            inputMode="tel"
            autoComplete="tel"
            placeholder="+919876543210"
            aria-invalid={Boolean(errors.phone)}
            {...register("phone", {
              pattern: {
                value: /^$|^\+[1-9]\d{7,14}$/,
                message: "Use international format, for example +919876543210.",
              },
              validate: (value) =>
                Boolean(value.trim() || contact[0].trim()) ||
                "Enter an email or international phone number.",
            })}
          />
          {errors.phone && <span className="field-error">{errors.phone.message}</span>}
        </label>
      </div>

      <div className="field-pair">
        <label>
          <span>
            Inquiry type <span aria-hidden="true">*</span>
          </span>
          <select {...register("intent", { required: true })}>
            <option value="buy">Buy</option>
            <option value="rent">Rent</option>
            <option value="sell">Sell</option>
            <option value="information">Request information</option>
          </select>
        </label>
        <label>
          Preferred contact
          <select
            aria-invalid={Boolean(errors.preferredContactMethod)}
            {...register("preferredContactMethod", {
              validate: (value) =>
                ((value !== "email" || Boolean(contact[0].trim())) &&
                  (!["phone", "whatsapp"].includes(value) || Boolean(contact[1].trim()))) ||
                "Add the contact detail for your preferred method.",
            })}
          >
            <option value="no_preference">No preference</option>
            <option value="email">Email</option>
            <option value="phone">Phone</option>
            <option value="whatsapp">WhatsApp</option>
          </select>
          {errors.preferredContactMethod && (
            <span className="field-error">{errors.preferredContactMethod.message}</span>
          )}
        </label>
      </div>

      <details>
        <summary>Add timing, budget, or a question</summary>
        <div className="optional-fields">
          <label>
            Budget range
            <select {...register("budgetBand")}>
              <option value="">Prefer not to say</option>
              <option value="300000-400000">₹3–4 lakh</option>
            </select>
          </label>
          <label>
            Time frame
            <select {...register("timeframe")}>
              <option value="">Not decided</option>
              <option value="1-3-months">1–3 months</option>
            </select>
          </label>
          <label className="wide-field">
            Question or context
            <textarea
              rows={4}
              aria-invalid={Boolean(errors.message)}
              {...register("message", {
                maxLength: { value: 2000, message: "Use 2,000 characters or fewer." },
              })}
            />
            <span className="field-hint">
              Do not include IDs, bank details, passwords, or other sensitive information.
            </span>
            {errors.message && <span className="field-error">{errors.message.message}</span>}
          </label>
        </div>
      </details>

      <div className="honeypot" aria-hidden="true">
        <label>
          Website
          <input tabIndex={-1} autoComplete="off" {...register("website", { maxLength: 200 })} />
        </label>
      </div>

      <fieldset className="consent-group">
        <legend>Contact and privacy choices</legend>
        <label className="check-row">
          <input
            type="checkbox"
            aria-invalid={Boolean(errors.requestedContact)}
            {...register("requestedContact", {
              required: "Confirm that you are requesting contact.",
            })}
          />
          <span>
            I’m requesting a response about this property. <strong>Required</strong>
          </span>
        </label>
        {errors.requestedContact && (
          <span className="field-error">{errors.requestedContact.message}</span>
        )}
        <label className="check-row">
          <input type="checkbox" {...register("marketing")} />
          <span>Send me occasional information about other properties. Optional.</span>
        </label>
        <label className="check-row">
          <input type="checkbox" {...register("adMeasurement")} />
          <span>Allow advertising measurement for this enquiry. Optional.</span>
        </label>
      </fieldset>

      <p className="test-notice">
        <strong>Local test notice — not approved for publication.</strong> Submitted details are
        used to respond to this property enquiry. Marketing and advertising measurement remain off
        unless selected separately.
      </p>
      <button type="submit" disabled={isSubmitting} aria-busy={isSubmitting}>
        {isSubmitting ? "Sending securely…" : "Send property enquiry"}
      </button>
      <p className="submit-note">
        No account required. Availability is confirmed by the property team.
      </p>
    </form>
  );
}
