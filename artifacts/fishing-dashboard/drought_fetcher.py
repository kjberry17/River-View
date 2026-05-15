import requests
from datetime import datetime
from cache_utils import ttl_cache

USDM_URL = "https://droughtmonitor.unl.edu/DmData/DataDownload/WebServiceInfo.aspx"

OREGON_COUNTIES_BY_REGION = {
    "Central Oregon": ["Deschutes", "Crook", "Jefferson"],
    "Willamette Valley": ["Lane", "Linn", "Benton", "Polk", "Marion", "Yamhill", "Washington"],
    "Eastern Oregon": ["Baker", "Grant", "Harney", "Malheur", "Morrow", "Umatilla", "Union", "Wallowa"],
    "Mt. Hood / Columbia Gorge": ["Hood River", "Wasco", "Clackamas", "Multnomah"],
    "Oregon Coast": ["Clatsop", "Tillamook", "Lincoln", "Coos", "Curry"],
    "Southern Oregon": ["Douglas", "Josephine", "Jackson", "Klamath", "Lake"],
    "Northeast Oregon": ["Wallowa", "Union", "Baker"],
}

DROUGHT_LABELS = {
    -1: {"label": "No Data", "color": "#888", "emoji": "❓"},
    0: {"label": "No Drought", "color": "#00ff87", "emoji": "🟢"},
    1: {"label": "D0 — Abnormally Dry", "color": "#ffd60a", "emoji": "🟡"},
    2: {"label": "D1 — Moderate Drought", "color": "#ff9f43", "emoji": "🟠"},
    3: {"label": "D2 — Severe Drought", "color": "#e74c3c", "emoji": "🔴"},
    4: {"label": "D3 — Extreme Drought", "color": "#c0392b", "emoji": "🔴"},
    5: {"label": "D4 — Exceptional Drought", "color": "#922b21", "emoji": "⛔"},
}


@ttl_cache(ttl=21600)
def fetch_drought_monitor():
    """Fetch US Drought Monitor data for Oregon counties via the USDM GeoJSON API."""
    results = {}
    today = datetime.now()
    try:
        resp = requests.get(
            "https://droughtmonitor.unl.edu/data/json/usdm/current.json",
            timeout=12,
        )
        resp.raise_for_status()
        data = resp.json()

        oregon_feature = None
        for feat in data.get("features", []):
            props = feat.get("properties", {})
            if props.get("st") == "OR" or props.get("state") == "OR":
                oregon_feature = feat
                break

        if oregon_feature:
            for county_name in _all_or_counties():
                results[county_name] = {
                    "drought_level": 0,
                    "label": DROUGHT_LABELS[0],
                    "date": today.strftime("%Y-%m-%d"),
                }
        else:
            results["error"] = "Oregon not found in USDM data"
            return results

        stats_resp = requests.get(
            "https://droughtmonitor.unl.edu/DmData/DataTables.aspx/GetTabularCountyStatistics",
            json={"area": "00049", "statisticType": "1", "droughtLevel": "0"},
            headers={"Content-Type": "application/json"},
            timeout=12,
        )
        if stats_resp.ok:
            stats_data = stats_resp.json()
            rows = stats_data.get("d", [])
            oregon_rows = [r for r in rows if isinstance(r, dict) and r.get("State", "") == "OR"]
            for row in oregon_rows:
                county = row.get("County", "")
                if county in results:
                    for level, key in [("D0", 1), ("D1", 2), ("D2", 3), ("D3", 4), ("D4", 5)]:
                        pct = row.get(key, 0)
                        if pct is None:
                            pct = 0
                        if key not in results[county] or pct > results[county].get(key, 0):
                            results[county][key] = pct
                            results[county][f"{key}_percent"] = pct

                    d0 = row.get("D0", 0) or 0
                    d1 = row.get("D1", 0) or 0
                    d2 = row.get("D2", 0) or 0
                    d3 = row.get("D3", 0) or 0
                    d4 = row.get("D4", 0) or 0
                    if d4 > 0:
                        level = 5
                    elif d3 > 0:
                        level = 4
                    elif d2 > 0:
                        level = 3
                    elif d1 > 0:
                        level = 2
                    elif d0 > 0:
                        level = 1
                    else:
                        level = 0
                    results[county]["drought_level"] = level
                    results[county]["label"] = DROUGHT_LABELS[level]

    except Exception as e:
        results["error"] = str(e)[:120]

    return results


@ttl_cache(ttl=21600)
def fetch_drought_by_region():
    drought_data = fetch_drought_monitor()
    regions = {}
    for region, counties in OREGON_COUNTIES_BY_REGION.items():
        max_level = 0
        county_levels = {}
        for county in counties:
            cd = drought_data.get(county, {})
            level = cd.get("drought_level", 0)
            county_levels[county] = {
                "level": level,
                "label": DROUGHT_LABELS.get(level, DROUGHT_LABELS[0]),
                "d0_pct": cd.get("D0_percent"),
                "d1_pct": cd.get("D1_percent"),
                "d2_pct": cd.get("D2_percent"),
                "d3_pct": cd.get("D3_percent"),
                "d4_pct": cd.get("D4_percent"),
            }
            max_level = max(max_level, level)

        regions[region] = {
            "max_drought_level": max_level,
            "label": DROUGHT_LABELS.get(max_level, DROUGHT_LABELS[0]),
            "counties": county_levels,
            "fishing_impact": _drought_fishing_impact(max_level, region),
        }
    return regions


def _drought_fishing_impact(level, region) -> dict:
    if level >= 4:
        return {"label": "Critical — Avoid Fishing", "color": "#922b21", "notes": "Extreme drought. Streamflows critically low, temps lethally high. Do not fish."}
    elif level == 3:
        return {"label": "Severe — Limit Fishing to AM Only", "color": "#c0392b", "notes": "Low flows, high water temps. Fish dawn only. Target tailwaters and spring creeks. Handle fish minimally."}
    elif level == 2:
        return {"label": "Moderate — Fish Early/Late", "color": "#ff9f43", "notes": "Below-normal flows. Fish mornings and evenings. Spring-fed rivers and tailwaters will fish best."}
    elif level == 1:
        return {"label": "Dry — Watch Water Levels", "color": "#ffd60a", "notes": "Slightly below normal. Check specific river conditions. Tailwaters and spring creeks fine."}
    else:
        return {"label": "Normal — Fish Freely", "color": "#00ff87", "notes": "No drought stress. All waters fishing normally."}


def _all_or_counties():
    counties = set()
    for cs in OREGON_COUNTIES_BY_REGION.values():
        counties.update(cs)
    return sorted(counties)
