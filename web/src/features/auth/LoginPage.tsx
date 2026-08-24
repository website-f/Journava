import { type FormEvent, useState } from "react";
import { toast } from "sonner";
import { Compass, LogIn, ShieldCheck, Sparkles, UserPlus, Wallet } from "@/components/ui/icons";
import { Button } from "@/components/ui";
import { useAuth } from "@/providers/AuthProvider";
import { cn } from "@/lib/cn";

type Mode = "signin" | "signup";

const FIELD = cn(
  "w-full h-12 rounded-[var(--r-md)] border border-[var(--border)]",
  "bg-[var(--surface)] px-4 text-[0.9375rem] text-[var(--text)] placeholder:text-[var(--muted)]",
  "outline-none transition-[border-color,box-shadow] duration-[var(--dur)]",
  "focus-visible:border-[var(--brand-400)] focus-visible:ring-2 focus-visible:ring-[var(--accent)]",
);

const LABEL = "text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-[var(--muted)]";

/** What the traveller actually gets — shown on the brand panel, not marketing fluff. */
const PITCH: Array<{ icon: typeof Compass; title: string; body: string }> = [
  {
    icon: Sparkles,
    title: "21 agents, one brief",
    body: "Say where you're going. Flights, stays, food, visas and safety come back together.",
  },
  {
    icon: Wallet,
    title: "Priced in your currency",
    body: "Live FX on every fare, so a Tokyo flight crawled in USD still reads in ringgit.",
  },
  {
    icon: ShieldCheck,
    title: "Watched after you book",
    body: "Your agents keep tracking fares, weather and local news until you're home.",
  },
];

/**
 * Auth-wall entry (spec §1).
 *
 * A split layout: a solid deep-teal brand panel that carries the product story on
 * tablet and up, and the form column that is the whole screen on a phone. The
 * panel is a flat fill with a single sand rule rather than a gradient or a stock
 * travel photo — the rest of the app is flat by design, and a login screen that
 * doesn't match the app it opens is the first thing that reads as generic.
 *
 * No native dialogs — errors surface as toasts, the submit button owns its own
 * loading/disabled state.
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
    <div className="min-h-[100dvh] bg-[var(--bg)] text-[var(--text)] lg:grid lg:grid-cols-[1.05fr_1fr]">
      <BrandPanel />

      <main
        className="flex min-h-[100dvh] flex-col justify-center px-5 py-10 sm:px-8 lg:min-h-0 lg:px-12"
        style={{ paddingTop: "calc(2.5rem + var(--safe-top))", paddingBottom: "calc(2.5rem + var(--safe-bottom))" }}
      >
        <div className="mx-auto w-full max-w-[24rem]">
          {/* Phones don't get the brand panel, so the mark comes back here. */}
          <div className="mb-8 lg:hidden">
            <BrandMark />
          </div>

          <h2 className="font-[family-name:var(--font-display)] text-[1.75rem] font-bold leading-[1.15] tracking-[-0.025em]">
            {mode === "signin" ? "Welcome back" : "Create your workspace"}
          </h2>
          <p className="mt-1.5 text-sm leading-relaxed text-[var(--muted)]">
            {mode === "signin"
              ? "Pick up where your agents left off."
              : "One account holds your trips, budget and agent memory."}
          </p>

          {/* A segmented control, not a link buried under the button — switching
              intent is a primary action on an auth screen, not an afterthought. */}
          <div
            role="tablist"
            aria-label="Account"
            className="mt-6 grid grid-cols-2 gap-1 rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--surface)] p-1"
          >
            {(["signin", "signup"] as const).map((value) => (
              <button
                key={value}
                type="button"
                role="tab"
                aria-selected={mode === value}
                onClick={() => setMode(value)}
                className={cn(
                  "rounded-[calc(var(--r-md)-4px)] py-2 text-[0.8125rem] font-semibold",
                  "transition-colors duration-[var(--dur)] active:scale-[0.98]",
                  mode === value
                    ? "bg-[var(--brand-600)] text-white shadow-[var(--shadow-1)]"
                    : "text-[var(--muted)] hover:text-[var(--text)]",
                )}
              >
                {value === "signin" ? "Sign in" : "Sign up"}
              </button>
            ))}
          </div>

          <form onSubmit={submit} className="mt-6 space-y-4">
            {mode === "signup" && (
              <div className="space-y-1.5">
                <label htmlFor="name" className={LABEL}>
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
              <label htmlFor="email" className={LABEL}>
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
                inputMode="email"
              />
            </div>

            <div className="space-y-1.5">
              <label htmlFor="password" className={LABEL}>
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
              {mode === "signup" && (
                <p className="text-[0.7rem] text-[var(--muted)]">At least 8 characters.</p>
              )}
            </div>

            <Button type="submit" loading={busy} size="lg" className="mt-2 w-full">
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
          </form>

          {import.meta.env.DEV && (
            <div className="mt-8 rounded-[var(--r-md)] border border-dashed border-[var(--border)] p-3.5">
              <p className={LABEL}>Demo accounts</p>
              <p className="mt-1.5 text-[0.7rem] leading-relaxed text-[var(--muted)]">
                traveler@journava.test · hotel@journava.test · admin@journava.test
                <br />
                password <span className="font-[family-name:var(--font-mono)]">Journava!2026</span>
              </p>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

function BrandMark({ tone = "light" }: { tone?: "light" | "dark" }) {
  return (
    <div className="flex items-center gap-2.5">
      <span
        className={cn(
          "grid h-9 w-9 place-items-center rounded-[var(--r-md)]",
          tone === "dark" ? "bg-white/12 text-white" : "bg-[var(--brand-600)] text-white",
        )}
      >
        <Compass className="h-5 w-5" weight="bold" />
      </span>
      <span
        className={cn(
          "font-[family-name:var(--font-display)] text-[1.375rem] font-bold tracking-[-0.02em]",
          tone === "dark" && "text-white",
        )}
      >
        Journava
      </span>
    </div>
  );
}

/**
 * The story column. Hidden below `lg` rather than stacked above the form — on a
 * phone, three value props between the traveller and the password field is a
 * landing page, not an app.
 */
function BrandPanel() {
  return (
    <aside className="relative hidden overflow-hidden bg-[var(--brand-600)] text-white lg:flex lg:flex-col lg:justify-between lg:p-12">
      <span aria-hidden className="absolute inset-x-0 top-0 h-[3px] bg-[var(--accent)]" />

      <BrandMark tone="dark" />

      <div className="max-w-[30rem]">
        <h1 className="font-[family-name:var(--font-display)] text-[3rem] font-bold leading-[1.02] tracking-[-0.035em] xl:text-[3.5rem]">
          Plan the whole trip
          <br />
          <span className="text-[var(--accent)]">in one sentence.</span>
        </h1>

        <ul className="mt-10 space-y-6">
          {PITCH.map(({ icon: Icon, title, body }) => (
            <li key={title} className="flex gap-4">
              <span className="mt-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-[var(--r-md)] bg-white/10 ring-1 ring-inset ring-white/15">
                <Icon className="h-[1.15rem] w-[1.15rem]" />
              </span>
              <div className="min-w-0">
                <p className="text-[0.9375rem] font-semibold">{title}</p>
                <p className="mt-1 text-[0.8125rem] leading-relaxed text-white/65">{body}</p>
              </div>
            </li>
          ))}
        </ul>
      </div>

      <p className="text-[0.7rem] uppercase tracking-[0.16em] text-white/40">
        Agentic travel, end to end
      </p>
    </aside>
  );
}
