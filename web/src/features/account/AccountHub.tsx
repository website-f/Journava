import type { ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { User, Building2, Cpu, KeyRound, Zap, TrendingUp, type IconType } from "@/components/ui/icons";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui";
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
    <div className="mx-auto w-full max-w-6xl">
      <Tabs
        value={active}
        onValueChange={(value) => setParams(value === "profile" ? {} : { tab: value })}
      >
        <TabsList>
          {tabs.map(({ value, label, icon: Icon }) => (
            <TabsTrigger key={value} value={value}>
              <Icon className="h-4 w-4" /> {label}
            </TabsTrigger>
          ))}
        </TabsList>
        {tabs.map((tab) => (
          <TabsContent key={tab.value} value={tab.value}>
            {tab.render()}
          </TabsContent>
        ))}
      </Tabs>
    </div>
  );
}
