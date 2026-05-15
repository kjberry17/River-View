import requests
from datetime import datetime
from cache_utils import ttl_cache

OREGON_FISHING_AQI = {
    "Bend / Central Oregon": {"zip": "97701", "rivers": ["Deschutes River", "Crooked River", "Metolius River", "Fall River"]},
    "Eugene / Willamette Valley": {"zip": "97401", "rivers": ["McKenzie River", "Willamette River", "Long Tom River"]},
    "Medford / Southern Oregon": {"zip": "97501", "rivers": ["Rogue River", "Applegate River", "Illinois River"]},
    "Portland Metro": {"zip": "97201", "rivers": ["Sandy River", "Clackamas River"]},
    "Salem / North Santiam": {"zip": "97301", "rivers": ["North Santiam River", "South Santiam River"]},
    "La Grande / Eastern Oregon": {"zip": "97850", "rivers": ["Grande Ronde River", "Umatilla River"]},
    "Klamath Falls": {"zip": "97601", "rivers": ["Williamson River", "Klamath River"]},
    "Hood River / Gorge": {"zip": "97031", "rivers": ["Hood River"]},
    "Lincoln City / Coast": {"zip": "97367", "rivers": ["Siletz River", "Nestucca River", "Alsea River"]},
    "Coos Bay / South Coast": {"zip": "97420", "rivers": ["Coquille River"]},
    "Brookings / Far South": {"zip": "97415", "rivers": ["Chetco River"]},
    "Tillamook / North Coast": {"zip": "97141", "rivers": ["Wilson River"]},
}

AQI_LABELS = {
    (0, 50): {"label": "Good", "color": "#00e400", "emoji": "🟢", "fishing": "Clean air — excellent fishing conditions."},
    (51, 100): {"label": "Moderate", "color": "#ffff00", "emoji": "🟡", "fishing": "Acceptable. May affect sensitive groups only."},
    (101, 150): {"label": "Unhealthy for Sensitive", "color": "#ff7e00", "emoji": "🟠", "fishing": "Limit exertion. Short fishing sessions advised."},
    (151, 200): {"label": "Unhealthy", "color": "#ff0000", "emoji": "🔴", "fishing": "Avoid prolonged outdoor activity. Consider not fishing."},
    (201, 300): {"label": "Very Unhealthy", "color": "#99004c", "emoji": "🔴", "fishing": "Do not fish. Stay indoors."},
    (301, 999): {"label": "Hazardous", "color": "#800000", "emoji": "⛔", "fishing": "Emergency conditions. Evacuation zone likely."},
}


def _aqi_label(aqi_val):
    if aqi_val is None:
        return {"label": "No Data", "color": "#888", "emoji": "❓", "fishing": "Unknown air quality"}
    for (lo, hi), info in AQI_LABELS.items():
        if lo <= aqi_val <= hi:
            return info
    return {"label": "Unknown", "color": "#888", "emoji": "❓", "fishing": ""}


@ttl_cache(ttl=1800)
def fetch_airnow_aqi():
    results = {}
    api_key = None
    for env_var in ["AIRNOW_API_KEY", "AIRNOW_KEY"]:
        import os
        api_key = os.environ.get(env_var)
        if api_key:
            break

    if api_key:
        return _fetch_airnow_api(api_key)

    return _fetch_airnow_fallback()


def _fetch_airnow_api(api_key):
    results = {}
    for zone, info in OREGON_FISHING_AQI.items():
        try:
            resp = requests.get(
                "https://www.airnowapi.org/aq/observation/zipCode/current/",
                params={
                    "format": "application/json",
                    "zipCode": info["zip"],
                    "distance": "25",
                    "API_KEY": api_key,
                },
                timeout=10,
            )
            if resp.ok:
                observations = resp.json()
                if observations:
                    o = observations[0]
                    aqi = o.get("AQI")
                    results[zone] = {
                        "aqi": aqi,
                        "label": _aqi_label(aqi),
                        "parameter": o.get("ParameterName", "Unknown"),
                        "reporting_area": o.get("ReportingArea", ""),
                        "pm25": o.get("PM2_5"),
                        "o3": o.get("Ozone"),
                        "rivers": info["rivers"],
                        "updated": datetime.utcnow().strftime("%H:%M UTC"),
                    }
                else:
                    results[zone] = {"aqi": None, "label": _aqi_label(None), "rivers": info["rivers"]}
            else:
                results[zone] = {"aqi": None, "label": _aqi_label(None), "rivers": info["rivers"], "error": f"HTTP {resp.status_code}"}
        except Exception as e:
            results[zone] = {"aqi": None, "label": _aqi_label(None), "rivers": info["rivers"], "error": str(e)[:80]}
    return results


def _fetch_airnow_fallback():
    today = datetime.now()
    month = today.month
    results = {}
    for zone, info in OREGON_FISHING_AQI.items():
        if month in [7, 8, 9]:
            aqi = 75 if "Portland" in zone or "Gorge" in zone else 50 if "Coast" in zone else 65
            note = "Wildfire season — expect variable AQI. Check AirNow.gov for updates."
        elif month in [5, 6, 10]:
            aqi = 40
            note = "Shoulder season. Generally good air quality."
        else:
            aqi = 25
            note = "Winter/spring — typically excellent air quality."

        results[zone] = {
            "aqi": aqi,
            "label": _aqi_label(aqi),
            "rivers": info["rivers"],
            "updated": today.strftime("%Y-%m-%d"),
            "note": f"ESTIMATED: {note} Set AIRNOW_API_KEY for live data.",
            "estimated": True,
        }
    return results


def get_fishing_air_quality_summary():
    data = fetch_airnow_aqi()
    summary = []
    for zone, d in data.items():
        aqi = d.get("aqi")
        label = d.get("label", {})
        summary.append({
            "zone": zone,
            "aqi": aqi,
            "status": label.get("label", "Unknown"),
            "color": label.get("color", "#888"),
            "fishing_advice": label.get("fishing", ""),
            "rivers": d.get("rivers", []),
            "note": d.get("note", ""),
            "estimated": d.get("estimated", False),
        })
    summary.sort(key=lambda x: x.get("aqi") or 999)
    return summary
