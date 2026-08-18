"""Weather / Risk Agent — Open-Meteo + GDELT; triggers replanning (spec §4.5).

Phase 2: wires Open-Meteo (geocode + forecast) AND GDELT (global events/news)
to produce a real weather + risk summary with threat detection.

When rain days exceed the threshold (4+) or GDELT detects active threats,
publishes a "monitoring" SSE event so the UI can warn the traveler proactively.
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.base import BaseAgent
from app.agents.schemas import AgentResult, TravelerProfile, TripRequest
from app.tools import gdelt
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

        # 2. Get the weather forecast
        forecast_data = await forecast(lat, lng, days=days)
        if forecast_data is None:
            self.emit("monitoring", "Open-Meteo forecast unavailable")
            weather_summary = "Weather forecast service temporarily unavailable"
            risk_level = "unknown"
            daily_breakdown: list[dict[str, Any]] = []
            rain_days = 0
        else:
            weather_summary, risk_level, daily_breakdown, rain_days = self._summarize(
                forecast_data, destination
            )

        # 3. GDELT global events & threat detection
        self.emit("working", f"GDELT: scanning global events for {destination}")
        events_data = await gdelt.events(destination, days=14, max_records=15)
        threats = await gdelt.threat_keywords(destination, days=14)
        tone = await gdelt.tone_analysis(destination, days=14)

        # Build event risk summary
        event_risk = "low"
        active_threats: list[str] = []
        if threats:
            active_threats = threats
            if len(threats) >= 3:
                event_risk = "high"
            elif len(threats) >= 1:
                event_risk = "medium"

        avg_tone = tone.get("avg_tone", 0)
        if avg_tone < -5:
            event_risk = "high"
        elif avg_tone < -2 and event_risk == "low":
            event_risk = "medium"

        recent_events = [
            {
                "title": a.get("title", ""),
                "source": a.get("source", ""),
                "url": a.get("url", ""),
                "tone": a.get("tone", 0),
            }
            for a in events_data[:10]
        ]

        # 4. Combine weather risk + event risk
        risk_priority = {"low": 0, "medium": 1, "high": 2, "unknown": -1}
        combined_risk = max(risk_level, event_risk, key=lambda r: risk_priority.get(r, -1))

        # 5. Publish SSE event
        if combined_risk == "high":
            alerts = []
            if rain_days >= RAIN_THRESHOLD:
                alerts.append(f"{rain_days} rain days expected")
            if active_threats:
                alerts.append(f"threats detected: {', '.join(active_threats[:3])}")
            self.emit("monitoring", f"Risk alert for {destination}: {'; '.join(alerts)}")
        else:
            self.emit("active", f"Weather & risk OK — {combined_risk} risk for {destination}")

        # 6. Build final summary
        summary_parts = [weather_summary]
        if active_threats:
            summary_parts.append(f"GDELT threats: {', '.join(active_threats[:3])}")
        if recent_events:
            summary_parts.append(f"{len(events_data)} recent events scanned")
        summary = " | ".join(summary_parts)

        return AgentResult(
            agent=self.slug,
            summary=summary,
            data={
                "destination": destination,
                "coordinates": {"lat": lat, "lng": lng},
                "risk_level": combined_risk,
                "weather_risk": risk_level,
                "event_risk": event_risk,
                "rain_days": rain_days,
                "forecast": daily_breakdown,
                "gdelt": {
                    "active_threats": active_threats,
                    "avg_tone": avg_tone,
                    "num_articles": tone.get("num_articles", 0),
                    "recent_events": recent_events,
                },
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

            daily_breakdown.append(
                {
                    "date": dt,
                    "high_c": high,
                    "low_c": low,
                    "precipitation_pct": precip,
                    "weather_code": code,
                    "description": _wmo_code_to_text(code),
                }
            )

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
