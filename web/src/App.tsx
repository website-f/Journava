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
// B2B desktop console — its own full-screen shell (no PWA bottom nav), served to
// agency/corporate users. Split out so consumers never download it.
const ConsoleApp = lazy(() =>
  import("@/features/console/ConsoleApp").then((m) => ({ default: m.ConsoleApp })),
);
// Public, no-auth read-only plan a client opens from a Telegram/WhatsApp link.
const SharedPlan = lazy(() =>
  import("@/features/shared/SharedPlan").then((m) => ({ default: m.SharedPlan })),
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
  const { status, isAgency } = useAuth();
  // Only real agency/corporate orgs land on the B2B console. Platform admins
  // keep the consumer PWA (they test traveller flows) but can still open
  // /console manually — ConsoleApp allows them through for support.
  const isB2B = isAgency;

  // Public shared-plan link — renders for anyone, before the auth wall, so a
  // client with no account can open the interactive itinerary. Wrapped in a
  // Route so useParams() sees the :token.
  if (location.pathname.startsWith("/s/")) {
    return (
      <ErrorBoundary resetKey={location.pathname}>
        <Suspense fallback={<RouteFallback />}>
          <Routes location={location}>
            <Route path="/s/:token" element={<SharedPlan />} />
          </Routes>
        </Suspense>
      </ErrorBoundary>
    );
  }

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

  // B2B console: a desktop-first dashboard shell rendered OUTSIDE the PWA shell
  // (no bottom nav). Consumers never reach it (redirects to "/").
  if (location.pathname.startsWith("/console")) {
    return (
      <ErrorBoundary resetKey={location.pathname}>
        <Suspense fallback={<RouteFallback />}>
          <ConsoleApp />
        </Suspense>
      </ErrorBoundary>
    );
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
              <Route path="/" element={isB2B ? <Navigate to="/console" replace /> : <CommandCenter />} />
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
