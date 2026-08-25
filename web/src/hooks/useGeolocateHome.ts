import { useEffect } from "react";
import { toast } from "sonner";
import { api } from "@/lib/api";

const FLAG = "journava:geo-detected";

type ProfileShape = { home_airport?: string | null } & Record<string, unknown>;

type ReverseGeo = {
  detected: boolean;
  source?: string;
  city?: string;
  label?: string;
  home_value?: string;
};

/**
 * One-time, best-effort home detection on first app open.
 *
 * Behaviour is deliberately unobtrusive:
 *  - runs once per browser (a localStorage flag), never on every mount;
 *  - only fills an EMPTY home airport — a value the traveller already set is
 *    left untouched (we still set the flag so we stop asking);
 *  - browser GPS first (accurate; the app is a secure context on localhost),
 *    falling back to server-side IP geolocation if permission is denied;
 *  - silent on any failure — a travel app must not nag for location.
 */
export function useGeolocateHome(enabled: boolean) {
  useEffect(() => {
    if (!enabled) return;
    if (localStorage.getItem(FLAG)) return;

    let cancelled = false;

    const run = async () => {
      let profile: ProfileShape | null = null;
      try {
        profile = await api.get<ProfileShape>("/profile");
      } catch {
        // No profile yet is fine — we'll create one with the detected home.
      }
      if (cancelled) return;

      // Respect an existing choice; just stop asking.
      if (profile?.home_airport) {
        localStorage.setItem(FLAG, "1");
        return;
      }

      const apply = async (body: { lat?: number; lon?: number }) => {
        localStorage.setItem(FLAG, "1"); // one attempt, whatever the outcome
        try {
          const res = await api.post<ReverseGeo>("/geo/reverse", body);
          if (cancelled || !res?.detected || !res.home_value) return;
          await api.post("/profile", { ...(profile ?? {}), home_airport: res.home_value });
          toast.success(
            `Detected you're near ${res.label ?? res.home_value}. Set as your home — change it in Account → Profile.`,
          );
        } catch {
          // ignore — detection is a convenience, not a requirement
        }
      };

      if ("geolocation" in navigator) {
        navigator.geolocation.getCurrentPosition(
          (pos) => void apply({ lat: pos.coords.latitude, lon: pos.coords.longitude }),
          () => void apply({}), // denied / unavailable → IP fallback
          { timeout: 8000, maximumAge: 10 * 60 * 1000 },
        );
      } else {
        void apply({});
      }
    };

    void run();
    return () => {
      cancelled = true;
    };
  }, [enabled]);
}
