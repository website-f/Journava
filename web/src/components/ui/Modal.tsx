import type { ReactNode } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { X } from "@/components/ui/icons";
import { cn } from "@/lib/cn";

/**
 * Modal + Drawer — the two overlay shells the console uses so that *every* form
 * lives behind a button instead of stacked inline on the page (spec: forms in
 * modals/off-canvas). Both are Radix Dialog underneath, so they focus-trap, close
 * on Escape/outside-click, and portal above the app. Styling is elevation-first
 * (`--shadow-3` on `--elevated`) rather than a hard border, matching the consumer
 * PWA's floating surfaces.
 *
 *   <Modal open={open} onOpenChange={setOpen} title="New booking" icon={<Calendar/>}
 *          footer={<Button>Save</Button>}>
 *     …fields…
 *   </Modal>
 */

const OVERLAY = "fixed inset-0 z-[80] bg-black/45 backdrop-blur-sm data-[state=open]:animate-in";

type Common = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  icon?: ReactNode;
  children: ReactNode;
  /** Sticky action row pinned to the bottom of the panel. */
  footer?: ReactNode;
  className?: string;
};

function Header({ title, description, icon }: Pick<Common, "title" | "description" | "icon">) {
  return (
    <div className="flex items-start gap-3 border-b border-[var(--border)] px-5 py-4">
      {icon && (
        <span className="mt-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-[var(--r-md)] bg-[color-mix(in_srgb,var(--brand-400)_16%,transparent)] text-[var(--brand-500)]">
          {icon}
        </span>
      )}
      <div className="min-w-0 flex-1">
        <Dialog.Title className="font-[family-name:var(--font-display)] text-lg tracking-tight">
          {title}
        </Dialog.Title>
        {description && (
          <Dialog.Description className="mt-0.5 text-sm text-[var(--muted)]">
            {description}
          </Dialog.Description>
        )}
      </div>
      <Dialog.Close
        aria-label="Close"
        className="tap-target -mr-1 grid h-8 w-8 shrink-0 place-items-center rounded-full text-[var(--muted)] transition-colors hover:bg-[var(--bg)] hover:text-[var(--text)]"
      >
        <X className="h-4 w-4" />
      </Dialog.Close>
    </div>
  );
}

/** Centered dialog — the default for short forms and confirmations. */
export function Modal({ open, onOpenChange, title, description, icon, children, footer, className }: Common) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className={OVERLAY} />
        <Dialog.Content
          className={cn(
            "radix-panel fixed left-1/2 top-1/2 z-[81] flex max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)] max-w-lg",
            "-translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-[var(--r-lg)]",
            "border border-[var(--border)] bg-[var(--elevated)] shadow-[var(--shadow-3)]",
            className,
          )}
        >
          <Header title={title} description={description} icon={icon} />
          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
          {footer && (
            <div className="flex flex-wrap items-center justify-end gap-2 border-t border-[var(--border)] bg-[var(--surface)] px-5 py-3">
              {footer}
            </div>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/** Right-side off-canvas sheet — for richer, taller content (AI composer, details). */
export function Drawer({ open, onOpenChange, title, description, icon, children, footer, className }: Common) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className={OVERLAY} />
        <Dialog.Content
          className={cn(
            "radix-sheet fixed right-0 top-0 z-[81] flex h-[100dvh] w-full max-w-md flex-col",
            "border-l border-[var(--border)] bg-[var(--elevated)] shadow-[var(--shadow-3)]",
            className,
          )}
        >
          <Header title={title} description={description} icon={icon} />
          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
          {footer && (
            <div className="flex flex-wrap items-center justify-end gap-2 border-t border-[var(--border)] bg-[var(--surface)] px-5 py-3">
              {footer}
            </div>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
