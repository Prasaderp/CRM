import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, type ReactNode, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  ApiError,
  type AssigneeChoice,
  getInquiry,
  type InquiryDetailRecord,
  type InquiryStatus,
  listAssignees,
  updateInquiryAssignment,
  updateInquiryStatus,
} from "../../api/client";

const STATUS_OPTIONS: readonly [InquiryStatus, string][] = [
  ["new", "New"],
  ["contacted", "Contacted"],
  ["qualified", "Qualified"],
  ["viewing", "Viewing arranged"],
  ["won", "Won"],
  ["lost", "Lost"],
  ["closed", "Closed"],
];
export const INQUIRY_DETAIL_STALE_MS = 5_000;
const dateTime = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

function DetailField({ label, children }: { label: string; children: ReactNode }): ReactNode {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{children || <span className="muted">Not provided</span>}</dd>
    </div>
  );
}

function useSessionExpiry(error: unknown): void {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  useEffect(() => {
    if (!(error instanceof ApiError) || error.status !== 401) return;
    queryClient.clear();
    navigate("/login", { replace: true });
  }, [error, navigate, queryClient]);
}

export function InquiryDetail(): ReactNode {
  const { inquiryId = "" } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<InquiryStatus>("new");
  const [assigneeId, setAssigneeId] = useState("");
  const [assignees, setAssignees] = useState<AssigneeChoice[]>([]);
  const [assigneeLoadFailed, setAssigneeLoadFailed] = useState(false);
  const [conflict, setConflict] = useState(false);
  const initializedInquiry = useRef("");
  const query = useQuery({
    queryKey: ["inquiry", inquiryId],
    queryFn: ({ signal }) => getInquiry(inquiryId, signal),
    retry: (count, error) =>
      !(error instanceof ApiError && [401, 404].includes(error.status)) && count < 2,
    staleTime: INQUIRY_DETAIL_STALE_MS,
  });

  useEffect(() => {
    if (!query.data || initializedInquiry.current === inquiryId) return;
    initializedInquiry.current = inquiryId;
    setStatus(query.data.status);
    setAssigneeId(query.data.assignee?.id ?? "");
  }, [inquiryId, query.data]);
  useEffect(() => {
    const controller = new AbortController();
    setAssigneeLoadFailed(false);
    listAssignees(controller.signal)
      .then(setAssignees)
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        if (error instanceof ApiError && error.status === 401) {
          queryClient.clear();
          navigate("/login", { replace: true });
          return;
        }
        setAssigneeLoadFailed(true);
      });
    return () => controller.abort();
  }, [navigate, queryClient]);

  const finishMutation = async (detail: InquiryDetailRecord): Promise<void> => {
    setConflict(false);
    setStatus(detail.status);
    setAssigneeId(detail.assignee?.id ?? "");
    queryClient.setQueryData(["inquiry", inquiryId], detail);
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["inquiry", inquiryId] }),
      queryClient.invalidateQueries({ queryKey: ["inquiries"] }),
    ]);
  };
  const handleMutationError = async (error: unknown): Promise<void> => {
    if (error instanceof ApiError && error.status === 409) {
      setConflict(true);
      await query.refetch();
    }
  };
  const statusMutation = useMutation({
    mutationFn: (expectedVersion: number) =>
      updateInquiryStatus(inquiryId, status, expectedVersion),
    onSuccess: finishMutation,
    onError: handleMutationError,
  });
  const assignmentMutation = useMutation({
    mutationFn: (expectedVersion: number) =>
      updateInquiryAssignment(inquiryId, assigneeId || null, expectedVersion),
    onSuccess: finishMutation,
    onError: handleMutationError,
  });
  const mutationError = statusMutation.error ?? assignmentMutation.error;
  useSessionExpiry(query.error ?? mutationError);

  const submit = (
    event: FormEvent,
    mutation: typeof statusMutation | typeof assignmentMutation,
  ): void => {
    event.preventDefault();
    if (query.data && !mutation.isPending) mutation.mutate(query.data.version);
  };
  const unavailable = mutationError instanceof ApiError && mutationError.retryable;

  if (query.isPending) {
    return (
      <main className="crm-state" id="main-content" role="status">
        Loading inquiry…
      </main>
    );
  }
  if (query.isError || !query.data) {
    const missing = query.error instanceof ApiError && query.error.status === 404;
    return (
      <main className="crm-state" id="main-content" role="alert">
        <h1>{missing ? "Inquiry not found" : "Inquiry couldn’t be loaded"}</h1>
        <p>
          {missing
            ? "It may have been removed or the link is invalid."
            : "No customer information was changed. Try loading it again."}
        </p>
        {missing ? (
          <Link className="button-link" to="/crm/inquiries">
            Back to inquiries
          </Link>
        ) : (
          <button type="button" onClick={() => query.refetch()}>
            Try again
          </button>
        )}
      </main>
    );
  }

  const detail = query.data;
  return (
    <main className="crm-page inquiry-detail" id="main-content">
      <Link className="back-link" to="/crm/inquiries">
        ← All inquiries
      </Link>
      <header className="detail-heading">
        <div>
          <p className="eyebrow">{detail.reference}</p>
          <h1>{detail.contact.fullName}</h1>
          <p>{detail.property.title}</p>
        </div>
        <span className={`status-pill status-${detail.status}`}>{detail.status}</span>
      </header>

      {conflict && (
        <div className="conflict-alert" role="alert">
          <strong>This inquiry changed in another session.</strong>
          <span>The latest version is shown. Review your selection, then save again.</span>
        </div>
      )}
      {detail.dedupeState === "review" && (
        <div className="review-alert" role="status">
          <strong>Possible duplicate contact details.</strong>
          <span>Review this inquiry independently; records have not been merged.</span>
        </div>
      )}
      {Boolean(mutationError) &&
        !(mutationError instanceof ApiError && mutationError.status === 409) && (
          <div className="form-alert" role="alert">
            {unavailable
              ? "The change could not be confirmed. Check your connection before trying again."
              : "The change was not saved. Refresh the inquiry and try again."}
          </div>
        )}

      <div className="detail-layout">
        <div className="detail-main">
          <section className="detail-card" aria-labelledby="contact-heading">
            <h2 id="contact-heading">Contact</h2>
            <dl className="detail-grid">
              <DetailField label="Email">
                {detail.contact.email && (
                  <a href={`mailto:${detail.contact.email}`}>{detail.contact.email}</a>
                )}
              </DetailField>
              <DetailField label="Phone">
                {detail.contact.phone && (
                  <a href={`tel:${detail.contact.phone}`}>{detail.contact.phone}</a>
                )}
              </DetailField>
              <DetailField label="Preferred contact">
                {detail.preferredContactMethod?.replace("_", " ")}
              </DetailField>
              <DetailField label="Received">
                <time dateTime={detail.submittedAt}>
                  {dateTime.format(new Date(detail.submittedAt))}
                </time>
              </DetailField>
            </dl>
          </section>

          <section className="detail-card" aria-labelledby="request-heading">
            <h2 id="request-heading">Request</h2>
            <dl className="detail-grid">
              <DetailField label="Intent">{detail.intent}</DetailField>
              <DetailField label="Timeframe">{detail.timeframe}</DetailField>
              <DetailField label="Budget">{detail.budgetBand}</DetailField>
              <DetailField label="Source">{detail.sourcePlatform}</DetailField>
              <DetailField label="Capture surface">{detail.captureSurface}</DetailField>
              <DetailField label="Form version">{detail.formVersion}</DetailField>
              <DetailField label="Record review">
                {detail.dedupeState === "review" ? "Review needed" : "Clear"}
              </DetailField>
              <DetailField label="Last updated">
                <time dateTime={detail.updatedAt}>
                  {dateTime.format(new Date(detail.updatedAt))}
                </time>
              </DetailField>
            </dl>
            <h3>Customer message</h3>
            <p className="customer-message">{detail.message ?? "No message provided."}</p>
          </section>

          <section className="detail-card" aria-labelledby="history-heading">
            <h2 id="history-heading">Status history</h2>
            {detail.statusHistory.length ? (
              <ol className="history-list">
                {detail.statusHistory.map((item) => (
                  <li key={item.id}>
                    <span>
                      <strong>{item.fromStatus}</strong> → <strong>{item.toStatus}</strong>
                    </span>
                    <small>
                      {item.actor.displayName} ·{" "}
                      <time dateTime={item.createdAt}>
                        {dateTime.format(new Date(item.createdAt))}
                      </time>
                    </small>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="muted">No status changes yet.</p>
            )}
          </section>
        </div>

        <aside className="detail-actions" aria-label="Inquiry actions">
          <form className="action-card" onSubmit={(event) => submit(event, statusMutation)}>
            <h2>Status</h2>
            <label htmlFor="inquiry-status">Current stage</label>
            <select
              id="inquiry-status"
              value={status}
              onChange={(event) => setStatus(event.target.value as InquiryStatus)}
            >
              {STATUS_OPTIONS.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
            <button type="submit" disabled={statusMutation.isPending || status === detail.status}>
              {statusMutation.isPending ? "Saving…" : "Save status"}
            </button>
          </form>

          <form className="action-card" onSubmit={(event) => submit(event, assignmentMutation)}>
            <h2>Owner</h2>
            <label htmlFor="inquiry-owner">Assigned team member</label>
            <select
              id="inquiry-owner"
              value={assigneeId}
              disabled={assigneeLoadFailed}
              onChange={(event) => setAssigneeId(event.target.value)}
            >
              <option value="">Unassigned</option>
              {assignees.map((user) => (
                <option key={user.id} value={user.id}>
                  {user.displayName}
                </option>
              ))}
            </select>
            {assigneeLoadFailed && <p className="field-error">Team members couldn’t be loaded.</p>}
            <button
              type="submit"
              disabled={
                assignmentMutation.isPending ||
                assigneeLoadFailed ||
                assigneeId === (detail.assignee?.id ?? "")
              }
            >
              {assignmentMutation.isPending ? "Saving…" : "Save owner"}
            </button>
          </form>

          <section className="consent-card" aria-labelledby="consent-heading">
            <h2 id="consent-heading">Contact permission</h2>
            <p>
              {detail.consent?.requestedContact
                ? "Customer requested a response."
                : "No contact permission recorded."}
            </p>
            <dl>
              <DetailField label="Notice version">{detail.consent?.noticeVersion}</DetailField>
              <DetailField label="Marketing">
                {detail.consent?.marketing ? "Opted in" : "Not opted in"}
              </DetailField>
              <DetailField label="Ad measurement">
                {detail.consent?.adMeasurement ? "Opted in" : "Not opted in"}
              </DetailField>
              <DetailField label="Recorded">
                {detail.consent && (
                  <time dateTime={detail.consent.recordedAt}>
                    {dateTime.format(new Date(detail.consent.recordedAt))}
                  </time>
                )}
              </DetailField>
            </dl>
          </section>
        </aside>
      </div>
    </main>
  );
}
