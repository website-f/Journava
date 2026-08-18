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
  Pencil,
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
// Model Presets — pick a provider, then pick a model
// --------------------------------------------------------------------------- //

interface ModelPreset {
  label: string;
  value: string;
  tag?: string;
}

interface ProviderPreset {
  name: string;
  icon: string;
  models: ModelPreset[];
  suggestedRpm?: number;
}

const PROVIDER_PRESETS: ProviderPreset[] = [
  {
    name: "DashScope (Qwen)",
    icon: "🟠",
    suggestedRpm: 30,
    models: [
      { label: "Qwen Plus", value: "dashscope/qwen-plus", tag: "recommended" },
      { label: "Qwen Turbo", value: "dashscope/qwen-turbo", tag: "fast" },
      { label: "Qwen Max", value: "dashscope/qwen-max" },
      { label: "Qwen Long", value: "dashscope/qwen-long", tag: "128k ctx" },
      { label: "Qwen VL Plus", value: "dashscope/qwen-vl-plus", tag: "vision" },
    ],
  },
  {
    name: "Groq",
    icon: "⚡",
    suggestedRpm: 30,
    models: [
      { label: "Llama 3.3 70B", value: "groq/llama-3.3-70b-versatile", tag: "recommended" },
      { label: "Llama 3.1 8B", value: "groq/llama-3.1-8b-instant", tag: "fast" },
      { label: "Llama 3 70B", value: "groq/llama3-70b-8192" },
      { label: "Mixtral 8x7B", value: "groq/mixtral-8x7b-32768" },
      { label: "Gemma 2 9B", value: "groq/gemma2-9b-it" },
    ],
  },
  {
    name: "Google Gemini",
    icon: "🔵",
    suggestedRpm: 15,
    models: [
      { label: "Gemini 2.0 Flash", value: "gemini/gemini-2.0-flash", tag: "recommended" },
      { label: "Gemini 1.5 Flash", value: "gemini/gemini-1.5-flash", tag: "fast" },
      { label: "Gemini 1.5 Pro", value: "gemini/gemini-1.5-pro" },
    ],
  },
  {
    name: "OpenRouter",
    icon: "🟢",
    models: [
      { label: "Llama 3.1 8B (free)", value: "openrouter/meta-llama/llama-3.1-8b-instruct:free", tag: "free" },
      { label: "Qwen 2 72B (free)", value: "openrouter/qwen/qwen-2-72b-instruct:free", tag: "free" },
      { label: "Mistral 7B (free)", value: "openrouter/mistralai/mistral-7b-instruct:free", tag: "free" },
      { label: "Llama 3.3 70B", value: "openrouter/meta-llama/llama-3.3-70b-instruct" },
      { label: "DeepSeek V3", value: "openrouter/deepseek/deepseek-chat" },
    ],
  },
  {
    name: "DeepSeek",
    icon: "🟣",
    suggestedRpm: 20,
    models: [
      { label: "DeepSeek Chat (V3)", value: "deepseek/deepseek-chat", tag: "recommended" },
      { label: "DeepSeek Coder", value: "deepseek/deepseek-coder" },
      { label: "DeepSeek Reasoner (R1)", value: "deepseek/deepseek-reasoner", tag: "thinking" },
    ],
  },
  {
    name: "Cerebras",
    icon: "🔴",
    suggestedRpm: 30,
    models: [
      { label: "Llama 3.3 70B", value: "cerebras/llama3.3-70b", tag: "recommended" },
      { label: "Llama 3.1 8B", value: "cerebras/llama3.1-8b", tag: "fast" },
    ],
  },
  {
    name: "OpenAI",
    icon: "⚫",
    models: [
      { label: "GPT-4o mini", value: "openai/gpt-4o-mini", tag: "fast" },
      { label: "GPT-4o", value: "openai/gpt-4o" },
      { label: "GPT-4.1", value: "openai/gpt-4.1" },
    ],
  },
  {
    name: "Mistral",
    icon: "🟤",
    models: [
      { label: "Mistral Large", value: "mistral/mistral-large-latest" },
      { label: "Mistral Small", value: "mistral/mistral-small-latest", tag: "fast" },
      { label: "Codestral", value: "mistral/codestral-latest", tag: "code" },
    ],
  },
];

