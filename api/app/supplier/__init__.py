"""B2B Supplier Portal (Phase 4).

The other side of the marketplace: a hotel/attraction org lists properties and
bookable listings, which surface as a **direct** source in the Hotel Agent (owns
the guest, no OTA commission). Travelers create leads the supplier works.

- `store`  — org-scoped CRUD + the traveler-facing destination search + leads.
- `router` — supplier endpoints (agency-gated) + traveler lead creation.
"""
