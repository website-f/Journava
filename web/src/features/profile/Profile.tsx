import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Switch } from "@/components/ui/Switch";
import { cn } from "@/lib/cn";
import { Button, Select, Badge } from "@/components/ui";
import { CURRENCIES } from "@/lib/currencies";
import { useAsync } from "@/lib/useAsync";
import { api } from "@/lib/api";

interface ProfileData {
  halal_required: boolean;
  allergies: string[];
  cuisine_likes: string[];
  cuisine_dislikes: string[];
  interests: string[];
  pace: "relaxed" | "balanced" | "packed";
  budget_currency: string;
  home_airport: string | null;
  max_connections: number | null;
  avoid_red_eye: boolean;
  seat_preference: "window" | "aisle" | "none" | null;
  accessibility: Record<string, unknown>;
  companions: number;
}

const DEFAULT_PROFILE: ProfileData = {
  halal_required: false,
  allergies: [],
  cuisine_likes: [],
  cuisine_dislikes: [],
  interests: [],
  pace: "balanced",
  budget_currency: "MYR",
  home_airport: null,
  max_connections: null,
  avoid_red_eye: false,
  seat_preference: null,
  accessibility: {},
  companions: 1,
};

const INTERESTS = ["culture", "food", "nature", "nightlife", "adventure", "shopping", "history", "art"];

/**
 * Profile & Preferences (spec §3.5 / §7.5).
 * Standing preferences narrow agent scope; an absent preference means global
 * search. Flights are the exception — never filtered, only ranked (+ meal code).
 */
