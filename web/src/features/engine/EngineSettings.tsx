import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  ArrowDown,
  ArrowUp,
  BadgeCheck,
  Cpu,
  ExternalLink,
  Info,
  Plus,
  RefreshCw,
  RotateCcw,
  Save,
  Trash2,
  Zap,
} from "@/components/ui/icons";
import { toast } from "sonner";
import * as Dialog from "@radix-ui/react-dialog";
import {
  Badge,
  Button,
  EmptyState,
  NumberField,
  Select,
  Skeleton,
  confirm,
} from "@/components/ui";
import type { SelectGroup } from "@/components/ui";
import { StatusPill } from "@/components/ui/SourceBadge";
import { cn } from "@/lib/cn";
import { api, ApiError } from "@/lib/api";
import type {
  DiscoveredModel,
  EngineCatalogue,
  EngineStat,
  LlmProvider,
  ProbeVerdict,
  ProviderPreset,
} from "@/lib/types";

/**
 * Engine — the AI model rotation pool.
 *
 * The pool is walked in priority order; a `429` rests a key briefly, a `401`
 * marks it invalid so it stops being tried, and when every cloud key is spent the
 * gateway falls back to local Ollama. That behaviour is only trustworthy if the
 * operator can see it, so this page shows real health and real usage.
 *
 * Quota bars are **locally metered**: no provider publishes a usable
 * "remaining quota", so Journava counts calls against ceilings you set. The page
 * says so rather than implying the numbers come from the provider.
 */

