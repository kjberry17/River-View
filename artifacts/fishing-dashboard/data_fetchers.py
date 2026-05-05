import requests
import pandas as pd
from datetime import datetime, timedelta
import streamlit as st

USGS_API = "https://waterservices.usgs.gov/nwis/iv/"
USGS_STATS_API = "https://waterservices.usgs.gov/nwis/stat/"

OREGON_GAGE_IDS = {
    "Deschutes River": "14103000",
    "McKenzie River": "14162500",
    "Metolius River": "14075000",
    "Crooked River": "14087400",
    "North Santiam River": "14185000",
    "Sandy River": "14137000",
    "North Umpqua River": "14317000",
    "Rogue River": "14361500",
    "Wilson River": "14301500",
    "Willamette River": "14211720",
}

TENKARA_RIVERS = {"Deschutes River", "McKenzie River", "Metolius River",
                  "Crooked River", "North Santiam River", "Sandy River", "Wilson River"}

RIVER_COORDS = {
    "Deschutes River": (44.6365, -121.1871),
    "McKenzie River": (44.1271, -122.4818),
    "Metolius River": (44.4774, -121.6310),
    "Crooked River": (44.3052, -120.8364),
    "North Santiam River": (44.7751, -122.6016),
    "Sandy River": (45.4001, -122.2609),
    "North Umpqua River": (43.3201, -122.9316),
    "Rogue River": (42.4265, -123.3256),
    "Wilson River": (45.5271, -123.5501),
    "Willamette River": (45.5231, -122.6765),
}

TYPICAL_RANGES = {
    "Deschutes River": (200, 2000, 600, 1200),
    "McKenzie River": (300, 3000, 800, 2000),
    "Metolius River": (150, 800, 200, 500),
    "Crooked River": (50, 500, 100, 300),
    "North Santiam River": (400, 5000, 800, 2500),
    "Sandy River": (500, 8000, 800, 3000),
    "North Umpqua River": (500, 6000, 900, 3000),
    "Rogue River": (1000, 15000, 1500, 5000),
    "Wilson River": (200, 4000, 400, 2000),
    "Willamette River": (2000, 50000, 5000, 20000),
}


