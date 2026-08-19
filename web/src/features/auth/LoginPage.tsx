import { type FormEvent, useState } from "react";
import { toast } from "sonner";
import { LogIn, UserPlus } from "@/components/ui/icons";
import { Button } from "@/components/ui";
import { useAuth } from "@/providers/AuthProvider";
import { cn } from "@/lib/cn";

type Mode = "signin" | "signup";

const FIELD = cn(
  "w-full h-11 rounded-[var(--r-md)] border border-[var(--border)]",
  "bg-[var(--surface)] px-4 text-[var(--text)] placeholder:text-[var(--muted)]",
  "outline-none transition-colors duration-[var(--dur)]",
  "focus-visible:border-[var(--brand-400)] focus-visible:ring-2 focus-visible:ring-[var(--accent)]",
);

/**
 * Auth-wall entry (spec §1). No native dialogs — errors surface as toasts, the
 * submit button owns its own loading/disabled state.
 */
export function LoginPage() {
  const { signIn, signUp } = useAuth();
  const [mode, setMode] = useState<Mode>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    try {
      if (mode === "signin") {
        await signIn(email.trim(), password);
      } else {
        await signUp(email.trim(), password, displayName.trim() || undefined);
        toast.success("Account created — welcome to Journava");
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-[100dvh] grid place-items-center bg-[var(--bg)] text-[var(--text)] p-6">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <h1 className="font-[family-name:var(--font-display)] text-3xl tracking-tight">
            Journava
          </h1>
          <p className="mt-1 text-sm text-[var(--muted)]">
            {mode === "signin"
              ? "Sign in to your travel workspace"
              : "Create your travel workspace"}
          </p>
        </div>

        <form
          onSubmit={submit}
          className="space-y-3 rounded-[var(--r-lg)] border border-[var(--border)] bg-[var(--surface)] p-6 shadow-[var(--shadow-1)]"
        >
          {mode === "signup" && (
            <div className="space-y-1.5">
              <label htmlFor="name" className="text-xs font-medium text-[var(--muted)]">
                Name
              </label>
              <input
                id="name"
                className={FIELD}
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                placeholder="Your name"
                autoComplete="name"
              />
            </div>
          )}

          <div className="space-y-1.5">
            <label htmlFor="email" className="text-xs font-medium text-[var(--muted)]">
              Email
            </label>
            <input
              id="email"
              type="email"
              required
              className={FIELD}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              autoComplete="email"
            />
          </div>

          <div className="space-y-1.5">
            <label htmlFor="password" className="text-xs font-medium text-[var(--muted)]">
              Password
            </label>
            <input
              id="password"
              type="password"
              required
              minLength={mode === "signup" ? 8 : undefined}
              className={FIELD}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              autoComplete={mode === "signin" ? "current-password" : "new-password"}
            />
          </div>

          <Button type="submit" loading={busy} className="w-full mt-2">
            {mode === "signin" ? (
              <>
                <LogIn className="h-4 w-4" /> Sign in
              </>
            ) : (
              <>
                <UserPlus className="h-4 w-4" /> Create account
              </>
            )}
          </Button>

          <button
            type="button"
            onClick={() => setMode(mode === "signin" ? "signup" : "signin")}
            className="w-full pt-1 text-center text-xs text-[var(--muted)] hover:text-[var(--text)]"
          >
            {mode === "signin"
              ? "No account? Create one"
              : "Already have an account? Sign in"}
          </button>
        </form>

        {import.meta.env.DEV && (
          <p className="mt-4 text-center text-[0.7rem] leading-relaxed text-[var(--muted)]">
            Demo — traveler@journava.test · hotel@journava.test · admin@journava.test
            <br />
            password: <span className="font-mono">Journava!2026</span>
          </p>
        )}
      </div>
    </div>
  );
}
