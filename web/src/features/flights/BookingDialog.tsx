import { useEffect, useState, type ReactNode } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { AnimatePresence, motion } from "framer-motion";
import {
  AlertTriangle,
  BadgeCheck,
  CheckCircle2,
  CreditCard,
  ExternalLink,
  Loader2,
  Plane,
  Ticket,
  TriangleAlert,
  X,
} from "@/components/ui/icons";
import { toast } from "sonner";
import { Badge, Button, confirm } from "@/components/ui";
import { StatusPill } from "@/components/ui/SourceBadge";
import { cn } from "@/lib/cn";
import { api, ApiError } from "@/lib/api";
import { useScrollLock } from "@/hooks/useScrollLock";
import type { AtlasStatus, BookingStage, FlightBooking, PlanOption } from "@/lib/types";

/**
 * The Atlas purchase flow, one confirmed step at a time.
 *
 * Atlas is a state machine, and this dialog mirrors it rather than hiding it:
 * verify → confirm price → order → pay → ticket. Each step shows the response
 * code Atlas returned, because "PRICE_CHANGED" or "TOP_UP_REQUIRED" is the actual
 * answer and paraphrasing it would lose information the traveller needs.
 *
 * Three rules are enforced in the UI as well as the backend:
 *
 * - **Sandbox is the default**, and a production run is called out in red.
 * - **A price increase needs a fresh confirmation.** The new figure is shown
 *   beside the old one and nothing proceeds until the traveller accepts.
 * - **Payment is attempted once.** After an attempt the button is replaced by
 *   "Check status", because a confirmation ID is single-use and retrying could
 *   double-charge.
 */

const STEPS: Array<{ stage: BookingStage; label: string }> = [
  { stage: "draft", label: "Selected" },
  { stage: "price_confirmed", label: "Price confirmed" },
  { stage: "ordered", label: "Order created" },
  { stage: "paid", label: "Paid" },
  { stage: "ticketed", label: "Ticketed" },
];

const STAGE_INDEX: Record<BookingStage, number> = {
  draft: 0,
  price_confirmed: 1,
  ordered: 2,
  paying: 3,
  paid: 3,
  ticketed: 4,
  failed: -1,
};

interface PassengerForm {
  given_name: string;
  surname: string;
  date_of_birth: string;
  gender: "male" | "female" | "";
  nationality: string;
  passport_number: string;
  passport_expiry: string;
  email: string;
  phone: string;
}

const EMPTY_PASSENGER: PassengerForm = {
  given_name: "",
  surname: "",
  date_of_birth: "",
  gender: "",
  nationality: "MY",
  passport_number: "",
  passport_expiry: "",
  email: "",
  phone: "",
};

