import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { CheckCircle2, Check } from "@/components/ui/icons";
import { Button } from "./Button";
import { Badge } from "./Badge";
import { Select } from "./Select";
import { Modal } from "./Modal";
import { Money } from "./Money";
import { api } from "@/lib/api";
import { useBookings } from "@/stores/bookingsStore";

type MonitorResult = {
  disrupted?: boolean;
  reason?: string;
  status?: { status?: string; delay_minutes?: number | null; carrier?: string; route?: string; mode?: string };
  recovery?: { summary?: string; additional_cost?: string };
  alternatives?: { id: string; title: string; price_amount: number | null; price_currency: string | null; within_budget: boolean | null }[];
};

/**
 * "Booked" state + mark control for a flight/hotel option. Most consumer
 * bookings happen off-platform (via the OTA compare links), so the traveller
 * marks an option booked here — the card then locks to a Booked · ref · details
 * state (parent hides its own book buttons) instead of offering to book again.
 * Flights carry a direction (outbound/return); hotels carry a check-in date.
 */
export function BookingMark({
  kind, itemKey, title, provider, priceAmount, priceCurrency, snapshot, canMark = true,
}: {
  kind: "flight" | "hotel";
  itemKey: string;
  title: string;
  provider?: string | null;
  priceAmount?: number | null;
  priceCurrency?: string | null;
  snapshot?: unknown;
  /** Show the manual "Mark booked" control. False for Atlas (booked via purchase). */
  canMark?: boolean;
}) {
  const marks = useBookings((s) => s.marks);
  const load = useBookings((s) => s.load);
  const add = useBookings((s) => s.add);
  const remove = useBookings((s) => s.remove);
  useEffect(() => { void load(); }, [load]);

  const mine = useMemo(() => marks.filter((m) => m.item_key === itemKey), [marks, itemKey]);
  const [form, setForm] = useState<null | { direction: string; check_in: string; ref: string }>(null);
  const [detail, setDetail] = useState<(typeof mine)[number] | null>(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<MonitorResult | null>(null);
  const [checking, setChecking] = useState(false);

  const checkStatus = async () => {
    setChecking(true);
    try {
      // Reuses the trip's flight monitor: real status, and — if disrupted — the
      // recovery summary + best alternatives already bounded to the traveller's budget.
      setStatus(await api.post<MonitorResult>("/monitor/flight", { simulate: null, auto_reschedule: false, threshold_minutes: 90 }));
    } catch {
      toast.error("Couldn't check flight status.");
    } finally {
      setChecking(false);
    }
  };

  const confirm = async () => {
    setBusy(true);
    try {
      await add({
        item_kind: kind, item_key: itemKey,
        direction: kind === "flight" ? (form?.direction || "outbound") : "",
        title, provider: provider ?? null, price_amount: priceAmount ?? null, price_currency: priceCurrency ?? null,
        booking_ref: form?.ref?.trim() || undefined,
        check_in: kind === "hotel" ? (form?.check_in || undefined) : undefined,
        source: "external", snapshot,
      });
      toast.success("Marked as booked");
      setForm(null);
    } catch { toast.error("Couldn't save that."); } finally { setBusy(false); }
  };

  return (
    <div className="mt-2 space-y-1.5">
      {mine.map((m) => (
        <div key={m.id} className="flex flex-wrap items-center gap-2 rounded-[var(--r-md)] bg-[color-mix(in_srgb,var(--success)_12%,transparent)] px-2.5 py-1.5 text-xs">
          <CheckCircle2 className="h-4 w-4 shrink-0 text-[var(--success)]" weight="fill" />
          <span className="font-semibold text-[var(--success)]">Booked</span>
          {m.direction && <Badge variant="success">{m.direction}</Badge>}
          {m.check_in && <span className="text-[var(--muted)]">check-in {m.check_in}</span>}
          {m.booking_ref && <span className="font-[family-name:var(--font-mono)] text-[var(--muted)]">{m.booking_ref}</span>}
          <span className="ml-auto flex items-center gap-2">
            <button onClick={() => setDetail(m)} className="text-[var(--brand-600)] hover:underline">View details</button>
            <button onClick={() => void remove(m.id)} className="text-[var(--muted)] hover:text-[var(--danger)]">Unmark</button>
          </span>
        </div>
      ))}

      {kind === "flight" && mine.length > 0 && (
        <div className="rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--bg)] p-2.5">
          {/* Stack on a narrow card so the label and button never collide; the
              button goes full-width on mobile (a proper tap target) and only
              sits inline once there's room. */}
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <span className="text-xs font-medium">Flight status &amp; delays</span>
            <Button size="sm" variant="secondary" className="w-full sm:w-auto" onClick={() => void checkStatus()} loading={checking}>Check for delays</Button>
          </div>
          {status && (status.reason ? (
            <p className="mt-1.5 text-xs text-[var(--muted)]">{status.reason}</p>
          ) : !status.disrupted ? (
            <p className="mt-1.5 flex items-center gap-1 text-xs text-[var(--success)]">
              <CheckCircle2 className="h-3.5 w-3.5" /> On time{status.status?.carrier ? ` — ${status.status.carrier} ${status.status.route ?? ""}` : ""}
            </p>
          ) : (
            <div className="mt-1.5 space-y-1">
              <p className="text-xs font-semibold text-[var(--warning)]">
                Disrupted{status.status?.delay_minutes ? ` · ~${status.status.delay_minutes} min` : ""} — {status.recovery?.summary}
              </p>
              {(status.alternatives ?? []).slice(0, 3).map((a) => (
                <div key={a.id} className="flex items-center justify-between gap-2 text-xs">
                  <span className="min-w-0 truncate text-[var(--muted)]">{a.title}</span>
                  {a.price_amount != null && (
                    <span className={a.within_budget ? "text-[var(--success)]" : "text-[var(--warning)]"}>
                      <Money amount={a.price_amount} currency={a.price_currency ?? "MYR"} />
                    </span>
                  )}
                </div>
              ))}
              <p className="text-[0.65rem] text-[var(--muted)]">Suggested alternatives — book one and mark it as your new flight.</p>
            </div>
          ))}
        </div>
      )}

      {canMark && mine.length === 0 && (
        <button
          onClick={() => setForm({ direction: "outbound", check_in: "", ref: "" })}
          className="inline-flex items-center gap-1.5 rounded-[var(--r-pill)] border border-dashed border-[var(--border)] px-2.5 py-1 text-xs font-medium text-[var(--muted)] transition-colors hover:border-[var(--brand-400)] hover:text-[var(--brand-600)]"
        >
          <Check className="h-3.5 w-3.5" /> {kind === "hotel" ? "Mark booked (I booked this)" : "Mark booked"}
        </button>
      )}

      {/* Mark form */}
      <Modal
        open={!!form}
        onOpenChange={(o) => { if (!o) setForm(null); }}
        title="Mark as booked"
        description={title}
        icon={<Check className="h-5 w-5" />}
        footer={<>
          <Button variant="ghost" onClick={() => setForm(null)}>Cancel</Button>
          <Button onClick={confirm} loading={busy}>Mark booked</Button>
        </>}
      >
        {form && (
          <div className="space-y-3">
            {kind === "flight" ? (
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-[var(--muted)]">Which leg?</span>
                <Select value={form.direction} onValueChange={(v) => setForm({ ...form, direction: v })}
                  options={[{ value: "outbound", label: "Outbound (go)" }, { value: "return", label: "Return (back)" }]} aria-label="leg" />
              </label>
            ) : (
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-[var(--muted)]">Check-in date</span>
                <input type="date" value={form.check_in} onChange={(e) => setForm({ ...form, check_in: e.target.value })}
                  className="w-full rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm outline-none focus:border-[var(--brand-400)]" />
              </label>
            )}
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-[var(--muted)]">Booking reference (optional)</span>
              <input value={form.ref} onChange={(e) => setForm({ ...form, ref: e.target.value })} placeholder="Auto-generated if blank"
                className="w-full rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm outline-none focus:border-[var(--brand-400)]" />
            </label>
          </div>
        )}
      </Modal>

      {/* Detail */}
      <Modal
        open={!!detail}
        onOpenChange={(o) => { if (!o) setDetail(null); }}
        title="Booking details"
        icon={<CheckCircle2 className="h-5 w-5" />}
        footer={<Button variant="ghost" onClick={() => setDetail(null)}>Close</Button>}
      >
        {detail && (
          <div className="space-y-0">
            <Row label="Status"><Badge variant="success">{detail.status}</Badge></Row>
            <Row label="Item">{detail.title}</Row>
            {detail.direction && <Row label="Leg">{detail.direction}</Row>}
            {detail.provider && <Row label="Provider">{detail.provider}</Row>}
            {detail.price_amount != null && <Row label="Price"><Money amount={detail.price_amount} currency={detail.price_currency ?? "MYR"} /></Row>}
            {detail.check_in && <Row label="Check-in">{detail.check_in}</Row>}
            {detail.booking_ref && <Row label="Reference"><span className="font-[family-name:var(--font-mono)]">{detail.booking_ref}</span></Row>}
            {detail.source && <Row label="Booked via">{detail.source === "external" ? "External (OTA / direct)" : detail.source}</Row>}
            {detail.created_at && <Row label="Marked on">{detail.created_at.slice(0, 10)}</Row>}
          </div>
        )}
      </Modal>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-[var(--border)] py-2 last:border-0">
      <span className="text-xs text-[var(--muted)]">{label}</span>
      <span className="min-w-0 text-right text-sm font-medium">{children}</span>
    </div>
  );
}
