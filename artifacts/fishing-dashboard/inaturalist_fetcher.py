import requests
from datetime import datetime, timedelta
from cache_utils import ttl_cache

INAT_BASE = "https://api.inaturalist.org/v1"

OREGON_BOUNDS = {
    "swlat": 41.99, "swlng": -124.71,
    "nelat": 46.29, "nelng": -116.46,
}

OREGON_FISH_TAXA = {
    "Rainbow Trout / Steelhead": 47509,
    "Chinook Salmon": 54168,
    "Coho Salmon": 47513,
    "Sockeye Salmon": 47493,
    "Cutthroat Trout": 47510,
    "Brook Trout": 61946,
    "Brown Trout": 47535,
    "Bull Trout": 49138,
    "Lake Trout": 51470,
    "Smallmouth Bass": 49587,
    "Largemouth Bass": 49597,
    "Mountain Whitefish": 62001,
    "Pacific Lamprey": 48691,
    "White Sturgeon": 49368,
}

AQUATIC_INSECTS = {
    "Caddisflies (Trichoptera)": 62157,
    "Mayflies (Ephemeroptera)": 47612,
    "Stoneflies (Plecoptera)": 56206,
    "Midges (Chironomidae)": 64594,
    "Dragonflies (Odonata)": 47609,
}


@ttl_cache(ttl=3600)
def fetch_inaturalist_observations(taxon_id=None, days_back=7, limit=50):
    today = datetime.now()
    d1 = (today - timedelta(days=days_back)).strftime("%Y-%m-%d")
    d2 = today.strftime("%Y-%m-%d")

    try:
        params = {
            "nelat": OREGON_BOUNDS["nelat"],
            "nelng": OREGON_BOUNDS["nelng"],
            "swlat": OREGON_BOUNDS["swlat"],
            "swlng": OREGON_BOUNDS["swlng"],
            "d1": d1, "d2": d2,
            "per_page": min(limit, 50),
            "order": "desc",
            "order_by": "created_at",
            "quality_grade": "research",
        }
        if taxon_id:
            params["taxon_id"] = taxon_id

        resp = requests.get(f"{INAT_BASE}/observations", params=params, timeout=15)
        if not resp.ok:
            return {"error": f"iNaturalist HTTP {resp.status_code}", "results": []}

        data = resp.json()
        observations = []
        for obs in data.get("results", []):
            taxon = obs.get("taxon", {})
            location = obs.get("location", "")
            coords = obs.get("geojson", {}).get("coordinates", [None, None]) if obs.get("geojson") else [None, None]
            photos = []
            for photo in obs.get("photos", []):
                url = photo.get("url", "")
                if url and "square" in url:
                    url = url.replace("square", "medium")
                photos.append(url)

            observations.append({
                "id": obs.get("id"),
                "species": taxon.get("preferred_common_name") or taxon.get("name", "Unknown"),
                "scientific_name": taxon.get("name", ""),
                "location": location,
                "lat": coords[1],
                "lon": coords[0],
                "observed_on": obs.get("observed_on", ""),
                "photos": photos,
                "quality_grade": obs.get("quality_grade", ""),
                "uri": obs.get("uri", ""),
            })

        return {
            "total_results": data.get("total_results", 0),
            "results": observations,
            "date_range": f"{d1} to {d2}",
        }

    except Exception as e:
        return {"error": str(e)[:120], "results": []}


@ttl_cache(ttl=3600)
def fetch_recent_fish_obs(days_back=7):
    results = {}
    for name, taxon_id in OREGON_FISH_TAXA.items():
        obs = fetch_inaturalist_observations(taxon_id=taxon_id, days_back=days_back, limit=20)
        if not obs.get("error") and obs.get("results"):
            results[name] = obs
    return results


@ttl_cache(ttl=3600)
def fetch_aquatic_insect_obs(days_back=14):
    results = {}
    for name, taxon_id in AQUATIC_INSECTS.items():
        obs = fetch_inaturalist_observations(taxon_id=taxon_id, days_back=days_back, limit=15)
        if not obs.get("error") and obs.get("results"):
            results[name] = obs
    return results


@ttl_cache(ttl=3600)
def fetch_inaturalist_summary():
    fish = fetch_recent_fish_obs(days_back=7)
    insects = fetch_aquatic_insect_obs(days_back=14)

    summary = {
        "fish_species": {},
        "insect_species": {},
        "total_fish_obs": 0,
        "total_insect_obs": 0,
    }

    for name, obs in fish.items():
        count = len(obs.get("results", []))
        summary["fish_species"][name] = count
        summary["total_fish_obs"] += count

    for name, obs in insects.items():
        count = len(obs.get("results", []))
        summary["insect_species"][name] = count
        summary["total_insect_obs"] += count

    return summary
