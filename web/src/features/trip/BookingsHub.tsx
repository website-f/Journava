import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import * as Dialog from "@radix-ui/react-dialog";
import { motion } from "framer-motion";
import {
  ArrowRight,
  Clock,
  CreditCard,
  Plane,
  ShoppingCart,
  Ticket,
  X,
  RefreshCw,
  CheckCircle2,
  AlertTriangle,
  Loader2,
} from "@/components/ui/icons";
import { toast } from "sonner";
import { Button, EmptyState, Skeleton } from "@/components/ui";
import { cn } from "@/lib/cn";
import { api } from "@/lib/api";
import type { BookingStage, FlightBooking } from "@/lib/types";
import { BookingDialog } from "@/features/flights/BookingDialog";

/**
 * The traveller's bookings, split into two honest views:
 *
 * - **Orders** — anything still in flight (drafted, verified, ordered, paying, or
 *   failed). These are resumable: pick up exactly where you stopped.
 * - **Payments** — completed purchases (paid / ticketed), each openable as a
 *   receipt. This is the purchase history.
 *
 * Both read the one `/history/bookings` feed and filter by stage, so a booking
 * moves from Orders to Payments automatically as it progresses.
 */

const PENDING_STAGES = new Set<BookingStage>(["draft", "price_confirmed", "ordered", "paying"]);
const DONE_STAGES = new Set<BookingStage>(["paid", "ticketed"]);

const STAGE_META: Record<BookingStage, { label: string; tone: string; next?: string }> = {
  draft: { label: "Selected", tone: "muted", next: "Verify the fare" },
  price_confirmed: { label: "Price confirmed", tone: "brand", next: "Add passenger & order" },
  ordered: { label: "Awaiting payment", tone: "warning", next: "Pay now" },
  paying: { label: "Payment processing", tone: "warning", next: "Check status" },
  paid: { label: "Paid", tone: "success" },
  ticketed: { label: "Ticketed", tone: "success" },
  failed: { label: "Failed", tone: "danger", next: "Review" },
};

const TONE_CLASS: Record<string, string> = {
  muted: "text-[var(--muted)] bg-[color-mix(in_srgb,var(--muted)_14%,transparent)]",
  brand: "text-[var(--brand-500)] bg-[color-mix(in_srgb,var(--brand-400)_16%,transparent)]",
  warning: "text-[var(--warning)] bg-[color-mix(in_srgb,var(--warning)_16%,transparent)]",
  success: "text-[var(--success)] bg-[color-mix(in_srgb,var(--success)_14%,transparent)]",
  danger: "text-[var(--danger)] bg-[color-mix(in_srgb,var(--danger)_14%,transparent)]",
};

function when(value: string | null): string {
  if (!value) return "";
  const d = new Date(value);
  return Number.isNaN(d.getTime())
    ? ""
    : d.toLocaleString(undefined, { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

function money(b: FlightBooking): string | null {
  return b.total_amount != null ? `${b.currency ?? ""} ${Number(b.total_amount).toLocaleString()}`.trim() : null;
}

export function BookingsHub({ mode }: { mode: "pending" | "payments" }) {
  const qc = useQueryClient();
  const [resume, setResume] = useState<FlightBooking | null>(null);
  const [receipt, setReceipt] = useState<FlightBooking | null>(null);
  const [recover, setRecover] = useState<FlightBooking | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["bookings"],
    queryFn: () => api.get<FlightBooking[]>("/history/bookings"),
  });

  const rows = (data ?? []).filter((b) =>
    mode === "pending"
      ? PENDING_STAGES.has(b.stage) || b.stage === "failed"
      : DONE_STAGES.has(b.stage),
  );

  const refresh = () => void qc.invalidateQueries({ queryKey: ["bookings"] });

  if (isLoading) {
    return (
      <div className="space-y-3 py-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-24 w-full" />
        ))}
      </div>
    );
  }

  if (rows.length === 0) {
    return (
      <div className="py-10">
        <EmptyState
          icon={mode === "pending" ? <ShoppingCart className="h-10 w-10" /> : <CreditCard className="h-10 w-10" />}
          title={mode === "pending" ? "No orders in progress" : "No payments yet"}
          description={
            mode === "pending"
              ? "Start a flight booking and it shows up here — you can stop any time and resume later."
              : "Completed purchases and their receipts will appear here."
          }
        />
      </div>
    );
  }

  return (
    <div className="space-y-3 py-3">
      {rows.map((b) => {
        const meta = STAGE_META[b.stage];
        return (
          <div key={b.id} className="surface-card flex flex-wrap items-center gap-3 p-4">
            <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-[color-mix(in_srgb,var(--brand-400)_14%,transparent)]">
              {b.stage === "ticketed" ? (
                <Ticket className="h-5 w-5 text-[var(--brand-500)]" />
              ) : (
                <Plane className="h-5 w-5 text-[var(--brand-500)]" />
              )}
            </span>

            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-semibold">{b.route ?? "Flight"}</p>
              <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.65rem] text-[var(--muted)]">
                {b.depart_date && <span>Depart {b.depart_date}</span>}
                <span className="flex items-center gap-1">
                  <Clock className="h-3 w-3" /> {when(b.updated_at ?? b.created_at)}
                </span>
                {b.simulated && <span className="uppercase tracking-wide">Sandbox</span>}
              </div>
            </div>

            <div className="text-right">
              {money(b) && <p className="text-sm font-semibold">{money(b)}</p>}
              <span
                className={cn(
                  "mt-1 inline-flex items-center gap-1 rounded-[var(--r-pill)] px-2 py-0.5 text-[0.6rem] font-semibold uppercase tracking-wide",
                  TONE_CLASS[meta.tone],
                )}
              >
                {meta.label}
              </span>
            </div>

            <div className="flex w-full justify-end gap-2 sm:w-auto">
              {mode === "pending" ? (
                <Button size="sm" onClick={() => setResume(b)}>
                  {meta.next ?? "Resume"}
                  <ArrowRight className="h-4 w-4" />
                </Button>
              ) : (
                <>
                  {b.stage === "paid" && (
                    <Button variant="secondary" size="sm" onClick={() => setResume(b)}>
                      Check ticket status
                    </Button>
                  )}
                  <Button variant="secondary" size="sm" onClick={() => setRecover(b)}>
                    <RefreshCw className="h-4 w-4" /> Flight disrupted?
                  </Button>
                  <Button variant="secondary" size="sm" onClick={() => setReceipt(b)}>
                    View receipt
                  </Button>
                </>
              )}
            </div>
          </div>
        );
      })}

      {resume && (
        <BookingDialog
          initialBooking={resume}
          onClose={() => {
            setResume(null);
            refresh();
          }}
        />
      )}
      {receipt && <ReceiptDialog booking={receipt} onClose={() => setReceipt(null)} />}
      {recover && (
        <AutoRecoverDialog
          booking={recover}
          onClose={() => {
            setRecover(null);
            refresh();
          }}
        />
      )}
    </div>
  );
}

