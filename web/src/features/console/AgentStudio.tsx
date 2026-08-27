import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Sparkles, Plus, Trash2, Loader2, X, Compass, ArrowRight, Users, CheckCircle2, Copy, Zap } from "@/components/ui/icons";
import { Button, Skeleton } from "@/components/ui";
import { Switch } from "@/components/ui/Switch";
import { cn } from "@/lib/cn";
import { api } from "@/lib/api";
import { Section } from "./ui";

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

      <Boardroom />

      <KnowledgeCard />

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

      {agents && agents.length >= 2 && <TeamRunner agents={agents} />}
    </div>
  );
}

/**
 * Agent Teams — chain your agents into an autonomous workflow. Pick them in
 * order (Lead Qualifier → Package Planner → Copywriter → …), give one brief, and
 * each agent works on the brief plus the previous teammate's output, handing off
 * down the line. An AI back-office running itself.
 */
function TeamRunner({ agents }: { agents: Agent[] }) {
  const [order, setOrder] = useState<string[]>([]);
  const [brief, setBrief] = useState("");
  const [running, setRunning] = useState(false);
  const [steps, setSteps] = useState<Array<{ agent: { name: string; emoji: string }; output: string; ok: boolean }> | null>(null);

  const toggle = (id: string) => setOrder((o) => (o.includes(id) ? o.filter((x) => x !== id) : [...o, id]));
  const byId = (id: string) => agents.find((a) => a.id === id);

  const run = async () => {
    if (order.length < 2 || !brief.trim()) return;
    setRunning(true);
    setSteps(null);
    try {
      const res = await api.post<{ steps: typeof steps }>("/studio/teams/run", { agent_ids: order, brief });
      setSteps(res.steps);
    } catch {
      toast.error("The team run couldn't finish — try again.");
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="surface-card mt-6 p-5">
      <div className="mb-1 flex items-center gap-2 text-sm font-semibold">
        <Sparkles className="h-4 w-4 text-[var(--accent)]" weight="fill" /> Agent Teams — chain them into a workflow
      </div>
      <p className="mb-3 text-xs text-[var(--muted)]">Tap agents in the order they should work — each hands its output to the next.</p>

      <div className="mb-3 flex flex-wrap gap-1.5">
        {agents.map((a) => {
          const pos = order.indexOf(a.id);
          return (
            <button
              key={a.id}
              onClick={() => toggle(a.id)}
              className={cn(
                "inline-flex items-center gap-1 rounded-[var(--r-pill)] border px-2.5 py-1 text-xs",
                pos >= 0 ? "border-[var(--brand-500)] bg-[color-mix(in_srgb,var(--brand-400)_14%,transparent)] text-[var(--brand-600)] font-semibold" : "border-[var(--border)] text-[var(--muted)]",
              )}
            >
              {pos >= 0 && <span className="grid h-4 w-4 place-items-center rounded-full bg-[var(--brand-500)] text-[0.6rem] text-white">{pos + 1}</span>}
              {a.emoji} {a.name}
            </button>
          );
        })}
      </div>

      {order.length >= 2 && (
        <div className="mb-3 flex flex-wrap items-center gap-1.5 text-xs text-[var(--muted)]">
          Pipeline:
          {order.map((id, i) => (
            <span key={id} className="flex items-center gap-1.5">
              <span className="rounded-[var(--r-pill)] bg-[var(--bg)] px-2 py-0.5 font-medium text-[var(--text)]">{byId(id)?.emoji} {byId(id)?.name}</span>
              {i < order.length - 1 && <ArrowRight className="h-3 w-3" />}
            </span>
          ))}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <input className="min-w-0 flex-1 rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm" placeholder="The brief for the team (e.g. a WhatsApp enquiry to turn into a sent package)" value={brief} onChange={(e) => setBrief(e.target.value)} />
        <Button loading={running} disabled={order.length < 2 || !brief.trim()} onClick={() => void run()}>Run team</Button>
      </div>

      {running && <p className="mt-2 flex items-center gap-2 text-xs text-[var(--brand-600)]"><Loader2 className="h-3.5 w-3.5 animate-spin" /> The team is working, agent by agent…</p>}

      {steps && (
        <div className="mt-3 space-y-2">
          {steps.map((s, i) => (
            <div key={i} className="rounded-[var(--r-md)] bg-[var(--bg)] p-3">
              <p className="mb-1 flex items-center gap-1.5 text-xs font-semibold">
                <span>{s.agent.emoji}</span> {i + 1}. {s.agent.name}
              </p>
              <p className="whitespace-pre-wrap text-sm leading-relaxed">{s.output || "(no output)"}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

type KbEntry = { id: string; title: string; source: string; chars: number; preview: string };

/** Train-your-AI: ingest the business's own facts (a website URL or pasted text)
 *  so every agent + the inbox answer from real, business-specific knowledge. */
function KnowledgeCard() {
  const [entries, setEntries] = useState<KbEntry[]>([]);
  const [open, setOpen] = useState(false);
  const [url, setUrl] = useState("");
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);

  const load = async () => {
    try {
      setEntries((await api.get<{ entries: KbEntry[] }>("/studio/kb")).entries);
    } catch {
      /* ignore */
    }
  };
  useEffect(() => {
    void load();
  }, []);

  const addUrl = async () => {
    if (!url.trim()) return;
    setBusy(true);
    try {
      await api.post("/studio/kb/url", { url });
      setUrl("");
      toast.success("Learned from the page.");
      await load();
    } catch {
      toast.error("Couldn't read that page — paste the text instead.");
    } finally {
      setBusy(false);
    }
  };
  const addText = async () => {
    if (text.trim().length < 10) return;
    setBusy(true);
    try {
      await api.post("/studio/kb/text", { title: title || "Note", content: text });
      setTitle("");
      setText("");
      toast.success("Added to your AI's knowledge.");
      await load();
    } catch {
      toast.error("Couldn't save that.");
    } finally {
      setBusy(false);
    }
  };
  const del = async (id: string) => {
    try {
      await api.del(`/studio/kb/${id}`);
      setEntries((e) => e.filter((x) => x.id !== id));
    } catch {
      /* ignore */
    }
  };

  return (
    <div className="surface-card mb-5 p-4">
      <button className="flex w-full items-center justify-between" onClick={() => setOpen((v) => !v)}>
        <span className="flex items-center gap-2 text-sm font-semibold">
          <Compass className="h-4 w-4 text-[var(--brand-500)]" /> Train your AI on your business
          {entries.length > 0 && (
            <span className="rounded-[var(--r-pill)] bg-[color-mix(in_srgb,var(--brand-400)_16%,transparent)] px-2 py-0.5 text-[0.65rem] text-[var(--brand-600)]">
              {entries.length} source{entries.length === 1 ? "" : "s"}
            </span>
          )}
        </span>
        <span className="text-xs text-[var(--muted)]">{open ? "Hide" : "Manage"}</span>
      </button>
      <p className="mt-1 text-xs text-[var(--muted)]">
        Add your website or brochure and every agent + the inbox answers from your real facts.
      </p>

      {open && (
        <div className="mt-3 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <input
              className="min-w-0 flex-1 rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm"
              placeholder="https://your-hotel.com"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
            />
            <Button size="sm" variant="secondary" loading={busy} onClick={() => void addUrl()}>
              Learn from URL
            </Button>
          </div>
          <div className="rounded-[var(--r-md)] border border-[var(--border)] p-2">
            <input
              className="mb-2 w-full rounded-[var(--r-sm)] border border-[var(--border)] bg-[var(--bg)] px-2.5 py-1.5 text-sm"
              placeholder="Title (e.g. Rooms & rates)"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
            <textarea
              rows={2}
              className="w-full resize-none rounded-[var(--r-sm)] border border-[var(--border)] bg-[var(--bg)] px-2.5 py-1.5 text-sm"
              placeholder="Paste facts about your business — room types, rates, amenities, policies…"
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
            <div className="mt-2">
              <Button size="sm" variant="secondary" loading={busy} onClick={() => void addText()}>
                <Plus className="h-3.5 w-3.5" /> Add text
              </Button>
            </div>
          </div>
          {entries.length > 0 && (
            <div className="space-y-1.5">
              {entries.map((e) => (
                <div key={e.id} className="flex items-center gap-2 rounded-[var(--r-md)] border border-[var(--border)] px-3 py-1.5">
                  <span className="min-w-0 flex-1 truncate text-sm">
                    {e.title} <span className="text-[0.65rem] text-[var(--muted)]">· {e.source} · {e.chars} chars</span>
                  </span>
                  <button onClick={() => void del(e.id)} aria-label="Remove" className="rounded-full p-1 text-[var(--muted)] hover:text-[var(--danger)]">
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))}
            </div>
          )}
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
        <div className="mt-4 rounded-[var(--r-lg)] border border-[var(--border)] bg-[var(--bg)] p-4">
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
    <div className={cn("surface-card flex flex-col p-4 transition-shadow", open && "sm:col-span-2 lg:col-span-3", running && "ring-1 ring-[var(--brand-400)]")}>
      <div className="flex items-start gap-3">
        <span className={cn("relative grid h-11 w-11 shrink-0 place-items-center rounded-[var(--r-md)] bg-[color-mix(in_srgb,var(--brand-400)_12%,transparent)] text-2xl", running && "ring-2 ring-[var(--brand-400)]")}>
          {agent.emoji}
          {/* Live heartbeat while this agent is actually running. */}
          {running && (
            <span className="absolute -right-1 -top-1 flex h-3.5 w-3.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[var(--brand-500)] opacity-75" />
              <span className="relative inline-flex h-3.5 w-3.5 rounded-full bg-[var(--brand-500)] ring-2 ring-[var(--surface)]" />
            </span>
          )}
        </span>
        <div className="min-w-0 flex-1">
          <p className="flex items-center gap-1.5 truncate font-semibold">
            {agent.name}
            {running && <span className="shrink-0 rounded-[var(--r-pill)] bg-[color-mix(in_srgb,var(--brand-400)_16%,transparent)] px-1.5 py-0.5 text-[0.55rem] font-bold uppercase tracking-wide text-[var(--brand-600)]">Running</span>}
          </p>
          <p className="line-clamp-2 text-xs text-[var(--muted)]">{agent.tagline || agent.role}</p>
        </div>
        <button onClick={() => void del()} disabled={running} aria-label="Delete agent" className="shrink-0 rounded-full p-1 text-[var(--muted)] hover:text-[var(--danger)] disabled:opacity-30">
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
        {running ? (
          // Locked + heartbeat while a task is in flight — no re-trigger, no close.
          <span className="flex flex-1 items-center justify-center gap-2 rounded-[var(--r-md)] bg-[color-mix(in_srgb,var(--brand-400)_16%,transparent)] px-3 py-2 text-sm font-semibold text-[var(--brand-600)]">
            <span className="relative flex h-2.5 w-2.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[var(--brand-500)] opacity-75" />
              <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-[var(--brand-500)]" />
            </span>
            Running…
          </span>
        ) : (
          <Button variant={open ? "secondary" : "primary"} size="sm" className="flex-1" onClick={() => setOpen((v) => !v)}>
            {open ? "Close" : "Run this agent"}
          </Button>
        )}
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
            <div className="mt-3 rounded-[var(--r-md)] bg-[var(--bg)] p-3">
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

/* ---------------------------------------------------------- Boardroom */

type Participant = { name: string; emoji: string; role: string };
type Turn = { speaker: string; emoji: string; role: string; text: string };
type ActionItem = { owner: string; action: string };
type Meeting = { id?: string; topic?: string; summary?: string; transcript: Turn[]; decisions: string[]; action_items: ActionItem[]; marketing_draft?: string; created_at?: string };
type BoardroomData = { settings: { enabled: boolean; focus: string | null }; participants: Participant[]; meetings: Meeting[] };

function fmtMeetingDate(value?: string): string {
  if (!value) return "Meeting";
  const d = new Date(value);
  return Number.isNaN(d.getTime())
    ? "Meeting"
    : d.toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

/**
 * Autonomous Boardroom — the org's agents (built-in Revenue/Bookings/Marketing
 * leads + every custom agent) convene by themselves, speak to the real numbers,
 * and a Chair records decisions, action items and a ready-to-post marketing
 * draft. Flip Autopilot on and it convenes on the schedule, unattended.
 */
function Boardroom() {
  const [data, setData] = useState<BoardroomData | null>(null);
  const [latest, setLatest] = useState<Meeting | null>(null);
  const [topic, setTopic] = useState("");
  const [busy, setBusy] = useState(false);
  // WhatsApp-style chat canvas: fixed height, newest at the bottom. `shown`
  // windows the meeting history so a long backlog paginates (load earlier at top).
  const scrollRef = useRef<HTMLDivElement>(null);
  const [shown, setShown] = useState(2);

  const load = async () => {
    try {
      const d = await api.get<BoardroomData>("/boardroom");
      setData(d);
      setLatest((prev) => prev ?? d.meetings[0] ?? null);
    } catch {
      setData({ settings: { enabled: false, focus: null }, participants: [], meetings: [] });
    }
  };
  useEffect(() => { void load(); }, []);
  // Pin to the newest turn on first load + whenever a new meeting lands (not when
  // the user loads earlier history, so scrolling up stays put).
  useEffect(() => {
    const c = scrollRef.current;
    if (c) c.scrollTop = c.scrollHeight;
  }, [latest?.id]);

  const convene = async () => {
    setBusy(true);
    try {
      const r = await api.post<{ meeting: Meeting }>("/boardroom/convene", { topic: topic.trim() || undefined });
      setLatest(r.meeting);
      toast.success("The boardroom met — minutes are in.");
      void load();
    } catch {
      toast.error("The boardroom couldn't convene — try again.");
    } finally {
      setBusy(false);
    }
  };
  const toggleAuto = async (v: boolean) => {
    setData((d) => (d ? { ...d, settings: { ...d.settings, enabled: v } } : d));
    try { await api.post("/boardroom/settings", { enabled: v }); }
    catch { toast.error("Couldn't update autopilot."); }
  };

  const participants = data?.participants ?? [];
  const enabled = data?.settings.enabled ?? false;
  const chrono = [...(data?.meetings ?? [])].reverse(); // oldest → newest, like a chat
  const visible = chrono.slice(Math.max(0, chrono.length - shown));

  return (
    <Section
      icon={Users}
      title="Autonomous Boardroom"
      subtitle="Your agents meet on their own — grow revenue, handle bookings, and market — within this org."
      className="mb-5"
      actions={<>
        <label className="flex items-center gap-2 text-xs font-medium"><Switch checked={enabled} onCheckedChange={(v) => void toggleAuto(v)} aria-label="autopilot" /> Autopilot</label>
        <Button size="sm" loading={busy} onClick={() => void convene()}><Zap className="h-4 w-4" /> Convene now</Button>
      </>}
    >
      <div className="space-y-4">
        <div>
          <p className="mb-1.5 text-xs font-medium text-[var(--muted)]">{participants.length} in the room{enabled ? " · convenes on schedule" : ""} — build more in Agent Studio and they all get a seat</p>
          <div className="flex flex-wrap gap-1.5">
            {participants.map((p) => (
              <span key={p.name} className="inline-flex items-center gap-1.5 rounded-[var(--r-pill)] bg-[var(--bg)] px-2.5 py-1 text-xs">
                <span>{p.emoji}</span> {p.name}
                {p.role === "custom" && <span className="text-[0.6rem] text-[var(--muted)]">· yours</span>}
              </span>
            ))}
          </div>
        </div>

        <input
          className="w-full rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm outline-none focus:border-[var(--brand-400)]"
          placeholder="Optional topic (else they take on revenue + bookings + marketing)"
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
        />

        {busy && <p className="flex items-center gap-2 text-xs text-[var(--brand-600)]"><Loader2 className="h-3.5 w-3.5 animate-spin" /> The room is discussing…</p>}

        {latest ? (
          <div className="space-y-4">
            {latest.summary && (
              <div className="rounded-[var(--r-md)] bg-[color-mix(in_srgb,var(--brand-400)_10%,transparent)] p-3">
                <p className="text-sm"><span className="font-semibold">Chair's readout — </span>{latest.summary}</p>
              </div>
            )}
            {/* Chat canvas — fixed height, newest at the bottom; scroll up for
                earlier turns, "Load earlier" pages in older meetings. */}
            <div
              ref={scrollRef}
              className="max-h-[60vh] min-h-[15rem] space-y-3 overflow-y-auto overscroll-contain rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--bg)] p-3"
            >
              {shown < chrono.length && (
                <div className="flex justify-center pb-1">
                  <button
                    onClick={() => setShown((n) => n + 3)}
                    className="rounded-[var(--r-pill)] border border-[var(--border)] bg-[var(--surface)] px-3 py-1 text-xs font-medium text-[var(--muted)] hover:text-[var(--brand-600)]"
                  >
                    ↑ Load earlier meetings
                  </button>
                </div>
              )}
              {visible.map((m, mi) => (
                <div key={m.id ?? mi} className="space-y-2">
                  <div className="flex items-center gap-2 py-1">
                    <span className="h-px flex-1 bg-[var(--border)]" />
                    <span className="rounded-[var(--r-pill)] bg-[var(--surface)] px-2.5 py-0.5 text-[0.6rem] font-medium text-[var(--muted)]">
                      {m.topic ? `${m.topic} · ` : ""}{fmtMeetingDate(m.created_at)}
                    </span>
                    <span className="h-px flex-1 bg-[var(--border)]" />
                  </div>
                  {m.transcript.map((t, i) => (
                    <div key={i} className="flex gap-2.5">
                      <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-full bg-[var(--surface)] text-base ring-1 ring-[var(--border)]">{t.emoji}</span>
                      <div className="min-w-0 flex-1 rounded-[var(--r-md)] rounded-tl-sm bg-[var(--surface)] px-3 py-2 shadow-[var(--shadow-1)]">
                        <p className="text-[0.7rem] font-semibold">{t.speaker}</p>
                        <p className="mt-0.5 whitespace-pre-wrap text-sm text-[var(--muted)]">{t.text}</p>
                      </div>
                    </div>
                  ))}
                </div>
              ))}
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              {!!latest.decisions.length && (
                <div>
                  <p className="mb-1.5 text-xs font-semibold">Decisions</p>
                  <ul className="space-y-1">
                    {latest.decisions.map((d, i) => (
                      <li key={i} className="flex items-start gap-1.5 text-sm"><CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-[var(--success)]" /> {d}</li>
                    ))}
                  </ul>
                </div>
              )}
              {!!latest.action_items.length && (
                <div>
                  <p className="mb-1.5 text-xs font-semibold">Action items</p>
                  <ul className="space-y-1">
                    {latest.action_items.map((a, i) => (
                      <li key={i} className="text-sm"><span className="font-medium">{a.owner}:</span> <span className="text-[var(--muted)]">{a.action}</span></li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
            {latest.marketing_draft && (
              <div className="rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--bg)] p-3">
                <div className="mb-1 flex items-center gap-2">
                  <span className="text-xs font-semibold">📣 Marketing draft — ready to post</span>
                  <button onClick={() => { void navigator.clipboard?.writeText(latest.marketing_draft || ""); toast.success("Copied"); }} className="ml-auto inline-flex items-center gap-1 text-xs text-[var(--brand-600)] hover:underline"><Copy className="h-3.5 w-3.5" /> Copy</button>
                </div>
                <p className="whitespace-pre-wrap text-sm">{latest.marketing_draft}</p>
              </div>
            )}
          </div>
        ) : (
          <p className="text-sm text-[var(--muted)]">No meetings yet — press <strong>Convene now</strong> and your agents will meet and produce a plan. Turn on <strong>Autopilot</strong> to have them convene on their own.</p>
        )}
      </div>
    </Section>
  );
}