/** All models flattened for the dropdown */
const ALL_MODEL_OPTIONS = PROVIDER_PRESETS.flatMap((p) =>
  p.models.map((m) => ({
    label: `${p.icon} ${p.name} — ${m.label}`,
    value: m.value,
    tag: m.tag,
    providerName: p.name,
    suggestedRpm: p.suggestedRpm,
  }))
);

// --------------------------------------------------------------------------- //
// Main Page
// --------------------------------------------------------------------------- //

export function EngineSettings() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [stats, setStats] = useState<UsageStat[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editingProvider, setEditingProvider] = useState<Provider | null>(null);

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
    setEditingProvider(null);
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
            Manage your provider failover chain. The engine rotates through providers on failure.
          </p>
        </div>
        <Button onClick={() => { setShowForm(!showForm); setEditingProvider(null); }} size="sm">
          {showForm ? "Cancel" : <><Plus className="h-4 w-4" /> Add Provider</>}
        </Button>
      </div>

      {/* Failover Chain Visualization */}
      {enabledProviders.length > 0 && (
        <FailoverChain providers={enabledProviders} />
      )}

      {/* Add / Edit Provider Form */}
      {(showForm || editingProvider) && (
        <ProviderForm
          onSaved={handleSaved}
          editing={editingProvider}
          onCancel={() => { setShowForm(false); setEditingProvider(null); }}
        />
      )}

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
              onEdit={(provider) => { setEditingProvider(provider); setShowForm(false); }}
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
  onEdit,
}: {
  provider: Provider;
  index: number;
  total: number;
  onToggle: (p: Provider) => void;
  onDelete: (id: string, name: string) => void;
  onReorder: (p: Provider, dir: "up" | "down") => void;
  onEdit: (p: Provider) => void;
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
        toast.error(`${provider.name}: ${result.error?.slice(0, 80)}`);
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
            <Badge variant="info">P{provider.priority}</Badge>
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
          <button
            onClick={() => onReorder(provider, "up")}
            disabled={index === 0}
            className="p-1.5 rounded hover:bg-[color-mix(in_srgb,var(--brand-400)_10%,transparent)] disabled:opacity-30 transition"
            title="Move up"
          >
            <ArrowUp className="h-4 w-4" />
          </button>
          <button
            onClick={() => onReorder(provider, "down")}
            disabled={index === total - 1}
            className="p-1.5 rounded hover:bg-[color-mix(in_srgb,var(--brand-400)_10%,transparent)] disabled:opacity-30 transition"
            title="Move down"
          >
            <ArrowDown className="h-4 w-4" />
          </button>

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

          <button
            onClick={handleTest}
            disabled={testing}
            className="p-1.5 rounded hover:bg-[color-mix(in_srgb,var(--brand-400)_10%,transparent)] transition disabled:opacity-50"
            title="Test connection"
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

          <button
            onClick={() => onEdit(provider)}
            className="p-1.5 rounded hover:bg-[color-mix(in_srgb,var(--brand-400)_10%,transparent)] transition"
            title="Edit provider"
          >
            <Pencil className="h-4 w-4" />
          </button>

          <button
            onClick={() => onDelete(provider.id, provider.name)}
            className="p-1.5 rounded hover:bg-[color-mix(in_srgb,var(--danger)_10%,transparent)] text-[var(--muted)] hover:text-[var(--danger)] transition"
            title="Remove provider"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </div>

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
// Add / Edit Provider Form
// --------------------------------------------------------------------------- //

function ProviderForm({
  onSaved,
  editing,
  onCancel,
}: {
  onSaved: () => void;
  editing: Provider | null;
  onCancel: () => void;
}) {
  const [name, setName] = useState(editing?.name ?? "");
  const [litellmModel, setLitellmModel] = useState(editing?.litellm_model ?? "");
  const [apiKey, setApiKey] = useState("");
  const [priority, setPriority] = useState(editing?.priority ?? 0);
  const [maxRpm, setMaxRpm] = useState(editing?.max_rpm?.toString() ?? "");
  const [saving, setSaving] = useState(false);
  const [selectedPreset, setSelectedPreset] = useState("");

  const handlePresetChange = (value: string) => {
    setSelectedPreset(value);
    if (!value) return;
    // Find the preset and auto-fill
    const option = ALL_MODEL_OPTIONS.find((o) => o.value === value);
    if (option) {
      setLitellmModel(option.value);
      // Auto-fill provider name from preset (strip parenthetical)
      setName(option.providerName.replace(/ \(.*\)/, ""));
      if (option.suggestedRpm && !maxRpm) {
        setMaxRpm(option.suggestedRpm.toString());
      }
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name || !litellmModel) {
      toast.error("Name and model are required");
      return;
    }
    if (!editing && !apiKey) {
      toast.error("API key is required for new providers");
      return;
    }
    setSaving(true);
    try {
      const payload: Record<string, unknown> = {
        name,
        litellm_model: litellmModel,
        priority,
        enabled: true,
        max_rpm: maxRpm ? parseInt(maxRpm, 10) : null,
      };
      if (apiKey) payload.api_key = apiKey; // only send if provided (for edit)

      if (editing) {
        await api.patch(`/engine/providers/${editing.id}`, payload);
        toast.success(`${name} updated`);
      } else {
        await api.post("/engine/providers", payload);
        toast.success(`${name} added to chain`);
      }
      onSaved();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save provider");
    } finally {
      setSaving(false);
    }
  };

  const isEditing = editing !== null;

  return (
    <form
      onSubmit={handleSubmit}
      className="rounded-[var(--r-lg)] border border-[var(--brand-400)]/30 bg-[var(--surface)] p-5 space-y-4"
    >
      <h3 className="text-sm font-medium flex items-center gap-2">
        <Shield className="h-4 w-4 text-[var(--brand-500)]" />
        {isEditing ? "Edit Provider" : "Add Provider"}
      </h3>

      {/* Model Preset Picker */}
      {!isEditing && (
        <Field label="Quick Pick — choose a provider + model" hint="Or type a custom model below">
          <select
            value={selectedPreset}
            onChange={(e) => handlePresetChange(e.target.value)}
            className="input-field"
          >
            <option value="">— Select a preset —</option>
            {PROVIDER_PRESETS.map((p) => (
              <optgroup key={p.name} label={`${p.icon} ${p.name}`}>
                {p.models.map((m) => (
                  <option key={m.value} value={m.value}>
                    {m.label}{m.tag ? ` (${m.tag})` : ""}
                  </option>
                ))}
              </optgroup>
            ))}
            <option value="__custom">✏️ Custom model (type below)</option>
          </select>
        </Field>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Field label="Provider Name" hint='e.g. "Groq", "DashScope"'>
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
        <Field
          label={isEditing ? "API Key (leave blank to keep current)" : "API Key"}
          hint="Stored server-side only"
        >
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder={isEditing ? "•••• unchanged ••••" : "gsk_..."}
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

      <div className="flex justify-end gap-2">
        <Button type="button" variant="secondary" size="sm" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" size="sm" loading={saving}>
          <Plus className="h-4 w-4" /> {isEditing ? "Save Changes" : "Add to Chain"}
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
        Click <strong>Add Provider</strong> and pick a preset to get started.
        The engine falls back to environment variables when no DB providers exist.
      </p>
    </div>
  );
}
