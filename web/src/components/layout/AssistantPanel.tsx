import * as Dialog from "@radix-ui/react-dialog";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Sparkles, X, Plus, ArrowUp, CheckCircle2, Paperclip } from "@/components/ui/icons";
import { Button } from "@/components/ui";
import { useAgentStream } from "@/hooks/useAgentStream";
import { API_BASE, api } from "@/lib/api";
import { getAccessToken } from "@/lib/auth";
import { cn } from "@/lib/cn";

/**
 * Journava AI — a ChatGPT-style assistant in an off-canvas panel.
 *
 * Answers any travel question, and (via the backend) can launch Journava's
 * autonomous agents in the background — the run streams to the live agent feed
 * and lands in History/Trip when done.
 */

type Action = { type: string; job_id?: string; scope?: string; goal?: string } | null;
type Msg = { role: "user" | "assistant"; content: string; action?: Action; image?: string };
type Doc = { filename: string; kind: string; summary: string; text: string };

/** Three bouncing dots shown in the assistant bubble before the first token. */
function TypingDots() {
  return (
    <span className="flex gap-1 py-0.5">
      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-[var(--muted)] [animation-delay:-0.2s]" />
      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-[var(--muted)] [animation-delay:-0.1s]" />
      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-[var(--muted)]" />
    </span>
  );
}

/** Minimal inline markdown: render **bold** (newlines are kept by the bubble's
 *  whitespace-pre-wrap), so the assistant's lists read cleanly. */
