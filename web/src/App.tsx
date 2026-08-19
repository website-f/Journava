import { Suspense, lazy, type ReactNode } from "react";
import { Routes, Route, Navigate, useLocation } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { AppShell } from "@/components/layout/AppShell";
import { Skeleton, Spinner } from "@/components/ui";
import { CommandCenter } from "@/features/command-center/CommandCenter";
import { LoginPage } from "@/features/auth/LoginPage";
import { useAuth } from "@/providers/AuthProvider";

/*
 * The Command Center is the landing surface, so it stays in the main bundle.
 * Everything else is split out — MapLibre (My Trip) and React Flow (Agents)
 * together weigh more than the rest of the app, and shipping them up front makes
 * the installable PWA shell needlessly heavy for a first paint that never uses
 * them.
 */
const ResearchBoard = lazy(() =>
  import("@/features/research/ResearchBoard").then((m) => ({ default: m.ResearchBoard })),
);
const MyTrip = lazy(() =>
  import("@/features/trip/MyTrip").then((m) => ({ default: m.MyTrip })),
);
const AgentControl = lazy(() =>
  import("@/features/agent-control/AgentControl").then((m) => ({ default: m.AgentControl })),
);
const EngineSettings = lazy(() =>
  import("@/features/engine/EngineSettings").then((m) => ({ default: m.EngineSettings })),
);
const Profile = lazy(() =>
  import("@/features/profile/Profile").then((m) => ({ default: m.Profile })),
);
const ApiVault = lazy(() =>
  import("@/features/vault/ApiVault").then((m) => ({ default: m.ApiVault })),
);
const History = lazy(() =>
  import("@/features/history/History").then((m) => ({ default: m.History })),
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
  const { status, isPlatformAdmin } = useAuth();

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

  // Admin-only surfaces are gated in the router too, not just hidden in the nav.
  const adminEl = (el: ReactNode) =>
    isPlatformAdmin ? el : <Navigate to="/" replace />;

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
          <Suspense fallback={<RouteFallback />}>
            <Routes location={location}>
              <Route path="/" element={<CommandCenter />} />
              <Route path="/research" element={<ResearchBoard />} />
              <Route path="/trip" element={<MyTrip />} />
              <Route path="/agents" element={<AgentControl />} />
              <Route path="/engine" element={adminEl(<EngineSettings />)} />
              <Route path="/vault" element={adminEl(<ApiVault />)} />
              <Route path="/history" element={<History />} />
              <Route path="/profile" element={<Profile />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </Suspense>
        </motion.div>
      </AnimatePresence>
    </AppShell>
  );
}
