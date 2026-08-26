import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Clock,
  ExternalLink,
  History as HistoryIcon,
  Plane,
  Search,
  Ticket,
  Trash2,
  Scales,
} from "@/components/ui/icons";
import { useCompareStore, MAX_COMPARE } from "@/stores/compareStore";
import { toast } from "sonner";
import {
  Badge,
  Button,
  EmptyState,
  Skeleton,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  confirm,
} from "@/components/ui";
import { StatusPill } from "@/components/ui/SourceBadge";
import { cn } from "@/lib/cn";
import { api } from "@/lib/api";
import { usePlanStore } from "@/stores/planStore";
import type { BookingStage, FlightBooking, HistoryEntry } from "@/lib/types";

/**
 * History — everything you have asked, and every flight you have booked.
 *
 * Each search keeps a snapshot of its result, so reopening one is instant rather
 * than a re-run: a plan costs real time and real tokens, and throwing the answer
 * away when the tab closes wastes both.
 */

export function History() {
  return (
    <div className="mx-auto w-full max-w-4xl">
      <header className="pt-2 pb-5">
        <h2 className="flex items-center gap-2 font-[family-name:var(--font-display)] text-2xl tracking-tight">
          <HistoryIcon className="h-6 w-6 text-[var(--brand-500)]" />
          History
        </h2>
        <p className="mt-1 text-sm text-[var(--muted)]">
          Past searches and bookings. Reopening a search restores the saved result
          instead of running the agents again.
        </p>
      </header>

      <Tabs defaultValue="searches">
        <TabsList>
          <TabsTrigger value="searches">
            <Search className="h-4 w-4" />
            Searches
          </TabsTrigger>
          <TabsTrigger value="bookings">
            <Ticket className="h-4 w-4" />
            Bookings
          </TabsTrigger>
        </TabsList>

        <TabsContent value="searches">
          <SearchHistory />
        </TabsContent>
        <TabsContent value="bookings">
          <BookingHistory />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function SearchHistory() {
  const [entries, setEntries] = useState<HistoryEntry[] | null>(null);
  const [opening, setOpening] = useState<string | null>(null);
  const navigate = useNavigate();
  const setResults = usePlanStore((s) => s.setResults);

  // Add-to-compare lives here (results are history the moment they're produced).
  // A history entry isn't a saved_results row, so on first add we persist its
  // snapshot as a result to get a stable id for the comparison; a local map
  // (historyId → savedId) lets the same entry toggle off without re-saving.
  const compareIds = useCompareStore((s) => s.ids);
  const addCompare = useCompareStore((s) => s.add);
  const removeCompare = useCompareStore((s) => s.remove);
  const [savedFor, setSavedFor] = useState<Record<string, string>>({});
  const [comparing, setComparing] = useState<string | null>(null);

  const toggleCompare = async (entry: HistoryEntry) => {
    const existing = savedFor[entry.id];
    if (existing && compareIds.includes(existing)) {
      removeCompare(existing);
      return;
    }
    setComparing(entry.id);
    try {
      let savedId = existing;
      if (!savedId) {
        const full = await api.get<HistoryEntry>(`/history/searches/${entry.id}`);
        if (!full.result_snapshot) {
          toast.error("That result wasn't saved in full — reopen and run it again.");
          return;
        }
        const saved = await api.post<{ id: string }>("/saved", {
          kind: "result",
          scope: full.scope,
          destination: entry.destination,
          results: full.result_snapshot,
        });
        savedId = saved.id;
        setSavedFor((m) => ({ ...m, [entry.id]: saved.id }));
      }
      if (!addCompare(savedId)) toast.error(`Compare holds up to ${MAX_COMPARE} trips.`);
      else toast.success("Added to comparison — open Compare to weigh them.");
    } catch {
      toast.error("Couldn't add this to the comparison.");
    } finally {
      setComparing(null);
    }
  };

  const load = useCallback(async () => {
    try {
      setEntries(await api.get<HistoryEntry[]>("/history/searches"));
    } catch {
      setEntries([]);
      toast.error("Could not load search history.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const reopen = async (entry: HistoryEntry) => {
    setOpening(entry.id);
    try {
      const full = await api.get<HistoryEntry>(`/history/searches/${entry.id}`);
      if (!full.result_snapshot) {
        toast.error("That result was not saved in full — run it again.");
        return;
      }
      setResults(full.result_snapshot, full.scope);
      navigate(`/?scope=${full.scope}`);
    } catch {
      toast.error("Could not reopen that search.");
    } finally {
      setOpening(null);
    }
  };

  const remove = async (entry: HistoryEntry) => {
    const ok = await confirm({
      title: "Delete this entry?",
      body: entry.goal,
      confirmText: "Delete",
      tone: "danger",
    });
    if (!ok) return;
    try {
      await api.del(`/history/searches/${entry.id}`);
      await load();
    } catch {
      toast.error("Could not delete that entry.");
    }
  };

  if (entries === null) {
    return (
      <div className="space-y-3 py-3">
        {Array.from({ length: 4 }).map((_, index) => (
          <Skeleton key={index} className="h-20 w-full" />
        ))}
      </div>
    );
  }

  if (entries.length === 0) {
    return (
      <div className="py-8">
        <EmptyState
          icon={<Search className="h-10 w-10" />}
          title="No searches yet"
          description="Anything you ask from the Command Center is saved here so you can come back to it."
        />
      </div>
    );
  }

  return (
    <div className="space-y-3 py-3">
      {entries.map((entry) => (
        <div key={entry.id} className="surface-card p-4">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{entry.goal}</p>
              <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                <Badge variant="brand">{entry.scope.replace(/_/g, " ")}</Badge>
                {entry.destination && <Badge>{entry.destination}</Badge>}
                <Badge>{entry.agent_count} agents</Badge>
                {entry.option_count > 0 && <Badge>{entry.option_count} options</Badge>}
              </div>
              <p className="mt-1.5 flex items-center gap-1.5 text-[0.65rem] text-[var(--muted)]">
                <Clock className="h-3 w-3" />
                {formatWhen(entry.created_at)}
                {entry.duration_ms != null && ` · took ${(entry.duration_ms / 1000).toFixed(1)}s`}
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-1">
              {(() => {
                const inCompare = Boolean(savedFor[entry.id] && compareIds.includes(savedFor[entry.id]));
                return (
                  <Button
                    variant={inCompare ? "primary" : "ghost"}
                    size="sm"
                    loading={comparing === entry.id}
                    aria-label={inCompare ? "In comparison" : "Add to compare"}
                    onClick={() => void toggleCompare(entry)}
                  >
                    <Scales className="h-4 w-4" weight={inCompare ? "fill" : "regular"} />
                    <span className="hidden sm:inline">{inCompare ? "In compare" : "Compare"}</span>
                  </Button>
                );
              })()}
              <Button
                variant="secondary"
                size="sm"
                loading={opening === entry.id}
                onClick={() => void reopen(entry)}
              >
                Reopen
              </Button>
              <Button
                variant="ghost"
                size="icon"
                aria-label="Delete entry"
                onClick={() => void remove(entry)}
              >
                <Trash2 className="h-4 w-4 text-[var(--danger)]" />
              </Button>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

const STAGE_TONE: Record<BookingStage, string> = {
  draft: "untested",
  price_confirmed: "untested",
  ordered: "rate_limited",
  paying: "rate_limited",
  paid: "healthy",
  ticketed: "healthy",
  failed: "invalid",
};

const STAGE_LABEL: Record<BookingStage, string> = {
  draft: "Selected",
  price_confirmed: "Price confirmed",
  ordered: "Order created",
  paying: "Payment submitted",
  paid: "Paid",
  ticketed: "Ticketed",
  failed: "Failed",
};

function BookingHistory() {
  const [bookings, setBookings] = useState<FlightBooking[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setBookings(await api.get<FlightBooking[]>("/history/bookings"));
    } catch {
      setBookings([]);
      toast.error("Could not load bookings.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const refreshStatus = async (booking: FlightBooking) => {
    setBusy(booking.id);
    try {
      await api.post(`/flights/booking/${booking.id}/status`);
      await load();
      toast.success("Status refreshed.");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not refresh status");
    } finally {
      setBusy(null);
    }
  };

  if (bookings === null) {
    return (
      <div className="space-y-3 py-3">
        {Array.from({ length: 3 }).map((_, index) => (
          <Skeleton key={index} className="h-24 w-full" />
        ))}
      </div>
    );
  }

  if (bookings.length === 0) {
    return (
      <div className="py-8">
        <EmptyState
          icon={<Ticket className="h-10 w-10" />}
          title="No bookings yet"
          description="Bookings started from a flight result appear here, sandbox rehearsals included."
        />
      </div>
    );
  }

  return (
    <div className="space-y-3 py-3">
      {bookings.map((booking) => {
        const orderLink = (booking.payload?.order as { order_link?: string } | undefined)
          ?.order_link;
        return (
          <div
            key={booking.id}
            className={cn(
              "surface-card p-4",
              booking.stage === "ticketed" && "border-[var(--success)]/40",
              booking.stage === "failed" && "border-[var(--danger)]/40",
            )}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="flex items-center gap-2 text-sm font-semibold">
                  <Plane className="h-4 w-4 text-[var(--brand-500)]" />
                  {booking.route ?? "Flight"}
                  {booking.depart_date && (
                    <span className="font-normal text-[var(--muted)]">
                      {booking.depart_date}
                    </span>
                  )}
                </p>
                <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                  <StatusPill
                    status={STAGE_TONE[booking.stage]}
                    detail={booking.last_message}
                  />
                  <Badge>{STAGE_LABEL[booking.stage]}</Badge>
                  {booking.simulated ? (
                    <Badge variant="info">sandbox</Badge>
                  ) : (
                    <Badge variant="danger">production</Badge>
                  )}
                  {booking.total_amount != null && (
                    <Badge variant="brand">
                      {booking.currency} {booking.total_amount.toLocaleString()}
                    </Badge>
                  )}
                </div>
                {booking.order_no && (
                  <p className="mt-1.5 font-[family-name:var(--font-mono)] text-[0.65rem] text-[var(--muted)]">
                    order {booking.order_no}
                  </p>
                )}
                {booking.last_code && (
                  <p className="mt-1 text-[0.65rem] text-[var(--muted)]">
                    <span className="font-[family-name:var(--font-mono)] text-[var(--brand-500)]">
                      {booking.last_code}
                    </span>
                    {booking.last_message ? ` — ${booking.last_message}` : ""}
                  </p>
                )}
                <p className="mt-1 flex items-center gap-1.5 text-[0.65rem] text-[var(--muted)]">
                  <Clock className="h-3 w-3" />
                  {formatWhen(booking.created_at)}
                </p>
              </div>

              <div className="flex shrink-0 flex-col items-end gap-1.5">
                {booking.order_no && booking.stage !== "ticketed" && (
                  <Button
                    variant="secondary"
                    size="sm"
                    loading={busy === booking.id}
                    onClick={() => void refreshStatus(booking)}
                  >
                    Check status
                  </Button>
                )}
                {orderLink && (
                  <a
                    href={orderLink}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="inline-flex items-center gap-1 text-xs text-[var(--brand-500)] hover:underline"
                  >
                    <ExternalLink className="h-3 w-3" />
                    On Atlas
                  </a>
                )}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function formatWhen(value: string | null): string {
  if (!value) return "unknown time";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}
