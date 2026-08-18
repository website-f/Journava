import { toast } from "sonner";
import { api } from "./api";
import type { PlanOption } from "@/stores/planStore";

/**
 * Outcome learning client (spec §7 ③).
 *
 * Accepting or rejecting a recommendation is the only feedback Journava gets
 * about whether its reasoning was any good, so the thumbs in the Research Board
 * have to reach the brain. They post here; the backend writes to Gnosion's
 * preference classifier and to `decision_outcomes`.
 */

export type OutcomeDomain =
  | "flight"
  | "hotel"
  | "activity"
  | "restaurant"
  | "research"
  | "itinerary";

type OutcomeResponse = {
  recorded: boolean;
  domain: string;
  accepted: boolean;
  persisted: boolean;
};

/** Record one accepted/rejected decision. Resolves false if the write failed. */
export async function recordOutcome(
  domain: OutcomeDomain,
  recommendation: Record<string, unknown>,
  accepted: boolean,
  options: { note?: string; silent?: boolean } = {},
): Promise<boolean> {
  try {
    const res = await api.post<OutcomeResponse>("/outcome", {
      domain,
      recommendation,
      accepted,
      user_note: options.note,
    });
    if (!options.silent) {
      toast.success(
        accepted
          ? "Noted — your agents will favour picks like this."
          : "Noted — your agents will avoid picks like this.",
      );
    }
    return res.recorded;
  } catch {
    if (!options.silent) toast.error("Could not save that feedback.");
    return false;
  }
}

/** Convenience wrapper for the common case: feedback on a ranked option. */
export function recordOptionOutcome(
  option: PlanOption,
  accepted: boolean,
): Promise<boolean> {
  const domain: OutcomeDomain =
    option.kind === "restaurant"
      ? "restaurant"
      : option.kind === "flight"
        ? "flight"
        : option.kind === "hotel"
          ? "hotel"
          : "activity";

  return recordOutcome(
    domain,
    {
      id: option.id,
      title: option.title,
      provider: option.provider,
      price_amount: option.price_amount,
      price_currency: option.price_currency,
      halal_confidence: option.halal_confidence,
      reasoning: option.reasoning,
    },
    accepted,
  );
}
