import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { ThumbsUp, Users } from "@/components/ui/icons";
import { Button } from "@/components/ui";
import { API_BASE } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { PlanResults } from "@/stores/planStore";

/**
 * Collaborative voting — friends who open a shared link vote on which places
 * make the trip. Public (no account); votes tally live for everyone. The voter
 * sets a name once (stored locally).
 */

type VotableItem = { title: string; kind: string };
type Tally = { tallies: Record<string, number>; mine: string[] };

const VOTER_KEY = "journava:voter";

export function GroupVote({ token, results }: { token: string; results: PlanResults }) {
  const items = useMemo<VotableItem[]>(() => {
    const seen = new Set<string>();
    const out: VotableItem[] = [];
    const research = (results.research?.options ?? []) as { title?: string; kind?: string }[];
    const itin = (results.itinerary?.items ?? []) as { title?: string; kind?: string }[];
    for (const o of [...research, ...itin]) {
      const kind = o.kind ?? "";
      if (kind !== "activity" && kind !== "restaurant" && kind !== "meal") continue;
      const title = (o.title ?? "").trim();
      if (!title || seen.has(title.toLowerCase())) continue;
      seen.add(title.toLowerCase());
      out.push({ title, kind });
    }
    return out.slice(0, 30);
  }, [results]);

  const [voter, setVoter] = useState<string>(() => {
    try {
      return localStorage.getItem(VOTER_KEY) ?? "";
    } catch {
      return "";
    }
  });
  const [nameInput, setNameInput] = useState("");
  const [data, setData] = useState<Tally>({ tallies: {}, mine: [] });

  const load = async () => {
    try {
      const res = await fetch(`${API_BASE}/shared/${token}/votes?voter=${encodeURIComponent(voter)}`);
      if (res.ok) setData(await res.json());
    } catch {
      /* ignore */
    }
  };
  useEffect(() => {
    void load();
  }, [token, voter]); // eslint-disable-line react-hooks/exhaustive-deps

  const saveName = () => {
    const n = nameInput.trim();
    if (!n) return;
    try {
      localStorage.setItem(VOTER_KEY, n);
    } catch {
      /* private mode */
    }
    setVoter(n);
  };

  const vote = async (title: string) => {
    if (!voter) {
      toast.info("Add your name first, then vote.");
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/shared/${token}/vote`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ item: title, voter }),
      });
      if (res.ok) setData(await res.json());
    } catch {
      toast.error("Couldn't record your vote.");
    }
  };

  if (items.length === 0) return null;
  const ranked = [...items].sort((a, b) => (data.tallies[b.title] ?? 0) - (data.tallies[a.title] ?? 0));

  return (
    <section className="mb-6">
      <div className="surface-card p-5">
        <div className="mb-1 flex items-center gap-2">
          <Users className="h-5 w-5 text-[var(--brand-500)]" />
          <h3 className="text-base font-semibold">Vote on places</h3>
        </div>
        <p className="mb-4 text-sm text-[var(--muted)]">
          Travelling as a group? Everyone votes for the spots they want — the tally updates live.
        </p>

        {!voter ? (
          <div className="mb-4 flex flex-wrap items-center gap-2">
            <input
              value={nameInput}
              onChange={(e) => setNameInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && saveName()}
              placeholder="Your name"
              className="flex-1 rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm"
            />
            <Button size="sm" onClick={saveName}>
              Start voting
            </Button>
          </div>
        ) : (
          <p className="mb-3 text-xs text-[var(--muted)]">
            Voting as <span className="font-medium text-[var(--text)]">{voter}</span>
          </p>
        )}

        <ul className="space-y-1.5">
          {ranked.map((it) => {
            const count = data.tallies[it.title] ?? 0;
            const mine = data.mine.includes(it.title);
            return (
              <li key={it.title} className="flex items-center gap-2 rounded-[var(--r-md)] border border-[var(--border)] px-3 py-2 text-sm">
                <span className="min-w-0 flex-1 truncate">{it.title}</span>
                <span className="shrink-0 tabular-nums text-[var(--muted)]">{count}</span>
                <button
                  onClick={() => void vote(it.title)}
                  aria-pressed={mine}
                  aria-label={mine ? "Remove vote" : "Vote"}
                  className={cn(
                    "inline-flex shrink-0 items-center gap-1 rounded-[var(--r-pill)] border px-2.5 py-1 text-xs font-medium transition-colors",
                    mine
                      ? "border-[var(--brand-500)] bg-[var(--brand-500)] text-white"
                      : "border-[var(--border)] text-[var(--muted)] hover:border-[var(--brand-400)] hover:text-[var(--brand-500)]",
                  )}
                >
                  <ThumbsUp className="h-3.5 w-3.5" />
                  Vote
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    </section>
  );
}