export function EngineSettings() {
  const [providers, setProviders] = useState<LlmProvider[] | null>(null);
  const [catalogue, setCatalogue] = useState<EngineCatalogue | null>(null);
  const [stats, setStats] = useState<EngineStat[]>([]);
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<LlmProvider | null>(null);

  const load = useCallback(async () => {
    const [providerList, cat, stat] = await Promise.all([
      api.get<LlmProvider[]>("/engine/providers").catch(() => []),
      api.get<EngineCatalogue>("/engine/catalogue").catch(() => null),
      api.get<EngineStat[]>("/engine/stats").catch(() => []),
    ]);
    setProviders(providerList);
    setCatalogue(cat);
    setStats(stat);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const move = async (index: number, direction: -1 | 1) => {
    if (!providers) return;
    const next = [...providers];
    const target = index + direction;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    setProviders(next);
    try {
      await api.post("/engine/providers/reorder", {
        ordered_ids: next.map((provider) => provider.id),
      });
    } catch {
      toast.error("Could not save the new order.");
      await load();
    }
  };

  const healthy = providers?.filter((p) => p.status === "healthy").length ?? 0;
  const usable =
    providers?.filter((p) => p.enabled && p.status !== "invalid" && !p.cooling_down)
      .length ?? 0;

  if (providers === null) {
    return (
      <div className="mx-auto w-full max-w-4xl space-y-4">
        <Skeleton className="h-10 w-48" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-32 w-full" />
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-4xl">
      <header className="pt-2 pb-5">
        <h2 className="flex items-center gap-2 font-[family-name:var(--font-display)] text-2xl tracking-tight">
          <Cpu className="h-6 w-6 text-[var(--brand-500)]" />
          Engine
        </h2>
        <p className="mt-1 text-sm text-[var(--muted)]">
          Your AI model pool. Keys are tried in order, rested when rate-limited,
          and skipped once a provider rejects them. Add as many as you like.
        </p>
      </header>

      {providers.length === 0 ? (
        <EmptyState
          icon={<Zap className="h-10 w-10" />}
          title="No models configured"
          description="Journava falls back to placeholder data without one. Add a provider — most have a free tier."
          action={<Button onClick={() => setAdding(true)}>Add your first model</Button>}
        />
      ) : (
        <>
          <div className="mb-4 grid grid-cols-3 gap-3">
            <Stat label="In pool" value={providers.length} />
            <Stat label="Healthy" value={healthy} tone="success" />
            <Stat label="Usable now" value={usable} tone="brand" />
          </div>

          <div className="mb-3 flex items-center justify-between">
            <p className="text-sm font-semibold">Rotation order</p>
            <Button variant="ghost" size="sm" onClick={() => void load()}>
              <RefreshCw className="h-4 w-4" />
              Refresh
            </Button>
          </div>

          <div className="space-y-2">
            {providers.map((provider, index) => (
              <ProviderRow
                key={provider.id}
                provider={provider}
                index={index}
                isFirst={index === 0}
                isLast={index === providers.length - 1}
                onMove={move}
                onChanged={load}
                onEdit={() => setEditing(provider)}
              />
            ))}
          </div>
        </>
      )}

      {catalogue?.ollama_fallback && (
        <div className="mt-4 flex items-start gap-2 rounded-[var(--r-md)] border border-dashed border-[var(--border)] p-3">
          <Info className="mt-0.5 h-4 w-4 shrink-0 text-[var(--muted)]" />
          <div className="text-xs">
            <p className="font-medium">
              Last resort: {catalogue.ollama_fallback.model}
              {catalogue.ollama_fallback.enabled ? "" : " (disabled)"}
            </p>
            <p className="mt-0.5 text-[var(--muted)]">
              {catalogue.ollama_fallback.note}
            </p>
          </div>
        </div>
      )}

      {!adding && !editing && providers.length > 0 && (
        <Button className="mt-4" variant="secondary" onClick={() => setAdding(true)}>
          <Plus className="h-4 w-4" />
          Add another model
        </Button>
      )}

      <Dialog.Root
        open={(adding || Boolean(editing)) && Boolean(catalogue)}
        onOpenChange={(open) => {
          if (!open) {
            setAdding(false);
            setEditing(null);
          }
        }}
      >
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-[70] bg-black/45 backdrop-blur-sm" />
          <Dialog.Content
            className={cn(
              "fixed left-1/2 top-1/2 z-[71] w-[min(40rem,92vw)] max-h-[85dvh]",
              "-translate-x-1/2 -translate-y-1/2 overflow-y-auto",
            )}
          >
            <Dialog.Title className="sr-only">
              {editing ? `Edit ${editing.name}` : "Add a model"}
            </Dialog.Title>
            <Dialog.Description className="sr-only">
              Add or edit an AI model provider in the rotation pool.
            </Dialog.Description>
            {catalogue && (
              <ProviderForm
                presets={catalogue.presets}
                editing={editing}
                onDone={async () => {
                  setAdding(false);
                  setEditing(null);
                  await load();
                }}
                onCancel={() => {
                  setAdding(false);
                  setEditing(null);
                }}
              />
            )}
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>

      {stats.length > 0 && <UsageTable stats={stats} />}
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
  tone?: "success" | "brand";
}) {
  return (
    <div className="surface-card p-3 text-center">
      <p
        className={cn(
          "text-xl font-semibold tabular-nums",
          tone === "success" && "text-[var(--success)]",
          tone === "brand" && "text-[var(--brand-500)]",
        )}
      >
        {value}
      </p>
      <p className="text-[0.65rem] text-[var(--muted)]">{label}</p>
    </div>
  );
}

function ProviderRow({
  provider,
  index,
  isFirst,
  isLast,
  onMove,
  onChanged,
  onEdit,
}: {
  provider: LlmProvider;
  index: number;
  isFirst: boolean;
  isLast: boolean;
  onMove: (index: number, direction: -1 | 1) => Promise<void>;
  onChanged: () => Promise<void>;
  onEdit: () => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);

  const act = async (key: string, fn: () => Promise<unknown>, success?: string) => {
    setBusy(key);
    try {
      await fn();
      if (success) toast.success(success);
      await onChanged();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Action failed");
    } finally {
      setBusy(null);
    }
  };

  const test = () =>
    act("test", async () => {
      const verdict = await api.post<ProbeVerdict>(
        `/engine/providers/${provider.id}/test`,
      );
      toast[verdict.ok ? "success" : "warning"](
        `${provider.name}: ${verdict.message}`,
      );
    });

  const remove = async () => {
    const ok = await confirm({
      title: `Remove ${provider.name}?`,
      body: "The pool will rotate to the remaining providers.",
      confirmText: "Remove",
      tone: "danger",
    });
    if (!ok) return;
    await act("delete", () => api.del(`/engine/providers/${provider.id}`), "Removed.");
  };

  return (
    <div
      className={cn(
        "surface-card p-3",
        provider.status === "invalid" && "border-[var(--danger)]/40",
        !provider.enabled && "opacity-60",
      )}
    >
      <div className="flex items-start gap-3">
        <div className="flex shrink-0 flex-col">
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6"
            aria-label="Move up"
            disabled={isFirst}
            onClick={() => void onMove(index, -1)}
          >
            <ArrowUp className="h-3.5 w-3.5" />
          </Button>
          <span className="text-center text-[0.6rem] text-[var(--muted)]">{index + 1}</span>
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6"
            aria-label="Move down"
            disabled={isLast}
            onClick={() => void onMove(index, 1)}
          >
            <ArrowDown className="h-3.5 w-3.5" />
          </Button>
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold">{provider.name}</span>
            <StatusPill status={provider.status} detail={provider.status_detail} />
            {provider.cooling_down && <Badge variant="warning">cooling down</Badge>}
            {!provider.enabled && <Badge>disabled</Badge>}
          </div>
          <p className="mt-0.5 font-[family-name:var(--font-mono)] text-[0.65rem] text-[var(--muted)]">
            {provider.litellm_model} · {provider.masked_key || "no key"}
          </p>
          {provider.status_detail && provider.status !== "healthy" && (
            <p className="mt-1 break-words text-[0.65rem] text-[var(--warning)]">
              {provider.status_detail}
            </p>
          )}
          {provider.usage && <QuotaBars usage={provider.usage} />}
        </div>

        <div className="flex shrink-0 items-center gap-1">
          <Button
            variant="ghost"
            size="sm"
            loading={busy === "test"}
            onClick={() => void test()}
          >
            Test
          </Button>
          <Button variant="ghost" size="icon" aria-label="Edit" onClick={onEdit}>
            <Save className="h-4 w-4" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            aria-label="Reset usage"
            loading={busy === "reset"}
            onClick={() =>
              void act(
                "reset",
                () => api.post(`/engine/providers/${provider.id}/reset`),
                "Status and usage cleared.",
              )
            }
          >
            <RotateCcw className="h-4 w-4" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            aria-label="Remove"
            loading={busy === "delete"}
            onClick={() => void remove()}
          >
            <Trash2 className="h-4 w-4 text-[var(--danger)]" />
          </Button>
        </div>
      </div>
    </div>
  );
}

function QuotaBars({ usage }: { usage: NonNullable<LlmProvider["usage"]> }) {
  const rows: Array<{ key: "rpm" | "rpd" | "tpd"; label: string }> = [
    { key: "rpm", label: "req/min" },
    { key: "rpd", label: "req/day" },
    { key: "tpd", label: "tokens/day" },
  ];
  const configured = rows.filter((row) => usage.limits[row.key]);
  if (configured.length === 0) {
    return (
      <p className="mt-1.5 text-[0.6rem] text-[var(--muted)]">
        No quota ceilings set — usage is not capped.
      </p>
    );
  }

  return (
    <div className="mt-2 space-y-1">
      {configured.map(({ key, label }) => {
        const limit = usage.limits[key] ?? 0;
        const count = usage.counts[key] ?? 0;
        const pct = limit > 0 ? Math.min(100, Math.round((count / limit) * 100)) : 0;
        return (
          <div key={key} className="flex items-center gap-2">
            <span className="w-16 shrink-0 text-[0.6rem] text-[var(--muted)]">{label}</span>
            <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-[var(--border)]">
              <span
                className="block h-full rounded-full transition-all"
                style={{
                  width: `${pct}%`,
                  backgroundColor:
                    pct >= 90
                      ? "var(--danger)"
                      : pct >= 70
                        ? "var(--warning)"
                        : "var(--brand-500)",
                }}
              />
            </span>
            <span className="w-20 shrink-0 text-right text-[0.6rem] tabular-nums text-[var(--muted)]">
              {count.toLocaleString()}/{limit.toLocaleString()}
            </span>
          </div>
        );
      })}
      <p className="text-[0.55rem] italic text-[var(--muted)]" title={usage.note}>
        Counted by Journava, not the provider
      </p>
    </div>
  );
}

function ProviderForm({
  presets,
  editing,
  onDone,
  onCancel,
}: {
  presets: ProviderPreset[];
  editing: LlmProvider | null;
  onDone: () => Promise<void>;
  onCancel: () => void;
}) {
  const [name, setName] = useState(editing?.name ?? "");
  const [model, setModel] = useState(editing?.litellm_model ?? "");
  const [apiKey, setApiKey] = useState("");
  const [maxRpm, setMaxRpm] = useState<number | null>(editing?.max_rpm ?? null);
  const [maxRpd, setMaxRpd] = useState<number | null>(editing?.max_rpd ?? null);
  const [preset, setPreset] = useState("");
  const [verdict, setVerdict] = useState<ProbeVerdict | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  /** Models the provider itself reported, once a key is available. */
  const [liveModels, setLiveModels] = useState<DiscoveredModel[] | null>(null);
  const [liveProvider, setLiveProvider] = useState<string | null>(null);

  const groups: SelectGroup[] = useMemo(() => {
    // A live listing outranks the presets: presets go stale the moment a provider
    // retires a model, and the resulting `model_not_found` looks like a bad key.
    if (liveModels && liveModels.length > 0) {
      return [
        {
          label: `✅ ${liveProvider} — live from the provider (${liveModels.length})`,
          options: liveModels.map((m) => ({
            value: m.value,
            label: m.context
              ? `${m.label} · ${Math.round(m.context / 1000)}k ctx`
              : m.label,
          })),
        },
        { label: "Other", options: [{ value: "__custom", label: "✏️ Custom model" }] },
      ];
    }
    return [
      ...presets.map((entry) => ({
        label: `${entry.icon} ${entry.name}${entry.free_tier ? " · free tier" : ""}`,
        options: entry.models.map((m) => ({
          value: m.value,
          label: m.tag ? `${m.label} (${m.tag})` : m.label,
        })),
      })),
      {
        label: "Other",
        options: [{ value: "__custom", label: "✏️ Custom model" }],
      },
    ];
  }, [presets, liveModels, liveProvider]);

  const activePreset = presets.find((entry) =>
    entry.models.some((m) => m.value === model),
  );

  const choosePreset = (value: string) => {
    setPreset(value);
    setVerdict(null);
    if (value === "__custom") {
      setModel("");
      return;
    }
    setModel(value);
    const owner = presets.find((entry) => entry.models.some((m) => m.value === value));
    if (owner) {
      if (!name || !editing) setName(owner.name);
      if (owner.suggested?.max_rpm) setMaxRpm(owner.suggested.max_rpm);
      if (owner.suggested?.max_rpd) setMaxRpd(owner.suggested.max_rpd);
    }
  };

  /** The provider slug implied by the model string, e.g. `groq/x` → `groq`. */
  const providerSlug = model.includes("/")
    ? model.split("/")[0]
    : (activePreset?.provider ?? "");

  const loadLiveModels = async () => {
    if (!providerSlug) {
      toast.error("Pick a provider first — or type a model id like groq/gpt-oss-120b.");
      return;
    }
    setBusy("models");
    try {
      const result = await api.post<{ models: DiscoveredModel[]; count: number }>(
        "/engine/models",
        { provider: providerSlug, api_key: apiKey || null },
      );
      if (result.count === 0) {
        toast.warning(`${providerSlug} returned no chat models.`);
        return;
      }
      setLiveModels(result.models);
      setLiveProvider(providerSlug);
      toast.success(`${result.count} live model(s) from ${providerSlug}.`);
      // Selecting a retired model is the whole failure mode this fixes, so if the
      // current choice is not in the live list, clear it.
      if (model && !result.models.some((m) => m.value === model)) {
        setModel("");
        setPreset("");
        toast.info("Your previous model is not on that list — pick one from it.");
      }
    } catch (error) {
      const message =
        error instanceof ApiError ? error.detail : "Could not list models";
      toast.error(message);
    } finally {
      setBusy(null);
    }
  };

  const test = async () => {
    if (!model || !apiKey) {
      toast.error("Pick a model and paste a key first.");
      return;
    }
    setBusy("test");
    try {
      const result = await api.post<ProbeVerdict>("/engine/test", {
        litellm_model: model,
        api_key: apiKey,
      });
      setVerdict(result);
      toast[result.ok ? "success" : "warning"](result.message);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Test failed");
    } finally {
      setBusy(null);
    }
  };

  const save = async () => {
    if (!name || !model) {
      toast.error("Name and model are required.");
      return;
    }
    if (!editing && !apiKey) {
      toast.error("A key is required.");
      return;
    }
    setBusy("save");
    try {
      const body: Record<string, unknown> = {
        name,
        litellm_model: model,
        max_rpm: maxRpm,
        max_rpd: maxRpd,
      };
      if (apiKey) body.api_key = apiKey;

      if (editing) {
        await api.patch(`/engine/providers/${editing.id}`, body);
      } else {
        // The backend tests the key and refuses to store one that fails, so a
        // broken provider never silently joins the rotation.
        await api.post("/engine/providers", { ...body, require_test: true });
      }
      toast.success(editing ? `${name} updated.` : `${name} added to the pool.`);
      await onDone();
    } catch (error) {
      const message =
        error instanceof ApiError ? error.detail : "Could not save the provider";
      toast.error(message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
      className="rounded-[var(--r-lg)] border border-[var(--brand-400)]/30 bg-[var(--surface)] p-5"
    >
      <h3 className="text-sm font-semibold">
        {editing ? `Edit ${editing.name}` : "Add a model"}
      </h3>

      <div className="mt-4 space-y-4">
        {!editing && (
          <label className="block">
            <span className="mb-1 flex flex-wrap items-center gap-2 text-xs font-medium">
              Quick pick
              <span className="font-normal text-[var(--muted)]">
                — or type a custom model below
              </span>
              {liveModels && (
                <Badge variant="success" title={`Listed by ${liveProvider} just now`}>
                  live list
                </Badge>
              )}
            </span>
            <Select
              value={preset}
              onValueChange={choosePreset}
              placeholder="Choose a provider and model"
              aria-label="Model preset"
              groups={groups}
            />
            <button
              type="button"
              onClick={() => void loadLiveModels()}
              disabled={busy === "models" || !providerSlug}
              className="mt-1.5 inline-flex items-center gap-1 text-[0.65rem] font-medium text-[var(--brand-500)] hover:underline disabled:opacity-50"
              title="Ask the provider which models it will serve right now"
            >
              <RefreshCw
                className={cn("h-3 w-3", busy === "models" && "animate-spin")}
              />
              {liveModels ? "Reload live models" : "Load live models from provider"}
            </button>
            <span className="mt-1 block text-[0.6rem] text-[var(--muted)]">
              Presets can go stale when a provider retires a model — the live list is
              authoritative.
            </span>
          </label>
        )}

        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block">
            <span className="mb-1 block text-xs font-medium">Display name</span>
            <input
              className="input-field"
              placeholder="e.g. Groq"
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium">LiteLLM model</span>
            <input
              className="input-field font-[family-name:var(--font-mono)]"
              placeholder="provider/model-name"
              value={model}
              onChange={(event) => {
                setModel(event.target.value);
                setVerdict(null);
              }}
            />
          </label>
        </div>

        <label className="block">
          <span className="mb-1 block text-xs font-medium">
            API key {editing && <span className="font-normal text-[var(--muted)]">(leave empty to keep the current one)</span>}
          </span>
          <input
            type="password"
            autoComplete="off"
            className="input-field font-[family-name:var(--font-mono)]"
            placeholder={editing ? "Unchanged" : "Paste the key"}
            value={apiKey}
            onChange={(event) => {
              setApiKey(event.target.value);
              setVerdict(null);
            }}
          />
          {activePreset?.signup_url && (
            <a
              href={activePreset.signup_url}
              target="_blank"
              rel="noreferrer noopener"
              className="mt-1 inline-flex items-center gap-1 text-[0.65rem] text-[var(--brand-500)] hover:underline"
            >
              <ExternalLink className="h-3 w-3" />
              Get a {activePreset.name} key
            </a>
          )}
        </label>

        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block">
            <span className="mb-1 block text-xs font-medium">
              Max requests / minute
            </span>
            <NumberField
              min={0}
              placeholder="optional"
              value={maxRpm}
              onValueChange={setMaxRpm}
              aria-label="Max requests per minute"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium">Max requests / day</span>
            <NumberField
              min={0}
              placeholder="optional"
              value={maxRpd}
              onValueChange={setMaxRpd}
              aria-label="Max requests per day"
            />
          </label>
        </div>

        {activePreset?.note && (
          <p className="flex items-start gap-2 text-[0.65rem] text-[var(--muted)]">
            <Info className="mt-0.5 h-3 w-3 shrink-0" />
            {activePreset.note}
          </p>
        )}

        {verdict && (
          <div
            className={cn(
              "flex items-start gap-2 rounded-[var(--r-sm)] p-2.5 text-xs",
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
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-2">
        <Button
          type="button"
          variant="secondary"
          loading={busy === "test"}
          onClick={() => void test()}
          disabled={!model || !apiKey}
        >
          <Zap className="h-4 w-4" />
          Test connection
        </Button>
        <Button type="submit" loading={busy === "save"}>
          <Save className="h-4 w-4" />
          {editing ? "Save changes" : "Add to pool"}
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
      {!editing && (
        <p className="mt-2 text-[0.65rem] text-[var(--muted)]">
          The key is verified before it is stored, so a bad key fails here rather
          than during a trip plan.
        </p>
      )}
    </form>
  );
}

function UsageTable({ stats }: { stats: EngineStat[] }) {
  return (
    <section className="mt-8">
      <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold">
        <Activity className="h-4 w-4 text-[var(--brand-500)]" />
        Usage — last 7 days
      </h3>
      <div className="surface-card overflow-x-auto">
        <table className="w-full min-w-[34rem] text-xs">
          <thead>
            <tr className="border-b border-[var(--border)] text-left text-[var(--muted)]">
              <th className="p-3 font-medium">Model</th>
              <th className="p-3 text-right font-medium">Calls</th>
              <th className="p-3 text-right font-medium">Failed</th>
              <th className="p-3 text-right font-medium">Tokens</th>
              <th className="p-3 text-right font-medium">Avg latency</th>
            </tr>
          </thead>
          <tbody>
            {stats.map((row) => (
              <tr key={row.model} className="border-b border-[var(--border)] last:border-0">
                <td className="p-3 font-[family-name:var(--font-mono)]">{row.model}</td>
                <td className="p-3 text-right tabular-nums">{row.calls}</td>
                <td
                  className={cn(
                    "p-3 text-right tabular-nums",
                    row.failed > 0 && "text-[var(--danger)]",
                  )}
                >
                  {row.failed}
                </td>
                <td className="p-3 text-right tabular-nums">
                  {(row.tokens_in + row.tokens_out).toLocaleString()}
                </td>
                <td className="p-3 text-right tabular-nums">
                  {row.avg_latency_ms ? `${row.avg_latency_ms}ms` : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
