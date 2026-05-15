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


MARINE_ZONES = {
    "Columbia River Bar": {"lat": 46.25, "lon": -124.07, "rivers": ["Columbia River"], "desc": "Critical bar crossing zone. Most dangerous harbor entrance on West Coast."},
    "North Oregon Coast": {"lat": 45.80, "lon": -123.96, "rivers": ["Nehalem River"], "desc": "Seaside to Tillamook Head. Nearshore and shelf waters."},
    "Central Oregon Coast": {"lat": 44.65, "lon": -124.08, "rivers": ["Siletz River", "Nestucca River", "Wilson River", "Alsea River"], "desc": "Newport to Florence. Salmon and bottomfish zones."},
    "South Oregon Coast": {"lat": 43.34, "lon": -124.33, "rivers": ["Coquille River", "Umpqua River"], "desc": "Coos Bay to Port Orford."},
    "Southernmost Oregon Coast": {"lat": 42.30, "lon": -124.42, "rivers": ["Chetco River", "Rogue River (mouth)"], "desc": "Brookings area. Rogue River reef and Chetco approaches."},
}


@ttl_cache(ttl=1800)
def fetch_nws_marine():
    results = {}
    headers = {
        "User-Agent": "OregonFishingDashboard/4.0 (contact@example.com)",
        "Accept": "application/geo+json",
    }

    for zone, info in MARINE_ZONES.items():
        try:
            points_resp = requests.get(
                NWS_POINTS_URL.format(lat=info["lat"], lon=info["lon"]),
                headers=headers, timeout=8,
            )
            if points_resp.status_code != 200:
                results[zone] = {"error": f"NWS {points_resp.status_code}"}
                continue

            props = points_resp.json().get("properties", {})
            forecast_url = props.get("forecast")
            if not forecast_url:
                results[zone] = {"error": "No forecast URL"}
                continue

            fc_resp = requests.get(forecast_url, headers=headers, timeout=8)
            if fc_resp.status_code != 200:
                results[zone] = {"error": f"NWS forecast {fc_resp.status_code}"}
                continue

            periods = fc_resp.json().get("properties", {}).get("periods", [])
            if not periods:
                results[zone] = {"error": "No periods"}
                continue

            current = periods[0]
            temp_f = current.get("temperature", 0)
            wind_speed = current.get("windSpeed", "Unknown")
            wind_dir = current.get("windDirection", "")
            short_forecast = current.get("shortForecast", "Unknown")
            detailed = current.get("detailedForecast", "")
            is_day = current.get("isDaytime", True)

            bar_safety = _bar_safety_score(wind_speed, short_forecast, temp_f)
            boat_rating = _boat_rating_label(wind_speed, short_forecast)

            results[zone] = {
                "temp_f": temp_f,
                "wind_speed": wind_speed,
                "wind_dir": wind_dir,
                "short_forecast": short_forecast,
                "detailed_forecast": detailed,
                "is_daytime": is_day,
                "bar_safety": bar_safety,
                "boat_rating": boat_rating,
                "rivers": info["rivers"],
                "desc": info["desc"],
                "updated": datetime.utcnow().strftime("%H:%M UTC"),
            }

        except Exception as e:
            results[zone] = {"error": str(e)[:80]}

    return results


def _bar_safety_score(wind_speed, forecast, temp_f) -> dict:
    score = 100
    fl = forecast.lower()

    try:
        spd = int("".join(filter(str.isdigit, wind_speed.split(" ")[0])))
    except (ValueError, TypeError):
        spd = 0

    if any(w in fl for w in ["gale", "storm", "hurricane"]):
        return {"label": "DANGEROUS — Do Not Cross", "color": "#922b21", "score": 0, "notes": "Gale/storm conditions. Bar closed or impassable."}
    if any(w in fl for w in ["small craft", "hazardous"]):
        return {"label": "Hazardous — Avoid Bar", "color": "#ff4757", "score": 10, "notes": "Small craft advisory. Only experienced captains with local knowledge."}
    if spd > 25:
        return {"label": "Very Rough — Not Recommended", "color": "#e74c3c", "score": 20, "notes": "Whitecaps, breaking waves. Bar crossing dangerous."}
    if spd > 15:
        return {"label": "Rough — Caution", "color": "#ff9f43", "score": 40, "notes": "Moderate chop. Check tide — ebb tide + wind = dangerous bar."}
    if spd > 10:
        return {"label": "Choppy — Fair", "color": "#ffd60a", "score": 60, "notes": "Some chop. Bar passable with caution."}
    if any(w in fl for w in ["fog", "drizzle", "rain"]):
        return {"label": "Reduced Visibility — Caution", "color": "#ffd60a", "score": 55, "notes": "Low visibility. Monitor bar cameras and radio."}
    if any(w in fl for w in ["sunny", "clear", "mostly sunny", "partly cloudy"]):
        return {"label": "Good Bar Conditions", "color": "#00ff87", "score": 85, "notes": "Favorable for bar crossings. Still check tide phase."}
    return {"label": "Check Conditions", "color": "#ffd60a", "score": 50, "notes": "Review full marine forecast before crossing."}


def _boat_rating_label(wind_speed, forecast) -> dict:
    fl = forecast.lower()
    try:
        spd = int("".join(filter(str.isdigit, wind_speed.split(" ")[0])))
    except (ValueError, TypeError):
        spd = 999

    if spd > 30 or any(w in fl for w in ["gale", "storm"]):
        return {"label": "Do Not Launch", "color": "#922b21"}
    elif spd > 20:
        return {"label": "Dangerous — Experts Only", "color": "#ff4757"}
    elif spd > 12:
        return {"label": "Rough — Small Boats Caution", "color": "#ff9f43"}
    elif spd > 8:
        return {"label": "Breezy — Fair Boating", "color": "#ffd60a"}
    else:
        return {"label": "Calm — Good Boating", "color": "#00ff87"}
