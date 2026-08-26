import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Sparkles, Plus, Trash2, Loader2, X, Compass, ArrowRight } from "@/components/ui/icons";
import { Button, Skeleton } from "@/components/ui";
import { cn } from "@/lib/cn";
import { api } from "@/lib/api";

type Agent = {
  id: string;
  name: string;
  role: string;
  tagline?: string;
  emoji: string;
  system_prompt: string;
  skills: string[];
  tools: string[];
  runs: number;
};
type Draft = Omit<Agent, "id" | "runs">;
type ToolDef = { id: string; description: string };
type RunResult = { output: string; sources: string[]; used_research: boolean; agent: { name: string; emoji: string } };

const EXAMPLES = [
  "A front-desk concierge that answers guest questions about my resort and upsells room add-ons and tours",
  "A lead qualifier for WhatsApp enquiries that asks the right questions and drafts a package",
  "A competitor-rate watcher that checks nearby hotels weekly and suggests my pricing",
  "A package copywriter that turns a client's wishes into a polished proposal",
];

/**
 * Agent Studio — the plug-and-play role-agent builder. Describe a role in plain
 * language, the Architect drafts a deployable agent (identity + skills + tools),
 * and it runs for real (LLM + live web research). This is the "spin up a custom
 * AI employee in 15 seconds" surface.
 */
export function ConsoleAgentStudio() {
  const [agents, setAgents] = useState<Agent[] | null>(null);
  const [tools, setTools] = useState<Record<string, string>>({});
  const [creating, setCreating] = useState(false);

  const load = async () => {
    try {
      setAgents((await api.get<{ agents: Agent[] }>("/studio/agents")).agents);
    } catch {
      setAgents([]);
    }
  };
  useEffect(() => {
    void load();
    api.get<{ tools: ToolDef[] }>("/studio/tools").then((r) => {
      setTools(Object.fromEntries(r.tools.map((t) => [t.id, t.description])));
    }).catch(() => {});
  }, []);

  return (
    <div>
      <header className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-[var(--r-md)] bg-[color-mix(in_srgb,var(--brand-400)_16%,transparent)] text-[var(--brand-500)]">
            <Sparkles className="h-5 w-5" weight="fill" />
          </span>
          <div>
            <h1 className="font-[family-name:var(--font-display)] text-2xl font-bold tracking-tight">Agent Studio</h1>
            <p className="mt-0.5 max-w-xl text-sm text-[var(--muted)]">
              Describe a role — the Architect builds a working AI agent for your business in seconds.
              No code. It researches the web, drafts documents, and answers customers for real.
            </p>
          </div>
        </div>
        {!creating && (
          <Button onClick={() => setCreating(true)}>
            <Plus className="h-4 w-4" /> New agent
          </Button>
        )}
      </header>

      {creating && (
        <CreateAgent
          tools={tools}
          onClose={() => setCreating(false)}
          onDeployed={() => {
            setCreating(false);
            void load();
          }}
        />
      )}

      {agents === null ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-40 w-full rounded-[var(--r-lg)]" />
          ))}
        </div>
      ) : agents.length === 0 && !creating ? (
        <div className="surface-card grid place-items-center gap-3 p-10 text-center">
          <span className="grid h-14 w-14 place-items-center rounded-full bg-[color-mix(in_srgb,var(--brand-400)_14%,transparent)] text-3xl">🤖</span>
          <p className="text-lg font-semibold">Build your first AI employee</p>
          <p className="max-w-md text-sm text-[var(--muted)]">
            A concierge, a lead qualifier, a rate-watcher, a copywriter — describe the role and deploy it in one step.
          </p>
          <Button onClick={() => setCreating(true)}>
            <Plus className="h-4 w-4" /> Create an agent
          </Button>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {agents.map((a) => (
            <AgentCard key={a.id} agent={a} onDeleted={() => void load()} />
          ))}
        </div>
      )}
    </div>
  );
}

