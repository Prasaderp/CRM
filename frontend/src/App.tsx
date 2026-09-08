import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Component, type ReactNode, useEffect } from "react";
import { Link, Navigate, Outlet, Route, Routes, useLocation, useNavigate } from "react-router-dom";

import { ApiError, getSession, type LeadAccepted, logout } from "./api/client";
import { LoginPage } from "./features/auth/LoginPage";
import { InquiriesPage } from "./features/inquiries/InquiriesPage";
import { InquiryDetail } from "./features/inquiries/InquiryDetail";
import { PropertyPage } from "./features/lead-capture/PropertyPage";

type ErrorBoundaryProps = { children: ReactNode };
type ErrorBoundaryState = { failed: boolean };

export class ApplicationErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  override state: ErrorBoundaryState = { failed: false };

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { failed: true };
  }

  override render(): ReactNode {
    if (!this.state.failed) return this.props.children;
    return (
      <main className="state-page" id="main-content">
        <p className="eyebrow">Something went wrong</p>
        <h1>We couldn’t display this page.</h1>
        <p>Your information has not been submitted. Refresh the page to try again.</p>
        <button type="button" onClick={() => window.location.reload()}>
          Refresh page
        </button>
      </main>
    );
  }
}

function AppFrame(): ReactNode {
  const session = useSession();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const logoutMutation = useMutation({
    mutationFn: () => logout(),
    onSuccess: () => {
      queryClient.clear();
      navigate("/login", { replace: true });
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 401) {
        queryClient.clear();
        navigate("/login", { replace: true });
      }
    },
  });
  return (
    <div className="app-frame">
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <header className="site-header">
        <Link className="brand" to="/" aria-label="Property enquiries home">
          <span aria-hidden="true">RE</span>
          <strong>Property enquiries</strong>
        </Link>
        <nav aria-label="Primary navigation">
          {session.data ? (
            <div className="session-controls">
              <span>{session.data.displayName}</span>
              <button
                type="button"
                disabled={logoutMutation.isPending}
                onClick={() => logoutMutation.mutate()}
              >
                {logoutMutation.isPending ? "Signing out…" : "Sign out"}
              </button>
            </div>
          ) : (
            <Link to="/login">Team sign in</Link>
          )}
        </nav>
      </header>
      {logoutMutation.isError &&
        !(logoutMutation.error instanceof ApiError && logoutMutation.error.status === 401) && (
          <div className="header-alert" role="alert">
            Couldn’t sign out. Check your connection and try again.
          </div>
        )}
      <Outlet />
      <footer className="site-footer">
        <p>Property details and availability are confirmed by the property team.</p>
      </footer>
    </div>
  );
}

function HomePage(): ReactNode {
  return (
    <main className="state-page" id="main-content">
      <p className="eyebrow">Property enquiries</p>
      <h1>Use the property link shared with you.</h1>
      <p>Each approved listing has a dedicated page with its current details and enquiry form.</p>
    </main>
  );
}

function ConfirmationPage(): ReactNode {
  const location = useLocation();
  const state = location.state as { accepted?: LeadAccepted; propertyTitle?: string } | null;
  if (!state?.accepted) return <Navigate replace to="/" />;
  return (
    <main className="state-page" id="main-content" aria-labelledby="confirmation-heading">
      <span className="status-mark" aria-hidden="true">
        ✓
      </span>
      <p className="eyebrow">Enquiry received</p>
      <h1 id="confirmation-heading">Thank you.</h1>
      <p>Your enquiry{state.propertyTitle ? ` for ${state.propertyTitle}` : ""} was saved.</p>
      <p className="reference">
        Reference: <strong>{state.accepted.reference}</strong>
      </p>
      <p>
        The property team will confirm availability and respond using your selected contact details.
      </p>
      <Link className="button-link" to="/">
        Finish
      </Link>
    </main>
  );
}

function useSession() {
  return useQuery({
    queryKey: ["session"],
    queryFn: ({ signal }) => getSession(signal),
    retry: false,
    staleTime: 60_000,
  });
}

function LoginRoute(): ReactNode {
  const session = useSession();
  return session.isPending ? (
    <main className="crm-state" id="main-content" role="status">
      Checking your session…
    </main>
  ) : (
    <LoginPage session={session.data} />
  );
}

function AuthenticatedCrmBoundary(): ReactNode {
  const session = useSession();
  const queryClient = useQueryClient();
  const unauthorized = session.error instanceof ApiError && session.error.status === 401;
  useEffect(() => {
    if (unauthorized)
      queryClient.removeQueries({ predicate: ({ queryKey }) => queryKey[0] !== "session" });
  }, [queryClient, unauthorized]);
  if (session.isPending)
    return (
      <main className="crm-state" id="main-content" role="status">
        Opening workspace…
      </main>
    );
  if (unauthorized) return <Navigate replace to="/login" />;
  if (session.isError)
    return (
      <main className="crm-state" id="main-content" role="alert">
        <h1>Workspace unavailable</h1>
        <p>Your session could not be checked. No customer information has been displayed.</p>
        <button type="button" onClick={() => session.refetch()}>
          Try again
        </button>
      </main>
    );
  return <Outlet />;
}

function NotFoundPage(): ReactNode {
  return (
    <main className="state-page" id="main-content">
      <p className="eyebrow">Page not found</p>
      <h1>This link doesn’t match an available page.</h1>
      <p>Check the complete property link or return to the start.</p>
      <Link className="button-link" to="/">
        Return home
      </Link>
    </main>
  );
}

export function App(): ReactNode {
  return (
    <Routes>
      <Route element={<AppFrame />}>
        <Route index element={<HomePage />} />
        <Route path="p/:propertySlug" element={<PropertyPage />} />
        <Route path="confirmation" element={<ConfirmationPage />} />
        <Route path="login" element={<LoginRoute />} />
        <Route path="crm" element={<AuthenticatedCrmBoundary />}>
          <Route index element={<Navigate replace to="inquiries" />} />
          <Route path="inquiries" element={<InquiriesPage />} />
          <Route path="inquiries/:inquiryId" element={<InquiryDetail />} />
          <Route path="*" element={<Navigate replace to="inquiries" />} />
        </Route>
        <Route path="not-found" element={<NotFoundPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
