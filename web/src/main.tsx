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
      {/* Top-CENTER + a safe-area offset so mobile toasts sit fully on-screen
          under the notch/top bar (top-right clipped off the edge). Toned down —
          no richColors — and constrained so they read as a native banner. */}
      <Toaster
        position="top-center"
        closeButton
        offset="calc(env(safe-area-inset-top) + 0.75rem)"
        toastOptions={{ style: { maxWidth: "calc(100vw - 1.5rem)", borderRadius: "var(--r-md)" } }}
      />
      <ConfirmDialogHost />
    </QueryClientProvider>
  </StrictMode>,
);
