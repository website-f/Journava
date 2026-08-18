"""Weather / Risk Agent — Open-Meteo + GDELT; triggers replanning (spec §4.5).

Phase 2: wires the existing Open-Meteo tool (geocode + forecast) to produce a
real weather summary with a risk level. GDELT events remain Phase 3.

When rain days exceed the threshold (4+), publishes a "monitoring" SSE event
so the UI can warn the traveler proactively.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from app.agents.base import BaseAgent
from app.agents.schemas import AgentResult, TravelerProfile, TripRequest
from app.tools.open_meteo import forecast, geocode

logger = logging.getLogger(__name__)

RAIN_THRESHOLD = 4  # days with >60% precipitation probability


class WeatherRiskAgent(BaseAgent):
    slug = "weather_risk"
    name = "Weather / Risk"
    role = "Open-Meteo · GDELT"

    async def run(
        self,
        request: TripRequest,
        profile: TravelerProfile,
        *,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        destination = request.destination or "unknown"
        self.emit("working", f"Fetching weather forecast for {destination}")

        # Calculate trip length for forecast days
        days = 7
        if request.start_date and request.end_date:
            days = max(1, min(16, (request.end_date - request.start_date).days + 1))

        # 1. Geocode the destination
        geo = await geocode(destination)
        if geo is None:
            self.emit("monitoring", f"Could not resolve coordinates for {destination}")
            return AgentResult(
                agent=self.slug,
                summary=f"Weather unavailable — could not geocode {destination}",
                warnings=[f"Geocode failed for '{destination}'"],
                data={"destination": destination, "risk_level": "unknown", "forecast": None},
            )

        lat = geo.get("latitude", 0.0)
        lng = geo.get("longitude", 0.0)

        # 2. Get the forecast
        forecast_data = await forecast(lat, lng, days=days)
        if forecast_data is None:
            self.emit("monitoring", "Open-Meteo forecast unavailable")
            return AgentResult(
                agent=self.slug,
                summary="Weather forecast service temporarily unavailable",
                warnings=["Open-Meteo forecast failed"],
                data={"destination": destination, "risk_level": "unknown", "forecast": None, "coordinates": {"lat": lat, "lng": lng}},
            )

        # 3. Summarize the forecast
        summary, risk_level, daily_breakdown, rain_days = self._summarize(forecast_data, destination)

        # 4. If high risk, publish monitoring event
        if risk_level == "high":
            self.emit("monitoring", f"Weather alert: {rain_days} rain days expected in {destination}")
        else:
            self.emit("active", f"Weather OK — {risk_level} risk for {destination}")

        return AgentResult(
            agent=self.slug,
            summary=summary,
            data={
                "destination": destination,
                "coordinates": {"lat": lat, "lng": lng},
                "risk_level": risk_level,
                "rain_days": rain_days,
                "forecast": daily_breakdown,
            },
        )

    @staticmethod
    def _summarize(
        forecast_data: dict[str, Any],
        destination: str,
    ) -> tuple[str, str, list[dict[str, Any]], int]:
        """Parse Open-Meteo response into a human-readable summary."""
        daily = forecast_data.get("daily", {})
        dates = daily.get("time", [])
        max_temps = daily.get("temperature_2m_max", [])
        min_temps = daily.get("temperature_2m_min", [])
        precip_probs = daily.get("precipitation_probability_max", [])
        weather_codes = daily.get("weather_code", [])

        if not dates:
            return "No forecast data available", "unknown", [], 0

        # Build daily breakdown
        daily_breakdown: list[dict[str, Any]] = []
        rain_days = 0
        all_highs: list[float] = []
        all_lows: list[float] = []

        for i, dt in enumerate(dates):
            high = max_temps[i] if i < len(max_temps) else None
            low = min_temps[i] if i < len(min_temps) else None
            precip = precip_probs[i] if i < len(precip_probs) else 0
            code = weather_codes[i] if i < len(weather_codes) else 0

            if high is not None:
                all_highs.append(high)
            if low is not None:
                all_lows.append(low)
            if precip >= 60:
                rain_days += 1

            daily_breakdown.append({
                "date": dt,
                "high_c": high,
                "low_c": low,
                "precipitation_pct": precip,
                "weather_code": code,
                "description": _wmo_code_to_text(code),
            })

        # Determine risk level
        avg_high = round(sum(all_highs) / len(all_highs), 1) if all_highs else 0
        avg_low = round(sum(all_lows) / len(all_lows), 1) if all_lows else 0
        extreme_heat = any(t > 38 for t in all_highs)
        extreme_cold = any(t < 5 for t in all_lows)

        if rain_days >= 6 or extreme_heat or extreme_cold:
            risk_level = "high"
        elif rain_days >= RAIN_THRESHOLD:
            risk_level = "medium"
        else:
            risk_level = "low"

        # Human-readable summary
        summary = (
            f"{destination}: avg {avg_low}–{avg_high}°C, "
            f"{rain_days}/{len(dates)} rainy days, risk={risk_level}"
        )

        return summary, risk_level, daily_breakdown, rain_days


def _wmo_code_to_text(code: int) -> str:
    """Convert WMO weather code to a short human description."""
    mapping = {
        0: "Clear sky",
        1: "Mainly clear",
        2: "Partly cloudy",
        3: "Overcast",
        45: "Foggy",
        48: "Depositing rime fog",
        51: "Light drizzle",
        53: "Moderate drizzle",
        55: "Dense drizzle",
        61: "Slight rain",
        63: "Moderate rain",
        65: "Heavy rain",
        66: "Light freezing rain",
        67: "Heavy freezing rain",
        71: "Slight snow",
        73: "Moderate snow",
        75: "Heavy snow",
        77: "Snow grains",
        80: "Slight rain showers",
        81: "Moderate rain showers",
        82: "Violent rain showers",
        85: "Slight snow showers",
        86: "Heavy snow showers",
        95: "Thunderstorm",
        96: "Thunderstorm with slight hail",
        99: "Thunderstorm with heavy hail",
    }
    return mapping.get(code, f"Weather code {code}")
