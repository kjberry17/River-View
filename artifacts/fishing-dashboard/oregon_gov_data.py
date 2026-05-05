"""
Oregon & Federal Agency Real-Time Data APIs — Confirmed Working
--------------------------------------------------------------
NDBC Ocean Buoys  : https://www.ndbc.noaa.gov  (10-min updates)
NOAA Tides        : https://api.tidesandcurrents.noaa.gov (6-min updates)
"""
import requests
import streamlit as st
from datetime import datetime

# ============================================================
# NDBC — National Data Buoy Center
# Real buoys off Oregon coast, 10-minute update cycle
# ============================================================
NDBC_BUOYS = {
    "Stonewall Banks (off Newport)": {
        "id": "46050",
        "lat": 44.794, "lon": -124.524,
        "depth_m": 130,
        "desc": "127nm WNW of Newport · Offshore swell & pressure reference",
        "fishing_zones": ["Siletz River", "Alsea River", "Nestucca River", "Wilson River"],
    },
    "Umpqua Offshore": {
        "id": "46229",
        "lat": 43.769, "lon": -124.549,
        "depth_m": 100,
        "desc": "Off Winchester Bay / Umpqua River mouth",
        "fishing_zones": ["Umpqua River", "Coquille River"],
    },
    "Cape Arago / Coos Bay": {
        "id": "46015",
        "lat": 42.747, "lon": -124.832,
        "depth_m": 400,
        "desc": "Southern Oregon offshore · Coos Bay / Chetco zone",
        "fishing_zones": ["Chetco River", "Coquille River"],
    },
}

NDBC_URL = "https://www.ndbc.noaa.gov/data/realtime2/{buoy_id}.txt"

NDBC_COLS = {
    "year": 0, "month": 1, "day": 2, "hour": 3, "minute": 4,
    "wdir": 5, "wspd": 6, "gst": 7, "wvht": 8, "dpd": 9,
    "apd": 10, "mwd": 11, "pres": 12, "atmp": 13, "wtmp": 14,
    "dewp": 15, "vis": 16, "ptdy": 17, "tide": 18,
}


@st.cache_data(ttl=600)
def fetch_ndbc_buoys() -> dict:
    """Fetch real-time ocean conditions from NDBC buoys off Oregon coast."""
    results = {}
    for name, info in NDBC_BUOYS.items():
        try:
            url = NDBC_URL.format(buoy_id=info["id"])
            resp = requests.get(url, timeout=10,
                                headers={"User-Agent": "OregonFishingDashboard/3.0"})
            if resp.status_code != 200:
                results[name] = {"error": f"HTTP {resp.status_code}", **info}
                continue
            parsed = _parse_ndbc_text(resp.text, info)
            if parsed:
                results[name] = {**parsed, **info}
            else:
                results[name] = {"error": "Parse failed", **info}
        except Exception as e:
            results[name] = {"error": str(e)[:60], **info}
    return results


def _parse_ndbc_text(text: str, info: dict) -> dict | None:
    """Parse NDBC realtime2 text file. Aggregates best values across recent rows
    because buoys don't emit all fields every observation (wave height every 30min, etc.)."""
    lines = [l for l in text.strip().split("\n") if not l.startswith("#") and l.strip()]
    if not lines:
        return None

    def _val(cols, idx, scale=1.0):
        v = cols[idx] if idx < len(cols) else "MM"
        if v in ("MM", "999", "9999", "9.99", "999.0", "9999.0", "99.0", "9999.9"):
            return None
        try:
            return round(float(v) * scale, 2)
        except ValueError:
            return None

    # Collect best (non-None) values across the last 12 observations (~2 hours)
    best = {}
    obs_time = obs_date = None
    for line in lines[:12]:
        cols = line.split()
        if len(cols) < 14:
            continue
        if obs_time is None:
            obs_time = f"{int(cols[3]):02d}:{int(cols[4]):02d} UTC"
            obs_date = f"{cols[1]}/{cols[2]}/{cols[0]}"

        for key, idx in [("wvht", 8), ("dpd", 9), ("apd", 10), ("pres", 12),
                         ("atmp", 13), ("wtmp", 14), ("wspd", 6), ("wdir", 5)]:
            if key not in best:
                v = _val(cols, idx)
                if v is not None:
                    best[key] = v

    if obs_time is None:
        return None

    wvht_m = best.get("wvht")
    dpd = best.get("dpd")
    pres = best.get("pres")
    atmp_c = best.get("atmp")
    wtmp_c = best.get("wtmp")
    wspd = best.get("wspd")
    wdir = best.get("wdir")

    wdir_str = ""
    if wdir is not None:
        directions = ["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW"]
        wdir_str = directions[int((wdir + 11.25) / 22.5) % 16]

    fishing_impact = _wave_fishing_impact(wvht_m, wspd, dpd)

    return {
        "wave_height_m": wvht_m,
        "wave_height_ft": round(wvht_m * 3.281, 1) if wvht_m else None,
        "dominant_period_s": dpd,
        "pressure_hpa": pres,
        "air_temp_c": atmp_c,
        "air_temp_f": round(atmp_c * 9/5 + 32, 1) if atmp_c is not None else None,
        "sst_c": wtmp_c,
        "sst_f": round(wtmp_c * 9/5 + 32, 1) if wtmp_c is not None else None,
        "wind_speed_ms": wspd,
        "wind_speed_kts": round(wspd * 1.944, 1) if wspd is not None else None,
        "wind_dir_deg": wdir,
        "wind_dir_str": wdir_str,
        "obs_time": obs_time,
        "obs_date": obs_date,
        "fishing_impact": fishing_impact,
    }