function CreateAgent({
  tools,
  onClose,
  onDeployed,
}: {
  tools: Record<string, string>;
  onClose: () => void;
  onDeployed: () => void;
}) {
  const [role, setRole] = useState("");
  const [designing, setDesigning] = useState(false);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [deploying, setDeploying] = useState(false);

  const design = async () => {
    if (role.trim().length < 3) return;
    setDesigning(true);
    setDraft(null);
    try {
      const res = await api.post<{ draft: Draft }>("/studio/design", { role });
      setDraft(res.draft);
    } catch {
      toast.error("Couldn't draft that agent — try rephrasing the role.");
    } finally {
      setDesigning(false);
    }
  };

  const deploy = async () => {
    if (!draft) return;
    setDeploying(true);
    try {
      await api.post("/studio/agents", draft);
      toast.success(`${draft.emoji} ${draft.name} deployed.`);
      onDeployed();
    } catch {
      toast.error("Couldn't deploy the agent.");
    } finally {
      setDeploying(false);
    }
  };

  return (
    <div className="surface-card mb-5 p-5">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold">Describe the role</h3>
        <button onClick={onClose} aria-label="Close" className="rounded-full p-1 text-[var(--muted)] hover:text-[var(--text)]">
          <X className="h-4 w-4" />
        </button>
      </div>
      <textarea
        value={role}
        onChange={(e) => setRole(e.target.value)}
        rows={2}
        placeholder="e.g. A front-desk concierge that answers guest questions and upsells tours"
        className="w-full resize-none rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm"
      />
      <div className="mt-2 flex flex-wrap gap-1.5">
        {EXAMPLES.map((ex) => (
          <button
            key={ex}
            onClick={() => setRole(ex)}
            className="rounded-[var(--r-pill)] border border-[var(--border)] px-2.5 py-1 text-[0.7rem] text-[var(--muted)] hover:border-[var(--brand-400)] hover:text-[var(--brand-600)]"
          >
            {ex.length > 42 ? ex.slice(0, 42) + "…" : ex}
          </button>
        ))}
      </div>
      <div className="mt-3">
        <Button loading={designing} disabled={role.trim().length < 3} onClick={() => void design()}>
          <Sparkles className="h-4 w-4" /> Generate agent
        </Button>
      </div>

      {draft && (
        <div className="mt-4 rounded-[var(--r-lg)] border border-[var(--brand-400)]/40 bg-[color-mix(in_srgb,var(--brand-400)_6%,transparent)] p-4">
          <div className="flex items-start gap-3">
            <span className="grid h-11 w-11 shrink-0 place-items-center rounded-[var(--r-md)] bg-[var(--surface)] text-2xl">{draft.emoji}</span>
            <div className="min-w-0 flex-1">
              <input
                value={draft.name}
                onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                className="w-full bg-transparent font-[family-name:var(--font-display)] text-lg font-bold outline-none"
              />
              <p className="text-xs text-[var(--muted)]">{draft.tagline}</p>
            </div>
          </div>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {draft.skills.map((s) => (
              <span key={s} className="rounded-[var(--r-pill)] bg-[var(--surface)] px-2.5 py-1 text-[0.7rem] font-medium">{s}</span>
            ))}
          </div>
          <div className="mt-3">
            <p className="mb-1 text-[0.65rem] font-semibold uppercase tracking-wide text-[var(--muted)]">Tools</p>
            <div className="flex flex-wrap gap-1.5">
              {draft.tools.map((t) => (
                <span key={t} className="inline-flex items-center gap-1 rounded-[var(--r-pill)] border border-[var(--brand-400)]/40 px-2.5 py-1 text-[0.7rem] text-[var(--brand-600)]">
                  {t === "web_research" || t === "competitor_watch" ? <Compass className="h-3 w-3" /> : <Sparkles className="h-3 w-3" />}
                  {tools[t] ? t.replace(/_/g, " ") : t}
                </span>
              ))}
            </div>
          </div>
          <textarea
            value={draft.system_prompt}
            onChange={(e) => setDraft({ ...draft, system_prompt: e.target.value })}
            rows={3}
            className="mt-3 w-full resize-none rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-xs text-[var(--muted)]"
          />
          <div className="mt-3 flex gap-2">
            <Button loading={deploying} onClick={() => void deploy()}>
              Deploy agent <ArrowRight className="h-4 w-4" />
            </Button>
            <Button variant="secondary" onClick={() => void design()} disabled={designing}>
              Regenerate
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

function AgentCard({ agent, onDeleted }: { agent: Agent; onDeleted: () => void }) {
  const [open, setOpen] = useState(false);
  const [task, setTask] = useState("");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<RunResult | null>(null);

  const run = async () => {
    if (!task.trim()) return;
    setRunning(true);
    setResult(null);
    try {
      setResult(await api.post<RunResult>(`/studio/agents/${agent.id}/run`, { task }));
    } catch {
      toast.error("The agent couldn't complete that — try again.");
    } finally {
      setRunning(false);
    }
  };

  const del = async () => {
    try {
      await api.del(`/studio/agents/${agent.id}`);
      onDeleted();
    } catch {
      toast.error("Couldn't remove that agent.");
    }
  };

  return (
    <div className={cn("surface-card flex flex-col p-4", open && "sm:col-span-2 lg:col-span-3")}>
      <div className="flex items-start gap-3">
        <span className="grid h-11 w-11 shrink-0 place-items-center rounded-[var(--r-md)] bg-[color-mix(in_srgb,var(--brand-400)_12%,transparent)] text-2xl">
          {agent.emoji}
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate font-semibold">{agent.name}</p>
          <p className="line-clamp-2 text-xs text-[var(--muted)]">{agent.tagline || agent.role}</p>
        </div>
        <button onClick={() => void del()} aria-label="Delete agent" className="shrink-0 rounded-full p-1 text-[var(--muted)] hover:text-[var(--danger)]">
          <Trash2 className="h-4 w-4" />
        </button>
      </div>

      <div className="mt-2.5 flex flex-wrap gap-1.5">
        {agent.skills.slice(0, 4).map((s) => (
          <span key={s} className="rounded-[var(--r-pill)] bg-[var(--bg)] px-2 py-0.5 text-[0.65rem] text-[var(--muted)]">{s}</span>
        ))}
      </div>
      {agent.tools.some((t) => t === "web_research" || t === "competitor_watch") && (
        <p className="mt-2 inline-flex items-center gap-1 text-[0.65rem] text-[var(--brand-600)]">
          <Compass className="h-3 w-3" /> researches the live web
        </p>
      )}

      <div className="mt-3 flex items-center gap-2">
        <Button variant={open ? "secondary" : "primary"} size="sm" className="flex-1" onClick={() => setOpen((v) => !v)}>
          {open ? "Close" : "Run this agent"}
        </Button>
        {agent.runs > 0 && <span className="text-[0.65rem] text-[var(--muted)]">{agent.runs} run{agent.runs === 1 ? "" : "s"}</span>}
      </div>

      {open && (
        <div className="mt-3 border-t border-[var(--border)] pt-3">
          <div className="flex gap-2">
            <input
              value={task}
              onChange={(e) => setTask(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && void run()}
              placeholder={`Give ${agent.name} a task…`}
              className="min-w-0 flex-1 rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm"
            />
            <Button size="sm" loading={running} onClick={() => void run()}>Run</Button>
          </div>
          {running && (
            <p className="mt-2 flex items-center gap-2 text-xs text-[var(--brand-600)]">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              {agent.tools.some((t) => t === "web_research" || t === "competitor_watch")
                ? "Researching the web and drafting…"
                : "Working…"}
            </p>
          )}
          {result && (
            <div className="mt-3 rounded-[var(--r-md)] border-l-2 border-[var(--brand-500)] bg-[color-mix(in_srgb,var(--brand-400)_7%,transparent)] p-3">
              <p className="whitespace-pre-wrap text-sm leading-relaxed">{result.output}</p>
              {result.used_research && result.sources.length > 0 && (
                <div className="mt-2 border-t border-[var(--border)] pt-2">
                  <p className="mb-1 text-[0.6rem] font-semibold uppercase tracking-wide text-[var(--muted)]">Sources</p>
                  <ul className="space-y-0.5">
                    {result.sources.slice(0, 5).map((s) => (
                      <li key={s} className="truncate text-[0.65rem]">
                        <a href={s} target="_blank" rel="noreferrer" className="text-[var(--brand-600)] hover:underline">{s}</a>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
