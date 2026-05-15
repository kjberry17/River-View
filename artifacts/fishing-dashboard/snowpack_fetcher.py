import requests
from datetime import datetime
from cache_utils import ttl_cache

AWDB_BASE = "https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1"

OREGON_SNOTEL_SITES = {
    "Three Creeks Meadow (Deschutes)": {
        "id": "22E07S",
        "lat": 44.10, "lon": -121.63,
        "elevation_ft": 5690,
        "region": "Central Oregon",
        "rivers": ["Deschutes River", "Crooked River", "Metolius River", "Fall River"],
        "desc": "Snowpack for upper Deschutes/Crooked basin. Determines summer tailwater flows.",
    },
    "McKenzie (Willamette Pass)": {
        "id": "22E05S",
        "lat": 44.20, "lon": -121.87,
        "elevation_ft": 4790,
        "region": "Willamette Valley",
        "rivers": ["McKenzie River", "Willamette River", "Middle Fork Willamette"],
        "desc": "Snowpack for McKenzie basin. Drives spring Chinook run timing and summer flows.",
    },
    "Hood River Test Site": {
        "id": "21E05S",
        "lat": 45.22, "lon": -121.60,
        "elevation_ft": 5370,
        "region": "Mt. Hood",
        "rivers": ["Hood River", "Sandy River", "Clackamas River"],
        "desc": "Mt. Hood snowpack. Controls Hood, Sandy, Clackamas summer flows.",
    },
    "Annie Springs (Crater Lake)": {
        "id": "21E08S",
        "lat": 42.87, "lon": -122.17,
        "elevation_ft": 6030,
        "region": "Southern Oregon",
        "rivers": ["Rogue River", "Williamson River", "Klamath River"],
        "desc": "Crater Lake / Upper Rogue basin. Critical for Rogue summer steelhead flows.",
    },
    "Summit Guard (Blue Mountains)": {
        "id": "17E04S",
        "lat": 44.92, "lon": -118.45,
        "elevation_ft": 5600,
        "region": "Eastern Oregon",
        "rivers": ["Grande Ronde River", "Umatilla River", "John Day River"],
        "desc": "Blue Mountains snowpack. Determines Grande Ronde/John Day summer river levels.",
    },
    "Mt. Howard (Wallowa Mountains)": {
        "id": "17E05S",
        "lat": 45.26, "lon": -117.18,
        "elevation_ft": 7910,
        "region": "Eastern Oregon",
        "rivers": ["Imnaha River", "Grande Ronde River", "Wallowa Lake"],
        "desc": "Wallowa Mountains snowpack. Feeds Imnaha, Wallowa, upper Grande Ronde.",
    },
    "Santiam Junction (Santiam Pass)": {
        "id": "21E18S",
        "lat": 44.43, "lon": -121.93,
        "elevation_ft": 3750,
        "region": "Willamette Valley / Central Oregon",
        "rivers": ["North Santiam River", "South Santiam River", "Metolius River"],
        "desc": "Santiam Pass snowpack. Controls North and South Santiam April-July flows.",
    },
    "Marion Forks (North Santiam)": {
        "id": "21E19S",
        "lat": 44.60, "lon": -121.95,
        "elevation_ft": 2600,
        "region": "Willamette Valley",
        "rivers": ["North Santiam River", "South Santiam River"],
        "desc": "Lower elevation snowpack for Santiam basin. Affects early-season runoff.",
    },
}


