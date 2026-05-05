import math
import requests
import logging

log = logging.getLogger(__name__)

RIVER_COORDS = {
    "Deschutes River":       (44.75, -121.00),
    "McKenzie River":        (44.07, -122.45),
    "Metolius River":        (44.52, -121.64),
    "Crooked River":         (44.28, -120.58),
    "North Santiam River":   (44.78, -122.58),
    "South Santiam River":   (44.40, -122.68),
    "Sandy River":           (45.53, -122.25),
    "North Umpqua River":    (43.27, -122.95),
    "South Umpqua River":    (43.30, -123.25),
    "Rogue River":           (42.43, -123.33),
    "Illinois River":        (42.12, -123.71),
    "Applegate River":       (42.09, -123.22),
    "Wilson River":          (45.53, -123.47),
    "Nestucca River":        (45.30, -123.71),
    "Siletz River":          (44.90, -123.93),
    "Alsea River":           (44.35, -123.76),
    "Chetco River":          (42.11, -124.22),
    "Coquille River":        (43.10, -124.20),
    "Willamette River":      (45.52, -122.67),
    "Molalla River":         (45.15, -122.58),
    "Clackamas River":       (45.37, -122.27),
    "Yamhill River":         (45.21, -123.20),
    "Long Tom River":        (44.27, -123.25),
    "Middle Fork Willamette":(43.80, -122.78),
    "Hood River":            (45.70, -121.70),
    "Umatilla River":        (45.68, -118.47),
    "Grande Ronde River":    (45.92, -117.94),
    "Imnaha River":          (45.47, -116.89),
    "John Day River":        (44.57, -120.27),
    "Owyhee River":          (43.80, -117.22),
    "Malheur River":         (43.97, -117.30),
    "Fall River":            (43.77, -121.47),
    "Williamson River":      (42.77, -121.87),
    "Klamath River":         (41.97, -122.58),
}

HATCHERY_COORDS = [
    {"name": "Wizard Falls Hatchery",     "lat": 44.51, "lon": -121.63, "region": "Central Oregon",   "species": ["Rainbow Trout", "Brook Trout", "Atlantic Salmon"]},
    {"name": "Deschutes River Hatchery",  "lat": 44.92, "lon": -120.89, "region": "Central Oregon",   "species": ["Steelhead", "Chinook"]},
    {"name": "Sandy River Hatchery",      "lat": 45.42, "lon": -121.97, "region": "Mt. Hood",         "species": ["Winter Steelhead", "Spring Chinook"]},
    {"name": "Bonneville Hatchery",       "lat": 45.64, "lon": -121.94, "region": "Columbia Gorge",   "species": ["Spring Chinook", "Coho", "Steelhead"]},
    {"name": "McKenzie River Hatchery",   "lat": 44.15, "lon": -122.57, "region": "Willamette Valley","species": ["Spring Chinook", "Summer Steelhead"]},
    {"name": "North Santiam Hatchery",    "lat": 44.73, "lon": -122.53, "region": "Willamette Valley","species": ["Winter Steelhead", "Spring Chinook"]},
    {"name": "Klaskanine Hatchery",       "lat": 46.08, "lon": -123.65, "region": "Oregon Coast",     "species": ["Coho", "Spring Chinook"]},
    {"name": "Roaring River Hatchery",    "lat": 44.83, "lon": -122.85, "region": "Willamette Valley","species": ["Rainbow Trout"]},
    {"name": "Willamette Hatchery",       "lat": 43.72, "lon": -122.67, "region": "Southern Willamette","species": ["Spring Chinook", "Rainbow Trout"]},
    {"name": "Cole Rivers Hatchery",      "lat": 42.78, "lon": -122.75, "region": "Southern Oregon",  "species": ["Chinook", "Coho", "Steelhead", "Rainbow Trout"]},
    {"name": "Alsea River Hatchery",      "lat": 44.43, "lon": -123.64, "region": "Oregon Coast",     "species": ["Winter Steelhead", "Coho"]},
    {"name": "Siletz Valley Hatchery",    "lat": 44.88, "lon": -123.85, "region": "Oregon Coast",     "species": ["Winter Steelhead", "Coho"]},
    {"name": "Necanicum River Hatchery",  "lat": 45.83, "lon": -123.79, "region": "North Coast",      "species": ["Coho", "Chinook"]},
    {"name": "Umatilla Hatchery",         "lat": 45.63, "lon": -118.62, "region": "Eastern Oregon",   "species": ["Summer Steelhead", "Spring Chinook"]},
    {"name": "Imnaha Hatchery",           "lat": 45.49, "lon": -116.87, "region": "Eastern Oregon",   "species": ["Spring Chinook", "Summer Steelhead"]},
]


def _haversine_miles(lat1, lon1, lat2, lon2):
    R = 3958.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def geocode(query):
    headers = {"User-Agent": "OregonFishingDashboard/1.0 (fishing-dashboard)"}
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": query, "format": "json", "limit": 1, "countrycodes": "us"},
            headers=headers,
            timeout=8,
        )
        r.raise_for_status()
        results = r.json()
        if not results:
            return None
        top = results[0]
        return {
            "name": top.get("display_name", query),
            "short_name": _shorten(top.get("display_name", query)),
            "lat": float(top["lat"]),
            "lon": float(top["lon"]),
            "type": top.get("type", ""),
        }
    except Exception as e:
        log.error("geocode error: %s", e)
        return None


