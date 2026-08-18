import { useState, useEffect, useCallback } from "react";
import {
  Cpu,
  Plus,
  Trash2,
  Zap,
  ArrowUp,
  ArrowDown,
  CheckCircle2,
  XCircle,
  RefreshCw,
  Shield,
} from "lucide-react";
import { Button, Badge, Spinner } from "@/components/ui";
import { cn } from "@/lib/cn";
import { api } from "@/lib/api";
import { toast } from "sonner";

// --------------------------------------------------------------------------- //
// Types
// --------------------------------------------------------------------------- //

interface Provider {
  id: string;
  name: string;
  litellm_model: string;
  api_key: string; // masked by backend
  priority: number;
  enabled: boolean;
  max_rpm: number | null;
  created_at?: string;
  updated_at?: string;
}

interface UsageStat {
  name: string;
  litellm_model: string;
  total_calls: number;
  successful: number;
  tokens_in: number;
  tokens_out: number;
  avg_latency_ms: number;
}

interface TestResult {
  success: boolean;
  response?: string;
  error?: string;
  latency_ms: number;
  model: string;
}

// --------------------------------------------------------------------------- //
// Main Page
// --------------------------------------------------------------------------- //

export function EngineSettings() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [stats, setStats] = useState<UsageStat[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);

  const fetchProviders = useCallback(async () => {
    try {
      const data = await api.get<Provider[]>("/engine/providers");
      setProviders(data);
    } catch {
      toast.error("Failed to load providers");
    }
  }, []);

  const fetchStats = useCallback(async () => {
    try {
      const data = await api.get<UsageStat[]>("/engine/stats");
      setStats(data);
    } catch {
      // Stats may be empty if no DB — that's fine
    }
  }, []);

  useEffect(() => {
    Promise.all([fetchProviders(), fetchStats()]).finally(() => setLoading(false));
  }, [fetchProviders, fetchStats]);

  const handleDelete = async (id: string, name: string) => {
    if (!confirm(`Remove provider "${name}"?`)) return;
    try {
      await api.del(`/engine/providers/${id}`);
      toast.success(`${name} removed`);
      await fetchProviders();
    } catch {
      toast.error("Failed to delete provider");
    }
  };

  const handleToggle = async (provider: Provider) => {
    try {
      await api.patch(`/engine/providers/${provider.id}`, {
        enabled: !provider.enabled,
      });
      await fetchProviders();
    } catch {
      toast.error("Failed to toggle provider");
    }
  };

  const handleReorder = async (provider: Provider, direction: "up" | "down") => {
    const sorted = [...providers].sort((a, b) => a.priority - b.priority);
    const idx = sorted.findIndex((p) => p.id === provider.id);
    if (direction === "up" && idx === 0) return;
    if (direction === "down" && idx === sorted.length - 1) return;

    const swapIdx = direction === "up" ? idx - 1 : idx + 1;
    const swapProvider = sorted[swapIdx];

    try {
      await Promise.all([
        api.patch(`/engine/providers/${provider.id}`, { priority: swapProvider.priority }),
        api.patch(`/engine/providers/${swapProvider.id}`, { priority: provider.priority }),
      ]);
      await fetchProviders();
    } catch {
      toast.error("Failed to reorder");
    }
  };

  const handleSaved = () => {
    setShowForm(false);
    fetchProviders();
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Spinner className="h-8 w-8" />
      </div>
    );
  }

  const sorted = [...providers].sort((a, b) => a.priority - b.priority);
  const enabledProviders = sorted.filter((p) => p.enabled);

  return (
    <div className="max-w-4xl mx-auto space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-[family-name:var(--font-display)] text-2xl tracking-tight flex items-center gap-2">
            <Cpu className="h-6 w-6 text-[var(--brand-500)]" />
            LLM Engine
          </h1>
          <p className="text-sm text-[var(--muted)] mt-1">
            Manage your provider failover chain. The engine rotates through providers automatically.
          </p>
        </div>
        <Button onClick={() => setShowForm(!showForm)} size="sm">
          {showForm ? "Cancel" : <><Plus className="h-4 w-4" /> Add Provider</>}
        </Button>
      </div>

      {/* Failover Chain Visualization */}
      {enabledProviders.length > 0 && (
        <FailoverChain providers={enabledProviders} />
      )}

      {/* Add Provider Form */}
      {showForm && <ProviderForm onSaved={handleSaved} />}

      {/* Provider List */}
      <div className="space-y-3">
        <h2 className="text-sm font-medium text-[var(--muted)] uppercase tracking-wide">
          Providers ({providers.length})
        </h2>
        {sorted.length === 0 ? (
          <EmptyEngineState />
        ) : (
          sorted.map((p, idx) => (
            <ProviderCard
              key={p.id}
              provider={p}
              index={idx}
              total={sorted.length}
              onToggle={handleToggle}
              onDelete={handleDelete}
              onReorder={handleReorder}
            />
          ))
        )}
      </div>

      {/* Usage Stats */}
      {stats.length > 0 && <UsageStats stats={stats} onRefresh={fetchStats} />}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Failover Chain Visualization
// --------------------------------------------------------------------------- //

function FailoverChain({ providers }: { providers: Provider[] }) {
  return (
    <div className="rounded-[var(--r-lg)] border border-[var(--border)] bg-[var(--surface)] p-4">
      <h3 className="text-xs font-medium text-[var(--muted)] uppercase tracking-wide mb-3">
        Active Failover Chain
      </h3>
      <div className="flex items-center gap-2 flex-wrap">
        {providers.map((p, idx) => (
          <div key={p.id} className="flex items-center gap-2">
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-[var(--r-pill)] bg-[color-mix(in_srgb,var(--success)_10%,transparent)] border border-[color-mix(in_srgb,var(--success)_30%,transparent)]">
              <div className="h-2 w-2 rounded-full bg-[var(--success)]" />
              <span className="text-sm font-medium">{p.name}</span>
              <span className="text-xs text-[var(--muted)]">{p.litellm_model}</span>
            </div>
            {idx < providers.length - 1 && (
              <span className="text-[var(--muted)] text-lg">&rarr;</span>
            )}
          </div>
        ))}
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-[var(--r-pill)] bg-[color-mix(in_srgb,var(--muted)_10%,transparent)] border border-dashed border-[var(--border)]">
          <span className="text-sm text-[var(--muted)]">env fallback</span>
        </div>
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Provider Card
// --------------------------------------------------------------------------- //

function ProviderCard({
  provider,
  index,
  total,
  onToggle,
  onDelete,
  onReorder,
}: {
  provider: Provider;
  index: number;
  total: number;
  onToggle: (p: Provider) => void;
  onDelete: (id: string, name: string) => void;
  onReorder: (p: Provider, dir: "up" | "down") => void;
}) {
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<TestResult | null>(null);

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const result = await api.post<TestResult>(`/engine/test/${provider.id}`);
      setTestResult(result);
      if (result.success) {
        toast.success(`${provider.name}: ${result.latency_ms}ms`);
      } else {
        toast.error(`${provider.name}: ${result.error}`);
      }
    } catch {
      toast.error("Test request failed");
    } finally {
      setTesting(false);
    }
  };

  return (
    <div
      className={cn(
        "rounded-[var(--r-lg)] border bg-[var(--surface)] p-4 transition-colors",
        provider.enabled
          ? "border-[var(--border)]"
          : "border-dashed border-[var(--border)] opacity-60",
      )}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-medium">{provider.name}</span>
            <Badge variant={provider.enabled ? "success" : "default"}>
              {provider.enabled ? "Active" : "Disabled"}
            </Badge>
            <Badge variant="info">Priority {provider.priority}</Badge>
            {provider.max_rpm && (
              <Badge variant="warning">{provider.max_rpm} RPM</Badge>
            )}
          </div>
          <p className="text-sm text-[var(--muted)] mt-1 font-mono">
            {provider.litellm_model}
          </p>
          <p className="text-xs text-[var(--muted)] mt-0.5 font-mono">
            Key: {provider.api_key}
          </p>
        </div>

        <div className="flex items-center gap-1">
          {/* Reorder */}
          <button
            onClick={() => onReorder(provider, "up")}
            disabled={index === 0}
            className="p-1.5 rounded hover:bg-[color-mix(in_srgb,var(--brand-400)_10%,transparent)] disabled:opacity-30 transition"
            title="Move up (higher priority)"
          >
            <ArrowUp className="h-4 w-4" />
          </button>
          <button
            onClick={() => onReorder(provider, "down")}
            disabled={index === total - 1}
            className="p-1.5 rounded hover:bg-[color-mix(in_srgb,var(--brand-400)_10%,transparent)] disabled:opacity-30 transition"
            title="Move down (lower priority)"
          >
            <ArrowDown className="h-4 w-4" />
          </button>

          {/* Toggle */}
          <button
            onClick={() => onToggle(provider)}
            className={cn(
              "relative inline-flex h-5 w-9 items-center rounded-full transition-colors ml-2",
              provider.enabled ? "bg-[var(--success)]" : "bg-[var(--muted)]",
            )}
            title={provider.enabled ? "Disable" : "Enable"}
          >
            <span
              className={cn(
                "inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform",
                provider.enabled ? "translate-x-4.5" : "translate-x-0.5",
              )}
            />
          </button>

          {/* Test */}
          <button
            onClick={handleTest}
            disabled={testing}
            className="p-1.5 rounded hover:bg-[color-mix(in_srgb,var(--brand-400)_10%,transparent)] transition disabled:opacity-50"
            title="Test this provider"
          >
            {testing ? (
              <Spinner className="h-4 w-4" />
            ) : testResult ? (
              testResult.success ? (
                <CheckCircle2 className="h-4 w-4 text-[var(--success)]" />
              ) : (
                <XCircle className="h-4 w-4 text-[var(--danger)]" />
              )
            ) : (
              <Zap className="h-4 w-4" />
            )}
          </button>

          {/* Delete */}
          <button
            onClick={() => onDelete(provider.id, provider.name)}
            className="p-1.5 rounded hover:bg-[color-mix(in_srgb,var(--danger)_10%,transparent)] text-[var(--muted)] hover:text-[var(--danger)] transition"
            title="Remove provider"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Test result details */}
      {testResult && (
        <div
          className={cn(
            "mt-3 p-2.5 rounded-[var(--r-md)] text-xs font-mono",
            testResult.success
              ? "bg-[color-mix(in_srgb,var(--success)_8%,transparent)] text-[var(--success)]"
              : "bg-[color-mix(in_srgb,var(--danger)_8%,transparent)] text-[var(--danger)]",
          )}
        >
          {testResult.success
            ? `Response: "${testResult.response}" (${testResult.latency_ms}ms)`
            : `Error: ${testResult.error} (${testResult.latency_ms}ms)`}
        </div>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Add Provider Form
// --------------------------------------------------------------------------- //

function ProviderForm({ onSaved }: { onSaved: () => void }) {
  const [name, setName] = useState("");
  const [litellmModel, setLitellmModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [priority, setPriority] = useState(0);
  const [maxRpm, setMaxRpm] = useState("");
  const [saving, setSaving] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name || !litellmModel || !apiKey) {
      toast.error("Name, model, and API key are required");
      return;
    }
    setSaving(true);
    try {
      await api.post("/engine/providers", {
        name,
        litellm_model: litellmModel,
        api_key: apiKey,
        priority,
        enabled: true,
        max_rpm: maxRpm ? parseInt(maxRpm, 10) : null,
      });
      toast.success(`${name} added to chain`);
      onSaved();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to add provider");
    } finally {
      setSaving(false);
    }
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="rounded-[var(--r-lg)] border border-[var(--brand-400)]/30 bg-[var(--surface)] p-5 space-y-4"
    >
      <h3 className="text-sm font-medium flex items-center gap-2">
        <Shield className="h-4 w-4 text-[var(--brand-500)]" />
        Add Provider
      </h3>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Field label="Provider Name" hint='e.g. "Groq", "OpenRouter", "DashScope"'>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Groq"
            className="input-field"
          />
        </Field>
        <Field label="LiteLLM Model" hint='e.g. "groq/llama-3.3-70b-versatile"'>
          <input
            type="text"
            value={litellmModel}
            onChange={(e) => setLitellmModel(e.target.value)}
            placeholder="groq/llama-3.3-70b-versatile"
            className="input-field font-mono text-sm"
          />
        </Field>
        <Field label="API Key" hint="Stored server-side only">
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="gsk_..."
            className="input-field font-mono text-sm"
          />
        </Field>
        <Field label="Priority" hint="Lower = tried first (0 = primary)">
          <input
            type="number"
            value={priority}
            onChange={(e) => setPriority(parseInt(e.target.value, 10) || 0)}
            min={0}
            max={99}
            className="input-field"
          />
        </Field>
        <Field label="Max RPM (optional)" hint="Rate-limit guard">
          <input
            type="number"
            value={maxRpm}
            onChange={(e) => setMaxRpm(e.target.value)}
            placeholder="Unlimited"
            min={1}
            className="input-field"
          />
        </Field>
      </div>

      <div className="flex justify-end">
        <Button type="submit" size="sm" loading={saving}>
          <Plus className="h-4 w-4" /> Add to Chain
        </Button>
      </div>
    </form>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block space-y-1">
      <span className="text-xs font-medium text-[var(--muted)]">{label}</span>
      {children}
      {hint && <span className="text-xs text-[var(--muted)]/60">{hint}</span>}
    </label>
  );
}

// --------------------------------------------------------------------------- //
// Usage Stats
// --------------------------------------------------------------------------- //

function UsageStats({
  stats,
  onRefresh,
}: {
  stats: UsageStat[];
  onRefresh: () => void;
}) {
  return (
    <div className="rounded-[var(--r-lg)] border border-[var(--border)] bg-[var(--surface)] p-5">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-medium text-[var(--muted)] uppercase tracking-wide">
          Usage (7 days)
        </h2>
        <button
          onClick={onRefresh}
          className="p-1.5 rounded hover:bg-[color-mix(in_srgb,var(--brand-400)_10%,transparent)] transition"
        >
          <RefreshCw className="h-4 w-4 text-[var(--muted)]" />
        </button>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[var(--border)]">
              <th className="text-left py-2 px-2 text-[var(--muted)] font-medium">Provider</th>
              <th className="text-right py-2 px-2 text-[var(--muted)] font-medium">Calls</th>
              <th className="text-right py-2 px-2 text-[var(--muted)] font-medium">Success</th>
              <th className="text-right py-2 px-2 text-[var(--muted)] font-medium">Tokens In</th>
              <th className="text-right py-2 px-2 text-[var(--muted)] font-medium">Tokens Out</th>
              <th className="text-right py-2 px-2 text-[var(--muted)] font-medium">Avg Latency</th>
            </tr>
          </thead>
          <tbody>
            {stats.map((s, idx) => (
              <tr
                key={idx}
                className="border-b border-[var(--border)]/50 last:border-0"
              >
                <td className="py-2.5 px-2 font-medium">
                  {s.name || <span className="text-[var(--muted)]">env fallback</span>}
                </td>
                <td className="py-2.5 px-2 text-right font-mono">{s.total_calls}</td>
                <td className="py-2.5 px-2 text-right">
                  <span className="text-[var(--success)]">{s.successful}</span>
                  <span className="text-[var(--muted)]">/{s.total_calls}</span>
                </td>
                <td className="py-2.5 px-2 text-right font-mono">
                  {s.tokens_in.toLocaleString()}
                </td>
                <td className="py-2.5 px-2 text-right font-mono">
                  {s.tokens_out.toLocaleString()}
                </td>
                <td className="py-2.5 px-2 text-right font-mono">
                  {Math.round(s.avg_latency_ms)}ms
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Empty State
// --------------------------------------------------------------------------- //

function EmptyEngineState() {
  return (
    <div className="rounded-[var(--r-lg)] border border-dashed border-[var(--border)] p-8 text-center">
      <Cpu className="h-10 w-10 text-[var(--muted)] mx-auto mb-3" />
      <p className="text-[var(--muted)] text-sm">
        No providers configured yet.
      </p>
      <p className="text-[var(--muted)] text-xs mt-1">
        Add your API keys above to build the failover chain.
        The engine falls back to environment variables when no DB providers exist.
      </p>
    </div>
  );
}
