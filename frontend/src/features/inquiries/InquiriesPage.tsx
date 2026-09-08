import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import {
  ApiError,
  type Inquiry,
  type InquiryFilters,
  type InquiryStatus,
  listInquiries,
} from "../../api/client";

const STATUS_OPTIONS: readonly [InquiryStatus | "", string][] = [
  ["", "All statuses"],
  ["new", "New"],
  ["contacted", "Contacted"],
  ["qualified", "Qualified"],
  ["viewing", "Viewing arranged"],
  ["won", "Won"],
  ["lost", "Lost"],
  ["closed", "Closed"],
];

const dateFormatter = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short",
});

function InquiryRow({ inquiry }: { inquiry: Inquiry }): ReactNode {
  return (
    <tr>
      <td>
        <Link className="inquiry-link" to={`/crm/inquiries/${inquiry.id}`}>
          {inquiry.contact.fullName}
        </Link>
        <span className="table-secondary">{inquiry.reference}</span>
      </td>
      <td>
        {inquiry.property.title}
        <span className="table-secondary">{inquiry.intent ?? "General enquiry"}</span>
      </td>
      <td>
        <span className={`status-pill status-${inquiry.status}`}>{inquiry.status}</span>
      </td>
      <td>{inquiry.assignee?.displayName ?? <span className="unassigned">Unassigned</span>}</td>
      <td>
        <time dateTime={inquiry.submittedAt}>
          {dateFormatter.format(new Date(inquiry.submittedAt))}
        </time>
      </td>
    </tr>
  );
}

export function InquiriesPage(): ReactNode {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [status, setStatus] = useState<InquiryStatus | "">("");
  const filters: InquiryFilters = status ? { status } : {};
  const query = useInfiniteQuery({
    queryKey: ["inquiries", filters],
    queryFn: ({ pageParam, signal }) => listInquiries(filters, pageParam, signal),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (page) => page.nextCursor ?? undefined,
    retry: (count, error) => !(error instanceof ApiError && error.status === 401) && count < 2,
    staleTime: 10_000,
  });
  const inquiries = query.data?.pages.flatMap((page) => page.items) ?? [];
  const sessionEnded = query.error instanceof ApiError && query.error.status === 401;
  useEffect(() => {
    if (!sessionEnded) return;
    queryClient.clear();
    navigate("/login", { replace: true });
  }, [navigate, queryClient, sessionEnded]);

  return (
    <main className="crm-page" id="main-content">
      <header className="crm-heading">
        <div>
          <p className="eyebrow">Enquiry workspace</p>
          <h1>Inquiries</h1>
          <p>Review and route property enquiries without losing the customer’s context.</p>
        </div>
        <label className="filter-field" htmlFor="status-filter">
          <span>Status</span>
          <select
            id="status-filter"
            value={status}
            onChange={(event) => setStatus(event.target.value as InquiryStatus | "")}
          >
            {STATUS_OPTIONS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
      </header>

      {query.isPending ? (
        <div className="crm-state" role="status">
          Loading inquiries…
        </div>
      ) : query.isError ? (
        <div className="crm-state" role="alert">
          <h2>{sessionEnded ? "Your session has ended" : "Inquiries couldn’t be loaded"}</h2>
          <p>
            {sessionEnded
              ? "Sign in again to continue."
              : "No customer information was changed. Try loading the list again."}
          </p>
          {!sessionEnded && (
            <button type="button" onClick={() => query.refetch()}>
              Try again
            </button>
          )}
        </div>
      ) : inquiries.length === 0 ? (
        <div className="crm-state">
          <h2>No inquiries match this view</h2>
          <p>
            {status
              ? "Choose another status to broaden the list."
              : "New inquiries will appear here after they’re submitted."}
          </p>
        </div>
      ) : (
        <>
          <div className="inquiry-table-wrap">
            <table className="inquiry-table">
              <caption className="sr-only">Property inquiries</caption>
              <thead>
                <tr>
                  <th>Customer</th>
                  <th>Property</th>
                  <th>Status</th>
                  <th>Owner</th>
                  <th>Received</th>
                </tr>
              </thead>
              <tbody>
                {inquiries.map((inquiry) => (
                  <InquiryRow inquiry={inquiry} key={inquiry.id} />
                ))}
              </tbody>
            </table>
          </div>
          {query.hasNextPage && (
            <button
              className="load-more"
              type="button"
              disabled={query.isFetchingNextPage}
              onClick={() => query.fetchNextPage()}
            >
              {query.isFetchingNextPage ? "Loading…" : "Load more"}
            </button>
          )}
        </>
      )}
    </main>
  );
}
