import "@/styles/globals.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "sonner";
import { ConfirmDialogHost } from "@/components/ui";
import { AuthProvider } from "@/providers/AuthProvider";
import { App } from "./App";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <App />
        </AuthProvider>
      </BrowserRouter>
      {/* Top-CENTER, dropped BELOW the glass top bar (safe-area inset + the bar's
          own height) so a mobile toast never overlaps the header or hides under
          the notch. Toned down — no richColors — and width-capped so it reads as
          a native banner. `jv-toast*` classes style the surface + round close. */}
      <Toaster
        position="top-center"
        closeButton
        gap={8}
        offset="calc(var(--safe-top) + var(--top-bar) + 0.5rem)"
        mobileOffset="calc(var(--safe-top) + var(--top-bar) + 0.5rem)"
        toastOptions={{
          className: "jv-toast",
          closeButtonAriaLabel: "Dismiss",
          style: { maxWidth: "min(26rem, calc(100vw - 1.5rem))" },
        }}
      />
      <ConfirmDialogHost />
    </QueryClientProvider>
  </StrictMode>,
);
