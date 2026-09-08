import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import { App, ApplicationErrorBoundary } from "./App";
import "./styles.css";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      gcTime: 5 * 60_000,
      refetchOnWindowFocus: false,
      retry: (failureCount, error) =>
        !(error instanceof Response && error.status >= 400 && error.status < 500) &&
        failureCount < 2,
      retryDelay: (attempt) => Math.min(500 * 2 ** attempt, 4_000),
      staleTime: 0,
    },
    mutations: { retry: false },
  },
});

const root = document.getElementById("root");
if (!root) throw new Error("Application mount element is missing");

createRoot(root).render(
  <StrictMode>
    <ApplicationErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </QueryClientProvider>
    </ApplicationErrorBoundary>
  </StrictMode>,
);