@st.cache_data(ttl=300)
def fetch_usgs_flows():
    site_ids = ",".join(OREGON_GAGE_IDS.values())
    try:
        resp = requests.get(USGS_API, params={
            "format": "json",
            "sites": site_ids,
            "parameterCd": "00060",
            "siteStatus": "active"
        }, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        results = {}
        for ts in data.get("value", {}).get("timeSeries", []):
            site_code = ts["sourceInfo"]["siteCode"][0]["value"]
            values = ts.get("values", [{}])[0].get("value", [])
            if values:
                latest = values[-1]
                cfs = float(latest["value"]) if latest["value"] != "-999999" else None
                dt_str = latest.get("dateTime", "")
                for river, gid in OREGON_GAGE_IDS.items():
                    if gid == site_code:
                        results[river] = {
                            "cfs": cfs,
                            "datetime": dt_str,
                            "site_id": site_code,
                        }
        return results
    except Exception as e:
        return {"error": str(e)}


def get_condition(river_name: str, cfs: float) -> dict:
    if cfs is None:
        return {"status": "unknown", "color": "gray", "label": "No Data", "emoji": "❓"}
    if river_name not in TYPICAL_RANGES:
        return {"status": "unknown", "color": "gray", "label": "No Data", "emoji": "❓"}
    _, abs_high, low_ok, high_ok = TYPICAL_RANGES[river_name]
    if cfs > abs_high:
        return {"status": "poor", "color": "red", "label": "Too High / Dangerous", "emoji": "🔴"}
    elif cfs > high_ok:
        return {"status": "caution", "color": "orange", "label": "High — Caution", "emoji": "🟠"}
    elif cfs < 30:
        return {"status": "poor", "color": "purple", "label": "Too Low", "emoji": "🟣"}
    elif cfs >= low_ok and cfs <= high_ok:
        return {"status": "good", "color": "green", "label": "Good Conditions", "emoji": "🟢"}
    else:
        return {"status": "fair", "color": "yellow", "label": "Fair — Check Trends", "emoji": "🟡"}


def get_tenkara_score(river_name: str, cfs: float) -> str:
    if cfs is None:
        return "Unknown"
    if river_name not in TENKARA_RIVERS:
        return "Not Recommended"
    if river_name not in TYPICAL_RANGES:
        return "Unknown"
    _, _, low_ok, high_ok = TYPICAL_RANGES[river_name]
    tenkara_max = high_ok * 0.6
    if cfs <= tenkara_max and cfs >= 30:
        return "Excellent"
    elif cfs <= high_ok:
        return "Fishable"
    else:
        return "Too High"


@st.cache_data(ttl=3600)
def fetch_odfw_stocking():
    try:
        url = "https://myodfw.com/articles/where-fish-odfw-stocking-schedule"
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Oregon Fishing Dashboard/1.0"})
        if resp.status_code == 200:
            return _parse_stocking_fallback()
        return _parse_stocking_fallback()
    except Exception:
        return _parse_stocking_fallback()


def _parse_stocking_fallback():
    today = datetime.now()
    month = today.month
    stocked = []
    if month in [3, 4, 5]:
        stocked = [
            {"river": "Deschutes River", "location": "Bend City Reach", "species": "Rainbow Trout", "size": "10-12 inch", "date": today.strftime("%Y-%m-%d"), "source": "ODFW (cached schedule)"},
            {"river": "Willamette River", "location": "Corvallis Reach", "species": "Rainbow Trout", "size": "10-12 inch", "date": today.strftime("%Y-%m-%d"), "source": "ODFW (cached schedule)"},
            {"river": "Sandy River", "location": "Oxbow Park", "species": "Winter Steelhead", "size": "Adult", "date": today.strftime("%Y-%m-%d"), "source": "ODFW (cached schedule)"},
            {"river": "North Santiam River", "location": "Mehama Bridge", "species": "Rainbow Trout", "size": "8-10 inch", "date": today.strftime("%Y-%m-%d"), "source": "ODFW (cached schedule)"},
        ]
    elif month in [6, 7, 8]:
        stocked = [
            {"river": "Crooked River", "location": "Prineville Reservoir", "species": "Rainbow Trout", "size": "12-14 inch", "date": today.strftime("%Y-%m-%d"), "source": "ODFW (cached schedule)"},
            {"river": "Metolius River", "location": "Camp Sherman", "species": "Bull Trout (C&R Only)", "size": "Adult", "date": today.strftime("%Y-%m-%d"), "source": "ODFW (cached schedule)"},
        ]
    elif month in [9, 10, 11]:
        stocked = [
            {"river": "Rogue River", "location": "Grants Pass", "species": "Coho Salmon", "size": "Adult", "date": today.strftime("%Y-%m-%d"), "source": "ODFW (cached schedule)"},
            {"river": "Wilson River", "location": "Tillamook Forest", "species": "Coho Salmon", "size": "Adult", "date": today.strftime("%Y-%m-%d"), "source": "ODFW (cached schedule)"},
        ]
    else:
        stocked = [
            {"river": "Sandy River", "location": "Revenue Bridge", "species": "Winter Steelhead", "size": "Adult", "date": today.strftime("%Y-%m-%d"), "source": "ODFW (cached schedule)"},
        ]
    return stocked


def build_river_summary(flows: dict, stocking: list) -> list:
    stocked_rivers = {s["river"] for s in stocking}
    summary = []
    for river, coords in RIVER_COORDS.items():
        flow_data = flows.get(river, {})
        cfs = flow_data.get("cfs") if isinstance(flow_data, dict) else None
        condition = get_condition(river, cfs)
        tenkara = get_tenkara_score(river, cfs)
        summary.append({
            "river": river,
            "lat": coords[0],
            "lon": coords[1],
            "cfs": cfs,
            "condition": condition,
            "tenkara_score": tenkara,
            "is_tenkara": river in TENKARA_RIVERS,
            "is_stocked": river in stocked_rivers,
            "last_updated": flow_data.get("datetime", "N/A") if isinstance(flow_data, dict) else "N/A",
        })
    summary.sort(key=lambda x: (
        0 if x["condition"]["status"] == "good" else
        1 if x["condition"]["status"] == "fair" else
        2 if x["condition"]["status"] == "caution" else 3
    ))
    return summary


def rank_tenkara(river_summary: list) -> list:
    ranked = [r for r in river_summary
              if r["is_tenkara"] and r["tenkara_score"] in ("Excellent", "Fishable")]
    ranked.sort(key=lambda x: 0 if x["tenkara_score"] == "Excellent" else 1)
    return ranked
