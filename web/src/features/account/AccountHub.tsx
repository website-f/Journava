import type { ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import {
  User,
  Building2,
  Cpu,
  KeyRound,
  Zap,
  TrendingUp,
  ShieldCheck,
  type IconType,
} from "@/components/ui/icons";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui";
import { Page } from "@/components/layout/Page";
import { useAuth } from "@/providers/AuthProvider";
import { Profile } from "@/features/profile/Profile";
import { Integrations } from "@/features/account/Integrations";
import { AgencyConsole } from "@/features/agency/AgencyConsole";
import { SupplierPortal } from "@/features/supplier/SupplierPortal";
import { EngineSettings } from "@/features/engine/EngineSettings";
import { ApiVault } from "@/features/vault/ApiVault";

type AccountTab = {
  value: string;
  label: string;
  icon: IconType;
  render: () => ReactNode;
};

/**
 * Account destination — Profile plus the role-gated surfaces (Partner for
 * agencies, Engine + API Vault for platform admins), so settings-shaped pages
 * collapse into one bottom-nav slot. Tab is URL-linkable (`?tab=engine`).
 *
 * Opens with an identity card rather than a page title: on a phone, the first
 * thing you want from a settings screen is confirmation of *which* account you
 * are in and a way out of it. The tab strip below is the navigation, so a second
 * big heading here would just push the actual content off the fold.
 */
export function AccountHub() {
  const { isPlatformAdmin, isAgency } = useAuth();
  const [params, setParams] = useSearchParams();

  const tabs: AccountTab[] = [
    { value: "profile", label: "Profile", icon: User, render: () => <Profile /> },
    { value: "integrate", label: "Integrate", icon: Zap, render: () => <Integrations /> },
    ...(isAgency || isPlatformAdmin
      ? [{ value: "agency", label: "Agency", icon: TrendingUp, render: () => <AgencyConsole /> }]
      : []),
    ...(isAgency
      ? [{ value: "partner", label: "Partner", icon: Building2, render: () => <SupplierPortal /> }]
      : []),
    ...(isPlatformAdmin
      ? [
          { value: "engine", label: "Engine", icon: Cpu, render: () => <EngineSettings /> },
          { value: "vault", label: "API Vault", icon: KeyRound, render: () => <ApiVault /> },
        ]
      : []),
  ];

  const requested = params.get("tab");
  const active = tabs.some((t) => t.value === requested) ? requested! : "profile";

  return (
    <Page width="xl">
      <IdentityCard />

      <Tabs
        value={active}
        onValueChange={(value) => setParams(value === "profile" ? {} : { tab: value })}
      >
        {/*
          Sticky so the tab strip stays reachable while a long settings tab (Engine,
          Vault) scrolls under it — offset by the top bar's own height so it parks
          against the chrome instead of sliding beneath it.
        */}
        <div
          className="sticky z-10 -mx-4 bg-[var(--bg)]/85 px-4 py-2 backdrop-blur-md md:-mx-6 md:px-6"
          style={{ top: "var(--top-bar)" }}
        >
          <TabsList>
            {tabs.map(({ value, label, icon: Icon }) => (
              <TabsTrigger key={value} value={value}>
                <Icon className="h-4 w-4" weight={active === value ? "fill" : "regular"} /> {label}
              </TabsTrigger>
            ))}
          </TabsList>
        </div>
        {tabs.map((tab) => (
          <TabsContent key={tab.value} value={tab.value}>
            {tab.render()}
          </TabsContent>
        ))}
      </Tabs>
    </Page>
  );
}

/** Who you're signed in as, what you're allowed to see, and the way out. */
function IdentityCard() {
  const { user, isPlatformAdmin } = useAuth();
  if (!user) return null;

  // Guard every field: on the session-restore path `/auth/me` can omit
  // `memberships` (a plain traveller with no orgs), and a raw `.memberships[0]`
  // / `.email.split()` there throws and trips the whole-page ErrorBoundary.
  const name = user.display_name?.trim() || user.email?.split("@")[0] || "you";
  const initial = name.charAt(0).toUpperCase();
  const org = user.memberships?.[0];

  return (
    <section className="mb-5 rounded-[var(--r-xl)] bg-[var(--brand-600)] p-4 text-white shadow-[var(--shadow-2)] sm:p-5">
      <div className="flex items-start gap-3 sm:gap-4">
        <span
          aria-hidden
          className="grid h-12 w-12 shrink-0 place-items-center rounded-[var(--r-lg)] bg-white/12 font-[family-name:var(--font-display)] text-[1.35rem] font-bold ring-1 ring-inset ring-white/20 sm:h-14 sm:w-14 sm:text-[1.5rem]"
        >
          {initial}
        </span>
        <div className="min-w-0 flex-1">
          <div className="min-w-0">
            {/* Sign-out lives only in the top bar (AppShell) — a second button
                here was redundant. */}
            <h1 className="truncate font-[family-name:var(--font-display)] text-[1.2rem] font-bold leading-tight tracking-[-0.02em] sm:text-[1.35rem]">
              {name}
            </h1>
            <p className="mt-0.5 truncate text-[0.8125rem] text-white/70">{user.email}</p>
          </div>
          <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
            {isPlatformAdmin && (
              <span className="inline-flex items-center gap-1 rounded-[var(--r-pill)] bg-white/15 px-2.5 py-[0.1875rem] text-[0.6875rem] font-semibold uppercase tracking-[0.06em] text-white ring-1 ring-inset ring-white/20">
                <ShieldCheck className="h-3 w-3" weight="fill" /> Platform admin
              </span>
            )}
            {org && (
              <span className="inline-flex items-center gap-1 rounded-[var(--r-pill)] bg-white/10 px-2.5 py-[0.1875rem] text-[0.6875rem] font-medium text-white/85 ring-1 ring-inset ring-white/15">
                {org.org_name} · {org.role}
              </span>
            )}
            {!isPlatformAdmin && !org && (
              <span className="text-[0.6875rem] font-semibold uppercase tracking-[0.1em] text-white/55">
                Traveller
              </span>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
