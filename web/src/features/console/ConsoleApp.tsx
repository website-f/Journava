import { Suspense, lazy, useState } from "react";
import { NavLink, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { TrendingUp, Plane, ShieldCheck, CreditCard, FileCheck2, LogOut, Sparkles, Building2, Calendar, Wallet } from "@/components/ui/icons";
import { Skeleton } from "@/components/ui";
import { useAuth } from "@/providers/AuthProvider";
import { cn } from "@/lib/cn";

/**
 * B2B console — a desktop-first operations dashboard for agency / corporate
 * orgs, served *instead of* the consumer mobile PWA once such a user logs in.
 * Left rail + data-dense panels over the same agent mesh: commission saved,
 * disruption ops, the inventory firewall, the escrow ledger, and policy/ESG.
 *
 * vite-spa profile (auth-walled, desktop-primary): panels are lazy-loaded to
 * hold the per-route JS budget; the shell itself stays tiny.
 */

const ConsoleOverview = lazy(() => import("./panels").then((m) => ({ default: m.ConsoleOverview })));
const ConsoleClients = lazy(() => import("./panels").then((m) => ({ default: m.ConsoleClients })));
const ConsoleListings = lazy(() => import("./panels").then((m) => ({ default: m.ConsoleListings })));
const ConsoleBookings = lazy(() => import("./panels").then((m) => ({ default: m.ConsoleBookings })));
const ConsoleFinance = lazy(() => import("./panels").then((m) => ({ default: m.ConsoleFinance })));
const ConsoleDisruptions = lazy(() => import("./panels").then((m) => ({ default: m.ConsoleDisruptions })));
const ConsoleFirewall = lazy(() => import("./panels").then((m) => ({ default: m.ConsoleFirewall })));
const ConsoleEscrow = lazy(() => import("./panels").then((m) => ({ default: m.ConsoleEscrow })));
const ConsolePolicy = lazy(() => import("./panels").then((m) => ({ default: m.ConsolePolicy })));

type ConsoleMode = "clients" | "property";

// The console serves two partner shapes from one login: an agency that plans
// trips FOR clients, and a hotel that runs its OWN property. A mode toggle swaps
// the nav; Overview / Escrow / Policy are common to both.
const NAV_CLIENTS = [
  { to: "/console/clients", label: "Clients", icon: Sparkles },
  { to: "/console/disruptions", label: "Trip operations", icon: Plane },
];
const NAV_PROPERTY = [
  { to: "/console/listings", label: "Listings", icon: Building2 },
  { to: "/console/bookings", label: "Bookings", icon: Calendar },
  { to: "/console/firewall", label: "Inventory firewall", icon: ShieldCheck },
];

function navFor(mode: ConsoleMode) {
  const items = [
    { to: "/console", label: "Overview", icon: TrendingUp, end: true },
    ...(mode === "clients" ? NAV_CLIENTS : NAV_PROPERTY),
    { to: "/console/finance", label: "Finance", icon: Wallet },
    { to: "/console/escrow", label: "Escrow & refunds", icon: CreditCard },
    { to: "/console/policy", label: "Policy & ESG", icon: FileCheck2 },
  ];
  return items.map((i) => ({ end: false, ...i }));
}

export function ConsoleApp() {
  const { isAgency, user, signOut } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  // Console is for agency/corporate orgs only. A platform admin (or a consumer)
  // who lands here is bounced back to the traveller app.
  if (!isAgency) return <Navigate to="/" replace />;

  const handleSignOut = () => {
    navigate("/", { replace: true }); // reset the URL so the next login isn't stranded on /console
    signOut();
  };

  const [mode, setMode] = useState<ConsoleMode>(
    () => (localStorage.getItem("journava-console-mode") as ConsoleMode) || "clients",
  );
  const switchMode = (m: ConsoleMode) => {
    setMode(m);
    localStorage.setItem("journava-console-mode", m);
    navigate("/console");
  };
  const NAV = navFor(mode);

  const orgName =
    user?.memberships?.find((m) => m.org_kind === "agency")?.org_name ||
    user?.memberships?.[0]?.org_name ||
    "Journava";

  return (
    <div className="min-h-[100dvh] bg-[var(--bg)] text-[var(--text)] lg:flex">
      {/* Sidebar (desktop) */}
      <aside className="sticky top-0 hidden h-[100dvh] w-60 shrink-0 flex-col border-r border-[var(--border)] bg-[var(--surface)] lg:flex">
        <div className="flex items-center gap-2 px-5 py-5">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-[var(--brand-500)] text-white">
            <Sparkles className="h-4 w-4" />
          </span>
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold">Journava</p>
            <p className="truncate text-[0.7rem] text-[var(--muted)]">Agency console</p>
          </div>
        </div>
        <ModeToggle mode={mode} onChange={switchMode} className="mx-3 mb-2" />
        <nav className="flex-1 space-y-1 px-3">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end} className={navClass}>
              <Icon className="h-4 w-4 shrink-0" />
              <span className="truncate">{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-[var(--border)] p-3">
          <p className="truncate px-2 pb-2 text-xs text-[var(--muted)]">{orgName}</p>
          <NavLink to="/" className="mb-1 flex items-center gap-2 rounded-[var(--r-md)] px-3 py-2 text-sm text-[var(--muted)] hover:bg-[var(--bg)]">
            <Sparkles className="h-4 w-4" /> Traveller app
          </NavLink>
          <button onClick={handleSignOut} className="flex w-full items-center gap-2 rounded-[var(--r-md)] px-3 py-2 text-sm text-[var(--muted)] hover:bg-[var(--bg)]">
            <LogOut className="h-4 w-4" /> Sign out
          </button>
        </div>
      </aside>

      {/* Mobile top nav */}
      <div className="sticky top-0 z-20 border-b border-[var(--border)] bg-[var(--surface)] lg:hidden">
        <div className="flex items-center justify-between px-4 py-3">
          <span className="text-sm font-semibold">Journava · Console</span>
          <NavLink to="/" className="text-xs text-[var(--brand-600)]">Traveller app →</NavLink>
        </div>
        <ModeToggle mode={mode} onChange={switchMode} className="mx-3 mb-2" />
        <nav className="no-scrollbar flex gap-1 overflow-x-auto px-3 pb-2">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end} className={navPillClass}>
              <Icon className="h-4 w-4 shrink-0" />
              <span className="whitespace-nowrap">{label}</span>
            </NavLink>
          ))}
        </nav>
      </div>

      {/* Main */}
      <main className="min-w-0 flex-1 px-4 py-6 sm:px-8">
        <div className="mx-auto w-full max-w-6xl">
          <Suspense fallback={<PanelSkeleton />}>
            <Routes location={location}>
              <Route path="/console" element={<ConsoleOverview />} />
              <Route path="/console/clients" element={<ConsoleClients />} />
              <Route path="/console/listings" element={<ConsoleListings />} />
              <Route path="/console/bookings" element={<ConsoleBookings />} />
              <Route path="/console/finance" element={<ConsoleFinance />} />
              <Route path="/console/disruptions" element={<ConsoleDisruptions />} />
              <Route path="/console/firewall" element={<ConsoleFirewall />} />
              <Route path="/console/escrow" element={<ConsoleEscrow />} />
              <Route path="/console/policy" element={<ConsolePolicy />} />
              <Route path="*" element={<Navigate to="/console" replace />} />
            </Routes>
          </Suspense>
        </div>
      </main>
    </div>
  );
}