def _wave_fishing_impact(wvht_m, wspd, dpd) -> dict:
    if wvht_m is None:
        return {"label": "Unknown", "emoji": "❓", "color": "gray", "notes": "No wave data"}
    if wvht_m <= 2.0 and (wspd is None or wspd <= 7.0):
        return {
            "label": "Good for Coastal Fishing",
            "emoji": "🟢", "color": "green",
            "notes": f"Waves {wvht_m:.1f}m — manageable. Jetty and bar crossing feasible for small craft.",
        }
    elif wvht_m <= 3.5:
        return {
            "label": "Moderate — Check Bar Conditions",
            "emoji": "🟡", "color": "yellow",
            "notes": f"Waves {wvht_m:.1f}m — shore/jetty fishing fine. River bar crossings use caution.",
        }
    elif wvht_m <= 5.0:
        return {
            "label": "Rough — Shore Fishing Only",
            "emoji": "🟠", "color": "orange",
            "notes": f"Waves {wvht_m:.1f}m — ocean not advised. Fish river mouths and estuaries instead.",
        }
    else:
        return {
            "label": "Dangerous — Stay Off Water",
            "emoji": "🔴", "color": "red",
            "notes": f"Waves {wvht_m:.1f}m — dangerous sea state. River fishing only.",
        }


# ============================================================
# NOAA CO-OPS — Tide & Current Stations (Oregon Coast)
# https://api.tidesandcurrents.noaa.gov — 6-minute updates
# ============================================================
NOAA_TIDE_STATIONS = {
    "South Beach / Newport": {
        "id": "9435380",
        "lat": 44.625, "lon": -124.045,
        "desc": "Newport, OR — Siletz Bay, Alsea R. mouth, Newport Marina",
        "fishing_zones": ["Siletz River", "Alsea River", "Nestucca River"],
    },
    "Charleston / Coos Bay": {
        "id": "9432780",
        "lat": 43.345, "lon": -124.322,
        "desc": "Coos Bay / Charleston Harbor — Coquille, Umpqua zones",
        "fishing_zones": ["Coquille River", "South Umpqua River"],
    },
    "Brookings": {
        "id": "9431647",
        "lat": 42.051, "lon": -124.281,
        "desc": "Southern Oregon coast — Chetco River mouth",
        "fishing_zones": ["Chetco River"],
    },
    "Astoria / Columbia River": {
        "id": "9439040",
        "lat": 46.207, "lon": -123.769,
        "desc": "Columbia River mouth — Astoria, Youngs Bay",
        "fishing_zones": ["Columbia River", "Willamette River"],
    },
}

NOAA_TIDES_API = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"