function RichText({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return (
    <>
      {parts.map((part, i) =>
        part.startsWith("**") && part.endsWith("**") ? (
          <strong key={i}>{part.slice(2, -2)}</strong>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </>
  );
}

/** Live status of an agent run the assistant launched — polls the job and shows
 *  the latest agent activity, flipping to a results link when done. */
function RunStatusCard({ jobId, close }: { jobId: string; close: () => void }) {
  const navigate = useNavigate();
  const { events } = useAgentStream();
  const [status, setStatus] = useState<"running" | "done" | "failed">("running");

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const rec = await api.get<{ status?: string }>(`/jobs/${jobId}`);
        if (cancelled) return;
        const s = rec.status ?? "";
        if (s === "done" || s === "completed") return void setStatus("done");
        if (s === "failed" || s === "error") return void setStatus("failed");
      } catch {
        /* keep polling */
      }
      timer = window.setTimeout(poll, 2500);
    };
    void poll();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [jobId]);

  const go = (to: string) => {
    close();
    navigate(to);
  };

  if (status === "done") {
    return (
      <button
        onClick={() => go("/trip?tab=history")}
        className="mt-2 flex items-center gap-1.5 rounded-[var(--r-md)] bg-[color-mix(in_srgb,var(--success)_16%,transparent)] px-2.5 py-1.5 text-xs font-medium text-[var(--success)]"
      >
        <CheckCircle2 className="h-3.5 w-3.5" /> Done — view results
      </button>
    );
  }
  if (status === "failed") {
    return <p className="mt-2 text-xs text-[var(--warning)]">The run couldn't finish — try again.</p>;
  }

  const latest = events[0];
  return (
    <button
      onClick={() => go("/agents")}
      className="mt-2 flex w-full items-center gap-2 rounded-[var(--r-md)] bg-[color-mix(in_srgb,var(--brand-400)_14%,transparent)] px-2.5 py-2 text-left"
    >
      <span className="relative grid h-3 w-3 shrink-0 place-items-center">
        <span className="absolute inset-0 animate-ping rounded-full bg-[var(--brand-500)] opacity-60" />
        <span className="h-1.5 w-1.5 rounded-full bg-[var(--brand-500)]" />
      </span>
      <span className="min-w-0">
        <span className="block text-xs font-semibold text-[var(--brand-600)]">
          Agents working — running in the background
        </span>
        <span className="block truncate text-[0.65rem] text-[var(--muted)]">
          {latest ? `${latest.agent}: ${latest.message}` : "tap to watch live"}
        </span>
      </span>
    </button>
  );
}

const SUGGESTIONS = [
  "Halal places to eat in Chengdu",
  "Find flights KLIA → Chengdu on 5 Nov",
  "Do I need a visa for Japan?",
  "Plan a 5-day Bali trip",
];

const SOCIAL_URL_RE =
  /https?:\/\/\S*(tiktok\.com|instagram\.com|youtube\.com|youtu\.be|twitter\.com|x\.com|facebook\.com|fb\.watch)\S*/i;
const PLAN_INTENT_RE = /\b(plan|trip|itinerary|travel|visit|go here|take me)\b/i;
const FROM_POST_RE = /\b(from|based on|off)\b[^.]*\b(this|post|reel|video|clip|screenshot|photo|pic|it)\b/i;

/** True when the message is a "plan a trip from this post" request — a social
 *  link, a screenshot with planning intent, or a pasted caption with an explicit
 *  "from this post" phrasing. Routes to /assistant/from-social. */
function detectSocial(content: string, hasImage: boolean): boolean {
  if (SOCIAL_URL_RE.test(content)) return true;
  if (hasImage && (PLAN_INTENT_RE.test(content) || FROM_POST_RE.test(content))) return true;
  // A pasted caption after the "Plan from a post" prompt (needs real text, not
  // just the bare prompt) also routes to the extractor.
  if (FROM_POST_RE.test(content) && content.replace(/plan a trip from this post:?/i, "").trim().length > 40)
    return true;
  return false;
}

export function AssistantPanel({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [image, setImage] = useState<string | null>(null);
  const [doc, setDoc] = useState<Doc | null>(null);
  const [uploading, setUploading] = useState(false);
  const [sending, setSending] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, sending]);

  const send = async (text?: string) => {
    const content = (text ?? input).trim();
    if ((!content && !doc) || sending) return;
    const img = image;
    const attached = doc;
    const base: Msg[] = [
      ...messages,
      { role: "user", content: content || `About ${attached?.filename ?? "this document"}…`, image: img ?? undefined },
    ];
    // Add an empty assistant placeholder we stream tokens into.
    setMessages([...base, { role: "assistant", content: "" }]);
    setInput("");
    setImage(null);
    setDoc(null);
    setSending(true);

    // The document text rides along as context on the last user turn, but stays
    // out of the visible bubble (the summary was already shown on upload).
    const apiMessages = base.map((m, i) =>
      attached && i === base.length - 1
        ? {
            role: m.role,
            content: `${m.content}\n\n[Attached document "${attached.filename}" — kind: ${attached.kind}]\n${attached.text}`,
          }
        : { role: m.role, content: m.content },
    );

    const patchLast = (fn: (m: Msg) => Msg) =>
      setMessages((prev) => {
        const copy = [...prev];
        const i = copy.length - 1;
        if (copy[i]?.role === "assistant") copy[i] = fn(copy[i]);
        return copy;
      });

    // "Plan a trip from this post" — a social link or a screenshot + intent goes
    // to the extractor, which launches a background plan we track with a card.
    if (detectSocial(content, !!img)) {
      try {
        const token = getAccessToken();
        const url = content.match(SOCIAL_URL_RE)?.[0] ?? null;
        const res = await fetch(`${API_BASE}/assistant/from-social`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify({ url, text: content, image: img, scope: "full_trip" }),
        });
        const data = (await res.json()) as {
          error?: string;
          job?: { id: string; scope: string; goal: string };
          seed?: { destination: string; vibe?: string; source_kind?: string; places?: { name: string }[] };
        };
        if (data.error || !data.job || !data.seed) {
          patchLast((m) => ({ ...m, content: data.error ?? "I couldn't plan from that post." }));
        } else {
          const s = data.seed;
          const job = data.job;
          const places = (s.places ?? []).slice(0, 4).map((p) => p.name).filter(Boolean).join(", ");
          patchLast((m) => ({
            ...m,
            content:
              `📍 From your ${s.source_kind ?? "social"} post: **${s.destination}**` +
              (s.vibe ? ` · ${s.vibe}` : "") +
              `\n\nPlanning a trip${places ? ` around ${places}` : ""}… I'll add it to your History when it's done.`,
            action: { type: "plan_started", job_id: job.id, scope: job.scope, goal: job.goal },
          }));
        }
      } catch {
        patchLast((m) => ({ ...m, content: "Sorry — I couldn't reach the server. Try again?" }));
      } finally {
        setSending(false);
      }
      return;
    }

    try {
      const token = getAccessToken();
      const res = await fetch(`${API_BASE}/assistant/chat/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ messages: apiMessages, image: img }),
      });
      if (!res.ok || !res.body) throw new Error("stream failed");
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let idx: number;
        while ((idx = buf.indexOf("\n\n")) >= 0) {
          const frame = buf.slice(0, idx).trim();
          buf = buf.slice(idx + 2);
          if (!frame.startsWith("data:")) continue;
          let evt: { type: string; content?: string; action?: Action };
          try {
            evt = JSON.parse(frame.slice(5).trim());
          } catch {
            continue;
          }
          if (evt.type === "token" && evt.content) {
            const tok = evt.content;
            patchLast((m) => ({ ...m, content: m.content + tok }));
          } else if (evt.type === "action") {
            const act = evt.action ?? null;
            patchLast((m) => ({ ...m, action: act }));
          }
        }
      }
    } catch {
      patchLast((m) =>
        m.content ? m : { ...m, content: "Sorry — I couldn't reach the server. Try again?" },
      );
    } finally {
      setSending(false);
    }
  };

  const uploadDoc = async (file: File) => {
    setUploading(true);
    try {
      const token = getAccessToken();
      const form = new FormData();
      form.append("file", file);
      const res = await fetch(`${API_BASE}/assistant/upload`, {
        method: "POST",
        headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: form,
      });
      const data = (await res.json()) as Doc & { error?: string; highlights?: string[] };
      if (!res.ok || data.error) {
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: `⚠️ ${data.error ?? "Couldn't read that file."}` },
        ]);
        return;
      }
      setDoc({ filename: data.filename, kind: data.kind, summary: data.summary, text: data.text });
      const hl = (data.highlights ?? []).map((h) => `- ${h}`).join("\n");
      const hint =
        data.kind === "booking"
          ? "\n\nWant me to add this to your trip?"
          : data.kind === "policy"
            ? "\n\nI'll keep this policy in mind for your next search."
            : "";
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: `📄 **${data.filename}** · ${data.kind}\n\n${data.summary}${hl ? "\n\n" + hl : ""}${hint}`,
        },
      ]);
    } catch {
      setMessages((prev) => [...prev, { role: "assistant", content: "⚠️ Couldn't upload that file." }]);
    } finally {
      setUploading(false);
    }
  };

  const onFile = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (file.type.startsWith("image/")) {
      const reader = new FileReader();
      reader.onload = () => setImage(reader.result as string);
      reader.readAsDataURL(file);
    } else {
      void uploadDoc(file);
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[90] bg-black/40 backdrop-blur-sm" />
        <Dialog.Content
          aria-describedby={undefined}
          className={cn(
            "radix-panel fixed z-[91] flex flex-col bg-[var(--surface)] shadow-[var(--shadow-2)]",
            "inset-0 sm:inset-y-0 sm:right-0 sm:left-auto sm:w-[27rem] sm:max-w-[calc(100vw-1rem)]",
          )}
          style={{ paddingTop: "env(safe-area-inset-top)", paddingBottom: "env(safe-area-inset-bottom)" }}
        >
          <header className="flex items-center gap-2 border-b border-[var(--border)] px-4 py-3">
            <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-[color-mix(in_srgb,var(--brand-400)_16%,transparent)] text-[var(--brand-500)]">
              <Sparkles className="h-4 w-4" />
            </span>
            <div className="min-w-0 flex-1">
              <Dialog.Title className="text-sm font-semibold">Journava AI</Dialog.Title>
              <p className="truncate text-[0.65rem] text-[var(--muted)]">
                Ask anything about travel — or start a search
              </p>
            </div>
            <Dialog.Close
              aria-label="Close"
              className="grid h-8 w-8 shrink-0 place-items-center rounded-full text-[var(--muted)] hover:bg-[var(--bg)]"
            >
              <X className="h-4 w-4" />
            </Dialog.Close>
          </header>

          <div ref={listRef} className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-4">
            {messages.length === 0 && (
              <div className="space-y-3">
                <p className="text-sm text-[var(--muted)]">
                  Hi! I can answer travel questions or kick off your agents. Try:
                </p>
                <div className="flex flex-wrap gap-2">
                  {SUGGESTIONS.map((s) => (
                    <button
                      key={s}
                      onClick={() => void send(s)}
                      className="rounded-[var(--r-pill)] border border-[var(--border)] px-3 py-1.5 text-xs hover:bg-[var(--bg)]"
                    >
                      {s}
                    </button>
                  ))}
                  <button
                    onClick={() => setInput("Plan a trip from this post: ")}
                    className="rounded-[var(--r-pill)] border border-dashed border-[var(--brand-400)] px-3 py-1.5 text-xs text-[var(--brand-600)] hover:bg-[var(--bg)]"
                  >
                    📱 Plan from a TikTok / IG / YouTube post
                  </button>
                </div>
              </div>
            )}

            {messages.map((m, i) => (
              <div key={i} className={cn("flex", m.role === "user" ? "justify-end" : "justify-start")}>
                <div
                  className={cn(
                    "min-w-0 max-w-[85%] whitespace-pre-wrap break-words rounded-[var(--r-lg)] px-3 py-2 text-sm",
                    m.role === "user"
                      ? "bg-[var(--brand-500)] text-white"
                      : "bg-[var(--bg)] text-[var(--text)]",
                  )}
                >
                  {m.image && m.role === "user" && (
                    <img src={m.image} alt="attachment" className="mb-2 max-h-40 rounded-[var(--r-md)]" />
                  )}
                  {m.role === "assistant" ? (
                    m.content ? (
                      <RichText text={m.content} />
                    ) : (
                      <TypingDots />
                    )
                  ) : (
                    m.content
                  )}
                  {m.action?.type === "plan_started" && m.action.job_id && (
                    <RunStatusCard jobId={m.action.job_id} close={() => onOpenChange(false)} />
                  )}
                </div>
              </div>
            ))}
          </div>

          <div className="border-t border-[var(--border)] p-3">
            {image && (
              <div className="mb-2 flex items-center gap-2">
                <img src={image} alt="preview" className="h-12 w-12 rounded-[var(--r-md)] object-cover" />
                <button onClick={() => setImage(null)} className="text-xs text-[var(--muted)] hover:underline">
                  Remove
                </button>
              </div>
            )}
            {uploading && (
              <div className="mb-2 flex items-center gap-2 text-xs text-[var(--muted)]">
                <span className="h-3 w-3 animate-spin rounded-full border-2 border-[var(--border)] border-t-[var(--brand-500)]" />
                Reading document…
              </div>
            )}
            {doc && (
              <div className="mb-2 flex items-center gap-2 rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--bg)] px-2.5 py-1.5">
                <Paperclip className="h-3.5 w-3.5 shrink-0 text-[var(--brand-500)]" />
                <span className="min-w-0 flex-1 truncate text-xs">
                  {doc.filename} <span className="text-[var(--muted)]">· {doc.kind}</span>
                </span>
                <button
                  onClick={() => setDoc(null)}
                  aria-label="Remove document"
                  className="shrink-0 text-[var(--muted)] hover:text-[var(--text)]"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            )}
            <div className="flex items-end gap-2">
              <input
                ref={fileRef}
                type="file"
                accept="image/*,application/pdf,.pdf,text/plain,.txt,.md"
                hidden
                onChange={onFile}
              />
              <button
                onClick={() => fileRef.current?.click()}
                disabled={uploading}
                aria-label="Attach image or document"
                className="grid h-10 w-10 shrink-0 place-items-center rounded-[var(--r-md)] border border-[var(--border)] text-[var(--muted)] hover:bg-[var(--bg)] disabled:opacity-50"
              >
                <Plus className="h-5 w-5" />
              </button>
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    void send();
                  }
                }}
                rows={1}
                placeholder="Ask anything about your trip…"
                className="max-h-32 min-h-[40px] min-w-0 flex-1 resize-none rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[var(--accent)]"
              />
              <Button
                onClick={() => void send()}
                loading={sending}
                disabled={!input.trim() && !doc}
                size="icon"
                aria-label="Send"
              >
                <ArrowUp className="h-5 w-5" />
              </Button>
            </div>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
