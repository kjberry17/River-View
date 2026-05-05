import requests
from datetime import datetime
from cache_utils import ttl_cache

LAKE_USGS_SITES = {
    "Upper Klamath Lake": "11509500",
    "Agency Lake":        "11506000",
    "Wickiup Reservoir":  "14049900",
}

OREGON_LAKE_META = {
    "Lake Billy Chinook": {
        "elevation_ft": 2200, "depth_ft": 400,
        "region": "Central Oregon", "lat": 44.539, "lon": -121.496,
        "species": ["Kokanee", "Bull Trout", "Smallmouth Bass", "Redband Rainbow"],
        "regulations": "Standard Oregon regs. Boat required for most access.",
        "notes": "Reservoir behind Round Butte Dam. Excellent kokanee June–August. Trolling preferred.",
        "best_months": [5, 6, 7, 8],
        "fishing_style": ["Trolling (Kokanee)", "Bass fishing", "Fly fishing (Bull Trout C&R)"],
    },
    "Wickiup Reservoir": {
        "elevation_ft": 4350, "depth_ft": 60,
        "region": "Central Oregon", "lat": 43.685, "lon": -121.726,
        "species": ["Brown Trout", "Rainbow Trout", "Kokanee", "White Crappie"],
        "regulations": "Fly-fishing only on designated areas. Big browns to 10+ lbs.",
        "notes": "One of Oregon's best trophy brown trout fisheries. Ice fishing December–February.",
        "best_months": [3, 4, 9, 10, 11],
        "fishing_style": ["Fly fishing", "Trolling (Kokanee)", "Stillwater nymphing"],
    },
    "Crane Prairie Reservoir": {
        "elevation_ft": 4445, "depth_ft": 20,
        "region": "Central Oregon", "lat": 43.789, "lon": -121.808,
        "species": ["Largemouth Bass", "Rainbow Trout", "Brown Trout", "Crappie"],
        "regulations": "Mix of fly-fishing and general regs depending on area.",
        "notes": "Outstanding bass water. Weed beds provide great structure. Float tube access excellent.",
        "best_months": [5, 6, 7, 8, 9],
        "fishing_style": ["Bass fishing", "Float tube fly fishing", "Crappie jigging"],
    },
    "Davis Lake": {
        "elevation_ft": 4400, "depth_ft": 25,
        "region": "Central Oregon", "lat": 43.583, "lon": -121.836,
        "species": ["Rainbow Trout"],
        "regulations": "Fly-fishing only, artificial lures only. Large rainbows to 5+ lbs.",
        "notes": "Trophy fly-only lake. Leech and damsel fly patterns. Best May–June and September.",
        "best_months": [5, 6, 9],
        "fishing_style": ["Fly fishing only", "Float tube / pontoon"],
    },
    "Odell Lake": {
        "elevation_ft": 4800, "depth_ft": 285,
        "region": "Central Oregon", "lat": 43.556, "lon": -121.852,
        "species": ["Lake Trout (Mackinaw)", "Kokanee", "Rainbow Trout", "Bull Trout"],
        "regulations": "Standard Oregon regs. Deep trolling for lake trout.",
        "notes": "One of Oregon's best kokanee lakes. Mackinaw to 30+ lbs possible. Access via Hwy 58.",
        "best_months": [6, 7, 8, 9],
        "fishing_style": ["Deep trolling (Mackinaw)", "Kokanee trolling", "Fly fishing (Bull Trout C&R)"],
    },
    "Waldo Lake": {
        "elevation_ft": 5414, "depth_ft": 420,
        "region": "Willamette / Cascades", "lat": 43.742, "lon": -122.021,
        "species": ["Rainbow Trout", "Brook Trout"],
        "regulations": "Fly-fishing and artificial lures only. No motors (electric only).",
        "notes": "One of the purest lakes in the world. Small but wild trout. Wilderness hiking required.",
        "best_months": [7, 8, 9],
        "fishing_style": ["Fly fishing", "Canoe / electric-only boat"],
    },
    "Detroit Reservoir": {
        "elevation_ft": 1600, "depth_ft": 395,
        "region": "Willamette Valley", "lat": 44.723, "lon": -122.250,
        "species": ["Kokanee", "Rainbow Trout", "Brown Trout"],
        "regulations": "Standard Oregon regs.",
        "notes": "North Santiam impoundment. Excellent kokanee mid-summer. Boat launch at Mongold SP.",
        "best_months": [5, 6, 7, 8],
        "fishing_style": ["Kokanee trolling", "Trout fishing", "Downrigger trolling"],
    },
    "Timothy Lake": {
        "elevation_ft": 3200, "depth_ft": 70,
        "region": "Mt. Hood / Sandy", "lat": 45.115, "lon": -121.787,
        "species": ["Rainbow Trout", "Kokanee", "Cutthroat Trout"],
        "regulations": "Standard Oregon regs.",
        "notes": "Mt. Hood National Forest. Good kokanee and rainbow. Campground access.",
        "best_months": [6, 7, 8],
        "fishing_style": ["Trolling", "Bank fishing", "Fly fishing"],
    },
    "Lost Lake": {
        "elevation_ft": 3143, "depth_ft": 175,
        "region": "Mt. Hood / Sandy", "lat": 45.495, "lon": -121.821,
        "species": ["Rainbow Trout", "Brook Trout"],
        "regulations": "Standard Oregon regs. Boat rentals available.",
        "notes": "Classic Mt. Hood lake. Stocked regularly. Kayak/canoe fishing productive.",
        "best_months": [5, 6, 7, 8, 9],
        "fishing_style": ["Bank fishing", "Kayak / canoe", "Fly fishing"],
    },
    "Henry Hagg Lake": {
        "elevation_ft": 270, "depth_ft": 110,
        "region": "Willamette Valley", "lat": 45.476, "lon": -123.226,
        "species": ["Rainbow Trout", "Largemouth Bass", "Smallmouth Bass", "Crappie"],
        "regulations": "Standard Oregon regs.",
        "notes": "Washington County reservoir. Year-round trout stocking. Good bass April–October.",
        "best_months": [3, 4, 5, 6, 7, 8, 9, 10],
        "fishing_style": ["Trout fishing", "Bass fishing", "Crappie jigging"],
    },
    "Fern Ridge Reservoir": {
        "elevation_ft": 374, "depth_ft": 24,
        "region": "Willamette Valley", "lat": 44.121, "lon": -123.305,
        "species": ["Largemouth Bass", "Crappie", "Catfish", "Yellow Perch"],
        "regulations": "Standard Oregon regs.",
        "notes": "Lane County. Best bass in the valley. Catfish stocking in summer.",
        "best_months": [4, 5, 6, 7, 8, 9],
        "fishing_style": ["Bass fishing", "Crappie / perch", "Catfishing"],
    },
    "Wallowa Lake": {
        "elevation_ft": 4360, "depth_ft": 290,
        "region": "Eastern Oregon", "lat": 45.272, "lon": -117.208,
        "species": ["Kokanee", "Bull Trout", "Rainbow Trout"],
        "regulations": "Catch & release for bull trout. Standard regs otherwise.",
        "notes": "Spectacular Wallowa Mountains setting. Kokanee in July–September. State park access.",
        "best_months": [7, 8, 9],
        "fishing_style": ["Kokanee trolling", "Fly fishing", "Bull Trout (C&R only)"],
    },
    "Howard Prairie Reservoir": {
        "elevation_ft": 4540, "depth_ft": 60,
        "region": "Southern Oregon", "lat": 42.218, "lon": -122.458,
        "species": ["Rainbow Trout", "Brown Trout", "Largemouth Bass"],
        "regulations": "Standard Oregon regs.",
        "notes": "Jackson County. Spring and fall trout best. Good bass mid-summer.",
        "best_months": [4, 5, 6, 9, 10],
        "fishing_style": ["Trout trolling", "Bass fishing", "Fly fishing"],
    },
    "Hyatt Reservoir": {
        "elevation_ft": 5000, "depth_ft": 80,
        "region": "Southern Oregon", "lat": 42.153, "lon": -122.419,
        "species": ["Rainbow Trout", "Brown Trout"],
        "regulations": "Standard Oregon regs.",
        "notes": "High Cascade reservoir near Medford. Trolling and fly fishing productive.",
        "best_months": [5, 6, 7, 8, 9],
        "fishing_style": ["Trolling", "Fly fishing", "Bank fishing"],
    },
    "Upper Klamath Lake": {
        "elevation_ft": 4139, "depth_ft": 12,
        "region": "Southern Oregon", "lat": 42.430, "lon": -121.980,
        "species": ["Redband Rainbow Trout", "Largemouth Bass", "Yellow Perch"],
        "regulations": "Check tribal / state regs. Tribal waters on east shore.",
        "notes": "One of Oregon's largest lakes. Excellent trout and bass. Post dam-removal fish recovery ongoing.",
        "best_months": [4, 5, 6, 9, 10],
        "fishing_style": ["Bass fishing", "Trout fishing", "Perch jigging"],
    },
    "Agency Lake": {
        "elevation_ft": 4141, "depth_ft": 10,
        "region": "Southern Oregon", "lat": 42.640, "lon": -121.900,
        "species": ["Redband Rainbow Trout", "Largemouth Bass"],
        "regulations": "Check tribal regs — Klamath Tribes jurisdiction.",
        "notes": "Connected to Upper Klamath Lake. Good bass and redband trout fishing.",
        "best_months": [5, 6, 9, 10],
        "fishing_style": ["Bass fishing", "Trout fishing"],
    },
    "Prineville Reservoir": {
        "elevation_ft": 3030, "depth_ft": 165,
        "region": "Central Oregon", "lat": 44.270, "lon": -120.749,
        "species": ["Rainbow Trout", "Largemouth Bass", "Smallmouth Bass", "Crappie"],
        "regulations": "Standard Oregon regs.",
        "notes": "Crooked River impoundment. Trophy bass. Crappie in spring. Boat recommended.",
        "best_months": [4, 5, 6, 7, 8, 9],
        "fishing_style": ["Bass fishing", "Crappie jigging", "Trout trolling"],
    },
    "Ana Reservoir": {
        "elevation_ft": 4360, "depth_ft": 50,
        "region": "Eastern Oregon", "lat": 42.622, "lon": -120.681,
        "species": ["Rainbow Trout"],
        "regulations": "Fly-fishing and artificial lures only. Trophy class fish.",
        "notes": "Spring-fed reservoir near Summer Lake. Large rainbows. Remote but productive.",
        "best_months": [4, 5, 6, 9, 10],
        "fishing_style": ["Fly fishing only", "Float tube"],
    },
}

