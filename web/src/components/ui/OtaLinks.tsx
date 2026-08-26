/**
 * A compact "compare & book" row of OTA links (Booking.com · Agoda · Trip.com …
 * for stays; Skyscanner · Kayak · Trip.com … for flights). Backend attaches these
 * as `raw.ota_links` so a card is never limited to a single Google link.
 */
export function OtaLinks({
  links,
  label = "Compare & book",
}: {
  links?: { name: string; url: string }[] | null;
  label?: string;
}) {
  if (!links || links.length === 0) return null;
  return (
    <div className="mt-2 flex flex-wrap items-center gap-1.5">
      <span className="text-[0.6rem] font-semibold uppercase tracking-wide text-[var(--muted)]">{label}</span>
      {links.map((l) => (
        <a
          key={l.name}
          href={l.url}
          target="_blank"
          rel="noreferrer noopener"
          className="rounded-[var(--r-pill)] border border-[var(--border)] bg-[var(--bg)] px-2 py-0.5 text-[0.65rem] font-medium text-[var(--text)] transition-colors hover:border-[var(--brand-400)] hover:text-[var(--brand-600)]"
        >
          {l.name}
        </a>
      ))}
    </div>
  );
}
