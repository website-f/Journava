import { useEffect, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { motion } from "framer-motion";
import { toast } from "sonner";
import { ExternalLink, Eye, Plug, Plus, Trash2, X, Zap } from "@/components/ui/icons";
import { Button, EmptyState, Skeleton } from "@/components/ui";
import { cn } from "@/lib/cn";
import { api, ApiError } from "@/lib/api";

/**
 * Integrations — connect one or more Telegram bots so a background trip plan
 * pings you when it's ready. Each bot is a card with an enable toggle; add as
 * many as you like, edit or delete any.
 */

interface Bot {
  id: string;
  label: string;
  token_hint: string;
  chat_id: string;
  enabled: boolean;
}

export function Integrations() {
  const [bots, setBots] = useState<Bot[] | null>(null);
  const [editing, setEditing] = useState<Bot | "new" | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = async () => {
    try {
      setBots(await api.get<Bot[]>("/integrations/bots"));
    } catch {
      setBots([]);
    }
  };
  useEffect(() => {
    void load();
  }, []);

  const toggle = async (bot: Bot) => {
    setBusyId(bot.id);
    // Optimistic flip.
    setBots((prev) => prev?.map((b) => (b.id === bot.id ? { ...b, enabled: !b.enabled } : b)) ?? prev);
    try {
      await api.patch(`/integrations/bots/${bot.id}`, { enabled: !bot.enabled });
    } catch {
      toast.error("Could not update the bot.");
      await load();
    } finally {
      setBusyId(null);
    }
  };

  const test = async (bot: Bot) => {
    setBusyId(bot.id);
    try {
      const res = await api.post<{ ok: boolean; message: string }>(`/integrations/bots/${bot.id}/test`);
      if (res.ok) toast.success(`${bot.label}: test sent.`);
      else toast.warning(`${bot.label}: ${res.message}`);
    } catch (error) {
      toast.error(error instanceof ApiError ? error.detail : "Test failed.");
    } finally {
      setBusyId(null);
    }
  };

  const remove = async (bot: Bot) => {
    setBusyId(bot.id);
    try {
      await api.del(`/integrations/bots/${bot.id}`);
      await load();
      toast.success(`${bot.label} removed.`);
    } catch {
      toast.error("Could not remove the bot.");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="mx-auto w-full max-w-2xl">
      <header className="flex items-end justify-between gap-3 pt-2 pb-5">
        <div>
          <h2 className="flex items-center gap-2 font-[family-name:var(--font-display)] text-2xl tracking-tight">
            <Zap className="h-6 w-6 text-[var(--brand-500)]" />
            Integrate
          </h2>
          <p className="mt-1 text-sm text-[var(--muted)]">
            Telegram bots that get pinged when a background plan finishes.
          </p>
        </div>
        {bots && bots.length > 0 && (
          <Button size="sm" onClick={() => setEditing("new")}>
            <Plus className="h-4 w-4" />
            Add bot
          </Button>
        )}
      </header>

      {bots === null ? (
        <div className="space-y-3">
          {Array.from({ length: 2 }).map((_, i) => (
            <Skeleton key={i} className="h-20 w-full" />
          ))}
        </div>
      ) : bots.length === 0 ? (
        <div className="py-8">
          <EmptyState
            icon={<Plug className="h-10 w-10" />}
            title="No bots connected"
            description="Create a Telegram bot to get notified when a plan is ready."
          />
          <div className="mt-4 flex justify-center">
            <Button onClick={() => setEditing("new")}>
              <Plus className="h-4 w-4" />
              Create bot
            </Button>
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          {bots.map((bot) => (
            <div key={bot.id} className="surface-card flex flex-wrap items-center gap-3 p-4">
              <span
                className={cn(
                  "grid h-10 w-10 shrink-0 place-items-center rounded-full",
                  bot.enabled
                    ? "bg-[color-mix(in_srgb,var(--brand-400)_16%,transparent)] text-[var(--brand-500)]"
                    : "bg-[color-mix(in_srgb,var(--muted)_14%,transparent)] text-[var(--muted)]",
                )}
              >
                <Plug className="h-5 w-5" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold">{bot.label}</p>
                <p className="truncate text-[0.65rem] text-[var(--muted)]">
                  chat {bot.chat_id} · token {bot.token_hint}
                </p>
              </div>

              {/* Per-bot notification toggle */}
              <button
                type="button"
                role="switch"
                aria-checked={bot.enabled}
                aria-label="Receive notifications from this bot"
                disabled={busyId === bot.id}
                onClick={() => void toggle(bot)}
                className={cn(
                  "relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors",
                  bot.enabled ? "bg-[var(--brand-500)]" : "bg-[var(--border)]",
                )}
              >
                <span
                  className={cn(
                    "inline-block h-5 w-5 rounded-full bg-white shadow transition-transform",
                    bot.enabled ? "translate-x-[1.375rem]" : "translate-x-0.5",
                  )}
                />
              </button>

              <div className="flex w-full justify-end gap-1 sm:w-auto">
                <Button variant="ghost" size="icon" aria-label="Test" loading={busyId === bot.id} onClick={() => void test(bot)}>
                  <Eye className="h-4 w-4" />
                </Button>
                <Button variant="ghost" size="icon" aria-label="Edit" onClick={() => setEditing(bot)}>
                  <ExternalLink className="h-4 w-4 rotate-45" />
                </Button>
                <Button variant="ghost" size="icon" aria-label="Delete" onClick={() => void remove(bot)}>
                  <Trash2 className="h-4 w-4 text-[var(--danger)]" />
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}

      {editing && (
        <BotDialog
          bot={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            void load();
          }}
        />
      )}
    </div>
  );
}

function BotDialog({
  bot,
  onClose,
  onSaved,
}: {
  bot: Bot | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [label, setLabel] = useState(bot?.label ?? "");
  const [token, setToken] = useState("");
  const [chatId, setChatId] = useState(bot?.chat_id ?? "");
  const [enabled, setEnabled] = useState(bot?.enabled ?? true);
  const [busy, setBusy] = useState(false);
  const isEdit = Boolean(bot);

  const save = async () => {
    if (!label.trim()) return toast.error("Give the bot a name.");
    if (!chatId.trim()) return toast.error("Enter the chat id.");
    if (!isEdit && !token.trim()) return toast.error("Enter the bot token.");
    setBusy(true);
    try {
      if (isEdit) {
        await api.patch(`/integrations/bots/${bot!.id}`, {
          label: label.trim(),
          chat_id: chatId.trim(),
          enabled,
          ...(token.trim() ? { bot_token: token.trim() } : {}),
        });
        toast.success("Bot updated.");
      } else {
        const res = await api.post<{ test: { ok: boolean; message: string } }>("/integrations/bots", {
          label: label.trim(),
          bot_token: token.trim(),
          chat_id: chatId.trim(),
          enabled,
        });
        if (res.test?.ok) toast.success("Bot added — check Telegram for the confirmation.");
        else toast.warning(`Added, but test failed: ${res.test?.message ?? "check token & chat id"}`);
      }
      onSaved();
    } catch (error) {
      toast.error(error instanceof ApiError ? error.detail : "Could not save.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog.Root open onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay asChild>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="fixed inset-0 z-[85] bg-black/50 backdrop-blur-sm"
          />
        </Dialog.Overlay>
        <Dialog.Content asChild>
          <motion.div
            initial={{ opacity: 0, y: 16, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            className={cn(
              "fixed left-1/2 top-1/2 z-[86] w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2",
              "rounded-[var(--r-lg)] border border-[var(--border)] bg-[var(--elevated)] p-6 shadow-[var(--shadow-2)]",
            )}
          >
            <div className="flex items-start justify-between">
              <Dialog.Title className="font-[family-name:var(--font-display)] text-lg">
                {isEdit ? "Edit bot" : "Create Telegram bot"}
              </Dialog.Title>
              <Dialog.Close asChild>
                <Button variant="ghost" size="icon" aria-label="Close">
                  <X className="h-4 w-4" />
                </Button>
              </Dialog.Close>
            </div>

            {!isEdit && (
              <ol className="mt-3 space-y-1 text-xs text-[var(--muted)]">
                <li>
                  1. <a href="https://t.me/BotFather" target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-0.5 text-[var(--brand-500)] hover:underline">@BotFather <ExternalLink className="h-3 w-3" /></a> → <code>/newbot</code> → copy the token.
                </li>
                <li>
                  2. Message your bot, then <a href="https://t.me/userinfobot" target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-0.5 text-[var(--brand-500)] hover:underline">@userinfobot <ExternalLink className="h-3 w-3" /></a> for your chat id.
                </li>
              </ol>
            )}

            <div className="mt-4 grid gap-3">
              <label className="block">
                <span className="mb-1 block text-xs font-medium">Name</span>
                <input className="input-field" placeholder="e.g. My phone" value={label} onChange={(e) => setLabel(e.target.value)} />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-medium">
                  Bot token {isEdit && <span className="text-[var(--muted)]">(leave blank to keep)</span>}
                </span>
                <input
                  type="password"
                  autoComplete="off"
                  className="input-field font-[family-name:var(--font-mono)]"
                  placeholder={isEdit ? "Leave blank to keep the current token" : "123456:ABC-DEF…"}
                  value={token}
                  onChange={(e) => setToken(e.target.value)}
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-medium">Chat id</span>
                <input className="input-field font-[family-name:var(--font-mono)]" placeholder="e.g. 123456789" value={chatId} onChange={(e) => setChatId(e.target.value)} />
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} className="h-4 w-4 accent-[var(--brand-500)]" />
                Receive notifications from this bot
              </label>
            </div>

            <div className="mt-5 flex justify-end gap-2">
              <Button variant="ghost" onClick={onClose}>Cancel</Button>
              <Button loading={busy} onClick={() => void save()}>{isEdit ? "Save" : "Create & test"}</Button>
            </div>
          </motion.div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
