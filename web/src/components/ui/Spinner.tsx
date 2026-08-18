import { cn } from "@/lib/cn";

/** Token-coloured spinner. Uses currentColor so it inherits button variants. */
export function Spinner({ className }: { className?: string }) {
  return (
    <span
      role="status"
      aria-label="Loading"
      className={cn(
        "inline-block shrink-0 rounded-full border-2 border-current",
        "border-t-transparent [animation:journava-spin_700ms_linear_infinite]",
        "h-4 w-4",
        className,
      )}
    />
  );
}
