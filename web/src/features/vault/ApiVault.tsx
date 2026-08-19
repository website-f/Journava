import { useCallback, useEffect, useMemo, useState } from "react";
import {
  BadgeCheck,
  ExternalLink,
  Eye,
  Info,
  KeyRound,
  Plug,
  RefreshCw,
  Save,
  ShieldCheck,
  Trash2,
} from "@/components/ui/icons";
import { toast } from "sonner";
import { Badge, Button, EmptyState, Skeleton, Tabs, TabsContent, TabsList, TabsTrigger, confirm } from "@/components/ui";
import { StatusPill } from "@/components/ui/SourceBadge";
import { cn } from "@/lib/cn";
import { api, ApiError } from "@/lib/api";
import type {
  AtlasStatus,
  ProbeVerdict,
  VaultCatalogue,
  VaultProvider,
} from "@/lib/types";

/**
 * API Vault — every third-party credential, in one place, encrypted.
 *
 * This replaces `.env` for provider keys. Two behaviours make it worth using
 * rather than editing a file:
 *
 * - **Test before save.** Every provider has a probe, so a key is verified
 *   against the real service while the operator is still looking at the form.
 * - **Honest status.** `healthy · rate limited · limit reached · invalid ·
 *   untested`, observed from real calls. A provider with no probe says
 *   "untested" rather than showing a green tick it hasn't earned.
 *
 * A stored secret is never returned by the API — only a masked hint like
 * `sk-…4f2a`, so there is nothing here that can leak a key back out.
 */

export function ApiVault() {
  const [catalogue, setCatalogue] = useState<VaultCatalogue | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      setCatalogue(await api.get<VaultCatalogue>("/vault/catalogue"));
    } catch {
      toast.error("Could not load the vault.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const byCategory = useMemo(() => {
    const groups = new Map<string, VaultProvider[]>();
    for (const provider of catalogue?.providers ?? []) {
      groups.set(provider.category, [...(groups.get(provider.category) ?? []), provider]);
    }
    return groups;
  }, [catalogue]);

  const stats = useMemo(() => {
    const providers = catalogue?.providers ?? [];
    return {
      total: providers.length,
      configured: providers.filter((p) => p.configured && !p.keyless).length,
      healthy: providers.filter((p) => p.credential?.status === "healthy").length,
      problems: providers.filter(
        (p) =>
          p.credential?.status === "invalid" ||
          p.credential?.status === "limit_reached",
      ).length,
    };
  }, [catalogue]);

  if (loading) {
    return (
      <div className="mx-auto w-full max-w-4xl space-y-4">
        <Skeleton className="h-10 w-56" />
        <Skeleton className="h-24 w-full" />
        {Array.from({ length: 4 }).map((_, index) => (
          <Skeleton key={index} className="h-20 w-full" />
        ))}
      </div>
    );
  }

  if (!catalogue) {
    return (
      <div className="mx-auto w-full max-w-4xl">
        <EmptyState
          icon={<KeyRound className="h-10 w-10" />}
          title="Vault unavailable"
          description="The API could not be reached. Credentials are stored in Postgres — check that the database is running."
          action={
            <Button variant="secondary" onClick={() => void load()}>
              Retry
            </Button>
          }
        />
      </div>
    );
  }

  const categories = Object.entries(catalogue.categories).filter(([key]) =>
    byCategory.has(key),
  );

  return (
    <div className="mx-auto w-full max-w-4xl">
      <header className="pt-2 pb-5">
        <h2 className="flex items-center gap-2 font-[family-name:var(--font-display)] text-2xl tracking-tight">
          <ShieldCheck className="h-6 w-6 text-[var(--brand-500)]" />
          API Vault
        </h2>
        <p className="mt-1 text-sm text-[var(--muted)]">
          Every provider key lives here, encrypted at rest — not in <code>.env</code>.
          Keys are tested against the real service before they are saved, and only a
          masked hint is ever shown again.
        </p>
      </header>

      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Providers" value={stats.total} />
        <Stat label="Configured" value={stats.configured} tone="brand" />
        <Stat label="Healthy" value={stats.healthy} tone="success" />
        <Stat label="Need attention" value={stats.problems} tone="danger" />
      </div>

      <Tabs defaultValue={categories[0]?.[0] ?? "llm"}>
        <TabsList>
          {categories.map(([key, label]) => (
            <TabsTrigger key={key} value={key}>
              {label}
              <Badge>{byCategory.get(key)?.length ?? 0}</Badge>
            </TabsTrigger>
          ))}
        </TabsList>

        {categories.map(([key]) => (
          <TabsContent key={key} value={key}>
            <div className="space-y-3 py-3">
              {(byCategory.get(key) ?? []).map((provider) => (
                <ProviderCard
                  key={provider.slug}
                  provider={provider}
                  onChanged={load}
                />
              ))}
            </div>
          </TabsContent>
        ))}
      </Tabs>
    </div>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: "brand" | "success" | "danger";
}) {
  const colour =
    tone === "brand"
      ? "text-[var(--brand-500)]"
      : tone === "success"
        ? "text-[var(--success)]"
        : tone === "danger"
          ? "text-[var(--danger)]"
          : "text-[var(--text)]";
  return (
    <div className="surface-card p-3 text-center">
      <p className={cn("text-xl font-semibold tabular-nums", colour)}>{value}</p>
      <p className="text-[0.65rem] text-[var(--muted)]">{label}</p>
    </div>
  );
}