@st.cache_data(ttl=360)
def fetch_noaa_tides() -> dict:
    """Fetch real-time water levels and tide predictions from NOAA CO-OPS."""
    results = {}
    for name, info in NOAA_TIDE_STATIONS.items():
        try:
            params = {
                "date": "latest",
                "station": info["id"],
                "product": "water_level",
                "datum": "MLLW",
                "time_zone": "lst_ldt",
                "units": "english",
                "format": "json",
            }
            resp = requests.get(NOAA_TIDES_API, params=params, timeout=8)
            data_json = resp.json()

            wl_data = data_json.get("data", [])
            metadata = data_json.get("metadata", {})
            current_wl = float(wl_data[-1]["v"]) if wl_data else None
            current_sigma = float(wl_data[-1].get("s", 0)) if wl_data else None
            obs_time = wl_data[-1]["t"] if wl_data else "Unknown"

            # Trend: rising or falling?
            trend = "→ Stable"
            if len(wl_data) >= 3:
                recent = float(wl_data[-1]["v"])
                older = float(wl_data[-3]["v"])
                diff = recent - older
                if diff > 0.1:
                    trend = "⬆️ Rising"
                elif diff < -0.1:
                    trend = "⬇️ Falling"
                else:
                    trend = "→ Stable"

            # Fetch tide predictions (next highs/lows)
            pred_params = {
                "begin_date": datetime.now().strftime("%Y%m%d"),
                "range": 24,
                "station": info["id"],
                "product": "predictions",
                "datum": "MLLW",
                "time_zone": "lst_ldt",
                "interval": "hilo",
                "units": "english",
                "format": "json",
            }
            pred_resp = requests.get(NOAA_TIDES_API, params=pred_params, timeout=8)
            predictions = pred_resp.json().get("predictions", [])
            next_events = []
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
            for p in predictions[:8]:
                if p["t"] >= now_str:
                    tide_type = "High" if p["type"] == "H" else "Low"
                    next_events.append({
                        "type": tide_type,
                        "time": p["t"],
                        "level": float(p["v"]),
                        "emoji": "🌊" if p["type"] == "H" else "🏖️",
                    })

            fishing_note = _tide_fishing_note(current_wl, trend, next_events)

            results[name] = {
                **info,
                "water_level_ft": current_wl,
                "obs_time": obs_time,
                "trend": trend,
                "next_tide_events": next_events[:4],
                "fishing_note": fishing_note,
                "station_name": metadata.get("name", name),
            }

        except Exception as e:
            results[name] = {**info, "error": str(e)[:80]}

    return results


def _tide_fishing_note(wl_ft, trend, events) -> str:
    if not events:
        return "Tide timing unavailable — check local tide chart."
    next_event = events[0]
    hours_away = 0
    try:
        from datetime import datetime as dt
        next_dt = dt.strptime(next_event["time"], "%Y-%m-%d %H:%M")
        hours_away = (next_dt - dt.now()).total_seconds() / 3600
    except Exception:
        pass

    notes = []
    if next_event["type"] == "High" and hours_away <= 1.5:
        notes.append("🌊 Incoming high tide — tidal rivers and estuaries most productive now.")
    elif next_event["type"] == "High" and hours_away <= 3:
        notes.append(f"🌊 High tide in ~{hours_away:.0f}hrs — best estuary fishing approaching. Prepare now.")
    elif next_event["type"] == "Low" and hours_away <= 1:
        notes.append("🏖️ Near low tide — rocky shore exposed, good for perch/rockfish. Tidal rivers slowing.")
    elif trend == "⬆️ Rising":
        notes.append("⬆️ Incoming tide — salmon and steelhead push upriver. Fish tidal pools and river mouths.")
    elif trend == "⬇️ Falling":
        notes.append("⬇️ Outgoing tide — baitfish concentrate near structure. Stripers and salmon follow.")
    else:
        notes.append("→ Slack tide — fish structure edges. Next movement triggers bite.")

    return " ".join(notes) if notes else "Check local tide charts for optimal fishing windows."


# ============================================================
# Convenience: Get coastal summary for AI Buddy
# ============================================================
def get_coastal_summary() -> str:
    lines = ["=== COASTAL CONDITIONS (NDBC + NOAA Tides) ==="]
    try:
        buoys = fetch_ndbc_buoys()
        for name, b in buoys.items():
            if b.get("error"):
                lines.append(f"📡 {name}: Data unavailable ({b['error']})")
                continue
            sst = f"{b['sst_f']:.1f}°F" if b.get("sst_f") else "SST N/A"
            waves = f"{b['wave_height_ft']:.1f}ft/{b.get('dominant_period_s','?')}s" if b.get("wave_height_ft") else "waves N/A"
            wind = f"{b['wind_speed_kts']:.0f}kts {b['wind_dir_str']}" if b.get("wind_speed_kts") else ""
            impact = b.get("fishing_impact", {}).get("label", "Unknown")
            lines.append(f"🌊 {name}: {sst}, waves {waves}, {wind} | {impact}")
    except Exception as e:
        lines.append(f"Buoy data error: {e}")

    try:
        tides = fetch_noaa_tides()
        lines.append("")
        for name, t in tides.items():
            if t.get("error"):
                lines.append(f"🌊 {name} tide: unavailable")
                continue
            wl = f"{t['water_level_ft']:.2f}ft" if t.get("water_level_ft") is not None else "N/A"
            trend = t.get("trend", "?")
            note = t.get("fishing_note", "")
            lines.append(f"🌊 {name}: {wl} MLLW {trend} | {note}")
    except Exception as e:
        lines.append(f"Tide data error: {e}")

    return "\n".join(lines)