def _seasonal_lake_temp(elevation_ft: float, month: int) -> float:
    base = [38, 39, 44, 52, 60, 66, 72, 71, 64, 54, 46, 40]
    base_temp = base[month - 1]
    elev_penalty = (elevation_ft / 1000.0) * 3.5
    return round(max(34.0, base_temp - elev_penalty), 1)


def _temp_condition(temp_f: float) -> dict:
    if temp_f < 40:
        return {"label": "Ice / Very Cold", "color": "#4fc3f7", "fishing": "Poor — fish very sluggish", "emoji": "🧊"}
    elif temp_f < 50:
        return {"label": "Cold", "color": "#4fc3f7", "fishing": "Fair — slow presentations near bottom", "emoji": "❄️"}
    elif temp_f < 60:
        return {"label": "Cool — Good", "color": "#00ff87", "fishing": "Good — fish active, try subsurface flies", "emoji": "✅"}
    elif temp_f < 68:
        return {"label": "Prime", "color": "#00ff87", "fishing": "Prime — peak feeding activity", "emoji": "🟢"}
    elif temp_f < 74:
        return {"label": "Warm", "color": "#ff9f43", "fishing": "Fair — fish early/late, handle fish quickly", "emoji": "🟠"}
    else:
        return {"label": "Hot — Stress", "color": "#ff4757", "fishing": "Poor — thermal stress, consider not fishing", "emoji": "🔴"}


