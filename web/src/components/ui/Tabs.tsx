/**
 * Radix Tabs — styled to the Aurora design system (spec §10).
 *
 * The list is a native-style segmented control: one row that scrolls sideways on
 * overflow instead of wrapping, with the active trigger kept in view. Without the
 * auto-centering below, selecting the last tab of an overflowing strip (Trip has
 * four, Research has five) left the chip you just tapped half off-screen, which is
 * the sort of thing that makes a tab strip feel like a web page.
 */

import * as TabsPrimitive from "@radix-ui/react-tabs";
import { cn } from "@/lib/cn";
import { type ComponentPropsWithoutRef, useEffect, useRef } from "react";

export const Tabs = TabsPrimitive.Root;

/** Slides the active trigger to the middle of the strip, if the strip scrolls. */
function centerActive(list: HTMLElement) {
  if (list.scrollWidth <= list.clientWidth + 4) return;
  const active = list.querySelector<HTMLElement>('[role="tab"][data-state="active"]');
  if (!active) return;
  const left = active.offsetLeft - (list.clientWidth - active.offsetWidth) / 2;
  list.scrollTo({ left: Math.max(0, left), behavior: "smooth" });
}

export function TabsList({
  className,
  ...props
}: ComponentPropsWithoutRef<typeof TabsPrimitive.List>) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const list = ref.current;
    if (!list) return;
    centerActive(list);
    // Radix flips `data-state` on the triggers; there is no React-level callback
    // for it here (the value may be controlled anywhere up the tree), so observe
    // the attribute directly.
    const observer = new MutationObserver(() => centerActive(list));
    observer.observe(list, {
      subtree: true,
      attributes: true,
      attributeFilter: ["data-state"],
    });
    return () => observer.disconnect();
  }, []);

  return (
    <TabsPrimitive.List
      ref={ref}
      className={cn(
        "no-scrollbar flex max-w-full items-center gap-1 overflow-x-auto",
        "rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--bg)] p-1",
        // Scroll padding keeps a centered chip clear of the 4px inner padding, and
        // containment stops an over-swipe from panning the page or firing the
        // browser's back gesture.
        "scroll-p-1 [overscroll-behavior-inline:contain]",
        className,
      )}
      {...props}
    />
  );
}

export function TabsTrigger({
  className,
  ...props
}: ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      className={cn(
        "inline-flex shrink-0 items-center justify-center gap-1.5 whitespace-nowrap",
        "rounded-[calc(var(--r-md)-4px)] px-3.5 py-2",
        "text-[0.8125rem] font-semibold text-[var(--muted)] select-none",
        "transition-[color,background-color,box-shadow,transform] duration-[var(--dur)] ease-[var(--ease)]",
        "hover:text-[var(--text)] active:scale-[0.97]",
        "data-[state=active]:bg-[var(--surface)] data-[state=active]:text-[var(--text)]",
        "data-[state=active]:shadow-[var(--shadow-1)]",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]",
        className,
      )}
      {...props}
    />
  );
}

export function TabsContent({
  className,
  ...props
}: ComponentPropsWithoutRef<typeof TabsPrimitive.Content>) {
  return (
    <TabsPrimitive.Content
      className={cn(
        "mt-5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]",
        className,
      )}
      {...props}
    />
  );
}
