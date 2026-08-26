import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { Image as ImageIcon, X } from "@/components/ui/icons";
import type { IconType } from "@/components/ui/icons";

/**
 * Shared console layout primitives — the professional, non-generic look the
 * consumer PWA has: elevation-first surfaces, a titled `Section` band instead of
 * bare bordered boxes, headers that carry their own primary action, and forms
 * that live in modals/drawers rather than stacked inline. Kept in one module so
 * panels.tsx / AgentStudio.tsx render from the same vocabulary.
 */

export function useGet<T>(path: string) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const reload = useCallback(() => {
    setLoading(true);
    api.get<T>(path).then(setData).catch(() => setData(null)).finally(() => setLoading(false));
  }, [path]);
  useEffect(() => { reload(); }, [reload]);
  return { data, loading, reload };
}

/** Page header — icon tile, display title, subtitle, and a right-aligned slot for
 *  the panel's primary action (so "New booking", "Add client" etc. sit here). */
export function PageHead({
  title, subtitle, icon: Icon, actions,
}: { title: string; subtitle: string; icon: IconType; actions?: ReactNode }) {
  return (
    <header className="mb-6 flex flex-wrap items-start gap-3">
      <span className="mt-0.5 grid h-10 w-10 shrink-0 place-items-center rounded-[var(--r-md)] bg-[color-mix(in_srgb,var(--brand-400)_16%,transparent)] text-[var(--brand-500)]">
        <Icon className="h-5 w-5" weight="duotone" />
      </span>
      <div className="min-w-0 flex-1">
        <h1 className="font-[family-name:var(--font-display)] text-2xl tracking-tight">{title}</h1>
        <p className="mt-0.5 text-sm text-[var(--muted)]">{subtitle}</p>
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

/** Plain elevated surface (no header). */
export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("surface-card p-5", className)}>{children}</div>;
}

/** A titled section: header band (icon + title + subtitle + actions) over a body.
 *  This is the workhorse that makes the console read as organised rather than a
 *  column of identical boxes. */
export function Section({
  title, subtitle, icon: Icon, actions, children, className, bodyClassName, tone,
}: {
  title: ReactNode; subtitle?: ReactNode; icon?: IconType; actions?: ReactNode;
  children: ReactNode; className?: string; bodyClassName?: string;
  tone?: "brand" | "success";
}) {
  const accent = tone === "success" ? "var(--success)" : "var(--brand-500)";
  return (
    <section className={cn("surface-card overflow-hidden", className)}>
      <header className="flex flex-wrap items-center gap-3 border-b border-[var(--border)] px-5 py-3.5">
        {Icon && (
          <span
            className="grid h-8 w-8 shrink-0 place-items-center rounded-[var(--r-sm)]"
            style={{ background: `color-mix(in srgb, ${accent} 14%, transparent)`, color: accent }}
          >
            <Icon className="h-4 w-4" weight="duotone" />
          </span>
        )}
        <div className="min-w-0">
          <h2 className="text-sm font-semibold leading-tight">{title}</h2>
          {subtitle && <p className="mt-0.5 text-xs text-[var(--muted)]">{subtitle}</p>}
        </div>
        {actions && <div className="ml-auto flex flex-wrap items-center gap-2">{actions}</div>}
      </header>
      <div className={cn("p-5", bodyClassName)}>{children}</div>
    </section>
  );
}

export function Stat({ label, value, tone }: { label: string; value: ReactNode; tone?: "success" | "warning" | "brand" }) {
  const color = tone === "success" ? "text-[var(--success)]" : tone === "warning" ? "text-[var(--warning)]" : "text-[var(--brand-500)]";
  return (
    <div className="surface-card p-4">
      <p className={cn("text-2xl font-bold", color)}>{value}</p>
      <p className="mt-1 text-xs text-[var(--muted)]">{label}</p>
    </div>
  );
}

export function Chip({ children }: { children: ReactNode }) {
  return <span className="rounded-[var(--r-pill)] border border-[var(--border)] bg-[var(--bg)] px-2.5 py-1 text-xs">{children}</span>;
}

export const inputCls =
  "w-full rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm outline-none transition-colors focus:border-[var(--brand-400)] focus:ring-2 focus:ring-[var(--accent)]";

