import requests
from datetime import datetime, timedelta
from cache_utils import ttl_cache

WQP_BASE = "https://www.waterqualitydata.us/data/Result/search"

OREGON_WQP_SITES = {
    "Willamette River (Portland)": "14211720",
    "McKenzie River (Eugene)": "14162500",
    "Deschutes River (Bend)": "14103000",
    "Rogue River (Grants Pass)": "14361500",
    "Sandy River (Oxbow)": "14137000",
    "Clackamas River": "14211010",
    "North Santiam River": "14185000",
    "Hood River": "14120000",
    "Grande Ronde River": "13351000",
    "John Day River": "14048000",
    "Klamath River": "11510700",
}

WQP_PARAMETERS = {
    "temperature": "Temperature, water",
    "dissolved_oxygen": "Dissolved oxygen",
    "ph": "pH",
    "turbidity": "Turbidity",
    "specific_conductance": "Specific conductance",
    "phosphorus": "Phosphorus",
    "nitrogen": "Nitrogen",
    "e_coli": "Escherichia coli",
    "fecal_coliform": "Fecal Coliform",
}


@ttl_cache(ttl=7200)
def fetch_epa_wqp(river_name=None, parameter=None):
    today = datetime.now()
    start_date = (today - timedelta(days=90)).strftime("%m-%d-%Y")
    end_date = today.strftime("%m-%d-%Y")

    char_name = None
    if parameter:
        char_name = WQP_PARAMETERS.get(parameter)
    else:
        char_name = "Temperature, water"

    results = {}
    sites_to_query = OREGON_WQP_SITES if not river_name else {
        k: v for k, v in OREGON_WQP_SITES.items() if river_name.lower() in k.lower()
    }

    for name, site_id in sites_to_query.items():
        try:
            params = {
                "siteid": f"USGS-{site_id}",
                "characteristicName": char_name,
                "startDateLo": start_date,
                "startDateHi": end_date,
                "mimeType": "json",
                "sorted": "yes",
            }
            resp = requests.get(WQP_BASE, params=params, timeout=15)
            if not resp.ok:
                results[name] = {"error": f"HTTP {resp.status_code}"}
                continue

            data = resp.json()
            observations = data.get("organizations", [])
            values = []

            for org in observations:
                for act in org.get("activity", []):
                    activity_id = act.get("activityIdentifier", {}).get("activityIdentifier", "")
                    for result in act.get("result", []):
                        result_value = result.get("resultMeasure", {}).get("resultMeasureValue")
                        result_date = result.get("resultDescription", {}).get(
                            "analysisStartDate", ""
                        ) or result.get("resultDescription", {}).get("resultLaboratoryCommentCode", "")
                        if result_value:
                            try:
                                val = float(result_value)
                                values.append({
                                    "date": result_date[:10] if result_date else "",
                                    "value": val,
                                    "unit": result.get("resultMeasure", {}).get("resultMeasureUnitCode", ""),
                                })
                            except (ValueError, TypeError):
                                pass

            if values:
                recent_vals = sorted(values, key=lambda x: x["date"], reverse=True)[:10]
                avg_recent = sum(v["value"] for v in recent_vals) / len(recent_vals)
                results[name] = {
                    "site_id": site_id,
                    "parameter": parameter or "temperature",
                    "recent_values": recent_vals,
                    "count": len(values),
                    "avg_recent": round(avg_recent, 2),
                    "latest": recent_vals[0],
                }
            else:
                results[name] = {
                    "site_id": site_id,
                    "parameter": parameter or "temperature",
                    "count": 0,
                    "note": "No recent WQP data for this parameter at this site.",
                }

        except Exception as e:
            results[name] = {"site_id": site_id, "error": str(e)[:100]}

    return results


@ttl_cache(ttl=7200)
def fetch_epa_wqp_multi_param(river_name):
    results = {}
    for param_key in ["temperature", "dissolved_oxygen", "ph", "turbidity", "e_coli"]:
        r = fetch_epa_wqp(river_name=river_name, parameter=param_key)
        for site, data in r.items():
            if site not in results:
                results[site] = {}
            results[site][param_key] = data
    return results
