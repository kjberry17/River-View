import requests
from datetime import datetime
from cache_utils import ttl_cache

FISHING_ZONES = {
    "Central Oregon (Bend)": {"lat": 44.058, "lon": -121.312, "rivers": ["Deschutes River", "Crooked River", "Metolius River", "Fall River"]},
    "Willamette Valley (Eugene)": {"lat": 44.052, "lon": -123.087, "rivers": ["McKenzie River", "Willamette River", "Long Tom River"]},
    "Southern Oregon (Medford)": {"lat": 42.326, "lon": -122.875, "rivers": ["Rogue River", "Applegate River", "Illinois River"]},
    "Oregon Coast (Lincoln City)": {"lat": 44.958, "lon": -124.006, "rivers": ["Siletz River", "Nestucca River", "Alsea River", "Wilson River"]},
    "Eastern Oregon (La Grande)": {"lat": 45.324, "lon": -118.088, "rivers": ["Grande Ronde River", "Umatilla River"]},
    "Portland Metro / Mt. Hood": {"lat": 45.523, "lon": -122.676, "rivers": ["Sandy River", "Clackamas River", "Hood River"]},
    "North Santiam (Salem Area)": {"lat": 44.943, "lon": -123.035, "rivers": ["North Santiam River", "South Santiam River", "Molalla River"]},
    "Klamath Basin": {"lat": 42.224, "lon": -121.781, "rivers": ["Williamson River", "Klamath River"]},
}

NWS_POINTS_URL = "https://api.weather.gov/points/{lat},{lon}"
NWS_FORECAST_URL = "https://api.weather.gov/gridpoints/{office}/{x},{y}/forecast/hourly"


@ttl_cache(ttl=1800)
def fetch_nws_weather():
    results = {}
    headers = {
        "User-Agent": "OregonFishingDashboard/4.0 (contact@example.com)",
        "Accept": "application/geo+json",
    }

    for zone, info in FISHING_ZONES.items():
        try:
            points_resp = requests.get(
                NWS_POINTS_URL.format(lat=info["lat"], lon=info["lon"]),
                headers=headers, timeout=8,
            )
            if points_resp.status_code != 200:
                results[zone] = {"error": f"NWS {points_resp.status_code}"}
                continue

            props = points_resp.json().get("properties", {})
            office, gx, gy = props.get("gridId"), props.get("gridX"), props.get("gridY")
            if not all([office, gx, gy]):
                results[zone] = {"error": "NWS grid not found"}
                continue

            forecast_resp = requests.get(
                NWS_FORECAST_URL.format(office=office, x=gx, y=gy),
                headers=headers, timeout=8,
            )
            if forecast_resp.status_code != 200:
                results[zone] = {"error": f"NWS forecast {forecast_resp.status_code}"}
                continue

            periods = forecast_resp.json().get("properties", {}).get("periods", [])
            if not periods:
                results[zone] = {"error": "No periods"}
                continue

            current = periods[0]
            temp_f = current.get("temperature", 0)
            wind_speed = current.get("windSpeed", "Unknown")
            wind_dir = current.get("windDirection", "")
            short_forecast = current.get("shortForecast", "Unknown")
            precip_chance = current.get("probabilityOfPrecipitation", {}).get("value") or 0
            humidity = current.get("relativeHumidity", {}).get("value")
            next_6h = periods[:6]
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
                "updated": datetime.utcnow().strftime("%H:%M UTC"),
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
    fl = forecast.lower()
    if any(w in fl for w in ["thunderstorm", "lightning"]):
        score -= 40
    elif "heavy rain" in fl:
        score -= 20
    elif "showers" in fl:
        score -= 10
    elif any(w in fl for w in ["clear", "sunny", "mostly sunny", "partly cloudy"]):
        score += 5
    return max(0, min(100, score))


def _fishing_label(score: int) -> dict:
    if score >= 80:
        return {"label": "Excellent", "color": "#00ff87"}
    elif score >= 60:
        return {"label": "Good", "color": "#ffd60a"}
    elif score >= 40:
        return {"label": "Fair", "color": "#ff9f43"}
    else:
        return {"label": "Poor", "color": "#ff4757"}