function ProviderCard({
  provider,
  onChanged,
}: {
  provider: VaultProvider;
  onChanged: () => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [secret, setSecret] = useState("");
  const [extra, setExtra] = useState<Record<string, string>>({});
  const [verdict, setVerdict] = useState<ProbeVerdict | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const credential = provider.credential;
  const status = credential?.status ?? (provider.configured ? "untested" : "untested");

  const test = async () => {
    setBusy("test");
    try {
      const result = await api.post<ProbeVerdict>("/vault/test", {
        provider: provider.slug,
        secret: secret || null,
        extra,
      });
      setVerdict(result);
      if (result.ok) toast.success(`${provider.label}: ${result.message}`);
      else toast.warning(`${provider.label}: ${result.message}`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Test failed");
    } finally {
      setBusy(null);
    }
  };

  const save = async () => {
    if (provider.needs_secret && !secret && !credential) {
      toast.error("Enter a key first.");
      return;
    }
    setBusy("save");
    try {
      const saved = await api.post<{ test: ProbeVerdict }>("/vault/credentials", {
        provider: provider.slug,
        secret: secret || null,
        extra,
        // Deliberately not enforced: a provider without a probe would otherwise
        // be unsavable, and a rate-limited key is still a valid key.
        require_test: false,
      });
      setVerdict(saved.test);
      setSecret("");
      toast.success(`${provider.label} saved.`);
      await onChanged();
      setOpen(false);
    } catch (error) {
      const message =
        error instanceof ApiError ? error.detail : "Could not save the credential";
      toast.error(message);
    } finally {
      setBusy(null);
    }
  };

  const retest = async () => {
    setBusy("retest");
    try {
      const result = await api.post<ProbeVerdict>(
        `/vault/credentials/${provider.slug}/test`,
      );
      setVerdict(result);
      toast[result.ok ? "success" : "warning"](`${provider.label}: ${result.message}`);
      await onChanged();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Re-test failed");
    } finally {
      setBusy(null);
    }
  };

  const remove = async () => {
    const ok = await confirm({
      title: `Delete the ${provider.label} key?`,
      body: "Agents relying on this provider will fall back to whatever else is configured, or degrade gracefully.",
      confirmText: "Delete key",
      tone: "danger",
    });
    if (!ok) return;
    setBusy("delete");
    try {
      await api.del(`/vault/credentials/${provider.slug}`);
      toast.success(`${provider.label} removed.`);
      await onChanged();
    } catch {
      toast.error("Could not delete the credential.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div
      className={cn(
        "surface-card overflow-hidden",
        provider.credential?.status === "invalid" && "border-[var(--danger)]/40",
      )}
    >
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center gap-3 p-4 text-left transition-colors hover:bg-[color-mix(in_srgb,var(--brand-400)_5%,transparent)]"
      >
        <span
          className={cn(
            "grid h-9 w-9 shrink-0 place-items-center rounded-[var(--r-sm)]",
            provider.configured
              ? "bg-[color-mix(in_srgb,var(--success)_14%,transparent)] text-[var(--success)]"
              : "bg-[color-mix(in_srgb,var(--muted)_12%,transparent)] text-[var(--muted)]",
          )}
        >
          {provider.keyless ? <Plug className="h-4 w-4" /> : <KeyRound className="h-4 w-4" />}
        </span>

        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold">{provider.label}</span>
            {provider.keyless && <Badge variant="success">no key needed</Badge>}
            {provider.source === "env" && (
              <Badge variant="warning" title="Loaded from .env — move it into the vault">
                from .env
              </Badge>
            )}
            {credential && <StatusPill status={status} detail={credential.status_detail} />}
          </span>
          {credential?.masked_secret && (
            <span className="mt-0.5 block font-[family-name:var(--font-mono)] text-[0.65rem] text-[var(--muted)]">
              {credential.masked_secret}
            </span>
          )}
          {!provider.configured && (
            <span className="mt-0.5 block text-[0.65rem] text-[var(--muted)]">
              Not configured
            </span>
          )}
        </span>

        <span className="shrink-0 text-xs text-[var(--muted)]">{open ? "Hide" : "Manage"}</span>
      </button>

      {open && (
        <div className="border-t border-[var(--border)] p-4">
          {provider.note && (
            <p className="mb-3 flex items-start gap-2 text-xs text-[var(--muted)]">
              <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              {provider.note}
            </p>
          )}

          {provider.keyless ? (
            <p className="text-xs text-[var(--muted)]">
              This service needs no credential — it is listed so you can see everything
              the agents rely on.
            </p>
          ) : (
            <>
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="block sm:col-span-2">
                  <span className="mb-1 block text-xs font-medium">
                    {credential ? "Replace key" : "API key / secret"}
                  </span>
                  <input
                    type="password"
                    autoComplete="off"
                    className="input-field font-[family-name:var(--font-mono)]"
                    placeholder={credential ? "Leave empty to keep the current key" : "Paste the key"}
                    value={secret}
                    onChange={(event) => setSecret(event.target.value)}
                  />
                </label>

                {provider.extra_fields.map((field) => (
                  <label key={field} className="block">
                    <span className="mb-1 block text-xs font-medium capitalize">
                      {field.replace(/_/g, " ")}
                    </span>
                    <input
                      className="input-field"
                      placeholder={
                        field === "environment" ? "sandbox or production" : field
                      }
                      value={
                        extra[field] ??
                        String((credential?.extra?.[field] as string | undefined) ?? "")
                      }
                      onChange={(event) =>
                        setExtra((prev) => ({ ...prev, [field]: event.target.value }))
                      }
                    />
                  </label>
                ))}
              </div>

              {verdict && (
                <div
                  className={cn(
                    "mt-3 flex items-start gap-2 rounded-[var(--r-sm)] p-2.5 text-xs",
                    verdict.ok
                      ? "bg-[color-mix(in_srgb,var(--success)_12%,transparent)] text-[var(--success)]"
                      : "bg-[color-mix(in_srgb,var(--warning)_12%,transparent)] text-[var(--warning)]",
                  )}
                >
                  {verdict.ok ? (
                    <BadgeCheck className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  ) : (
                    <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  )}
                  <span className="min-w-0 break-words">
                    {verdict.message}
                    {verdict.latency_ms > 0 && ` · ${verdict.latency_ms}ms`}
                  </span>
                </div>
              )}

              <div className="mt-4 flex flex-wrap items-center gap-2">
                <Button
                  variant="secondary"
                  size="sm"
                  loading={busy === "test"}
                  onClick={() => void test()}
                  disabled={!secret && !credential}
                >
                  <Eye className="h-4 w-4" />
                  Test connection
                </Button>
                <Button size="sm" loading={busy === "save"} onClick={() => void save()}>
                  <Save className="h-4 w-4" />
                  Save
                </Button>
                {credential && (
                  <>
                    <Button
                      variant="ghost"
                      size="sm"
                      loading={busy === "retest"}
                      onClick={() => void retest()}
                    >
                      <RefreshCw className="h-4 w-4" />
                      Re-test stored
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      loading={busy === "delete"}
                      onClick={() => void remove()}
                    >
                      <Trash2 className="h-4 w-4 text-[var(--danger)]" />
                    </Button>
                  </>
                )}
                <div className="min-w-0 flex-1" />
                {provider.docs_url && (
                  <a
                    href={provider.docs_url}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="inline-flex items-center gap-1 text-xs text-[var(--brand-500)] hover:underline"
                  >
                    <ExternalLink className="h-3 w-3" />
                    Get a key
                  </a>
                )}
              </div>

              {provider.slug === "atlas" && <AtlasControls onChanged={onChanged} />}
            </>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * Atlas needs more than a key: the CLI owns authorisation and carries its own
 * sandbox/production switch, so those live here beside the credential.
 */
function AtlasControls({ onChanged }: { onChanged: () => Promise<void> }) {
  const [status, setStatus] = useState<AtlasStatus | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setStatus(await api.get<AtlasStatus>("/flights/atlas/status"));
    } catch {
      setStatus(null);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const setEnvironment = async (environment: "sandbox" | "production") => {
    if (environment === "production") {
      const ok = await confirm({
        title: "Switch Atlas to production?",
        body: "Searches will return live fares and any purchase will charge your real Atlas balance and issue a real ticket. Atlas does not support refunds or cancellations through this flow.",
        confirmText: "Use production",
        tone: "danger",
      });
      if (!ok) return;
    }
    setBusy(environment);
    try {
      await api.post("/flights/atlas/environment", { environment });
      toast.success(
        `Atlas is now in ${environment}. Any offer from before the switch has expired — search again.`,
      );
      await refresh();
      await onChanged();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not switch environment");
    } finally {
      setBusy(null);
    }
  };

  const authorize = async () => {
    setBusy("auth");
    try {
      const result = await api.post<{ authorization_url?: string; message: string }>(
        "/flights/atlas/authorize",
      );
      if (result.authorization_url) {
        window.open(result.authorization_url, "_blank", "noopener");
        toast.info("Complete the authorisation in the new tab, then press Poll.");
      } else {
        toast.info(result.message);
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not start authorisation");
    } finally {
      setBusy(null);
    }
  };

  const poll = async () => {
    setBusy("poll");
    try {
      const result = await api.post<{ authorized: boolean; message: string }>(
        "/flights/atlas/authorize/poll",
      );
      toast[result.authorized ? "success" : "info"](result.message);
      await refresh();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Poll failed");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="mt-4 rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--surface)] p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold">Atlas CLI</span>
        {status && (
          <>
            <StatusPill
              status={status.installed ? (status.authorised ? "healthy" : "invalid") : "invalid"}
              detail={status.detail}
            />
            {status.environment && <Badge>{status.environment}</Badge>}
          </>
        )}
      </div>
      {status?.detail && (
        <p className="mt-1.5 text-[0.65rem] text-[var(--muted)]">{status.detail}</p>
      )}

      <div className="mt-3 flex flex-wrap gap-2">
        <Button
          variant="secondary"
          size="sm"
          loading={busy === "auth"}
          onClick={() => void authorize()}
        >
          Authorise in browser
        </Button>
        <Button variant="ghost" size="sm" loading={busy === "poll"} onClick={() => void poll()}>
          Poll
        </Button>
        <Button
          variant="ghost"
          size="sm"
          loading={busy === "sandbox"}
          onClick={() => void setEnvironment("sandbox")}
        >
          Use sandbox
        </Button>
        <Button
          variant="ghost"
          size="sm"
          loading={busy === "production"}
          onClick={() => void setEnvironment("production")}
        >
          Use production
        </Button>
      </div>
      <p className="mt-2 text-[0.65rem] text-[var(--muted)]">
        Sandbox is the safe default: it rehearses the whole booking flow against test
        data without creating a real booking or moving money.
      </p>
    </div>
  );
}
