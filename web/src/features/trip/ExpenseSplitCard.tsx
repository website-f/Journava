import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Wallet, Plus, Trash2, ArrowRight } from "@/components/ui/icons";
import { Button } from "@/components/ui";
import { Money } from "@/components/ui/Money";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { AgentPlanResult } from "@/lib/types";

/**
 * Group expense split — log shared trip costs and see who owes whom, settled in
 * the fewest transfers. Scoped to this trip (same key as the checklist).
 */

type Expense = {
  id: string;
  description: string;
  amount: number;
  currency: string;
  paid_by: string;
  shared_by: string[];
};
type Balance = { name: string; net: number; currency: string };
type Settlement = { from: string; to: string; amount: number; currency: string };
type Payload = { expenses: Expense[]; balances: Balance[]; settlements: Settlement[]; total: number; currency: string };

export function ExpenseSplitCard({ results }: { results: Record<string, AgentPlanResult> }) {
  const chief = (results.chief?.data as { destination?: string; start_date?: string; budget_currency?: string } | undefined) ?? {};
  const tripKey = `${chief.destination ?? "trip"}:${chief.start_date ?? ""}`;
  const currency = chief.budget_currency ?? "MYR";

  const [data, setData] = useState<Payload | null>(null);
  const [desc, setDesc] = useState("");
  const [amount, setAmount] = useState("");
  const [paidBy, setPaidBy] = useState("");
  const [sharedBy, setSharedBy] = useState("");
  const [busy, setBusy] = useState(false);

  const load = async () => {
    try {
      setData(await api.get<Payload>(`/trip/expenses?trip_key=${encodeURIComponent(tripKey)}`));
    } catch {
      setData({ expenses: [], balances: [], settlements: [], total: 0, currency });
    }
  };
  useEffect(() => {
    void load();
  }, [tripKey]); // eslint-disable-line react-hooks/exhaustive-deps

  // Known travellers (for quick "split among everyone" default + hints).
  const people = useMemo(() => {
    const s = new Set<string>();
    for (const e of data?.expenses ?? []) {
      if (e.paid_by) s.add(e.paid_by);
      for (const p of e.shared_by) s.add(p);
    }
    return [...s];
  }, [data]);

  const add = async () => {
    const amt = Number(amount);
    if (!desc.trim() || !paidBy.trim() || !amt || amt <= 0) {
      toast.error("Enter a description, amount and who paid.");
      return;
    }
    const shared = sharedBy.trim()
      ? sharedBy.split(",").map((s) => s.trim()).filter(Boolean)
      : Array.from(new Set([paidBy.trim(), ...people])); // default: everyone
    setBusy(true);
    try {
      const res = await api.post<Payload>("/trip/expenses", {
        trip_key: tripKey,
        description: desc.trim(),
        amount: amt,
        currency,
        paid_by: paidBy.trim(),
        shared_by: shared,
      });
      setData(res);
      setDesc("");
      setAmount("");
      setSharedBy("");
      toast.success("Expense added.");
    } catch {
      toast.error("Couldn't add the expense.");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: string) => {
    try {
      setData(await api.del<Payload>(`/trip/expenses/${id}?trip_key=${encodeURIComponent(tripKey)}`));
    } catch {
      toast.error("Couldn't remove the expense.");
    }
  };

  const hasData = data && data.expenses.length > 0;

  return (
    <section className="mt-8">
      <div className="surface-card p-5">
        <div className="mb-3 flex items-center gap-2">
          <Wallet className="h-5 w-5 text-[var(--brand-500)]" />
          <h3 className="text-base font-semibold">Split expenses</h3>
        </div>
        <p className="mb-4 text-sm text-[var(--muted)]">
          Log shared costs — Journava tallies who owes whom and settles it in the fewest transfers.
        </p>

        {/* Add form */}
        <div className="mb-4 grid gap-2 sm:grid-cols-[1fr_7rem_8rem_8rem_auto]">
          <input value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="What for? (e.g. Dinner)"
            className="rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm" />
          <input value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" placeholder={`${currency} amt`}
            className="rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm" />
          <input value={paidBy} onChange={(e) => setPaidBy(e.target.value)} placeholder="Paid by"
            className="rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm" />
          <input value={sharedBy} onChange={(e) => setSharedBy(e.target.value)} placeholder="Split: A,B (all)"
            className="rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm" />
          <Button size="sm" loading={busy} onClick={() => void add()}>
            <Plus className="h-4 w-4" />
            Add
          </Button>
        </div>

        {hasData && (
          <>
            {/* Expenses */}
            <ul className="mb-4 space-y-1.5">
              {data!.expenses.map((e) => (
                <li key={e.id} className="flex items-center gap-2 rounded-[var(--r-md)] border border-[var(--border)] px-3 py-2 text-sm">
                  <span className="min-w-0 flex-1 truncate">
                    <span className="font-medium">{e.description}</span>
                    <span className="text-[var(--muted)]"> · {e.paid_by} paid · split {e.shared_by.length}</span>
                  </span>
                  <span className="shrink-0 font-medium text-[var(--brand-500)]">
                    <Money amount={e.amount} currency={e.currency} />
                  </span>
                  <button onClick={() => void remove(e.id)} aria-label="Remove" className="text-[var(--muted)] hover:text-[var(--danger)]">
                    <Trash2 className="h-4 w-4" />
                  </button>
                </li>
              ))}
            </ul>

            <div className="grid gap-4 sm:grid-cols-2">
              {/* Balances */}
              <div>
                <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">
                  Balances · total <Money amount={data!.total} currency={data!.currency} />
                </p>
                <ul className="space-y-1">
                  {data!.balances.map((b) => (
                    <li key={b.name} className="flex items-center justify-between text-sm">
                      <span>{b.name}</span>
                      <span className={cn("font-medium tabular-nums", b.net >= 0 ? "text-[var(--success)]" : "text-[var(--danger)]")}>
                        {b.net >= 0 ? "+" : "−"}
                        <Money amount={Math.abs(b.net)} currency={b.currency} />
                      </span>
                    </li>
                  ))}
                </ul>
              </div>

              {/* Settle-up */}
              <div>
                <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">Settle up</p>
                {data!.settlements.length === 0 ? (
                  <p className="text-sm text-[var(--muted)]">All square 🎉</p>
                ) : (
                  <ul className="space-y-1.5">
                    {data!.settlements.map((t, i) => (
                      <li key={i} className="flex items-center gap-2 rounded-[var(--r-md)] bg-[color-mix(in_srgb,var(--brand-400)_8%,transparent)] px-3 py-1.5 text-sm">
                        <span className="font-medium">{t.from}</span>
                        <ArrowRight className="h-3.5 w-3.5 text-[var(--muted)]" />
                        <span className="font-medium">{t.to}</span>
                        <span className="ml-auto font-semibold text-[var(--brand-500)]">
                          <Money amount={t.amount} currency={t.currency} />
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          </>
        )}
      </div>
    </section>
  );
}