export function Profile() {
  const [profile, setProfile] = useState<ProfileData>(DEFAULT_PROFILE);
  const [loaded, setLoaded] = useState(false);

  // Load existing profile on mount
  useEffect(() => {
    api.get<ProfileData>("/profile")
      .then((data) => {
        setProfile({ ...DEFAULT_PROFILE, ...data });
        setLoaded(true);
      })
      .catch(() => {
        setLoaded(true);
      });
  }, []);

  const save = useAsync(async () => {
    await api.post("/profile", profile);
    toast.success("Preferences saved to Gnosion.");
  });

  const update = <K extends keyof ProfileData>(key: K, value: ProfileData[K]) => {
    setProfile((prev) => ({ ...prev, [key]: value }));
  };

  if (!loaded) return null;

  return (
    <div className="mx-auto w-full max-w-2xl">
      <header className="pt-2 pb-6">
        <h2 className="font-[family-name:var(--font-display)] text-2xl tracking-tight">
          Profile & Preferences
        </h2>
        <p className="mt-1 text-sm text-[var(--muted)]">
          Set these once. Every agent reads them — and they improve with each trip.
        </p>
      </header>

      <div className="space-y-4">
        {/* Halal toggle */}
        <section className="surface-card p-5">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <h3 className="text-sm font-semibold">Halal required</h3>
              <p className="mt-1 text-xs text-[var(--muted)]">
                Restaurants and activities become halal-only with a confidence label.
                Flights stay global — a halal meal (MOML) is requested at booking.
              </p>
              {profile.halal_required && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  <Badge variant="success">Hard filter: restaurants</Badge>
                  <Badge variant="info">Soft: hotels</Badge>
                  <Badge variant="default">Flights: MOML only</Badge>
                </div>
              )}
            </div>
            <Switch
              checked={profile.halal_required}
              onCheckedChange={(v) => update("halal_required", v)}
              aria-label="Halal required"
            />
          </div>
        </section>

        {/* Dietary */}
        <section className="surface-card p-5 space-y-4">
          <h3 className="text-sm font-semibold">Dietary & Food</h3>
          <label className="block">
            <span className="mb-1 block text-xs text-[var(--muted)]">Allergies (comma-separated)</span>
            <input
              type="text"
              value={profile.allergies.join(", ")}
              onChange={(e) => update("allergies", e.target.value.split(",").map((s) => s.trim()).filter(Boolean))}
              placeholder="e.g. peanuts, shellfish"
              className="w-full h-10 rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--surface)] px-3 text-sm outline-none focus:ring-2 focus:ring-[var(--accent)]"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs text-[var(--muted)]">Cuisine likes</span>
            <input
              type="text"
              value={profile.cuisine_likes.join(", ")}
              onChange={(e) => update("cuisine_likes", e.target.value.split(",").map((s) => s.trim()).filter(Boolean))}
              placeholder="e.g. ramen, seafood, Mediterranean"
              className="w-full h-10 rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--surface)] px-3 text-sm outline-none focus:ring-2 focus:ring-[var(--accent)]"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs text-[var(--muted)]">Cuisine dislikes</span>
            <input
              type="text"
              value={profile.cuisine_dislikes.join(", ")}
              onChange={(e) => update("cuisine_dislikes", e.target.value.split(",").map((s) => s.trim()).filter(Boolean))}
              placeholder="e.g. raw fish, spicy"
              className="w-full h-10 rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--surface)] px-3 text-sm outline-none focus:ring-2 focus:ring-[var(--accent)]"
            />
          </label>
        </section>

        {/* Interests */}
        <section className="surface-card p-5 space-y-3">
          <h3 className="text-sm font-semibold">Interests</h3>
          <div className="flex flex-wrap gap-2">
            {INTERESTS.map((interest) => {
              const active = profile.interests.includes(interest);
              return (
                <button
                  key={interest}
                  type="button"
                  onClick={() => update("interests", active
                    ? profile.interests.filter((i) => i !== interest)
                    : [...profile.interests, interest]
                  )}
                  className={cn(
                    "rounded-[var(--r-pill)] px-3 py-1.5 text-xs font-medium capitalize transition-colors",
                    "duration-[var(--dur)] ease-[var(--ease)]",
                    active
                      ? "bg-[var(--brand-500)] text-white"
                      : "bg-[var(--bg)] text-[var(--muted)] border border-[var(--border)] hover:border-[var(--brand-400)]",
                  )}
                >
                  {interest}
                </button>
              );
            })}
          </div>
        </section>

        {/* Travel preferences */}
        <section className="surface-card p-5 grid gap-4 sm:grid-cols-2">
          <label className="block">
            <span className="mb-2 block text-sm font-medium">Default pace</span>
            <Select
              value={profile.pace}
              onValueChange={(v) => update("pace", v as ProfileData["pace"])}
              aria-label="Default pace"
              options={[
                { value: "relaxed", label: "Relaxed" },
                { value: "balanced", label: "Balanced" },
                { value: "packed", label: "Packed" },
              ]}
            />
          </label>
          <label className="block">
            <span className="mb-2 block text-sm font-medium">Budget currency</span>
            <Select
              value={profile.budget_currency}
              onValueChange={(v) => update("budget_currency", v)}
              aria-label="Budget currency"
              options={CURRENCIES}
            />
            <p className="mt-1 text-xs text-[var(--muted)]">
              Every agent prices in this currency, and it's the default on results.
            </p>
          </label>
          <label className="block">
            <span className="mb-2 block text-sm font-medium">Home airport</span>
            <input
              type="text"
              value={profile.home_airport ?? ""}
              onChange={(e) => update("home_airport", e.target.value || null)}
              placeholder="e.g. KUL, SIN, LHR"
              className="w-full h-10 rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--surface)] px-3 text-sm outline-none focus:ring-2 focus:ring-[var(--accent)]"
            />
          </label>
          <label className="block">
            <span className="mb-2 block text-sm font-medium">Max connections</span>
            <Select
              value={profile.max_connections?.toString() ?? "any"}
              onValueChange={(v) => update("max_connections", v === "any" ? null : Number(v))}
              aria-label="Max connections"
              options={[
                { value: "any", label: "Any" },
                { value: "0", label: "Direct only" },
                { value: "1", label: "Max 1 stop" },
                { value: "2", label: "Max 2 stops" },
              ]}
            />
          </label>
        </section>

        {/* Flight preferences */}
        <section className="surface-card p-5 space-y-4">
          <h3 className="text-sm font-semibold">Flight Preferences</h3>
          <p className="text-xs text-[var(--muted)]">
            These only affect ranking — flights always stay global (§7.5).
          </p>
          <div className="flex items-center justify-between">
            <span className="text-sm">Avoid red-eye flights</span>
            <Switch
              checked={profile.avoid_red_eye}
              onCheckedChange={(v) => update("avoid_red_eye", v)}
              aria-label="Avoid red-eye flights"
            />
          </div>
          <label className="block">
            <span className="mb-2 block text-sm">Seat preference</span>
            <Select
              value={profile.seat_preference ?? "none"}
              onValueChange={(v) => update("seat_preference", v === "none" ? null : v as "window" | "aisle")}
              aria-label="Seat preference"
              options={[
                { value: "none", label: "No preference" },
                { value: "window", label: "Window" },
                { value: "aisle", label: "Aisle" },
              ]}
            />
          </label>
        </section>

        {/* Accessibility */}
        <section className="surface-card p-5 space-y-3">
          <h3 className="text-sm font-semibold">Accessibility</h3>
          <p className="text-xs text-[var(--muted)]">
            When set, this becomes a hard filter for hotels and activities (§7.5).
          </p>
          <textarea
            value={JSON.stringify(profile.accessibility) === "{}" ? "" : JSON.stringify(profile.accessibility)}
            onChange={(e) => {
              try {
                const parsed = e.target.value ? JSON.parse(e.target.value) : {};
                update("accessibility", parsed);
              } catch {
                // Allow free typing until valid JSON
              }
            }}
            placeholder='e.g. {"wheelchair": true, "notes": "Ground floor preferred"}'
            rows={2}
            className="w-full rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[var(--accent)] resize-none"
          />
        </section>
      </div>

      <div className="mt-6 flex justify-end">
        <Button loading={save.loading} onClick={() => void save.run()}>
          Save preferences
        </Button>
      </div>
    </div>
  );
}
