import { useCallback, useState } from "react";
import * as AlertDialog from "@radix-ui/react-alert-dialog";
import { create } from "zustand";
import { cn } from "@/lib/cn";
import { Button } from "./Button";

/**
 * Promise-based confirm — replaces window.confirm (spec §10.4).
 *
 *   const ok = await confirm({ title: "Apply recovery plan?", … });
 */
export type ConfirmOptions = {
  title: string;
  body?: string;
  confirmText?: string;
  cancelText?: string;
  tone?: "brand" | "danger";
};

type ConfirmRequest = ConfirmOptions & { resolve: (ok: boolean) => void };

type ConfirmStore = {
  request: ConfirmRequest | null;
  open: (request: ConfirmRequest) => void;
  close: () => void;
};

const useConfirmStore = create<ConfirmStore>((set) => ({
  request: null,
  open: (request) => set({ request }),
  close: () => set({ request: null }),
}));

export function confirm(options: ConfirmOptions): Promise<boolean> {
  return new Promise((resolve) => {
    useConfirmStore.getState().open({ ...options, resolve });
  });
}

/** Mount once, near the app root. */
export function ConfirmDialogHost() {
  const { request, close } = useConfirmStore();
  const [pending, setPending] = useState(false);

  const settle = useCallback(
    (ok: boolean) => {
      request?.resolve(ok);
      setPending(false);
      close();
    },
    [request, close],
  );

  const tone = request?.tone ?? "brand";

  return (
    <AlertDialog.Root
      open={Boolean(request)}
      onOpenChange={(open) => {
        if (!open) settle(false);
      }}
    >
      <AlertDialog.Portal>
        {/* z-[100]/[101] keeps the blocking confirm ABOVE every feature modal
            (booking dialog z-80/81, receipt z-80/81, engine z-71). A lower value
            renders it behind an open dialog — invisible but focus-trapping, which
            froze the whole screen when confirming payment. */}
        <AlertDialog.Overlay
          className={cn(
            "fixed inset-0 z-[100] bg-black/40 backdrop-blur-sm",
            "data-[state=open]:animate-in",
          )}
        />
        <AlertDialog.Content
          className={cn(
            "radix-panel fixed left-1/2 top-1/2 z-[101] w-[calc(100%-2rem)] max-w-md",
            "-translate-x-1/2 -translate-y-1/2 rounded-[var(--r-lg)]",
            "border border-[var(--border)] bg-[var(--elevated)] p-6",
            "shadow-[var(--shadow-2)]",
          )}
        >
          <AlertDialog.Title className="font-[family-name:var(--font-display)] text-lg">
            {request?.title}
          </AlertDialog.Title>
          {request?.body && (
            <AlertDialog.Description className="mt-2 text-sm text-[var(--muted)]">
              {request.body}
            </AlertDialog.Description>
          )}
          <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <AlertDialog.Cancel asChild>
              <Button variant="ghost" disabled={pending}>
                {request?.cancelText ?? "Cancel"}
              </Button>
            </AlertDialog.Cancel>
            <Button
              variant={tone === "danger" ? "danger" : "primary"}
              loading={pending}
              onClick={() => {
                setPending(true);
                settle(true);
              }}
            >
              {request?.confirmText ?? "Confirm"}
            </Button>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  );
}
