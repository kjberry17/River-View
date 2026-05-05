import requests
import streamlit as st
from datetime import datetime

FISHING_ZONES = {
    "Central Oregon (Bend)": {"lat": 44.058, "lon": -121.312, "rivers": ["Deschutes River", "Crooked River", "Metolius River", "Fall River"]},
    "Willamette Valley (Eugene)": {"lat": 44.052, "lon": -123.087, "rivers": ["McKenzie River", "Willamette River", "Long Tom River"]},
    "Southern Oregon (Medford)": {"lat": 42.326, "lon": -122.875, "rivers": ["Rogue River", "Applegate River", "Illinois River"]},
    "Oregon Coast (Lincoln City)": {"lat": 44.958, "lon": -124.006, "rivers": ["Siletz River", "Nestucca River", "Alsea River", "Wilson River"]},
    "Eastern Oregon (La Grande)": {"lat": 45.324, "lon": -118.088, "rivers": ["Grande Ronde River", "Umatilla River", "Powder River"]},
    "Portland Metro / Mt. Hood": {"lat": 45.523, "lon": -122.676, "rivers": ["Sandy River", "Clackamas River", "Hood River"]},
    "North Santiam (Salem Area)": {"lat": 44.943, "lon": -123.035, "rivers": ["North Santiam River", "South Santiam River", "Molalla River"]},
    "Klamath Basin": {"lat": 42.224, "lon": -121.781, "rivers": ["Williamson River", "Klamath River", "Sprague River"]},
}

NWS_POINTS_URL = "https://api.weather.gov/points/{lat},{lon}"
NWS_FORECAST_URL = "https://api.weather.gov/gridpoints/{office}/{x},{y}/forecast/hourly"


@st.cache_data(ttl=1800)
def fetch_nws_weather():
    results = {}
    headers = {"User-Agent": "OregonFishingDashboard/2.1 (two-dog-seeds@example.com)", "Accept": "application/geo+json"}

    for zone, info in FISHING_ZONES.items():
        try:
            points_resp = requests.get(
                NWS_POINTS_URL.format(lat=info["lat"], lon=info["lon"]),
                headers=headers, timeout=8
            )
            if points_resp.status_code != 200:
                results[zone] = {"error": f"NWS points {points_resp.status_code}"}
                continue

            props = points_resp.json().get("properties", {})
            office = props.get("gridId")
            gx = props.get("gridX")
            gy = props.get("gridY")
            if not all([office, gx, gy]):
                results[zone] = {"error": "NWS grid not found"}
                continue

            forecast_resp = requests.get(
                NWS_FORECAST_URL.format(office=office, x=gx, y=gy),
                headers=headers, timeout=8
            )
            if forecast_resp.status_code != 200:
                results[zone] = {"error": f"NWS forecast {forecast_resp.status_code}"}
                continue

            periods = forecast_resp.json().get("properties", {}).get("periods", [])
            if not periods:
                results[zone] = {"error": "No forecast periods"}
                continue

            current = periods[0]
            temp_f = current.get("temperature", 0)
            wind_speed = current.get("windSpeed", "Unknown")
            wind_dir = current.get("windDirection", "")
            short_forecast = current.get("shortForecast", "Unknown")
            precip_chance = current.get("probabilityOfPrecipitation", {}).get("value") or 0
            dew_point = current.get("dewpoint", {}).get("value")
            humidity = current.get("relativeHumidity", {}).get("value")

            next_6h = [p for p in periods[:6]]
            max_precip_6h = max((p.get("probabilityOfPrecipitation", {}).get("value") or 0) for p in next_6h)

            fishing_score = _compute_fishing_score(temp_f, precip_chance, max_precip_6h, short_forecast)

            results[zone] = {
                "temp_f": temp_f,
                "wind_speed": wind_speed,
                "wind_dir": wind_dir,
                "short_forecast": short_forecast,
                "precip_chance": precip_chance,
                "max_precip_6h": max_precip_6h,
                "humidity": humidity,
                "fishing_score": fishing_score,
                "fishing_label": _fishing_label(fishing_score),
                "rivers": info["rivers"],
                "updated": datetime.utcnow().strftime("%I:%M %p UTC"),
            }

        except Exception as e:
            results[zone] = {"error": str(e)[:80]}

    return results


def _compute_fishing_score(temp_f: float, precip: float, precip_6h: float, forecast: str) -> int:
    score = 100
    if temp_f < 35:
        score -= 30
    elif temp_f < 45:
        score -= 15
    elif temp_f > 95:
        score -= 25
    elif temp_f > 85:
        score -= 10

    if precip > 70:
        score -= 30
    elif precip > 40:
        score -= 15
    elif precip > 20:
        score -= 5

    if precip_6h > 60:
        score -= 20

    forecast_lower = forecast.lower()
    if any(w in forecast_lower for w in ["thunderstorm", "lightning"]):
        score -= 40
    elif "heavy rain" in forecast_lower:
        score -= 20
    elif "showers" in forecast_lower:
        score -= 10
    elif any(w in forecast_lower for w in ["clear", "sunny", "mostly sunny", "partly cloudy"]):
        score += 5

    return max(0, min(100, score))


def _fishing_label(score: int) -> dict:
    if score >= 80:
        return {"label": "Excellent", "emoji": "🟢", "color": "green"}
    elif score >= 60:
        return {"label": "Good", "emoji": "🟡", "color": "yellow"}
    elif score >= 40:
        return {"label": "Fair", "emoji": "🟠", "color": "orange"}
    else:
        return {"label": "Poor", "emoji": "🔴", "color": "red"}


def get_barometric_trend_note(precip_chance: float, max_precip_6h: float) -> str:
    if max_precip_6h > 60:
        return "⬇️ Pressure dropping — fish feeding may slow before the rain arrives. Go early."
    elif precip_chance < 10 and max_precip_6h < 20:
        return "⬆️ High pressure / stable — fish midday if it's overcast, early/late if sunny."
    elif precip_chance < 30:
        return "➡️ Stable pressure — consistent feeding windows. Standard hatch timing applies."
    else:
        return "⬇️ Incoming precip — rising water possible in smaller streams within 6–12 hours."
