/**
 * Radix Tabs — styled to the Aurora design system (spec §10).
 */

import * as TabsPrimitive from "@radix-ui/react-tabs";
import { cn } from "@/lib/cn";
import type { ComponentPropsWithoutRef } from "react";

export const Tabs = TabsPrimitive.Root;

export function TabsList({
  className,
  ...props
}: ComponentPropsWithoutRef<typeof TabsPrimitive.List>) {
  return (
    <TabsPrimitive.List
      className={cn(
        // Single row that scrolls horizontally on overflow (never wraps/stacks),
        // with the scrollbar hidden — the native-app tab-strip pattern. Triggers
        // are shrink-0 so they keep their size and the row scrolls instead.
        "flex max-w-full items-center gap-1 overflow-x-auto no-scrollbar rounded-[var(--r-md)] bg-[var(--bg)] p-1",
        "border border-[var(--border)]",
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
        "inline-flex shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-[var(--r-sm)] px-3 py-1.5",
        "text-sm font-medium text-[var(--muted)] select-none",
        "transition-[color,background] duration-[var(--dur)] ease-[var(--ease)]",
        "hover:text-[var(--text)]",
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
        "mt-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]",
        className,
      )}
      {...props}
    />
  );
}