@ttl_cache(ttl=3600)
def fetch_snotel_data():
    results = {}
    today = datetime.now()
    water_year = today.year if today.month >= 10 else today.year - 1

    for name, info in OREGON_SNOTEL_SITES.items():
        try:
            params = {
                "stationTriplets": f"{info['id']}:OR:SNTL",
                "elementCd": "WTEQ",
                "ordinal": "1",
                "duration": "DAILY",
                "getFlags": "false",
                "beginDate": f"{water_year}-10-01",
                "endDate": today.strftime("%Y-%m-%d"),
            }
            swe_resp = requests.get(f"{AWDB_BASE}/data", params=params, timeout=12)
            swe_data = swe_resp.json() if swe_resp.ok else []

            swe_values = []
            if swe_data:
                for entry in swe_data:
                    vals = entry.get("values", [])
                    if vals:
                        swe_values = [v for v in vals if v is not None]
                        break

            latest_swe = swe_values[-1] if swe_values else None
            peak_swe = max(swe_values) if swe_values else None
            peak_date_idx = swe_values.index(peak_swe) if peak_swe and swe_values else -1

            params["elementCd"] = "TOBS"
            temp_resp = requests.get(f"{AWDB_BASE}/data", params=params, timeout=12)
            temp_data = temp_resp.json() if temp_resp.ok else []
            latest_temp = None
            if temp_data:
                for entry in temp_data:
                    vals = entry.get("values", [])
                    clean_vals = [v for v in vals if v is not None]
                    if clean_vals:
                        latest_temp = round(clean_vals[-1] * 9 / 5 + 32, 1)
                        break

            params["elementCd"] = "SNWD"
            depth_resp = requests.get(f"{AWDB_BASE}/data", params=params, timeout=12)
            depth_data = depth_resp.json() if depth_resp.ok else []
            latest_depth = None
            if depth_data:
                for entry in depth_data:
                    vals = entry.get("values", [])
                    clean_vals = [v for v in vals if v is not None]
                    if clean_vals:
                        latest_depth = clean_vals[-1]
                        break

            percent_normal = round((latest_swe / peak_swe * 100), 0) if latest_swe and peak_swe and peak_swe > 0 else None
            melt_status = _get_melt_status(latest_swe, peak_swe) if latest_swe is not None and peak_swe is not None else "Unknown"

            results[name] = {
                **info,
                "swe_inches": round(latest_swe, 2) if latest_swe else None,
                "peak_swe_inches": round(peak_swe, 2) if peak_swe else None,
                "snow_depth_inches": round(latest_depth, 1) if latest_depth else None,
                "percent_of_peak": percent_normal,
                "melt_status": melt_status,
                "temp_f": latest_temp,
                "water_year": water_year,
                "updated": today.strftime("%Y-%m-%d"),
                "fishing_impact": _fishing_impact(latest_swe, peak_swe, today.month)
                if latest_swe is not None and peak_swe is not None
                else {"label": "Unknown", "color": "#888", "notes": "No snowpack data available."},
            }
        except Exception as e:
            results[name] = {**info, "error": str(e)[:100], "swe_inches": None}

    return results


def _get_melt_status(swe, peak_swe) -> str:
    if swe is None or peak_swe is None or peak_swe <= 0:
        return "No Data"
    ratio = swe / peak_swe
    if ratio > 0.9:
        return "Building / At Peak"
    elif ratio > 0.7:
        return "Early Melt"
    elif ratio > 0.4:
        return "Active Melt"
    elif ratio > 0.1:
        return "Late Melt"
    else:
        return "Melted Out"


def _fishing_impact(swe, peak_swe, month) -> dict:
    if swe is None or peak_swe is None or peak_swe <= 0:
        return {"label": "No snow data", "color": "#888", "notes": "No snowpack data for this basin."}

    if month is None:
        month = datetime.now().month

    ratio = swe / peak_swe

    if month in [11, 12, 1, 2]:
        if ratio >= 0.9:
            return {"label": "Snowpack Building", "color": "#4fc3f7", "notes": "Winter snow accumulating. Look for tailwaters and spring creeks until spring melt."}
        else:
            return {"label": "Below Normal Snowpack", "color": "#ff9f43", "notes": "Below-average snow. Potential for early runoff and low summer flows."}
    elif month in [3, 4]:
        if ratio < 0.3:
            return {"label": "Early Meltout — Summer Risk", "color": "#ff4757", "notes": "Snow is gone early. Prepare for low summer flows. Fish tailwaters now."}
        elif ratio < 0.7:
            return {"label": "Active Melt — High Runoff", "color": "#ff9f43", "notes": "Runoff may be peaking. Fish tailwaters and spring creeks. Avoid freestone rivers."}
        else:
            return {"label": "Good Snowpack — Late Runoff", "color": "#00ff87", "notes": "Deep snow still present. Runoff will be extended. Good summer flows expected."}
    elif month in [5, 6, 7]:
        if ratio < 0.1:
            return {"label": "Melted Out — Low Summer Flows", "color": "#ff4757", "notes": "Snow is gone. Fish early mornings. Target spring-fed rivers and tailwaters."}
        elif ratio < 0.3:
            return {"label": "Melting — Good Flows", "color": "#ffd60a", "notes": "Snow still feeding rivers. Good conditions on freestone rivers."}
        else:
            return {"label": "Deep Snow Still Melting — High Water", "color": "#4fc3f7", "notes": "Heavy melt still happening. Fish tailwaters or wait for flows to drop."}
    else:
        return {"label": "Snow-Free Season", "color": "#888", "notes": f"Snowpack data not relevant for {'fall' if month >= 9 else 'late summer'} fishing."}


@ttl_cache(ttl=3600)
def fetch_snotel_summary():
    data = fetch_snotel_data()
    summary = []
    for name, info in data.items():
        if info.get("error"):
            continue
        summary.append({
            "name": name,
            "region": info.get("region", ""),
            "swe_inches": info.get("swe_inches"),
            "percent_of_peak": info.get("percent_of_peak"),
            "melt_status": info.get("melt_status"),
            "fishing_impact": info.get("fishing_impact"),
            "rivers": info.get("rivers", []),
        })
    summary.sort(key=lambda x: (
        0 if x.get("melt_status") in ("Building / At Peak", "Active Melt")
        else 1 if x.get("melt_status") == "Early Melt"
        else 2 if x.get("melt_status") == "Late Melt"
        else 3
    ))
    return summary
