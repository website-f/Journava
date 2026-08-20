import { Suspense, lazy } from "react";
import { Routes, Route, Navigate, useLocation } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { AppShell } from "@/components/layout/AppShell";
import { Skeleton, Spinner, ErrorBoundary } from "@/components/ui";
import { CommandCenter } from "@/features/command-center/CommandCenter";
import { LoginPage } from "@/features/auth/LoginPage";
import { useAuth } from "@/providers/AuthProvider";

/*
 * Five destinations (bottom nav): Home (Command Center) · Research · Trip ·
 * Agents · Account. Trip folds in past runs; Account folds in Profile + the
 * role-gated Partner/Engine/Vault surfaces. Legacy paths redirect into those
 * hubs so deep links keep working.
 *
 * Command Center stays in the main bundle (landing surface); the rest split out
 * — MapLibre (Trip) and React Flow (Agents) are the heavy ones.
 */
const ResearchBoard = lazy(() =>
  import("@/features/research/ResearchBoard").then((m) => ({ default: m.ResearchBoard })),
);
const AgentControl = lazy(() =>
  import("@/features/agent-control/AgentControl").then((m) => ({ default: m.AgentControl })),
);
const TripHub = lazy(() =>
  import("@/features/trip/TripHub").then((m) => ({ default: m.TripHub })),
);
const AccountHub = lazy(() =>
  import("@/features/account/AccountHub").then((m) => ({ default: m.AccountHub })),
);

const pageVariants = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -4 },
};

/** Skeleton placeholder while a route chunk loads — never a bare spinner (§10.6). */
function RouteFallback() {
  return (
    <div className="mx-auto w-full max-w-5xl space-y-4">
      <Skeleton className="h-9 w-48" />
      <Skeleton className="h-24 w-full" />
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-28 w-full" />
        ))}
      </div>
    </div>
  );
}

export function App() {
  const location = useLocation();
  const { status } = useAuth();

  // Auth wall (spec §1): restoring a session, then either the app or login.
  if (status === "loading") {
    return (
      <div className="min-h-[100dvh] grid place-items-center bg-[var(--bg)]">
        <Spinner className="h-6 w-6 text-[var(--brand-500)]" />
      </div>
    );
  }
  if (status === "guest") {
    return <LoginPage />;
  }

  return (
    <AppShell>
      <AnimatePresence mode="wait">
        <motion.div
          key={location.pathname}
          variants={pageVariants}
          initial="initial"
          animate="animate"
          exit="exit"
          transition={{ duration: 0.18, ease: [0.2, 0.8, 0.2, 1] }}
        >
          <ErrorBoundary resetKey={location.pathname}>
            <Suspense fallback={<RouteFallback />}>
            <Routes location={location}>
              <Route path="/" element={<CommandCenter />} />
              <Route path="/research" element={<ResearchBoard />} />
              <Route path="/trip" element={<TripHub />} />
              <Route path="/agents" element={<AgentControl />} />
              <Route path="/account" element={<AccountHub />} />

              {/* Legacy deep links → consolidated hubs (roles enforced inside). */}
              <Route path="/history" element={<Navigate to="/trip?tab=history" replace />} />
              <Route path="/profile" element={<Navigate to="/account" replace />} />
              <Route path="/engine" element={<Navigate to="/account?tab=engine" replace />} />
              <Route path="/vault" element={<Navigate to="/account?tab=vault" replace />} />
              <Route path="/supplier" element={<Navigate to="/account?tab=partner" replace />} />

              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
            </Suspense>
          </ErrorBoundary>
        </motion.div>
      </AnimatePresence>
    </AppShell>
  );
}
