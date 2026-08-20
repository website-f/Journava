import { useEffect, useState } from "react";
import { toast } from "sonner";
import { CheckCircle2, ExternalLink, Eye, Plug, Trash2, Zap } from "@/components/ui/icons";
import { Button } from "@/components/ui";
import { StatusPill } from "@/components/ui/SourceBadge";
import { api, ApiError } from "@/lib/api";

interface TelegramStatus {
  configured: boolean;
  chat_id?: string | null;
  has_token?: boolean;
}

/**
 * Integrations — connect a Telegram bot so a background trip plan pings you when
 * it's ready. Fire a plan, walk away, get told when the agents are done.
 */
export function Integrations() {
  const [status, setStatus] = useState<TelegramStatus | null>(null);
  const [token, setToken] = useState("");
  const [chatId, setChatId] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  const load = async () => {
    try {
      const s = await api.get<TelegramStatus>("/integrations/telegram");
      setStatus(s);
      setChatId(s.chat_id ?? "");
    } catch {
      setStatus({ configured: false });
    }
  };
  useEffect(() => {
    void load();
  }, []);

  const save = async () => {
    if (!chatId.trim()) return toast.error("Enter your chat id first.");
    if (!token.trim() && !status?.has_token) return toast.error("Enter your bot token first.");
    setBusy("save");
    try {
      const res = await api.post<{ configured: boolean; test: { ok: boolean } }>(
        "/integrations/telegram",
        { bot_token: token.trim() || null, chat_id: chatId.trim() },
      );
      setToken("");
      await load();
      if (res.test?.ok) toast.success("Connected — check Telegram for the confirmation message.");
      else toast.warning("Saved, but the test message didn't arrive. Check the token and chat id.");
    } catch (error) {
      toast.error(error instanceof ApiError ? error.detail : "Could not save.");
    } finally {
      setBusy(null);
    }
  };

  const test = async () => {
    setBusy("test");
    try {
      const res = await api.post<{ ok: boolean; message: string }>("/integrations/telegram/test");
      if (res.ok) toast.success("Test message sent.");
      else toast.warning(res.message || "Test failed.");
    } catch (error) {
      toast.error(error instanceof ApiError ? error.detail : "Test failed.");
    } finally {
      setBusy(null);
    }
  };

  const disconnect = async () => {
    setBusy("disconnect");
    try {
      await api.del("/integrations/telegram");
      setToken("");
      setChatId("");
      await load();
      toast.success("Disconnected.");
    } catch {
      toast.error("Could not disconnect.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="mx-auto w-full max-w-2xl">
      <header className="pt-2 pb-5">
        <h2 className="flex items-center gap-2 font-[family-name:var(--font-display)] text-2xl tracking-tight">
          <Zap className="h-6 w-6 text-[var(--brand-500)]" />
          Integrate
        </h2>
        <p className="mt-1 text-sm text-[var(--muted)]">
          Connect a channel so Journava can reach you when a background job finishes.
        </p>
      </header>

      <section className="surface-card p-5">
        <div className="flex items-center justify-between gap-3">
          <h3 className="flex items-center gap-2 text-sm font-semibold">
            <Plug className="h-4 w-4 text-[var(--brand-500)]" />
            Telegram — trip-ready notifications
          </h3>
          <StatusPill
            status={status?.configured ? "healthy" : "untested"}
            detail={status?.configured ? "Connected" : "Not connected"}
          />
        </div>

        <ol className="mt-3 space-y-1 text-xs text-[var(--muted)]">
          <li>
            1. Open{" "}
            <a
              href="https://t.me/BotFather"
              target="_blank"
              rel="noreferrer noopener"
              className="inline-flex items-center gap-0.5 text-[var(--brand-500)] hover:underline"
            >
              @BotFather <ExternalLink className="h-3 w-3" />
            </a>{" "}
            → <code>/newbot</code> → copy the <strong>bot token</strong>.
          </li>
          <li>
            2. Message your new bot once, then open{" "}
            <a
              href="https://t.me/userinfobot"
              target="_blank"
              rel="noreferrer noopener"
              className="inline-flex items-center gap-0.5 text-[var(--brand-500)] hover:underline"
            >
              @userinfobot <ExternalLink className="h-3 w-3" />
            </a>{" "}
            to get your <strong>chat id</strong>.
          </li>
          <li>3. Paste both below, Save, and you'll get a confirmation ping.</li>
        </ol>

        <div className="mt-4 grid gap-3">
          <label className="block">
            <span className="mb-1 block text-xs font-medium">
              Bot token {status?.has_token && <span className="text-[var(--muted)]">(stored)</span>}
            </span>
            <input
              type="password"
              autoComplete="off"
              className="input-field font-[family-name:var(--font-mono)]"
              placeholder={status?.has_token ? "Leave blank to keep the current token" : "123456:ABC-DEF…"}
              value={token}
              onChange={(event) => setToken(event.target.value)}
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium">Chat id</span>
            <input
              className="input-field font-[family-name:var(--font-mono)]"
              placeholder="e.g. 123456789"
              value={chatId}
              onChange={(event) => setChatId(event.target.value)}
            />
          </label>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Button loading={busy === "save"} onClick={() => void save()}>
            <CheckCircle2 className="h-4 w-4" />
            {status?.configured ? "Update & test" : "Connect & test"}
          </Button>
          {status?.configured && (
            <>
              <Button variant="secondary" size="sm" loading={busy === "test"} onClick={() => void test()}>
                <Eye className="h-4 w-4" />
                Send test
              </Button>
              <Button variant="ghost" size="sm" loading={busy === "disconnect"} onClick={() => void disconnect()}>
                <Trash2 className="h-4 w-4 text-[var(--danger)]" />
                Disconnect
              </Button>
            </>
          )}
        </div>
      </section>
    </div>
  );
}