type RecoverStep = { step: string; ok: boolean; detail: string };
type RecoverReport = {
  disrupted: boolean;
  summary: string;
  steps: RecoverStep[];
  refund?: { amount: number; pct: number; currency: string; mode: string; rationale?: string };
  new_booking_ok?: boolean;
};

/**
 * Autonomous disruption recovery, shown as it happens. Pick "check real status"
 * or force a delay/cancellation (the demo path); the agent then detects, picks
 * the best alternative, refunds the old fare and rebooks — and every step it
 * took is listed, so nothing happens off-screen.
 */
function AutoRecoverDialog({ booking, onClose }: { booking: FlightBooking; onClose: () => void }) {
  const [running, setRunning] = useState(false);
  const [report, setReport] = useState<RecoverReport | null>(null);

  const run = async (simulate: string | null) => {
    setRunning(true);
    setReport(null);
    try {
      const res = await api.post<RecoverReport>(`/flights/booking/${booking.id}/auto-recover`, {
        simulate,
        execute: true,
      });
      setReport(res);
    } catch {
      toast.error("Recovery couldn't run — try again.");
    } finally {
      setRunning(false);
    }
  };

  return (
    <Dialog.Root open onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay asChild>
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="fixed inset-0 z-[80] bg-black/50 backdrop-blur-sm" />
        </Dialog.Overlay>
        <Dialog.Content asChild>
          <motion.div
            initial={{ opacity: 0, y: 16, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            className={cn(
              "fixed left-1/2 top-1/2 z-[81] max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 overflow-y-auto",
              "rounded-[var(--r-lg)] border border-[var(--border)] bg-[var(--elevated)] p-6 shadow-[var(--shadow-2)]",
            )}
          >
            <div className="flex items-start justify-between">
              <div>
                <Dialog.Title className="font-[family-name:var(--font-display)] text-lg">Flight recovery</Dialog.Title>
                <Dialog.Description className="text-xs text-[var(--muted)]">
                  {booking.route ?? "Flight"} · your agent handles the whole recovery
                </Dialog.Description>
              </div>
              <Dialog.Close asChild>
                <Button variant="ghost" size="icon" aria-label="Close">
                  <X className="h-4 w-4" />
                </Button>
              </Dialog.Close>
            </div>

            {!report && (
              <div className="mt-4 space-y-3">
                <p className="text-sm text-[var(--muted)]">
                  Check the live status, or simulate a disruption to see the agent detect it, refund this
                  fare and rebook the best alternative — automatically.
                </p>
                <div className="grid gap-2">
                  <Button loading={running} onClick={() => void run(null)}>
                    <RefreshCw className="h-4 w-4" /> Check real status &amp; recover
                  </Button>
                  <div className="grid grid-cols-2 gap-2">
                    <Button variant="secondary" size="sm" disabled={running} onClick={() => void run("delayed")}>
                      Simulate delay
                    </Button>
                    <Button variant="secondary" size="sm" disabled={running} onClick={() => void run("cancelled")}>
                      Simulate cancellation
                    </Button>
                  </div>
                </div>
                {running && (
                  <p className="flex items-center gap-2 text-xs text-[var(--brand-600)]">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" /> Agent working — detecting, refunding, rebooking…
                  </p>
                )}
              </div>
            )}

            {report && (
              <div className="mt-4 space-y-3">
                <ol className="space-y-2">
                  {report.steps.map((s, i) => (
                    <li key={i} className="flex items-start gap-2 text-sm">
                      {s.ok ? (
                        <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-[var(--success)]" weight="fill" />
                      ) : (
                        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-[var(--warning)]" weight="fill" />
                      )}
                      <span>
                        <span className="font-semibold capitalize">{s.step}</span> — {s.detail}
                      </span>
                    </li>
                  ))}
                </ol>
                <div
                  className={cn(
                    "rounded-[var(--r-md)] border-l-2 p-3 text-sm",
                    report.disrupted
                      ? "border-[var(--brand-500)] bg-[color-mix(in_srgb,var(--brand-400)_8%,transparent)]"
                      : "border-[var(--success)] bg-[color-mix(in_srgb,var(--success)_10%,transparent)]",
                  )}
                >
                  {report.summary}
                </div>
                <Button className="w-full" variant="secondary" onClick={onClose}>
                  Done
                </Button>
              </div>
            )}
          </motion.div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function ReceiptDialog({ booking, onClose }: { booking: FlightBooking; onClose: () => void }) {
  const tickets = booking.tickets ?? ((booking.payload?.ticketing as { tickets?: unknown[] })?.tickets ?? []);
  return (
    <Dialog.Root open onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay asChild>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-[80] bg-black/50 backdrop-blur-sm"
          />
        </Dialog.Overlay>
        <Dialog.Content asChild>
          <motion.div
            initial={{ opacity: 0, y: 16, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            className={cn(
              "fixed left-1/2 top-1/2 z-[81] w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2",
              "rounded-[var(--r-lg)] border border-[var(--border)] bg-[var(--elevated)] p-6 shadow-[var(--shadow-2)]",
            )}
          >
            <div className="flex items-start justify-between">
              <div>
                <Dialog.Title className="font-[family-name:var(--font-display)] text-lg">Receipt</Dialog.Title>
                <Dialog.Description className="text-xs text-[var(--muted)]">
                  {booking.simulated ? "Sandbox rehearsal — no real charge" : "Production purchase"}
                </Dialog.Description>
              </div>
              <Dialog.Close asChild>
                <Button variant="ghost" size="icon" aria-label="Close">
                  <X className="h-4 w-4" />
                </Button>
              </Dialog.Close>
            </div>

            <dl className="mt-4 space-y-2 text-sm">
              <ReceiptRow label="Route" value={booking.route ?? "—"} />
              {booking.depart_date && <ReceiptRow label="Departure" value={booking.depart_date} />}
              <ReceiptRow label="Passengers" value={String(booking.travellers ?? 1)} />
              {booking.order_no && <ReceiptRow label="Order no." value={booking.order_no} mono />}
              <ReceiptRow
                label="Amount paid"
                value={money(booking) ?? "—"}
                strong
              />
              <ReceiptRow label="Status" value={STAGE_META[booking.stage]?.label ?? booking.stage} />
              <ReceiptRow label="Environment" value={booking.simulated ? "Sandbox" : "Production"} />
              <ReceiptRow label="Date" value={when(booking.updated_at ?? booking.created_at) || "—"} />
            </dl>

            {tickets.length > 0 && (
              <div className="mt-4 rounded-[var(--r-md)] border border-[var(--success)]/40 bg-[color-mix(in_srgb,var(--success)_10%,transparent)] p-3">
                <p className="flex items-center gap-2 text-sm font-semibold text-[var(--success)]">
                  <Ticket className="h-4 w-4" />
                  {tickets.length} ticket(s) issued
                </p>
                <ul className="mt-1.5 space-y-0.5 font-[family-name:var(--font-mono)] text-[0.65rem] text-[var(--muted)]">
                  {tickets.map((t, i) => {
                    const rec = t as { ticket_number?: string; status?: string };
                    return (
                      <li key={i}>
                        {rec.ticket_number ?? `Ticket ${i + 1}`}
                        {rec.status ? ` · ${rec.status}` : ""}
                      </li>
                    );
                  })}
                </ul>
              </div>
            )}

            <Button className="mt-5 w-full" variant="secondary" onClick={onClose}>
              Done
            </Button>
          </motion.div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function ReceiptRow({
  label,
  value,
  mono,
  strong,
}: {
  label: string;
  value: string;
  mono?: boolean;
  strong?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-dashed border-[var(--border)] pb-2 last:border-0">
      <dt className="text-xs text-[var(--muted)]">{label}</dt>
      <dd className={cn("text-right", mono && "font-[family-name:var(--font-mono)] text-xs", strong && "font-semibold")}>
        {value}
      </dd>
    </div>
  );
}
