import { type FormEvent, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Building2, Plus, Trash2, Ticket, CheckCircle } from "@/components/ui/icons";
import { Button, Tabs, TabsList, TabsTrigger, TabsContent, EmptyState, confirm } from "@/components/ui";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";

type Listing = {
  id: string;
  title: string;
  price_amount: number | null;
  price_currency: string;
  capacity: number | null;
  perks: string[];
  available: boolean;
};
type Property = {
  id: string;
  name: string;
  kind: string;
  city: string;
  country?: string | null;
  halal_friendly: boolean;
  listings: Listing[];
};
type Lead = {
  id: string;
  status: string;
  note?: string | null;
  traveler_email?: string | null;
  property_name?: string | null;
  listing_title?: string | null;
  created_at?: string | null;
};
type Summary = {
  org: { id: string; name: string };
  properties: number;
  listings: number;
  leads: number;
  new_leads: number;
};

const FIELD =
  "h-10 w-full rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--surface)] px-3 text-sm outline-none focus-visible:border-[var(--brand-400)] focus-visible:ring-2 focus-visible:ring-[var(--accent)]";

/**
 * Supplier (Partner) Portal — the B2B side. A hotel/attraction org lists
 * properties + bookable listings (which surface as "direct" in traveler search)
 * and works the leads travelers send. Agency-gated in the router; this screen is
 * only routed to for agency users.
 */
