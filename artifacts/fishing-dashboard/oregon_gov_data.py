import requests
from datetime import datetime
from cache_utils import ttl_cache

NDBC_BUOYS = {
    "Stonewall Banks (Newport)": {
        "id": "46050",
        "lat": 44.794, "lon": -124.524,
        "desc": "127nm WNW of Newport · Offshore swell reference",
        "fishing_zones": ["Siletz River", "Alsea River", "Nestucca River"],
    },
    "Umpqua Offshore": {
        "id": "46229",
        "lat": 43.769, "lon": -124.549,
        "desc": "Off Winchester Bay / Umpqua River mouth",
        "fishing_zones": ["Umpqua River", "Coquille River"],
    },
    "Cape Arago / Coos Bay": {
        "id": "46015",
        "lat": 42.747, "lon": -124.832,
        "desc": "Southern Oregon offshore · Coos Bay zone",
        "fishing_zones": ["Chetco River", "Coquille River"],
    },
}

NDBC_URL = "https://www.ndbc.noaa.gov/data/realtime2/{buoy_id}.txt"

NOAA_TIDE_STATIONS = {
    "South Beach / Newport": {
        "id": "9435380",
        "lat": 44.625, "lon": -124.045,
        "desc": "Newport, OR — Siletz Bay, Alsea R. mouth",
    },
    "Charleston / Coos Bay": {
        "id": "9432780",
        "lat": 43.345, "lon": -124.322,
        "desc": "Coos Bay / Charleston Harbor",
    },
    "Brookings": {
        "id": "9431647",
        "lat": 42.051, "lon": -124.281,
        "desc": "Southern Oregon coast — Chetco River mouth",
    },
    "Astoria / Columbia River": {
        "id": "9439040",
        "lat": 46.207, "lon": -123.769,
        "desc": "Columbia River mouth — Astoria",
    },
}

NOAA_TIDES_API = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"


@ttl_cache(ttl=600)
def fetch_ndbc_buoys() -> dict:
    results = {}
    for name, info in NDBC_BUOYS.items():
        try:
            url = NDBC_URL.format(buoy_id=info["id"])
            resp = requests.get(url, timeout=10, headers={"User-Agent": "OregonFishingDashboard/4.0"})
            if resp.status_code != 200:
                results[name] = {"error": f"HTTP {resp.status_code}", **info}
                continue
            parsed = _parse_ndbc_text(resp.text)
            if parsed:
                results[name] = {**parsed, **info}
            else:
                results[name] = {"error": "Parse failed", **info}
        except Exception as e:
            results[name] = {"error": str(e)[:60], **info}
    return results


def _parse_ndbc_text(text: str) -> dict | None:
    lines = [l for l in text.strip().split("\n") if not l.startswith("#") and l.strip()]
    if not lines:
        return None

    def _val(cols, idx):
        v = cols[idx] if idx < len(cols) else "MM"
        if v in ("MM", "999", "9999", "9.99", "999.0", "9999.0", "99.0", "9999.9"):
            return None
        try:
            return round(float(v), 2)
        except ValueError:
            return None

    best = {}
    obs_time = None
    for line in lines[:12]:
        cols = line.split()
        if len(cols) < 14:
            continue
        if obs_time is None:
            obs_time = f"{int(cols[3]):02d}:{int(cols[4]):02d} UTC"
        for key, idx in [("wvht", 8), ("dpd", 9), ("pres", 12), ("atmp", 13), ("wtmp", 14), ("wspd", 6), ("wdir", 5)]:
            if key not in best:
                v = _val(cols, idx)
                if v is not None:
                    best[key] = v

    if obs_time is None:
        return None

    wvht_m = best.get("wvht")
    wtmp_c = best.get("wtmp")
    atmp_c = best.get("atmp")
    wspd = best.get("wspd")
    wdir = best.get("wdir")
    pres = best.get("pres")
    dpd = best.get("dpd")

    wdir_str = ""
    if wdir is not None:
        dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
        wdir_str = dirs[int((wdir + 11.25) / 22.5) % 16]

    fishing_impact = _wave_fishing_impact(wvht_m, wspd, dpd)

    return {
        "wave_height_m": wvht_m,
        "wave_height_ft": round(wvht_m * 3.281, 1) if wvht_m else None,
        "dominant_period_s": dpd,
        "pressure_hpa": pres,
        "air_temp_f": round(atmp_c * 9 / 5 + 32, 1) if atmp_c is not None else None,
        "sst_f": round(wtmp_c * 9 / 5 + 32, 1) if wtmp_c is not None else None,
        "wind_speed_kts": round(wspd * 1.944, 1) if wspd is not None else None,
        "wind_dir_str": wdir_str,
        "obs_time": obs_time,
        "fishing_impact": fishing_impact,
    }


def _wave_fishing_impact(wvht_m, wspd, dpd) -> dict:
    if wvht_m is None:
        return {"label": "Unknown", "color": "#888", "notes": "No wave data"}
    if wvht_m <= 2.0 and (wspd is None or wspd <= 7.0):
        return {"label": "Good for Coastal Fishing", "color": "#00ff87", "notes": f"Waves {wvht_m:.1f}m — manageable. Bar crossings feasible."}
    elif wvht_m <= 3.5:
        return {"label": "Moderate — Check Bar Conditions", "color": "#ffd60a", "notes": f"Waves {wvht_m:.1f}m — shore fishing fine. Bar crossings: caution."}
    elif wvht_m <= 5.0:
        return {"label": "Rough — Shore Fishing Only", "color": "#ff9f43", "notes": f"Waves {wvht_m:.1f}m — ocean not advised. Fish river mouths."}
    else:
        return {"label": "Dangerous — Stay Off Water", "color": "#ff4757", "notes": f"Waves {wvht_m:.1f}m — dangerous sea state. River fishing only."}


@ttl_cache(ttl=360)
def fetch_noaa_tides() -> dict:
    results = {}
    for name, info in NOAA_TIDE_STATIONS.items():
        try:
            params = {
                "date": "latest", "station": info["id"], "product": "water_level",
                "datum": "MLLW", "time_zone": "lst_ldt", "units": "english", "format": "json",
            }
            resp = requests.get(NOAA_TIDES_API, params=params, timeout=8)
            data_json = resp.json()
            wl_data = data_json.get("data", [])
            current_wl = float(wl_data[-1]["v"]) if wl_data else None
            obs_time = wl_data[-1]["t"] if wl_data else "Unknown"

            trend = "Stable"
            if len(wl_data) >= 3:
                diff = float(wl_data[-1]["v"]) - float(wl_data[-3]["v"])
                trend = "Rising" if diff > 0.1 else "Falling" if diff < -0.1 else "Stable"

            pred_params = {
                "begin_date": datetime.now().strftime("%Y%m%d"), "range": 24,
                "station": info["id"], "product": "predictions",
                "datum": "MLLW", "time_zone": "lst_ldt", "interval": "hilo",
                "units": "english", "format": "json",
            }
            pred_resp = requests.get(NOAA_TIDES_API, params=pred_params, timeout=8)
            predictions = pred_resp.json().get("predictions", [])
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
            next_events = []
            for p in predictions[:8]:
                if p["t"] >= now_str:
                    next_events.append({
                        "type": "High" if p["type"] == "H" else "Low",
                        "time": p["t"][-5:],
                        "level": float(p["v"]),
                    })

            results[name] = {
                **info,
                "water_level_ft": current_wl,
                "obs_time": obs_time,
                "trend": trend,
                "next_tide_events": next_events[:4],
            }
        except Exception as e:
            results[name] = {**info, "error": str(e)[:80]}
    return results