/** Labelled form field for modal/drawer forms. */
export function Field({ label, children, className, hint }: { label: string; children: ReactNode; className?: string; hint?: string }) {
  return (
    <label className={cn("block", className)}>
      <span className="mb-1 block text-xs font-medium text-[var(--muted)]">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[0.7rem] text-[var(--muted)]">{hint}</span>}
    </label>
  );
}

// --------------------------------------------------------------------------- //
// Drag-and-drop multi-image upload
// --------------------------------------------------------------------------- //

/** Downscale + JPEG-compress a dropped file to a compact data URL, so a gallery
 *  of several photos stays small enough to store inline (no object storage). */
async function fileToDataUrl(file: File, maxDim = 1400, quality = 0.72): Promise<string> {
  const raw = await new Promise<string>((res, rej) => {
    const fr = new FileReader();
    fr.onload = () => res(String(fr.result));
    fr.onerror = () => rej(new Error("read failed"));
    fr.readAsDataURL(file);
  });
  try {
    const img = document.createElement("img");
    await new Promise((res, rej) => { img.onload = res; img.onerror = rej; img.src = raw; });
    const scale = Math.min(1, maxDim / Math.max(img.width, img.height));
    if (scale >= 1 && raw.length < 220_000) return raw;
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(img.width * scale);
    canvas.height = Math.round(img.height * scale);
    const ctx = canvas.getContext("2d");
    if (!ctx) return raw;
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL("image/jpeg", quality);
  } catch {
    return raw; // if canvas is unavailable, keep the original
  }
}

export function ImageDropzone({
  value, onChange, max = 8, label = "Drag & drop room photos here",
}: { value: string[]; onChange: (urls: string[]) => void; max?: number; label?: string }) {
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const ingest = useCallback(async (files: FileList | File[]) => {
    const imgs = Array.from(files).filter((f) => f.type.startsWith("image/"));
    if (!imgs.length) return;
    setBusy(true);
    try {
      const room = Math.max(0, max - value.length);
      const urls = await Promise.all(imgs.slice(0, room).map((f) => fileToDataUrl(f)));
      onChange([...value, ...urls]);
    } finally {
      setBusy(false);
    }
  }, [value, onChange, max]);

  return (
    <div>
      <div
        role="button"
        tabIndex={0}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") inputRef.current?.click(); }}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); void ingest(e.dataTransfer.files); }}
        className={cn(
          "flex cursor-pointer flex-col items-center justify-center gap-1.5 rounded-[var(--r-md)] border-2 border-dashed px-4 py-6 text-center transition-colors",
          over
            ? "border-[var(--brand-400)] bg-[color-mix(in_srgb,var(--brand-400)_10%,transparent)]"
            : "border-[var(--border)] bg-[var(--bg)] hover:border-[var(--brand-400)]",
        )}
      >
        <ImageIcon className="h-6 w-6 text-[var(--brand-500)]" weight="duotone" />
        <p className="text-sm font-medium">{busy ? "Processing…" : label}</p>
        <p className="text-[0.7rem] text-[var(--muted)]">
          {value.length}/{max} · JPEG/PNG · click or drop multiple — the first is the cover
        </p>
        <input
          ref={inputRef}
          type="file"
          accept="image/*"
          multiple
          className="hidden"
          onChange={(e) => { if (e.target.files) void ingest(e.target.files); e.target.value = ""; }}
        />
      </div>

      {value.length > 0 && (
        <div className="mt-3 grid grid-cols-3 gap-2 sm:grid-cols-4">
          {value.map((url, i) => (
            <div key={i} className="group relative aspect-[4/3] overflow-hidden rounded-[var(--r-sm)] border border-[var(--border)]">
              <img src={url} alt={`photo ${i + 1}`} className="h-full w-full object-cover" />
              {i === 0 && (
                <span className="absolute left-1 top-1 rounded-[var(--r-pill)] bg-[var(--brand-500)] px-1.5 py-0.5 text-[0.55rem] font-semibold text-white">
                  Cover
                </span>
              )}
              <button
                type="button"
                aria-label="Remove photo"
                onClick={(e) => { e.stopPropagation(); onChange(value.filter((_, j) => j !== i)); }}
                className="absolute right-1 top-1 grid h-6 w-6 place-items-center rounded-full bg-black/55 text-white opacity-0 transition-opacity group-hover:opacity-100"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
