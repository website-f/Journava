import * as Dialog from "@radix-ui/react-dialog";
import { NavLink } from "react-router-dom";
import { X, Moon, Sun, Download, LogOut, type IconType } from "@/components/ui/icons";
import { cn } from "@/lib/cn";
import { useAuth } from "@/providers/AuthProvider";
import { useTheme } from "@/lib/theme";
import { useInstallPrompt } from "@/hooks/useInstallPrompt";

export type MoreLink = { to: string; label: string; icon: IconType };

/**
 * Mobile "More" bottom-sheet — the phone home for surfaces that don't fit the
 * 5-slot bottom bar (Profile, and, for admins, Engine + API Vault) plus theme,
 * install and sign-out. Fixes the "can't reach it on mobile" gap (§10.7).
 */
export function MobileMoreSheet({
  open,
  onOpenChange,
  links,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  links: readonly MoreLink[];
}) {
  const { user, signOut } = useAuth();
  const { theme, toggle } = useTheme();
  const { canInstall, install } = useInstallPrompt();

  const actionClass = cn(
    "flex flex-1 items-center justify-center gap-2 rounded-[var(--r-md)]",
    "border border-[var(--border)] py-2.5 text-sm font-medium",
    "hover:bg-[color-mix(in_srgb,var(--brand-400)_8%,transparent)]",
  );

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[70] bg-black/40 backdrop-blur-sm" />
        <Dialog.Content
          className={cn(
            "fixed inset-x-0 bottom-0 z-[71] rounded-t-[var(--r-lg)]",
            "border-t border-[var(--border)] bg-[var(--elevated)]",
            "p-4 pb-[calc(env(safe-area-inset-bottom)+1rem)] shadow-[var(--shadow-2)]",
          )}
        >
          <Dialog.Description className="sr-only">Account, settings and more pages</Dialog.Description>
          <div className="mx-auto mb-4 h-1 w-10 rounded-full bg-[var(--border)]" />

          <div className="mb-3 flex items-center justify-between">
            <div className="flex min-w-0 items-center gap-3">
              <div className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-[color-mix(in_srgb,var(--brand-400)_18%,transparent)] text-sm font-semibold text-[var(--brand-500)]">
                {(user?.display_name || user?.email || "?").slice(0, 1).toUpperCase()}
              </div>
              <div className="min-w-0">
                <Dialog.Title className="truncate text-sm font-medium">
                  {user?.display_name ?? "Account"}
                </Dialog.Title>
                <p className="truncate text-xs text-[var(--muted)]">{user?.email}</p>
              </div>
            </div>
            <Dialog.Close
              aria-label="Close"
              className="rounded-[var(--r-sm)] p-2 text-[var(--muted)] hover:text-[var(--text)]"
            >
              <X className="h-5 w-5" />
            </Dialog.Close>
          </div>

          <nav className="grid gap-1">
            {links.map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                onClick={() => onOpenChange(false)}
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-3 rounded-[var(--r-md)] px-3 py-2.5 text-sm font-medium",
                    isActive
                      ? "bg-[color-mix(in_srgb,var(--brand-400)_14%,transparent)] text-[var(--brand-500)]"
                      : "text-[var(--text)] hover:bg-[color-mix(in_srgb,var(--brand-400)_6%,transparent)]",
                  )
                }
              >
                <Icon className="h-[18px] w-[18px]" />
                {label}
              </NavLink>
            ))}
          </nav>

          <div className="mt-3 flex items-center gap-2 border-t border-[var(--border)] pt-3">
            <button onClick={() => toggle()} className={actionClass}>
              {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
              {theme === "dark" ? "Light" : "Dark"}
            </button>
            {canInstall && (
              <button onClick={() => install()} className={actionClass}>
                <Download className="h-4 w-4" /> Install
              </button>
            )}
            <button
              onClick={() => {
                onOpenChange(false);
                void signOut();
              }}
              className={cn(actionClass, "text-[var(--danger)]")}
            >
              <LogOut className="h-4 w-4" /> Sign out
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
