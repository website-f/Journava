"""Demo trip seed data — pre-loads a sample Venice trip so the demo starts instantly.

When the API boots and no active trip exists, this module populates the trip store
with a realistic pre-planned trip. Judges see a full itinerary immediately.

The demo trip uses the spec §3.1 example:
  "Plan a 7-day Venice trip for 2, budget RM8,000, we love food + culture, avoid crowds, max 1 connection."
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def get_demo_trip() -> dict[str, Any]:
    """Return a comprehensive pre-planned Venice trip for demo purposes."""
    return {
        "chief": {
            "agent": "chief",
            "summary": "7-day Venice trip for 2 — food & culture focus, RM8,000 budget",
            "options": [],
            "items": [],
            "applied_preferences": {"interests": "food, culture", "pace": "relaxed"},
            "warnings": [],
            "data": {
                "destination": "Venice, Italy",
                "origin": "Kuala Lumpur (KUL)",
                "travellers": 2,
                "budget_amount": 8000,
                "budget_currency": "MYR",
                "goal": "7-day Venice trip for 2, food and culture focus, avoid crowds",
                "parsed_destinations": ["Venice", "Murano", "Burano"],
            },
        },
        "flight": {
            "agent": "flight",
            "summary": "3 flight options found — KUL→VCE from RM2,450",
            "options": [
                {
                    "id": "FLT-001", "kind": "flight", "title": "Qatar Airways — KUL→VCE via DOH",
                    "price_amount": 2450, "price_currency": "MYR", "provider": "Atlas Skill",
                    "booking_url": None, "reasoning": "Best value: 1 stop (Doha), 16h total, halal meal (MOML) included",
                    "halal_confidence": None, "verified": True, "last_checked": "2 min ago",
                    "raw": {"airline": "Qatar Airways", "stops": 1, "duration_h": 16, "meal": "MOML"},
                },
                {
                    "id": "FLT-002", "kind": "flight", "title": "Emirates — KUL→VCE via DXB",
                    "price_amount": 2890, "price_currency": "MYR", "provider": "Atlas Skill",
                    "booking_url": None, "reasoning": "Premium option: 1 stop (Dubai), 18h, newer aircraft",
                    "halal_confidence": None, "verified": True, "last_checked": "2 min ago",
                    "raw": {"airline": "Emirates", "stops": 1, "duration_h": 18, "meal": "MOML"},
                },
                {
                    "id": "FLT-003", "kind": "flight", "title": "Turkish Airlines — KUL→VCE via IST",
                    "price_amount": 2180, "price_currency": "MYR", "provider": "Atlas Skill",
                    "booking_url": None, "reasoning": "Cheapest: 1 stop (Istanbul), 19h, halal-certified catering",
                    "halal_confidence": None, "verified": True, "last_checked": "2 min ago",
                    "raw": {"airline": "Turkish Airlines", "stops": 1, "duration_h": 19, "meal": "MOML"},
                },
            ],
            "items": [],
            "applied_preferences": {"halal_meal": "MOML", "max_connections": 1},
            "warnings": ["All flights include halal meal request (MOML)"],
            "data": {"global_search": True, "meal_request": "MOML"},
        },
        "hotel": {
            "agent": "hotel",
            "summary": "3 hotels shortlisted — from RM280/night near San Marco",
            "options": [
                {
                    "id": "HTL-001", "kind": "hotel", "title": "Hotel Belle Arti — San Marco",
                    "price_amount": 320, "price_currency": "MYR", "provider": "Hotels API",
                    "booking_url": None, "reasoning": "Best location: 2 min walk to St Mark's Square, breakfast included, halal-friendly",
                    "halal_confidence": "muslim_friendly", "verified": True, "last_checked": "5 min ago",
                    "raw": {"stars": 3, "per_night": True, "breakfast": True, "near_transit": True},
                },
                {
                    "id": "HTL-002", "kind": "hotel", "title": "Ca' dei Dogi — Castello",
                    "price_amount": 280, "price_currency": "MYR", "provider": "Hotels API",
                    "booking_url": None, "reasoning": "Best value: quiet area, 10 min to Rialto, kitchen available for self-catering",
                    "halal_confidence": None, "verified": True, "last_checked": "5 min ago",
                    "raw": {"stars": 3, "per_night": True, "breakfast": False, "kitchen": True},
                },
                {
                    "id": "HTL-003", "kind": "hotel", "title": "Aman Venice — Grand Canal",
                    "price_amount": 890, "price_currency": "MYR", "provider": "Hotels API",
                    "booking_url": None, "reasoning": "Luxury pick: Grand Canal view, private garden, halal menu on request",
                    "halal_confidence": "muslim_friendly", "verified": True, "last_checked": "5 min ago",
                    "raw": {"stars": 5, "per_night": True, "breakfast": True, "canal_view": True},
                },
            ],
            "items": [],
            "applied_preferences": {"near_transit": "soft_ranking"},
            "warnings": [],
            "data": {"nights": 6},
        },
        "research": {
            "agent": "research",
            "summary": "8 attractions, 6 dining picks for Venice (via 4 live sources) — positive sentiment for food culture",
            "options": [
                {
                    "id": "RSH-A001", "kind": "activity", "title": "St Mark's Basilica — skip-the-line",
                    "price_amount": 25, "price_currency": "MYR", "provider": "Camofox + Google",
                    "booking_url": None, "reasoning": "Per Wikipedia: 1,000-year-old Byzantine masterpiece. Go at 8:30 AM to avoid crowds (per Reddit)",
                    "halal_confidence": None, "verified": False, "last_checked": None,
                    "raw": {"source": "research", "kind": "landmark"},
                },
                {
                    "id": "RSH-A002", "kind": "activity", "title": "Murano Glass Factory Tour",
                    "price_amount": 40, "price_currency": "MYR", "provider": "Camofox + YouTube",
                    "booking_url": None, "reasoning": "Per YouTube: authentic glass-blowing demo included. Avoid tourist trap shops (per Reddit)",
                    "halal_confidence": None, "verified": False, "last_checked": None,
                    "raw": {"source": "research", "kind": "experience"},
                },
                {
                    "id": "RSH-A003", "kind": "activity", "title": "Burano Island — colorful houses",
                    "price_amount": 0, "price_currency": "MYR", "provider": "Camofox + Wikipedia",
                    "booking_url": None, "reasoning": "Per Wikipedia: UNESCO-adjacent, iconic pastel houses. Best photographed at golden hour",
                    "halal_confidence": None, "verified": False, "last_checked": None,
                    "raw": {"source": "research", "kind": "landmark"},
                },
                {
                    "id": "RSH-A004", "kind": "activity", "title": "Rialto Market — morning food tour",
                    "price_amount": 80, "price_currency": "MYR", "provider": "Camofox + Google",
                    "booking_url": None, "reasoning": "Per Google: best local food experience. Go before 10 AM for freshest produce and seafood",
                    "halal_confidence": None, "verified": False, "last_checked": None,
                    "raw": {"source": "research", "kind": "food_tour"},
                },
                {
                    "id": "RSH-D001", "kind": "restaurant", "title": "Al Covo — Venetian seafood",
                    "price_amount": 120, "price_currency": "MYR", "provider": "Camofox + Google",
                    "booking_url": None, "reasoning": "Per Google: 4.6★, traditional Venetian cuisine. Reservation essential",
                    "halal_confidence": "unverified", "verified": False, "last_checked": None,
                    "raw": {"source": "research", "cuisine": "Italian seafood"},
                },
                {
                    "id": "RSH-D002", "kind": "restaurant", "title": "Orient Experience — halal Middle Eastern",
                    "price_amount": 45, "price_currency": "MYR", "provider": "Camofox + HalalTrip",
                    "booking_url": None, "reasoning": "Per HalalTrip: certified halal, Afghan/Venetian fusion. Popular with Muslim travelers",
                    "halal_confidence": "certified", "verified": False, "last_checked": None,
                    "raw": {"source": "research", "cuisine": "Middle Eastern / Afghan"},
                },
                {
                    "id": "RSH-D003", "kind": "restaurant", "title": "Gelateria Nico — Zattere",
                    "price_amount": 15, "price_currency": "MYR", "provider": "Camofox + Reddit",
                    "booking_url": None, "reasoning": "Per Reddit: best gelato in Venice, not touristy. Gianduiotto is the must-try",
                    "halal_confidence": "muslim_friendly", "verified": False, "last_checked": None,
                    "raw": {"source": "research", "cuisine": "Gelato / Dessert"},
                },
            ],
            "items": [],
            "applied_preferences": {"halal_required": "hard_filter", "interests": "food, culture"},
            "warnings": ["Halal results carry a confidence label — never an unverified claim"],
            "data": {
                "attractions": [
                    {"title": "St Mark's Basilica", "kind": "landmark", "reasoning": "1,000-year-old Byzantine masterpiece", "estimated_cost": 25},
                    {"title": "Murano Glass Factory", "kind": "experience", "reasoning": "Authentic glass-blowing demo", "estimated_cost": 40},
                    {"title": "Burano Island", "kind": "landmark", "reasoning": "Iconic pastel houses", "estimated_cost": 0},
                    {"title": "Rialto Market", "kind": "food_tour", "reasoning": "Best local food experience", "estimated_cost": 80},
                    {"title": "Doge's Palace", "kind": "museum", "reasoning": "Gothic masterpiece with Bridge of Sighs", "estimated_cost": 55},
                    {"title": "Peggy Guggenheim Collection", "kind": "museum", "reasoning": "Modern art on Grand Canal", "estimated_cost": 60},
                    {"title": "Libreria Acqua Alta", "kind": "landmark", "reasoning": "World's most beautiful bookshop", "estimated_cost": 0},
                    {"title": "Cicchetti Crawl — San Polo", "kind": "food_tour", "reasoning": "Venetian tapas tradition", "estimated_cost": 50},
                ],
                "dining": [
                    {"title": "Al Covo", "cuisine": "Italian seafood", "halal_confidence": "unverified", "reasoning": "Traditional Venetian, 4.6★", "estimated_cost": 120},
                    {"title": "Orient Experience", "cuisine": "Middle Eastern", "halal_confidence": "certified", "reasoning": "Certified halal per HalalTrip", "estimated_cost": 45},
                    {"title": "Gelateria Nico", "cuisine": "Gelato", "halal_confidence": "muslim_friendly", "reasoning": "Best gelato per Reddit", "estimated_cost": 15},
                    {"title": "Osteria Al Squero", "cuisine": "Cicchetti", "halal_confidence": "unverified", "reasoning": "Hidden gem near gondola workshop", "estimated_cost": 30},
                    {"title": "Paradiso Perduto", "cuisine": "Italian", "halal_confidence": "unverified", "reasoning": "Lively Cannaregio spot", "estimated_cost": 60},
                    {"title": "La Zucca", "cuisine": "Vegetarian", "halal_confidence": "muslim_friendly", "reasoning": "Pumpkin specialties, veg-friendly", "estimated_cost": 50},
                ],
                "safety_tips": ["Watch for pickpockets on vaporetto Line 1", "Acqua alta season: Oct–Jan, pack waterproof shoes"],
                "customs": ["Cover shoulders/knees for churches", "No sitting on bridges or steps — fined €100+"],
                "best_times": ["Apr–May, Sep–Oct for fewer crowds", "Early morning for St Mark's"],
                "sentiment_summary": "Positive: food culture, walkability. Concerns: overtourism, acqua alta season.",
                "sources_crawled": ["google", "wikipedia", "youtube", "reddit"],
            },
        },
        "weather_risk": {
            "agent": "weather_risk",
            "summary": "Venice: avg 12–21°C, 2/7 rainy days, risk=low | GDELT: no active threats",
            "options": [],
            "items": [],
            "applied_preferences": {},
            "warnings": [],
            "data": {
                "destination": "Venice, Italy",
                "coordinates": {"lat": 45.44, "lng": 12.32},
                "risk_level": "low",
                "weather_risk": "low",
                "event_risk": "low",
                "rain_days": 2,
                "forecast": [
                    {"date": "2026-11-06", "high_c": 18, "low_c": 12, "precipitation_pct": 20, "weather_code": 2, "description": "Partly cloudy"},
                    {"date": "2026-11-07", "high_c": 19, "low_c": 13, "precipitation_pct": 15, "weather_code": 1, "description": "Mainly clear"},
                    {"date": "2026-11-08", "high_c": 20, "low_c": 14, "precipitation_pct": 10, "weather_code": 0, "description": "Clear sky"},
                    {"date": "2026-11-09", "high_c": 21, "low_c": 13, "precipitation_pct": 30, "weather_code": 2, "description": "Partly cloudy"},
                    {"date": "2026-11-10", "high_c": 19, "low_c": 12, "precipitation_pct": 65, "weather_code": 61, "description": "Slight rain"},
                    {"date": "2026-11-11", "high_c": 17, "low_c": 11, "precipitation_pct": 70, "weather_code": 63, "description": "Moderate rain"},
                    {"date": "2026-11-12", "high_c": 18, "low_c": 12, "precipitation_pct": 25, "weather_code": 2, "description": "Partly cloudy"},
                ],
                "gdelt": {
                    "active_threats": [],
                    "avg_tone": -1.2,
                    "num_articles": 42,
                    "recent_events": [
                        {"title": "Venice introduces tourist entry fee for 2027", "source": "Reuters", "url": "#", "tone": -0.5},
                        {"title": "New vaporetto routes announced for winter season", "source": "ANSA", "url": "#", "tone": 1.2},
                    ],
                },
            },
        },
        "budget": {
            "agent": "budget",
            "summary": "Estimated RM6,840 / RM8,000 budget — RM1,160 remaining",
            "options": [],
            "items": [],
            "applied_preferences": {},
            "warnings": [],
            "data": {
                "currency": "MYR",
                "budget_amount": 8000,
                "spent_estimate": 6840,
                "remaining": 1160,
                "over_budget": False,
                "breakdown": {
                    "flights": 4900,
                    "hotels_total": 1920,
                    "activities": 320,
                    "food_estimate": 600,
                    "transport_local": 100,
                    "nights": 6,
                },
                "fx_rates": {"EUR": 4.72, "USD": 4.38},
            },
        },
        "itinerary": {
            "agent": "itinerary",
            "summary": "7-day Venice itinerary assembled — food & culture focus",
            "options": [],
            "items": [
                {"day_index": 1, "kind": "flight", "title": "Arrive KUL→VCE (Qatar Airways via DOH)", "starts_at": "06:30", "ends_at": "22:00", "reasoning": "Evening arrival — check in and rest", "cost_amount": 4900, "cost_currency": "MYR", "details": {"airline": "Qatar Airways"}},
                {"day_index": 1, "kind": "hotel", "title": "Check in — Hotel Belle Arti", "starts_at": "23:00", "ends_at": None, "reasoning": "Walking distance from Vaporetto stop, 2 min to St Mark's", "cost_amount": 320, "cost_currency": "MYR", "details": {}},
                {"day_index": 2, "kind": "activity", "title": "St Mark's Basilica — early entry", "starts_at": "08:30", "ends_at": "10:00", "reasoning": "Beat the crowds — go right at opening", "cost_amount": 25, "cost_currency": "MYR", "details": {}},
                {"day_index": 2, "kind": "activity", "title": "Doge's Palace + Bridge of Sighs", "starts_at": "10:30", "ends_at": "12:30", "reasoning": "Adjacent to Basilica, covers Venetian history", "cost_amount": 55, "cost_currency": "MYR", "details": {}},
                {"day_index": 2, "kind": "meal", "title": "Lunch — Orient Experience (halal)", "starts_at": "13:00", "ends_at": "14:00", "reasoning": "Certified halal, Afghan-Venetian fusion, 5 min walk", "cost_amount": 45, "cost_currency": "MYR", "details": {"halal": "certified"}},
                {"day_index": 2, "kind": "activity", "title": "Libreria Acqua Alta", "starts_at": "14:30", "ends_at": "15:30", "reasoning": "Instagram-famous bookshop, unique Venice experience", "cost_amount": 0, "cost_currency": "MYR", "details": {}},
                {"day_index": 2, "kind": "meal", "title": "Dinner — Gelateria Nico + evening stroll", "starts_at": "18:00", "ends_at": "20:00", "reasoning": "Best gelato on Zattere promenade, sunset views", "cost_amount": 15, "cost_currency": "MYR", "details": {}},
                {"day_index": 3, "kind": "activity", "title": "Rialto Market — morning food tour", "starts_at": "08:00", "ends_at": "10:00", "reasoning": "Freshest produce before 10 AM, local Venetian experience", "cost_amount": 80, "cost_currency": "MYR", "details": {}},
                {"day_index": 3, "kind": "activity", "title": "Cicchetti Crawl — San Polo", "starts_at": "12:00", "ends_at": "14:00", "reasoning": "Venetian tapas bar hopping, cultural food experience", "cost_amount": 50, "cost_currency": "MYR", "details": {}},
                {"day_index": 3, "kind": "activity", "title": "Peggy Guggenheim Collection", "starts_at": "15:00", "ends_at": "17:00", "reasoning": "Modern art, less crowded afternoons", "cost_amount": 60, "cost_currency": "MYR", "details": {}},
                {"day_index": 4, "kind": "activity", "title": "Murano Island — Glass Factory", "starts_at": "09:00", "ends_at": "12:00", "reasoning": "Authentic glass-blowing, avoid tourist trap shops", "cost_amount": 40, "cost_currency": "MYR", "details": {}},
                {"day_index": 4, "kind": "activity", "title": "Burano Island — colorful houses", "starts_at": "13:00", "ends_at": "17:00", "reasoning": "Golden hour photography, UNESCO-adjacent", "cost_amount": 0, "cost_currency": "MYR", "details": {}},
                {"day_index": 5, "kind": "activity", "title": "Free day — explore Dorsoduro", "starts_at": "10:00", "ends_at": "18:00", "reasoning": "Relaxed pace day, local cafés and art galleries", "cost_amount": 0, "cost_currency": "MYR", "details": {}},
                {"day_index": 6, "kind": "activity", "title": "Grand Canal gondola ride", "starts_at": "09:00", "ends_at": "10:00", "reasoning": "Early morning = fewer tourists, better photos", "cost_amount": 80, "cost_currency": "MYR", "details": {}},
                {"day_index": 6, "kind": "meal", "title": "Farewell dinner — La Zucca", "starts_at": "19:00", "ends_at": "21:00", "reasoning": "Pumpkin specialties, veg-friendly, local favorite", "cost_amount": 50, "cost_currency": "MYR", "details": {}},
                {"day_index": 7, "kind": "flight", "title": "Depart VCE→KUL", "starts_at": "10:00", "ends_at": "06:00+1", "reasoning": "Morning departure, arrive next day", "cost_amount": 0, "cost_currency": "MYR", "details": {}},
            ],
            "applied_preferences": {"interests": "food, culture", "pace": "relaxed"},
            "warnings": [],
            "data": {},
        },
        "memory": {
            "agent": "memory",
            "summary": "Trip saved to brain — 12 experiences recorded for future learning",
            "options": [],
            "items": [],
            "applied_preferences": {},
            "warnings": [],
            "data": {"experiences_recorded": 12, "brain_status": "active"},
        },
    }