def _shorten(display_name):
    parts = [p.strip() for p in display_name.split(",")]
    return ", ".join(parts[:3]) if len(parts) >= 3 else display_name


def find_nearby_rivers(lat, lon, river_summaries, max_miles=120):
    river_by_name = {r["river"]: r for r in river_summaries}
    results = []
    for river_name, (rlat, rlon) in RIVER_COORDS.items():
        dist = _haversine_miles(lat, lon, rlat, rlon)
        if dist > max_miles:
            continue
        summary = river_by_name.get(river_name)
        entry = {
            "river": river_name,
            "distance_miles": round(dist, 1),
            "lat": rlat,
            "lon": rlon,
        }
        if summary:
            entry.update({
                "cfs": summary.get("cfs"),
                "condition": summary.get("condition", {}),
                "temp_f": summary.get("temp_f"),
                "tenkara_score": summary.get("tenkara_score"),
                "species": summary.get("species", []),
                "region": summary.get("region", ""),
                "tenkara": summary.get("tenkara", False),
                "access": summary.get("access", ""),
                "regulations": summary.get("regulations", ""),
                "season_note": summary.get("season_note", ""),
            })
        else:
            entry.update({"cfs": None, "condition": {"status": "unknown", "label": "No data"}, "region": ""})
        results.append(entry)
    results.sort(key=lambda x: x["distance_miles"])
    return results[:10]


def get_nws_point_weather(lat, lon):
    try:
        headers = {"User-Agent": "OregonFishingDashboard/1.0 (fishing-dashboard)", "Accept": "application/geo+json"}
        points_r = requests.get(
            f"https://api.weather.gov/points/{lat:.4f},{lon:.4f}",
            headers=headers,
            timeout=(5, 15),
        )
        points_r.raise_for_status()
        props = points_r.json().get("properties", {})
        forecast_url = props.get("forecast")
        zone_name = props.get("relativeLocation", {}).get("properties", {})
        city = zone_name.get("city", "")
        state = zone_name.get("state", "")
        location_label = f"{city}, {state}" if city else "Local Area"

        if not forecast_url:
            return {"error": "No forecast URL", "location_label": location_label}

        fc_r = requests.get(forecast_url, headers=headers, timeout=8)
        fc_r.raise_for_status()
        periods = fc_r.json().get("properties", {}).get("periods", [])
        if not periods:
            return {"error": "No forecast periods", "location_label": location_label}

        p = periods[0]
        temp_f = p.get("temperature")
        short_fc = p.get("shortForecast", "")
        wind_speed = p.get("windSpeed", "")
        wind_dir = p.get("windDirection", "")
        is_day = p.get("isDaytime", True)
        detailed = p.get("detailedForecast", "")

        precip_chance = 0
        if "probability" in p:
            precip_chance = p.get("probability", {}).get("value") or 0

        score = _fishing_score(temp_f, short_fc, wind_speed)

        return {
            "location_label": location_label,
            "temp_f": temp_f,
            "short_forecast": short_fc,
            "wind_speed": wind_speed,
            "wind_dir": wind_dir,
            "is_daytime": is_day,
            "detailed_forecast": detailed,
            "fishing_score": score,
            "fishing_label": _score_label(score),
            "period_name": p.get("name", "Now"),
        }
    except Exception as e:
        log.error("nws point weather error: %s", e)
        return {"error": str(e)}


def _fishing_score(temp_f, forecast, wind_speed):
    score = 50
    if temp_f is not None:
        if 55 <= temp_f <= 75:
            score += 20
        elif 45 <= temp_f <= 85:
            score += 10
        elif temp_f < 35 or temp_f > 90:
            score -= 20

    fc_lower = forecast.lower()
    if any(w in fc_lower for w in ["sunny", "clear", "mostly sunny", "partly cloudy"]):
        score += 15
    elif any(w in fc_lower for w in ["rain", "shower", "storm", "thunderstorm"]):
        score -= 20
    elif any(w in fc_lower for w in ["overcast", "cloudy", "fog"]):
        score -= 5

    try:
        spd = int("".join(filter(str.isdigit, wind_speed.split(" ")[0])))
        if spd < 10:
            score += 10
        elif spd < 20:
            score += 0
        else:
            score -= 15
    except Exception:
        pass

    return max(0, min(100, score))


def _score_label(score):
    if score >= 80:
        return {"label": "Excellent", "color": "#00ff87"}
    if score >= 65:
        return {"label": "Good", "color": "#ffd60a"}
    if score >= 45:
        return {"label": "Fair", "color": "#ff9f43"}
    return {"label": "Poor", "color": "#ff4757"}


def find_nearby_hatcheries(lat, lon, max_miles=80):
    results = []
    for h in HATCHERY_COORDS:
        dist = _haversine_miles(lat, lon, h["lat"], h["lon"])
        if dist <= max_miles:
            results.append({**h, "distance_miles": round(dist, 1)})
    results.sort(key=lambda x: x["distance_miles"])
    return results[:5]