export function BookingDialog({
  option: optionProp,
  route: routeProp,
  initialBooking,
  onClose,
}: {
  option?: PlanOption;
  route?: { origin?: string; destination?: string; depart?: string };
  /** Resume an existing booking (from the Orders/Payments tab) instead of
   *  starting fresh from a search result. */
  initialBooking?: FlightBooking;
  onClose: () => void;
}) {
  // Resuming? Derive the display option/route from the stored booking snapshot.
  const option = optionProp ?? optionFromBooking(initialBooking);
  const route = routeProp ?? routeFromBooking(initialBooking);
  const [booking, setBooking] = useState<FlightBooking | null>(initialBooking ?? null);
  const [atlas, setAtlas] = useState<AtlasStatus | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [passenger, setPassenger] = useState<PassengerForm>(EMPTY_PASSENGER);
  const [log, setLog] = useState<Array<{ step: string; code: string; message: string }>>([]);

  useScrollLock(true);

  // Atlas's own health first: a flow that cannot start should say why up front.
  useEffect(() => {
    api
      .get<AtlasStatus>("/flights/atlas/status")
      .then(setAtlas)
      .catch(() => setAtlas(null));
  }, []);

  const push = (step: string, response?: { code: string; message: string }) => {
    if (!response) return;
    setLog((prev) => [...prev, { step, code: response.code, message: response.message }]);
  };

  const run = async <T,>(key: string, fn: () => Promise<T>): Promise<T | null> => {
    setBusy(key);
    try {
      return await fn();
    } catch (error) {
      const message =
        error instanceof ApiError
          ? typeof error.payload === "object" &&
            error.payload &&
            "detail" in error.payload
            ? describeDetail((error.payload as { detail: unknown }).detail)
            : error.detail
          : error instanceof Error
            ? error.message
            : "Something went wrong";
      toast.error(message);
      setLog((prev) => [...prev, { step: key, code: "ERROR", message }]);
      return null;
    } finally {
      setBusy(null);
    }
  };

  const start = () =>
    run("start", async () => {
      const created = await api.post<FlightBooking>("/flights/booking/start", {
        offer_id: option.raw?.offer_id ?? option.id,
        route:
          route.origin && route.destination
            ? `${route.origin}-${route.destination}`
            : option.title,
        depart_date: route.depart && route.depart !== "flexible" ? route.depart : null,
        travellers: 1,
        total_amount: option.price_amount,
        currency: option.price_currency,
        environment: atlas?.environment === "production" ? "production" : "sandbox",
        offer_snapshot: { id: option.id, title: option.title, raw: option.raw },
      });
      setBooking(created);
      return created;
    });

  const verify = (acceptPriceChange = false) =>
    run("verify", async () => {
      const current = booking ?? (await start());
      if (!current) return null;
      const updated = await api.post<FlightBooking>(
        `/flights/booking/${current.id}/verify`,
        { accept_price_change: acceptPriceChange },
      );
      setBooking(updated);
      push("verify", updated.atlas);
      if (updated.requires_confirmation) {
        toast.warning("The fare changed — review the new price before continuing.");
      } else if (updated.stage === "price_confirmed") {
        toast.success("Price confirmed by Atlas.");
      }
      return updated;
    });

  const createOrder = () =>
    run("order", async () => {
      if (!booking) return null;
      const updated = await api.post<FlightBooking>(
        `/flights/booking/${booking.id}/order`,
        {
          passengers: [
            {
              ...passenger,
              gender: passenger.gender || null,
              passenger_type: "adult",
            },
          ],
        },
      );
      setBooking(updated);
      push("order", updated.atlas);
      if (updated.warning) toast.warning(updated.warning);
      else if (updated.ready_to_pay) toast.success("Order created — ready to pay.");
      return updated;
    });

  const pay = async () => {
    if (!booking) return;
    const isProduction = booking.environment === "production";
    const ok = await confirm({
      title: isProduction ? "Pay for real?" : "Simulate the payment?",
      body: isProduction
        ? "This is PRODUCTION. Real money will leave your Atlas balance and a real ticket will be issued. This cannot be undone from here — Atlas does not support refunds or cancellations through this flow."
        : "Sandbox rehearsal: this walks the full payment path against Atlas test data. No real money moves and no real ticket is issued.",
      confirmText: isProduction ? "Pay now" : "Simulate payment",
      tone: isProduction ? "danger" : "brand",
    });
    if (!ok) return;

    await run("pay", async () => {
      const updated = await api.post<FlightBooking>(`/flights/booking/${booking.id}/pay`);
      setBooking(updated);
      push("pay", updated.atlas);
      if (updated.stage === "paid") toast.success("Payment accepted.");
      if (updated.next === "top_up") toast.warning("Atlas balance is short — top up first.");
      return updated;
    });
  };

  const checkStatus = () =>
    run("status", async () => {
      if (!booking) return null;
      const updated = await api.post<FlightBooking>(
        `/flights/booking/${booking.id}/status`,
      );
      setBooking(updated);
      push("status", updated.atlas);
      if (updated.stage === "ticketed") toast.success("Tickets issued.");
      return updated;
    });

  const stage: BookingStage = booking?.stage ?? "draft";
  const stepIndex = STAGE_INDEX[stage] ?? 0;
  const passengerReady =
    passenger.given_name.trim() !== "" &&
    passenger.surname.trim() !== "" &&
    passenger.date_of_birth !== "";

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
              "fixed left-1/2 top-1/2 z-[81] w-[calc(100%-2rem)] max-w-2xl",
              "max-h-[88dvh] -translate-x-1/2 -translate-y-1/2 overflow-y-auto",
              "rounded-[var(--r-lg)] border border-[var(--border)]",
              "bg-[var(--elevated)] p-6 shadow-[var(--shadow-2)]",
            )}
          >
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <Dialog.Title className="font-[family-name:var(--font-display)] text-lg">
                  Book with Atlas
                </Dialog.Title>
                <Dialog.Description className="mt-1 text-sm text-[var(--muted)]">
                  {option.title}
                  {option.price_amount != null && (
                    <>
                      {" · "}
                      <strong>
                        {option.price_currency}{" "}
                        {Number(option.price_amount).toLocaleString()}
                      </strong>
                    </>
                  )}
                </Dialog.Description>
              </div>
              <Dialog.Close asChild>
                <Button variant="ghost" size="icon" aria-label="Close">
                  <X className="h-4 w-4" />
                </Button>
              </Dialog.Close>
            </div>

            <EnvironmentBanner atlas={atlas} booking={booking} />
            <StepRail index={stepIndex} failed={stage === "failed"} />

            {/* Price change gate */}
            {booking?.requires_confirmation && (
              <div className="mt-4 rounded-[var(--r-md)] border border-[var(--warning)]/50 bg-[color-mix(in_srgb,var(--warning)_10%,transparent)] p-4">
                <p className="flex items-center gap-2 text-sm font-semibold text-[var(--warning)]">
                  <TriangleAlert className="h-4 w-4" />
                  The fare changed
                </p>
                <p className="mt-1 text-xs text-[var(--muted)]">
                  Was {booking.currency} {booking.previous_amount?.toLocaleString() ?? "—"} ·
                  now{" "}
                  <strong className="text-[var(--text)]">
                    {booking.currency} {booking.new_amount?.toLocaleString() ?? "—"}
                  </strong>
                  . Atlas requires an explicit confirmation before continuing.
                </p>
                <div className="mt-3 flex gap-2">
                  <Button
                    size="sm"
                    loading={busy === "verify"}
                    onClick={() => void verify(true)}
                  >
                    Accept new price
                  </Button>
                  <Button variant="ghost" size="sm" onClick={onClose}>
                    Cancel
                  </Button>
                </div>
              </div>
            )}

            {/* Passenger details, only when an order is next */}
            {stage === "price_confirmed" && (
              <PassengerFields value={passenger} onChange={setPassenger} />
            )}

            {(booking?.order_no || booking?.payment_summary) && (
              <OrderSummary booking={booking} />
            )}

            {booking?.tickets && booking.tickets.length > 0 && (
              <div className="mt-4 rounded-[var(--r-md)] border border-[var(--success)]/40 bg-[color-mix(in_srgb,var(--success)_10%,transparent)] p-3">
                <p className="flex items-center gap-2 text-sm font-semibold text-[var(--success)]">
                  <Ticket className="h-4 w-4" />
                  {booking.tickets.length} ticket(s) issued
                </p>
              </div>
            )}

            {/* What Atlas said, verbatim */}
            {log.length > 0 && (
              <div className="mt-4">
                <p className="mb-1.5 text-xs font-semibold">Atlas responses</p>
                <ol className="space-y-1 font-[family-name:var(--font-mono)] text-[0.65rem]">
                  {log.map((entry, index) => (
                    <li key={index} className="flex gap-2">
                      <span className="text-[var(--muted)]">{entry.step}</span>
                      <span
                        className={
                          entry.code === "ERROR"
                            ? "text-[var(--danger)]"
                            : "text-[var(--brand-500)]"
                        }
                      >
                        {entry.code}
                      </span>
                      <span className="min-w-0 break-words text-[var(--muted)]">
                        {entry.message}
                      </span>
                    </li>
                  ))}
                </ol>
              </div>
            )}

            <StepActions
              stage={stage}
              busy={busy}
              hasBooking={Boolean(booking)}
              readyToPay={Boolean(booking?.ready_to_pay ?? booking?.has_confirmation)}
              passengerReady={passengerReady}
              requiresConfirmation={Boolean(booking?.requires_confirmation)}
              onVerify={() => void verify(false)}
              onOrder={() => void createOrder()}
              onPay={() => void pay()}
              onStatus={() => void checkStatus()}
              onClose={onClose}
            />
          </motion.div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function EnvironmentBanner({
  atlas,
  booking,
}: {
  atlas: AtlasStatus | null;
  booking: FlightBooking | null;
}) {
  const environment = booking?.environment ?? atlas?.environment ?? "sandbox";
  const isProduction = environment === "production";

  if (atlas && !atlas.installed) {
    return (
      <div className="mt-4 flex items-start gap-2 rounded-[var(--r-md)] border border-[var(--danger)]/40 bg-[color-mix(in_srgb,var(--danger)_10%,transparent)] p-3">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-[var(--danger)]" />
        <div className="text-xs">
          <p className="font-semibold text-[var(--danger)]">Atlas CLI not installed</p>
          <p className="mt-0.5 text-[var(--muted)]">{atlas.detail}</p>
        </div>
      </div>
    );
  }

  if (atlas && !atlas.authorised) {
    return (
      <div className="mt-4 flex items-start gap-2 rounded-[var(--r-md)] border border-[var(--warning)]/40 bg-[color-mix(in_srgb,var(--warning)_10%,transparent)] p-3">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-[var(--warning)]" />
        <div className="text-xs">
          <p className="font-semibold text-[var(--warning)]">Atlas not authorised</p>
          <p className="mt-0.5 text-[var(--muted)]">
            Authorise from the API Vault (Atlas card) before booking. {atlas.detail}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div
      className={cn(
        "mt-4 flex items-center gap-2 rounded-[var(--r-md)] border p-2.5 text-xs",
        isProduction
          ? "border-[var(--danger)]/50 bg-[color-mix(in_srgb,var(--danger)_10%,transparent)]"
          : "border-[var(--border)] bg-[var(--surface)]",
      )}
    >
      {isProduction ? (
        <>
          <AlertTriangle className="h-4 w-4 shrink-0 text-[var(--danger)]" />
          <span className="font-semibold text-[var(--danger)]">
            PRODUCTION — real money, real tickets.
          </span>
        </>
      ) : (
        <>
          <BadgeCheck className="h-4 w-4 shrink-0 text-[var(--success)]" />
          <span>
            <strong>Sandbox rehearsal.</strong>{" "}
            <span className="text-[var(--muted)]">
              Test data. No real booking is created and no money moves.
            </span>
          </span>
        </>
      )}
      <span className="ml-auto">
        <StatusPill status={isProduction ? "invalid" : "healthy"} detail={environment} />
      </span>
    </div>
  );
}

function StepRail({ index, failed }: { index: number; failed: boolean }) {
  return (
    <ol className="mt-4 flex items-center gap-1">
      {STEPS.map((step, position) => {
        const done = !failed && position < index;
        const active = !failed && position === index;
        return (
          <li key={step.stage} className="flex min-w-0 flex-1 items-center gap-1">
            <span
              className={cn(
                "grid h-6 w-6 shrink-0 place-items-center rounded-full text-[0.6rem] font-bold",
                done && "bg-[var(--success)] text-white",
                active && "bg-[var(--brand-500)] text-white",
                !done && !active && "bg-[var(--border)] text-[var(--muted)]",
                failed && position === 0 && "bg-[var(--danger)] text-white",
              )}
            >
              {done ? <CheckCircle2 className="h-3.5 w-3.5" /> : position + 1}
            </span>
            <span
              className={cn(
                "hidden truncate text-[0.65rem] sm:block",
                active ? "font-semibold" : "text-[var(--muted)]",
              )}
            >
              {step.label}
            </span>
            {position < STEPS.length - 1 && (
              <span className="h-px min-w-2 flex-1 bg-[var(--border)]" />
            )}
          </li>
        );
      })}
    </ol>
  );
}

function StepActions({
  stage,
  busy,
  hasBooking,
  readyToPay,
  passengerReady,
  requiresConfirmation,
  onVerify,
  onOrder,
  onPay,
  onStatus,
  onClose,
}: {
  stage: BookingStage;
  busy: string | null;
  hasBooking: boolean;
  readyToPay: boolean;
  passengerReady: boolean;
  requiresConfirmation: boolean;
  onVerify: () => void;
  onOrder: () => void;
  onPay: () => void;
  onStatus: () => void;
  onClose: () => void;
}) {
  if (requiresConfirmation) return null;

  return (
    <div className="mt-5 flex flex-wrap items-center justify-end gap-2 border-t border-[var(--border)] pt-4">
      {stage === "draft" && (
        <Button loading={busy === "verify" || busy === "start"} onClick={onVerify}>
          <Plane className="h-4 w-4" />
          {hasBooking ? "Re-price with Atlas" : "Verify fare"}
        </Button>
      )}

      {stage === "price_confirmed" && (
        <Button
          loading={busy === "order"}
          disabled={!passengerReady}
          onClick={onOrder}
          title={passengerReady ? undefined : "Passenger name and date of birth are required"}
        >
          Create order
        </Button>
      )}

      {stage === "ordered" && (
        <Button
          loading={busy === "pay"}
          disabled={!readyToPay}
          onClick={onPay}
          title={readyToPay ? undefined : "Atlas did not return a payment confirmation"}
        >
          <CreditCard className="h-4 w-4" />
          Pay from Atlas balance
        </Button>
      )}

      {/* After an attempt, polling is the only safe move — a confirmation ID is
          single-use, so a retry button here could double-charge. */}
      {(stage === "paying" || stage === "paid") && (
        <Button loading={busy === "status"} onClick={onStatus}>
          <Loader2 className={cn("h-4 w-4", busy === "status" && "animate-spin")} />
          Check ticket status
        </Button>
      )}

      {stage === "ticketed" && (
        <Badge variant="success">Complete — tickets issued</Badge>
      )}

      {stage === "failed" && (
        <Button variant="secondary" onClick={onClose}>
          Close and search again
        </Button>
      )}

      <Button variant="ghost" onClick={onClose}>
        {stage === "ticketed" ? "Done" : "Cancel"}
      </Button>
    </div>
  );
}

function PassengerFields({
  value,
  onChange,
}: {
  value: PassengerForm;
  onChange: (next: PassengerForm) => void;
}) {
  const set = (patch: Partial<PassengerForm>) => onChange({ ...value, ...patch });

  return (
    <div className="mt-4 rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--surface)] p-4">
      <p className="text-sm font-semibold">Passenger</p>
      <p className="mt-0.5 text-[0.65rem] text-[var(--muted)]">
        Sent straight to Atlas and never stored by Journava — Atlas treats passenger
        details as one-time input, and so do we.
      </p>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <input
          className="input-field"
          placeholder="Given name *"
          value={value.given_name}
          onChange={(event) => set({ given_name: event.target.value })}
        />
        <input
          className="input-field"
          placeholder="Surname *"
          value={value.surname}
          onChange={(event) => set({ surname: event.target.value })}
        />
        <label className="block">
          <span className="mb-1 block text-[0.65rem] text-[var(--muted)]">
            Date of birth *
          </span>
          <input
            type="date"
            className="input-field"
            value={value.date_of_birth}
            onChange={(event) => set({ date_of_birth: event.target.value })}
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-[0.65rem] text-[var(--muted)]">
            Passport expiry
          </span>
          <input
            type="date"
            className="input-field"
            value={value.passport_expiry}
            onChange={(event) => set({ passport_expiry: event.target.value })}
          />
        </label>
        <input
          className="input-field"
          placeholder="Passport number"
          value={value.passport_number}
          onChange={(event) => set({ passport_number: event.target.value })}
        />
        <input
          className="input-field"
          placeholder="Nationality (e.g. MY)"
          value={value.nationality}
          onChange={(event) => set({ nationality: event.target.value.toUpperCase() })}
        />
        <input
          className="input-field"
          type="email"
          placeholder="Email"
          value={value.email}
          onChange={(event) => set({ email: event.target.value })}
        />
        <input
          className="input-field"
          placeholder="Phone"
          value={value.phone}
          onChange={(event) => set({ phone: event.target.value })}
        />
      </div>
    </div>
  );
}

/** The order/receipt block. Renders structured fields — never a raw object,
 *  which is what crashed the page when `payment_summary` became an object. */
function OrderSummary({ booking }: { booking: FlightBooking }) {
  const summary = booking.payment_summary;
  const summaryObj =
    summary && typeof summary === "object" ? (summary as Record<string, unknown>) : null;
  const summaryText = typeof summary === "string" ? summary : null;
  const passengerCount =
    (summaryObj?.passenger_count as number | undefined) ?? booking.travellers ?? 1;
  const deadline = booking.payment_deadline ?? (summaryObj?.payment_deadline as string | undefined);
  const total =
    booking.total_amount != null
      ? `${booking.currency ?? ""} ${Number(booking.total_amount).toLocaleString()}`.trim()
      : null;

  return (
    <div className="mt-4 rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--surface)] p-3">
      <p className="text-xs font-semibold">Order summary</p>
      <dl className="mt-1.5 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
        {booking.order_no && (
          <Row label="Order no.">
            <span className="font-[family-name:var(--font-mono)]">{booking.order_no}</span>
          </Row>
        )}
        {total && <Row label="Total">{total}</Row>}
        <Row label="Passengers">{passengerCount}</Row>
        <Row label="Environment">{booking.environment === "production" ? "Production" : "Sandbox"}</Row>
        {deadline && <Row label="Pay by">{deadline}</Row>}
      </dl>
      {summaryText && (
        <p className="mt-2 font-[family-name:var(--font-mono)] text-[0.65rem] text-[var(--muted)]">
          {summaryText}
        </p>
      )}
      {booking.order_link && (
        <a
          href={booking.order_link}
          target="_blank"
          rel="noreferrer noopener"
          className="mt-2 inline-flex items-center gap-1 text-xs text-[var(--brand-500)] hover:underline"
        >
          <ExternalLink className="h-3 w-3" />
          View the order on Atlas
        </a>
      )}
    </div>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-[var(--muted)]">{label}</dt>
      <dd className="text-right font-medium">{children}</dd>
    </>
  );
}

/** Reconstruct a display PlanOption from a stored booking's offer snapshot,
 *  so a resumed booking shows its flight without the original search result. */
function optionFromBooking(booking?: FlightBooking): PlanOption {
  const snap = (booking?.payload?.offer ?? {}) as {
    id?: string;
    title?: string;
    raw?: Record<string, unknown>;
  };
  return {
    id: snap.id ?? booking?.offer_id ?? booking?.id ?? "resume",
    kind: "flight",
    title: snap.title ?? booking?.route ?? "Flight",
    price_amount: booking?.total_amount ?? null,
    price_currency: booking?.currency ?? "MYR",
    provider: booking?.environment === "sandbox" ? "Atlas Sandbox" : "Atlas Flight Booking",
    booking_url: null,
    reasoning: null,
    halal_confidence: null,
    verified: false,
    last_checked: null,
    source: "atlas",
    source_url: null,
    bookable: true,
    raw: { ...(snap.raw ?? {}), offer_id: booking?.offer_id ?? snap.id },
  };
}

function routeFromBooking(booking?: FlightBooking): {
  origin?: string;
  destination?: string;
  depart?: string;
} {
  const [origin, destination] = (booking?.route ?? "").split("-");
  return {
    origin: origin || undefined,
    destination: destination || undefined,
    depart: booking?.depart_date ?? undefined,
  };
}

function describeDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object") {
    const record = detail as { code?: string; message?: string };
    if (record.message) {
      return record.code ? `${record.code}: ${record.message}` : record.message;
    }
  }
  return "Request failed";
}

/** Re-exported so the results panel can animate the dialog's presence. */
export { AnimatePresence };