@ttl_cache(ttl=3600)
def fetch_lake_temps():
    month = datetime.now().month
    usgs_temps = {}

    try:
        site_ids = ",".join(LAKE_USGS_SITES.values())
        resp = requests.get(
            "https://waterservices.usgs.gov/nwis/iv/",
            params={"format": "json", "sites": site_ids, "parameterCd": "00010", "siteStatus": "active"},
            timeout=15,
        )
        if resp.ok:
            data = resp.json()
            for ts in data.get("value", {}).get("timeSeries", []):
                site_code = ts["sourceInfo"]["siteCode"][0]["value"]
                values = ts.get("values", [{}])[0].get("value", [])
                if values:
                    raw = values[-1]["value"]
                    if raw and raw != "-999999":
                        try:
                            temp_c = float(raw)
                            for lake, sid in LAKE_USGS_SITES.items():
                                if sid == site_code:
                                    usgs_temps[lake] = round(temp_c * 9 / 5 + 32, 1)
                        except (ValueError, TypeError):
                            pass
    except Exception:
        pass

    result = []
    for name, meta in OREGON_LAKE_META.items():
        if name in usgs_temps:
            temp_f = usgs_temps[name]
            source = "USGS Live"
        else:
            temp_f = _seasonal_lake_temp(meta["elevation_ft"], month)
            source = "Seasonal Estimate"

        condition = _temp_condition(temp_f)
        is_best_season = month in meta.get("best_months", [])

        result.append({
            "name": name,
            "region": meta["region"],
            "lat": meta["lat"],
            "lon": meta["lon"],
            "elevation_ft": meta["elevation_ft"],
            "depth_ft": meta["depth_ft"],
            "temp_f": temp_f,
            "temp_c": round((temp_f - 32) * 5 / 9, 1),
            "temp_source": source,
            "condition": condition,
            "species": meta["species"],
            "regulations": meta["regulations"],
            "notes": meta["notes"],
            "best_months": meta["best_months"],
            "is_best_season": is_best_season,
            "fishing_style": meta.get("fishing_style", []),
        })

    result.sort(key=lambda x: x["name"])
    return result
