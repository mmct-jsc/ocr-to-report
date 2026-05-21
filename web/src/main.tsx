import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { AuthProvider } from "@/lib/auth";
import { ThemeProvider } from "@/lib/theme";
import { ToastProvider } from "@/components/toast";
import { App } from "@/App";

import "./styles.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 5_000,
    },
  },
});

// Vite injects ``import.meta.env.BASE_URL`` from the ``base`` config —
// it's "/" for the docker build and "/ocr-to-report/" for the Pages build.
// React Router needs the same prefix as ``basename`` so deep links like
// ``/demo`` resolve to ``/ocr-to-report/demo`` on Pages without changes
// to route definitions. Strip the trailing slash because BrowserRouter's
// basename convention wants no trailing slash.
const ROUTER_BASENAME = import.meta.env.BASE_URL.replace(/\/$/, "");

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <ToastProvider>
            <BrowserRouter basename={ROUTER_BASENAME}>
              <App />
            </BrowserRouter>
          </ToastProvider>
        </AuthProvider>
      </QueryClientProvider>
    </ThemeProvider>
  </StrictMode>,
);