function ModeToggle({ mode, onChange, className }: { mode: ConsoleMode; onChange: (m: ConsoleMode) => void; className?: string }) {
  return (
    <div className={cn("grid grid-cols-2 gap-1 rounded-[var(--r-md)] bg-[var(--bg)] p-1 text-xs font-medium", className)}>
      {(["clients", "property"] as ConsoleMode[]).map((m) => (
        <button
          key={m}
          onClick={() => onChange(m)}
          className={cn(
            "rounded-[calc(var(--r-md)-2px)] px-2 py-1.5 transition-colors",
            mode === m ? "bg-[var(--surface)] text-[var(--brand-600)] shadow-[var(--shadow-1)]" : "text-[var(--muted)]",
          )}
        >
          {m === "clients" ? "My clients" : "My property"}
        </button>
      ))}
    </div>
  );
}

function navClass({ isActive }: { isActive: boolean }) {
  return cn(
    "flex items-center gap-3 rounded-[var(--r-md)] px-3 py-2 text-sm font-medium transition-colors",
    isActive
      ? "bg-[color-mix(in_srgb,var(--brand-400)_16%,transparent)] text-[var(--brand-600)]"
      : "text-[var(--muted)] hover:bg-[var(--bg)] hover:text-[var(--text)]",
  );
}

function navPillClass({ isActive }: { isActive: boolean }) {
  return cn(
    "flex items-center gap-1.5 rounded-[var(--r-pill)] border px-3 py-1.5 text-xs font-medium",
    isActive
      ? "border-transparent bg-[var(--brand-500)] text-white"
      : "border-[var(--border)] text-[var(--muted)]",
  );
}

function PanelSkeleton() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-8 w-56" />
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-24 w-full" />
        ))}
      </div>
      <Skeleton className="h-64 w-full" />
    </div>
  );
}
