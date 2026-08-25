import { type ReactNode, useEffect, useState } from "react";
import { toast } from "sonner";
import { Switch } from "@/components/ui/Switch";
import { cn } from "@/lib/cn";
import { Button, Select, Badge } from "@/components/ui";
import { Page, SectionHeader } from "@/components/layout/Page";
import { Compass, Plane, Users, Utensils } from "@/components/ui/icons";
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

/** The accessibility needs that are real hard filters, kept as named toggles. */
const ACCESS_NEEDS: Array<{ key: string; label: string }> = [
  { key: "wheelchair", label: "Wheelchair access" },
  { key: "step_free", label: "Step-free routes" },
  { key: "ground_floor", label: "Ground floor rooms" },
  { key: "elevator", label: "Lift required" },
];

/**
 * Profile & Preferences (spec §3.5 / §7.5).
 *
 * Laid out as a native settings screen: grouped cards, one row per preference,
 * hairline dividers, the control on the trailing edge. A save bar sticks above
 * the tab bar so the button is reachable with a thumb without scrolling back —
 * the previous right-aligned button at the very bottom was a desktop habit.
 *
 * Standing preferences narrow agent scope; an absent preference means global
 * search. Flights are the exception — never filtered, only ranked (+ meal code).
 */
export function Profile() {
  const [profile, setProfile] = useState<ProfileData>(DEFAULT_PROFILE);
  const [loaded, setLoaded] = useState(false);
  const [dirty, setDirty] = useState(false);

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
    setDirty(false);
    toast.success("Preferences saved to Gnosion.");
  });

  const update = <K extends keyof ProfileData>(key: K, value: ProfileData[K]) => {
    setProfile((prev) => ({ ...prev, [key]: value }));
    setDirty(true);
  };

  /** Comma-separated text ⇄ string[], used by all three food fields. */
  const listField = (key: "allergies" | "cuisine_likes" | "cuisine_dislikes") => ({
    value: profile[key].join(", "),
    onChange: (e: React.ChangeEvent<HTMLInputElement>) =>
      update(key, e.target.value.split(",").map((s) => s.trim()).filter(Boolean)),
  });

  /** Unknown keys the backend may hold are preserved — only ours are written. */
  const setAccess = (key: string, value: unknown) => {
    const next = { ...profile.accessibility };
    if (value === false || value === "" || value == null) delete next[key];
    else next[key] = value;
    update("accessibility", next);
  };

  if (!loaded) return null;

  return (
    <Page width="md">
      {/* No page title here — AccountHub's identity card is the header for this
          tab, and a second h1 directly under the tab strip just repeats it. */}
      <p className="mb-6 text-sm leading-relaxed text-[var(--muted)]">
        Set these once. Every agent reads them — and they improve with each trip.
      </p>

      <div className="space-y-8">
        <section>
          <SectionHeader
            icon={<Utensils className="h-[1.15rem] w-[1.15rem]" />}
            title="Food & dietary"
            hint="Shapes restaurants and activities. Flights are never filtered by this."
          />
          <Card>
            <Row
              title="Halal required"
              description="Restaurants and activities become halal-only with a confidence label. Flights stay global — a halal meal (MOML) is requested at booking."
              control={
                <Switch
                  checked={profile.halal_required}
                  onCheckedChange={(v) => update("halal_required", v)}
                  aria-label="Halal required"
                />
              }
            >
              {profile.halal_required && (
                <div className="mt-2.5 flex flex-wrap gap-1.5">
                  <Badge variant="success">Hard filter: restaurants</Badge>
                  <Badge variant="info">Soft: hotels</Badge>
                  <Badge variant="default">Flights: MOML only</Badge>
                </div>
              )}
            </Row>

            <Field label="Allergies" hint="Comma-separated. Treated as a hard filter.">
              <input
                type="text"
                className="input-field"
                placeholder="e.g. peanuts, shellfish"
                {...listField("allergies")}
              />
            </Field>
            <Field label="Cuisine likes" hint="Ranked higher, never exclusive.">
              <input
                type="text"
                className="input-field"
                placeholder="e.g. ramen, seafood, Mediterranean"
                {...listField("cuisine_likes")}
              />
            </Field>
            <Field label="Cuisine dislikes">
              <input
                type="text"
                className="input-field"
                placeholder="e.g. raw fish, spicy"
                {...listField("cuisine_dislikes")}
              />
            </Field>
          </Card>
        </section>

        <section>
          <SectionHeader
            icon={<Compass className="h-[1.15rem] w-[1.15rem]" />}
            title="Interests"
            count={profile.interests.length}
            hint="What your days should lean towards."
          />
          <Card>
            <div className="flex flex-wrap gap-2 px-4 py-4">
              {INTERESTS.map((interest) => {
                const active = profile.interests.includes(interest);
                return (
                  <button
                    key={interest}
                    type="button"
                    aria-pressed={active}
                    onClick={() =>
                      update(
                        "interests",
                        active
                          ? profile.interests.filter((i) => i !== interest)
                          : [...profile.interests, interest],
                      )
                    }
                    className={cn(
                      "pressable rounded-[var(--r-pill)] px-3.5 py-2 text-[0.8125rem] font-semibold capitalize",
                      active
                        ? "bg-[var(--brand-500)] text-white shadow-[0_3px_10px_color-mix(in_srgb,var(--brand-500)_35%,transparent)]"
                        : "bg-[var(--bg)] text-[var(--muted)] ring-1 ring-inset ring-[var(--border)] hover:text-[var(--text)] hover:ring-[var(--brand-400)]",
                    )}
                  >
                    {interest}
                  </button>
                );
              })}
            </div>
          </Card>
        </section>

        <section>
          <SectionHeader
            icon={<Users className="h-[1.15rem] w-[1.15rem]" />}
            title="Trip defaults"
            hint="Pre-filled on every new plan, still editable per trip."
          />
          <Card>
            <Field label="Default pace">
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
            </Field>
            <Field
              label="Budget currency"
              hint="Every agent prices in this currency, and it's the default on results."
            >
              <Select
                value={profile.budget_currency}
                onValueChange={(v) => update("budget_currency", v)}
                aria-label="Budget currency"
                options={CURRENCIES}
              />
            </Field>
            <Field label="Travelling as" hint="Used to size rooms, tables and transfers.">
              <Select
                value={String(Math.max(1, profile.companions))}
                onValueChange={(v) => update("companions", Number(v))}
                aria-label="Travelling as"
                options={[
                  { value: "1", label: "Just me" },
                  { value: "2", label: "2 travellers" },
                  { value: "3", label: "3 travellers" },
                  { value: "4", label: "4 travellers" },
                  { value: "6", label: "5+ travellers" },
                ]}
              />
            </Field>
          </Card>
        </section>

        <section>
          <SectionHeader
            icon={<Plane className="h-[1.15rem] w-[1.15rem]" />}
            title="Flights"
            hint="These only affect ranking — flights always stay global (§7.5)."
          />
          <Card>
            <Field label="Home airport">
              <input
                type="text"
                className="input-field"
                value={profile.home_airport ?? ""}
                onChange={(e) => update("home_airport", e.target.value || null)}
                placeholder="e.g. KUL, SIN, LHR"
                autoCapitalize="characters"
              />
            </Field>
            <Field label="Max connections">
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
            </Field>
            <Field label="Seat preference">
              <Select
                value={profile.seat_preference ?? "none"}
                onValueChange={(v) =>
                  update("seat_preference", v === "none" ? null : (v as "window" | "aisle"))
                }
                aria-label="Seat preference"
                options={[
                  { value: "none", label: "No preference" },
                  { value: "window", label: "Window" },
                  { value: "aisle", label: "Aisle" },
                ]}
              />
            </Field>
            <Row
              title="Avoid red-eye flights"
              description="Overnight departures drop down the ranking instead of disappearing."
              control={
                <Switch
                  checked={profile.avoid_red_eye}
                  onCheckedChange={(v) => update("avoid_red_eye", v)}
                  aria-label="Avoid red-eye flights"
                />
              }
            />
          </Card>
        </section>

        <section>
          <SectionHeader
            title="Accessibility"
            hint="When set, these become hard filters for hotels and activities (§7.5)."
          />
          {/*
            Named toggles rather than the raw JSON textarea this used to be —
            asking a traveller to hand-write `{"wheelchair": true}` was never
            going to get filled in, so the filter never fired.
          */}
          <Card>
            {ACCESS_NEEDS.map(({ key, label }) => (
              <Row
                key={key}
                title={label}
                control={
                  <Switch
                    checked={profile.accessibility[key] === true}
                    onCheckedChange={(v) => setAccess(key, v)}
                    aria-label={label}
                  />
                }
              />
            ))}
            <Field label="Notes for your agents">
              <input
                type="text"
                className="input-field"
                value={typeof profile.accessibility.notes === "string" ? profile.accessibility.notes : ""}
                onChange={(e) => setAccess("notes", e.target.value)}
                placeholder="e.g. short walking distances, quiet rooms"
              />
            </Field>
          </Card>
        </section>
      </div>

      {/* Sticky save bar. Sits above the tab bar, and only appears once something
          actually changed so it isn't permanent furniture. */}
      {(dirty || save.loading) && (
        <div
          className="glass-strong sticky z-20 mt-8 flex items-center gap-3 rounded-[var(--r-lg)] p-3 shadow-[var(--shadow-2)]"
          style={{ bottom: "calc(var(--safe-bottom) + 6.75rem)" }}
        >
          <p className="min-w-0 flex-1 text-xs text-[var(--muted)]">Unsaved changes</p>
          <Button loading={save.loading} onClick={() => void save.run()}>
            Save preferences
          </Button>
        </div>
      )}
    </Page>
  );
}

/** A grouped settings card: children become rows separated by hairlines. */
function Card({ children }: { children: ReactNode }) {
  return (
    <div className="surface-card divide-y divide-[var(--border)] overflow-hidden p-0">{children}</div>
  );
}

/** Label + description on the leading edge, a control on the trailing edge. */
function Row({
  title,
  description,
  control,
  children,
}: {
  title: string;
  description?: string;
  control: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="px-4 py-4">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-[0.9375rem] font-medium leading-snug">{title}</p>
          {description && (
            <p className="mt-1 text-xs leading-relaxed text-[var(--muted)]">{description}</p>
          )}
        </div>
        <div className="shrink-0 pt-0.5">{control}</div>
      </div>
      {children}
    </div>
  );
}

/** A full-width input row: label above, control below, optional hint under it. */
function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="block px-4 py-4">
      <span className="mb-2 block text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-[var(--muted)]">
        {label}
      </span>
      {children}
      {hint && <span className="mt-1.5 block text-xs leading-relaxed text-[var(--muted)]">{hint}</span>}
    </label>
  );
}
