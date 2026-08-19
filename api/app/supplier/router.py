"""Supplier Portal endpoints.

Supplier (agency) endpoints are gated by `require_agency` and scoped to the
caller's org. Lead creation is traveler-facing (any signed-in user) — the lead
routes to the right supplier via the listing it references.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth.deps import current_claims, require_agency
from app.core.settings import settings
from app.supplier import store

router = APIRouter(prefix=f"{settings.api_prefix}/supplier", tags=["supplier"])


# --------------------------------------------------------------------------- #
# Supplier-side (agency-gated, org-scoped)
# --------------------------------------------------------------------------- #


class PropertyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    kind: str = Field(default="hotel")
    city: str = Field(min_length=1, max_length=120)
    country: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    halal_friendly: bool = False
    image_url: str | None = Field(default=None, max_length=500)


class ListingCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    price_amount: float | None = None
    price_currency: str = Field(default="MYR", max_length=8)
    capacity: int | None = None
    perks: list[str] = Field(default_factory=list)
    available: bool = True


@router.get("/summary")
async def supplier_summary(agency: dict = Depends(require_agency)) -> dict[str, Any]:
    return {"org": {"id": agency["org_id"], "name": agency["org_name"]}, **await store.summary(agency["org_id"])}


@router.get("/properties")
async def supplier_properties(agency: dict = Depends(require_agency)) -> dict[str, Any]:
    return {"properties": await store.list_properties(agency["org_id"])}


@router.post("/properties")
async def create_property(body: PropertyCreate, agency: dict = Depends(require_agency)) -> dict[str, Any]:
    prop = await store.create_property(agency["org_id"], **body.model_dump())
    if prop is None:
        raise HTTPException(status_code=503, detail="Could not save — the database is unavailable.")
    return prop


@router.delete("/properties/{property_id}")
async def delete_property(property_id: str, agency: dict = Depends(require_agency)) -> dict[str, bool]:
    return {"deleted": await store.delete_property(agency["org_id"], property_id)}


@router.post("/properties/{property_id}/listings")
async def create_listing(
    property_id: str, body: ListingCreate, agency: dict = Depends(require_agency)
) -> dict[str, Any]:
    listing = await store.add_listing(agency["org_id"], property_id, **body.model_dump())
    if listing is None:
        raise HTTPException(status_code=404, detail="Property not found for your organization.")
    return listing


@router.delete("/listings/{listing_id}")
async def delete_listing(listing_id: str, agency: dict = Depends(require_agency)) -> dict[str, bool]:
    return {"deleted": await store.delete_listing(agency["org_id"], listing_id)}


@router.get("/leads")
async def supplier_leads(agency: dict = Depends(require_agency)) -> dict[str, Any]:
    return {"leads": await store.list_leads(agency["org_id"])}


# --------------------------------------------------------------------------- #
# Traveler-side — create a lead against a listing (any signed-in user)
# --------------------------------------------------------------------------- #


class LeadCreate(BaseModel):
    listing_id: str
    note: str | None = Field(default=None, max_length=1000)


@router.post("/leads")
async def create_lead(body: LeadCreate, request: Request) -> dict[str, Any]:
    claims = current_claims(request)
    ctx = await store.listing_context(body.listing_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail="That listing is no longer available.")
    lead = await store.create_lead(
        org_id=ctx["org_id"],
        property_id=ctx["property_id"],
        listing_id=body.listing_id,
        traveler_user_id=str(claims["sub"]),
        traveler_email=claims.get("email"),
        note=body.note,
    )
    if lead is None:
        raise HTTPException(status_code=503, detail="Could not send your request right now.")
    return {"status": "sent", "lead_id": lead["id"]}
