import { useEffect, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { motion } from "framer-motion";
import { toast } from "sonner";
import { Copy, X, UserPlus, Trash2, ExternalLink } from "@/components/ui/icons";
import { Button, Skeleton } from "@/components/ui";
import { cn } from "@/lib/cn";
import { api } from "@/lib/api";
import type { PlanResults } from "@/lib/types";

type Collaborator = {
  id: string;
  email: string;
  role: "viewer" | "editor";
  status: "invited" | "accepted";
  user_id: string | null;
};

/**
 * Share & collaborate on one saved trip.
 *
 * Two levels, both here: a **public link** anyone can open read-only (no
 * account), and named **collaborators** the owner invites by email with a role
 * (viewer or editor). Only the owner sees the invite + manage controls.
 */
export function ShareCollabDialog({
  savedId,
  title,
  onClose,
}: {
  savedId: string;
  title: string;
  onClose: () => void;
}) {
  const [loading, setLoading] = useState(true);
  const [myRole, setMyRole] = useState<string | null>(null);
  const [collabs, setCollabs] = useState<Collaborator[]>([]);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<"viewer" | "editor">("editor");
  const [inviting, setInviting] = useState(false);
  const [link, setLink] = useState<string | null>(null);
  const [linkBusy, setLinkBusy] = useState(false);

  const load = async () => {
    try {
      const res = await api.get<{ collaborators: Collaborator[]; my_role: string }>(
        `/trip/${savedId}/collaborators`,
      );
      setCollabs(res.collaborators ?? []);
      setMyRole(res.my_role);
    } catch {
      /* access denied / not found — leave empty */
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [savedId]);

  const isOwner = myRole === "owner";

  const makeLink = async () => {
    setLinkBusy(true);
    try {
      // Share this specific saved trip's snapshot (not whatever's active).
      const full = await api.get<{ results: PlanResults }>(`/saved/${savedId}`);
      const res = await api.post<{ url: string }>("/trip/share", { results: full.results });
      const url = res.url.startsWith("http") ? res.url : `${window.location.origin}${res.url}`;
      setLink(url);
      await navigator.clipboard?.writeText(url).catch(() => {});
      toast.success("Public link copied — anyone can open it read-only.");
    } catch {
      toast.error("Couldn't create a public link.");
    } finally {
      setLinkBusy(false);
    }
  };

  const invite = async () => {
    const value = email.trim();
    if (!value || !value.includes("@")) {
      toast.error("Enter a valid email.");
      return;
    }
    setInviting(true);
    try {
      const res = await api.post<{ linked: boolean }>(`/trip/${savedId}/collaborators`, {
        email: value,
        role,
      });
      setEmail("");
      toast.success(
        res.linked ? "Invited — they can collaborate now." : "Invited — they'll get access when they sign in.",
      );
      await load();
    } catch {
      toast.error("Couldn't send that invite.");
    } finally {
      setInviting(false);
    }
  };

  const changeRole = async (c: Collaborator, next: "viewer" | "editor") => {
    try {
      await api.patch(`/trip/${savedId}/collaborators/${c.id}`, { role: next });
      await load();
    } catch {
      toast.error("Couldn't change that role.");
    }
  };

  const revoke = async (c: Collaborator) => {
    try {
      await api.del(`/trip/${savedId}/collaborators/${c.id}`);
      setCollabs((prev) => prev.filter((x) => x.id !== c.id));
    } catch {
      toast.error("Couldn't remove that person.");
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
              <div className="min-w-0">
                <Dialog.Title className="font-[family-name:var(--font-display)] text-lg">Share “{title}”</Dialog.Title>
                <Dialog.Description className="text-xs text-[var(--muted)]">
                  A public link for anyone, or invite people to collaborate.
                </Dialog.Description>
              </div>
              <Dialog.Close asChild>
                <Button variant="ghost" size="icon" aria-label="Close">
                  <X className="h-4 w-4" />
                </Button>
              </Dialog.Close>
            </div>

            {/* Public link */}
            <section className="mt-4">
              <h4 className="text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">Public link</h4>
              {link ? (
                <div className="mt-1.5 flex items-center gap-2 rounded-[var(--r-md)] border border-[var(--border)] p-2">
                  <span className="min-w-0 flex-1 truncate font-[family-name:var(--font-mono)] text-xs">{link}</span>
                  <button
                    onClick={() => void navigator.clipboard?.writeText(link)}
                    className="shrink-0 rounded-[var(--r-sm)] p-1 text-[var(--muted)] hover:text-[var(--brand-500)]"
                    aria-label="Copy link"
                  >
                    <Copy className="h-4 w-4" />
                  </button>
                  <a
                    href={link}
                    target="_blank"
                    rel="noreferrer"
                    className="shrink-0 rounded-[var(--r-sm)] p-1 text-[var(--muted)] hover:text-[var(--brand-500)]"
                    aria-label="Open link"
                  >
                    <ExternalLink className="h-4 w-4" />
                  </a>
                </div>
              ) : (
                <Button variant="secondary" size="sm" className="mt-1.5" loading={linkBusy} onClick={() => void makeLink()}>
                  <Copy className="h-4 w-4" /> Create public read-only link
                </Button>
              )}
            </section>

            {/* Collaborators */}
            <section className="mt-5">
              <h4 className="text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">People</h4>

              {isOwner && (
                <div className="mt-1.5 flex flex-wrap items-center gap-2">
                  <input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="name@email.com"
                    className="min-w-0 flex-1 rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm"
                  />
                  <select
                    value={role}
                    onChange={(e) => setRole(e.target.value as "viewer" | "editor")}
                    className="rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--bg)] px-2 py-2 text-sm"
                  >
                    <option value="editor">Can edit</option>
                    <option value="viewer">Can view</option>
                  </select>
                  <Button size="sm" loading={inviting} onClick={() => void invite()}>
                    <UserPlus className="h-4 w-4" /> Invite
                  </Button>
                </div>
              )}

              <div className="mt-3 space-y-1.5">
                {loading ? (
                  <Skeleton className="h-10 w-full" />
                ) : collabs.length === 0 ? (
                  <p className="text-xs text-[var(--muted)]">No collaborators yet.</p>
                ) : (
                  collabs.map((c) => (
                    <div key={c.id} className="flex items-center gap-2 rounded-[var(--r-md)] border border-[var(--border)] px-3 py-2">
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm">{c.email}</p>
                        <p className="text-[0.65rem] text-[var(--muted)]">
                          {c.status === "accepted" ? "Active" : "Invited"}
                        </p>
                      </div>
                      {isOwner ? (
                        <select
                          value={c.role}
                          onChange={(e) => void changeRole(c, e.target.value as "viewer" | "editor")}
                          className="rounded-[var(--r-sm)] border border-[var(--border)] bg-[var(--bg)] px-1.5 py-1 text-xs"
                        >
                          <option value="editor">Editor</option>
                          <option value="viewer">Viewer</option>
                        </select>
                      ) : (
                        <span className="rounded-[var(--r-pill)] bg-[color-mix(in_srgb,var(--brand-400)_16%,transparent)] px-2 py-0.5 text-[0.65rem] font-semibold capitalize text-[var(--brand-600)]">
                          {c.role}
                        </span>
                      )}
                      {isOwner && (
                        <button
                          onClick={() => void revoke(c)}
                          aria-label={`Remove ${c.email}`}
                          className="shrink-0 rounded-[var(--r-sm)] p-1 text-[var(--muted)] hover:text-[var(--danger)]"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      )}
                    </div>
                  ))
                )}
              </div>
            </section>

            <Button className="mt-5 w-full" variant="secondary" onClick={onClose}>
              Done
            </Button>
          </motion.div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