export function SupplierPortal() {
  const qc = useQueryClient();

  const summary = useQuery({ queryKey: ["supplier", "summary"], queryFn: () => api.get<Summary>("/supplier/summary") });
  const properties = useQuery({
    queryKey: ["supplier", "properties"],
    queryFn: () => api.get<{ properties: Property[] }>("/supplier/properties"),
  });
  const leads = useQuery({ queryKey: ["supplier", "leads"], queryFn: () => api.get<{ leads: Lead[] }>("/supplier/leads") });

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ["supplier"] });
  };

  const [name, setName] = useState("");
  const [city, setCity] = useState("");
  const [halal, setHalal] = useState(false);

  const createProperty = useMutation({
    mutationFn: (body: { name: string; city: string; halal_friendly: boolean }) =>
      api.post<Property>("/supplier/properties", { ...body, kind: "hotel" }),
    onSuccess: () => {
      toast.success("Property added");
      setName("");
      setCity("");
      setHalal(false);
      invalidate();
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Could not add property"),
  });

  const submitProperty = (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim() || !city.trim()) return;
    createProperty.mutate({ name: name.trim(), city: city.trim(), halal_friendly: halal });
  };

  const props = properties.data?.properties ?? [];
  const s = summary.data;

  return (
    <div className="mx-auto w-full max-w-5xl">
      <header className="pt-2 pb-5">
        <h2 className="flex items-center gap-2 font-[family-name:var(--font-display)] text-2xl tracking-tight">
          <Building2 className="h-6 w-6 text-[var(--brand-500)]" /> Partner Portal
        </h2>
        <p className="mt-1 text-sm text-[var(--muted)]">
          {s?.org.name ?? "Your properties"} — list inventory travelers can book direct, no OTA commission.
        </p>
      </header>

      {/* Summary tiles */}
      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          { label: "Properties", value: s?.properties ?? 0 },
          { label: "Listings", value: s?.listings ?? 0 },
          { label: "Leads", value: s?.leads ?? 0 },
          { label: "New leads", value: s?.new_leads ?? 0, accent: true },
        ].map((tile) => (
          <div key={tile.label} className="surface-card p-4">
            <p className="text-xs text-[var(--muted)]">{tile.label}</p>
            <p className={cn("mt-1 text-2xl font-semibold", tile.accent && "text-[var(--brand-500)]")}>
              {tile.value}
            </p>
          </div>
        ))}
      </div>

      <Tabs defaultValue="inventory">
        <TabsList>
          <TabsTrigger value="inventory">
            <Building2 className="h-4 w-4" /> Inventory
          </TabsTrigger>
          <TabsTrigger value="leads">
            <Ticket className="h-4 w-4" /> Leads
          </TabsTrigger>
        </TabsList>

        {/* Inventory */}
        <TabsContent value="inventory" className="space-y-4">
          <form onSubmit={submitProperty} className="surface-card flex flex-wrap items-end gap-3 p-4">
            <div className="min-w-[10rem] flex-1">
              <label className="mb-1 block text-xs font-medium text-[var(--muted)]">Property name</label>
              <input className={FIELD} value={name} onChange={(e) => setName(e.target.value)} placeholder="Kinabalu Bay Resort" />
            </div>
            <div className="min-w-[8rem] flex-1">
              <label className="mb-1 block text-xs font-medium text-[var(--muted)]">City</label>
              <input className={FIELD} value={city} onChange={(e) => setCity(e.target.value)} placeholder="Kota Kinabalu" />
            </div>
            <label className="flex h-10 items-center gap-2 text-sm">
              <input type="checkbox" checked={halal} onChange={(e) => setHalal(e.target.checked)} className="h-4 w-4 accent-[var(--brand-500)]" />
              Halal-friendly
            </label>
            <Button type="submit" loading={createProperty.isPending}>
              <Plus className="h-4 w-4" /> Add property
            </Button>
          </form>

          {props.length === 0 ? (
            <EmptyState title="No properties yet" description="Add your first property above — it becomes bookable in traveler search instantly." />
          ) : (
            props.map((property) => (
              <PropertyCard key={property.id} property={property} onChanged={invalidate} />
            ))
          )}
        </TabsContent>

        {/* Leads */}
        <TabsContent value="leads">
          {(leads.data?.leads ?? []).length === 0 ? (
            <EmptyState title="No leads yet" description="When a traveler books your property direct, their request shows up here." />
          ) : (
            <div className="space-y-2">
              {(leads.data?.leads ?? []).map((lead) => (
                <div key={lead.id} className="surface-card flex items-start gap-3 p-4">
                  <span className="mt-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-full bg-[color-mix(in_srgb,var(--brand-400)_16%,transparent)] text-[var(--brand-500)]">
                    <Ticket className="h-4 w-4" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium">
                      {lead.property_name ?? "Property"} — {lead.listing_title ?? "Listing"}
                    </p>
                    <p className="text-xs text-[var(--muted)] break-all">
                      {lead.traveler_email ?? "traveler"} · {lead.created_at ? new Date(lead.created_at).toLocaleString() : ""}
                    </p>
                    {lead.note && <p className="mt-1 text-sm">{lead.note}</p>}
                  </div>
                  <span className="shrink-0 rounded-[var(--r-pill)] bg-[color-mix(in_srgb,var(--warning)_16%,transparent)] px-2.5 py-1 text-[0.65rem] font-semibold uppercase text-[var(--warning)]">
                    {lead.status}
                  </span>
                </div>
              ))}
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}

// --------------------------------------------------------------------------- //

function PropertyCard({ property, onChanged }: { property: Property; onChanged: () => void }) {
  const [title, setTitle] = useState("");
  const [price, setPrice] = useState("");

  const addListing = useMutation({
    mutationFn: () =>
      api.post<Listing>(`/supplier/properties/${property.id}/listings`, {
        title: title.trim(),
        price_amount: price ? Number(price) : null,
        price_currency: "MYR",
      }),
    onSuccess: () => {
      toast.success("Listing added");
      setTitle("");
      setPrice("");
      onChanged();
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Could not add listing"),
  });

  const removeListing = async (id: string) => {
    await api.del(`/supplier/listings/${id}`);
    onChanged();
  };

  const removeProperty = async () => {
    const ok = await confirm({
      title: `Delete ${property.name}?`,
      body: "This removes the property and all its listings. This can't be undone.",
      confirmText: "Delete",
      tone: "danger",
    });
    if (!ok) return;
    await api.del(`/supplier/properties/${property.id}`);
    toast.info("Property deleted");
    onChanged();
  };

  return (
    <div className="surface-card p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-medium">
            {property.name}
            {property.halal_friendly && (
              <span className="ml-2 inline-flex items-center gap-1 rounded-[var(--r-pill)] bg-[color-mix(in_srgb,var(--success)_14%,transparent)] px-2 py-0.5 text-[0.6rem] font-semibold uppercase text-[var(--success)]">
                <CheckCircle className="h-3 w-3" /> Halal
              </span>
            )}
          </p>
          <p className="text-xs text-[var(--muted)]">{property.city}</p>
        </div>
        <button
          onClick={removeProperty}
          aria-label="Delete property"
          className="rounded-[var(--r-sm)] p-1.5 text-[var(--muted)] hover:bg-[color-mix(in_srgb,var(--danger)_10%,transparent)] hover:text-[var(--danger)]"
        >
          <Trash2 className="h-4 w-4" />
        </button>
      </div>

      <div className="mt-3 space-y-1.5">
        {property.listings.length === 0 && (
          <p className="text-xs text-[var(--muted)]">No listings yet — add a room or ticket below.</p>
        )}
        {property.listings.map((listing) => (
          <div key={listing.id} className="flex items-center gap-3 rounded-[var(--r-md)] border border-[var(--border)] px-3 py-2">
            <span className="min-w-0 flex-1 truncate text-sm">{listing.title}</span>
            <span className="shrink-0 text-sm font-medium">
              {listing.price_amount != null ? `${listing.price_currency} ${listing.price_amount.toLocaleString()}` : "—"}
            </span>
            <button
              onClick={() => void removeListing(listing.id)}
              aria-label="Delete listing"
              className="shrink-0 rounded-[var(--r-sm)] p-1 text-[var(--muted)] hover:text-[var(--danger)]"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (title.trim()) addListing.mutate();
        }}
        className="mt-3 flex flex-wrap items-end gap-2"
      >
        <input className={cn(FIELD, "min-w-[9rem] flex-1")} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Sea-View Deluxe" />
        <input className={cn(FIELD, "w-28")} value={price} onChange={(e) => setPrice(e.target.value)} placeholder="MYR / night" inputMode="numeric" />
        <Button type="submit" variant="secondary" size="sm" loading={addListing.isPending}>
          <Plus className="h-4 w-4" /> Add listing
        </Button>
      </form>
    </div>
  );
}
