import os
import time
import logging
from dotenv import load_dotenv
load_dotenv()

from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = Flask(__name__, static_folder="static")
CORS(app)

# Per-session tool result cache — survives across questions in the same browser session
SESSION_CACHE: dict = {}
SESSION_CACHE_TTL = 1800  # 30 minutes


def _get_session(session_id: str) -> dict:
    now = time.time()
    # Purge expired sessions
    expired = [k for k, v in SESSION_CACHE.items() if now - v.get("last_active", 0) > SESSION_CACHE_TTL]
    for k in expired:
        del SESSION_CACHE[k]
    if session_id not in SESSION_CACHE:
        SESSION_CACHE[session_id] = {"last_active": now, "web_searches": []}
    SESSION_CACHE[session_id]["last_active"] = now
    return SESSION_CACHE[session_id]

try:
    import database as _db
    _db.init_db()
except Exception as _e:
    log.warning("DB init skipped: %s", _e)

BASE = os.path.dirname(__file__)


@app.route("/_stcore/health")
def stcore_health():
    return "ok", 200


@app.route("/_stcore/host-config")
def stcore_host_config():
    return jsonify({
        "allowedOrigins": ["*"],
        "useExternalAuthToken": False,
        "enableCustomParentMessages": False,
        "mapboxToken": "",
    })


@app.route("/")
def index():
    return send_from_directory(os.path.join(BASE, "static"), "index.html")


@app.route("/fish/flows")
def api_flows():
    try:
        from data_fetchers import fetch_usgs_flows, fetch_odfw_stocking, build_river_summary
        flows = fetch_usgs_flows()
        stocking = fetch_odfw_stocking()
        summary = build_river_summary(flows, stocking)
        return jsonify(summary)
    except Exception as e:
        log.error("flows error: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/fish/passage")
def api_passage():
    try:
        from fish_passage import fetch_bonneville_passage, get_run_timing_calendar, FISH_ICONS, SPECIES_NOTES
        passage = fetch_bonneville_passage()
        calendar = get_run_timing_calendar()
        return jsonify({"passage": passage, "calendar": calendar, "icons": FISH_ICONS, "notes": SPECIES_NOTES})
    except Exception as e:
        log.error("passage error: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/fish/weather")
def api_weather():
    try:
        from weather_fetchers import fetch_nws_weather
        weather = fetch_nws_weather()
        return jsonify(weather)
    except Exception as e:
        log.error("weather error: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/fish/coastal")
def api_coastal():
    try:
        from oregon_gov_data import fetch_ndbc_buoys, fetch_noaa_tides
        buoys = fetch_ndbc_buoys()
        tides = fetch_noaa_tides()
        return jsonify({"buoys": buoys, "tides": tides})
    except Exception as e:
        log.error("coastal error: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/fish/hatcheries")
def api_hatcheries():
    try:
        from hatcheries import OREGON_HATCHERIES, OREGON_LAKES
        return jsonify({"hatcheries": OREGON_HATCHERIES, "lakes": OREGON_LAKES})
    except Exception as e:
        log.error("hatcheries error: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/fish/lakes")
def api_lakes():
    try:
        from lake_temps import fetch_lake_temps
        return jsonify(fetch_lake_temps())
    except Exception as e:
        log.error("lakes error: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/fish/location")
def api_location():
    from flask import request as freq
    q = freq.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "No location specified"}), 400
    try:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from location_api import geocode, find_nearby_rivers, get_nws_point_weather, find_nearby_hatcheries
        from data_fetchers import fetch_usgs_flows, fetch_odfw_stocking, build_river_summary

        geo = geocode(q)
        if not geo:
            return jsonify({"error": "Location not found — try a city, zip code, or river name"}), 404

        lat, lon = geo["lat"], geo["lon"]

        def _get_rivers():
            flows = fetch_usgs_flows()
            stocking = fetch_odfw_stocking()
            summaries = build_river_summary(flows, stocking)
            return find_nearby_rivers(lat, lon, summaries)

        def _get_weather():
            return get_nws_point_weather(lat, lon)

        def _get_hatcheries():
            return find_nearby_hatcheries(lat, lon)

        with ThreadPoolExecutor(max_workers=3) as ex:
            f_rivers = ex.submit(_get_rivers)
            f_weather = ex.submit(_get_weather)
            f_hatcheries = ex.submit(_get_hatcheries)
            nearby = f_rivers.result()
            weather = f_weather.result()
            hatcheries = f_hatcheries.result()

        return jsonify({
            "location": geo,
            "nearby_rivers": nearby,
            "weather": weather,
            "nearby_hatcheries": hatcheries,
        })
    except Exception as e:
        log.error("location error: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/fish/water-quality")
def api_water_quality():
    try:
        from data_fetchers import fetch_usgs_flows
        rivers = fetch_usgs_flows()
        return jsonify({"rivers": rivers})
    except Exception as e:
        log.error("water-quality error: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/fish/flow-stats")
def api_flow_stats():
    try:
        from data_fetchers import fetch_usgs_percentiles
        stats = fetch_usgs_percentiles()
        return jsonify(stats)
    except Exception as e:
        log.error("flow-stats error: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/fish/snowpack")
def api_snowpack():
    try:
        from snowpack_fetcher import fetch_snotel_summary
        return jsonify(fetch_snotel_summary())
    except Exception as e:
        log.error("snowpack error: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/fish/dams/all")
def api_all_dams():
    try:
        from fish_passage import fetch_all_dams_passage
        return jsonify(fetch_all_dams_passage())
    except Exception as e:
        log.error("dams error: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/fish/drought")
def api_drought():
    try:
        from drought_fetcher import fetch_drought_by_region
        return jsonify(fetch_drought_by_region())
    except Exception as e:
        log.error("drought error: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/fish/marine")
def api_marine():
    try:
        from weather_fetchers import fetch_nws_marine
        return jsonify(fetch_nws_marine())
    except Exception as e:
        log.error("marine error: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/fish/epa-wqp")
def api_epa_wqp():
    try:
        from water_quality_fetcher import fetch_epa_wqp_multi_param
        river = __import__("flask").request.args.get("river")
        return jsonify(fetch_epa_wqp_multi_param(river_name=river))
    except Exception as e:
        log.error("epa-wqp error: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/fish/aqi")
def api_aqi():
    try:
        from air_quality_fetcher import get_fishing_air_quality_summary
        return jsonify(get_fishing_air_quality_summary())
    except Exception as e:
        log.error("aqi error: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/fish/river-levels")
def api_river_levels():
    try:
        from flask import request as freq
        from wkcc_fetcher import fetch_wkcc_levels
        from data_fetchers import filter_gauges_for_river_system

        river = (freq.args.get("river") or "").strip()
        payload = fetch_wkcc_levels()
        if not river:
            return jsonify(payload)

        gauges = payload.get("gauges", [])
        filtered_gauges = filter_gauges_for_river_system(gauges, river)
        drainages = sorted({g.get("drainage", "") for g in filtered_gauges if g.get("drainage")})
        statuses = sorted({g.get("status", "") for g in filtered_gauges if g.get("status")})
        return jsonify({
            "source": payload.get("source"),
            "count": len(filtered_gauges),
            "drainages": drainages,
            "statuses": statuses,
            "gauges": filtered_gauges,
            "river_filter": river,
        })
    except Exception as e:
        log.error("river-levels error: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/fish/wildlife")
def api_wildlife():
    try:
        from inaturalist_fetcher import fetch_inaturalist_summary
        return jsonify(fetch_inaturalist_summary())
    except Exception as e:
        log.error("wildlife error: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/fish/reports")
def api_reports():
    try:
        from web_tools import extract_relevant_osint
        query = __import__("flask").request.args.get("q", "")
        return jsonify({"reports": extract_relevant_osint(query)})
    except Exception as e:
        log.error("reports error: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/fish/reddit")
def api_reddit():
    try:
        from web_tools import fetch_reddit_multisub
        return jsonify({"posts": fetch_reddit_multisub()})
    except Exception as e:
        log.error("reddit error: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/fish/search")
def api_search():
    try:
        from web_tools import search_fishing_reports_osint
        query = __import__("flask").request.args.get("q", "")
        return jsonify(search_fishing_reports_osint(zone_name=query))
    except Exception as e:
        log.error("search error: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/fish/conditions")
def api_conditions():
    try:
        from data_fetchers import fetch_usgs_flows, fetch_usgs_percentiles
        from weather_fetchers import fetch_nws_weather
        from oregon_gov_data import fetch_ndbc_buoys, fetch_noaa_tides
        from snowpack_fetcher import fetch_snotel_summary
        from drought_fetcher import fetch_drought_by_region
        from concurrent.futures import ThreadPoolExecutor
        results = {}
        with ThreadPoolExecutor(max_workers=6) as ex:
            f_flows = ex.submit(fetch_usgs_flows)
            f_stats = ex.submit(fetch_usgs_percentiles)
            f_weather = ex.submit(fetch_nws_weather)
            f_buoys = ex.submit(fetch_ndbc_buoys)
            f_tides = ex.submit(fetch_noaa_tides)
            f_snow = ex.submit(fetch_snotel_summary)
            results["rivers"] = f_flows.result()
            results["flow_stats"] = f_stats.result()
            results["weather"] = f_weather.result()
            results["buoys"] = f_buoys.result()
            results["tides"] = f_tides.result()
            results["snowpack"] = f_snow.result()
        results["drought"] = fetch_drought_by_region()
        return jsonify(results)
    except Exception as e:
        log.error("conditions error: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/fish/chat", methods=["POST"])
def api_chat():
    from flask import request as freq
    body = freq.get_json(silent=True) or {}
    user_message = (body.get("message") or "").strip()
    history = body.get("history") or []
    model_key = body.get("model") or "⚡ DeepSeek V4 Flash (Free)"
    use_stream = body.get("stream", False)
    session_id = (body.get("session_id") or "").strip()
    session_cache = _get_session(session_id) if session_id else {}

    if not user_message:
        return jsonify({"error": "No message provided"}), 400

    try:
        import database as db
        from data_fetchers import fetch_usgs_flows, fetch_odfw_stocking, build_river_summary
        from weather_fetchers import fetch_nws_weather
        from fish_passage import fetch_bonneville_passage

        flows = fetch_usgs_flows()
        stocking = fetch_odfw_stocking()
        river_summary = build_river_summary(flows, stocking)

        live_data = {}
        for r in river_summary:
            live_data[r["river"]] = r

        try:
            live_data["_weather"] = fetch_nws_weather()
        except Exception:
            live_data["_weather"] = {}

        try:
            live_data["_passage"] = fetch_bonneville_passage()
        except Exception:
            live_data["_passage"] = {}

        live_data["_stocking"] = [r for r in river_summary if r.get("is_stocked")]

        try:
            from wkcc_fetcher import fetch_wkcc_levels
            wkcc = fetch_wkcc_levels()
            live_data["_wkcc_gauges"] = wkcc.get("gauges", [])
        except Exception:
            live_data["_wkcc_gauges"] = []

        if use_stream:
            from ai_buddy import chat_with_buddy_stream
            import json as _json

            def generate():
                try:
                    for event in chat_with_buddy_stream(
                        user_message=user_message,
                        conversation_history=history,
                        live_data=live_data,
                        db_module=db,
                        model_key=model_key,
                        session_cache=session_cache,
                    ):
                        yield _json.dumps(event) + "\n"
                except Exception as gen_err:
                    yield _json.dumps({"type": "response", "content": f"⚠️ The Fisher encountered a streaming error: {str(gen_err)[:300]}"}) + "\n"
                    yield _json.dumps({"type": "done", "sources": [], "wiki_proposals": []}) + "\n"
            from flask import Response
            return Response(generate(), mimetype="application/x-ndjson")

        from ai_buddy import chat_with_buddy
        response, wiki_proposals = chat_with_buddy(
            user_message=user_message,
            conversation_history=history,
            live_data=live_data,
            db_module=db,
            model_key=model_key,
            session_cache=session_cache,
        )
        return jsonify({"response": response, "wiki_proposals": wiki_proposals})
    except Exception as e:
        log.error("chat error: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/fish/wiki", methods=["POST"])
def api_wiki_save():
    from flask import request as freq
    body = freq.get_json(silent=True) or {}
    try:
        import database as db
        entry_id = db.add_wiki_entry({
            "entry_type": body.get("entry_type", "spot"),
            "river": body.get("river"),
            "title": body.get("title", "Untitled"),
            "content": body.get("content", ""),
            "tags": body.get("tags", []),
            "confidence": body.get("confidence", "personal"),
        })
        return jsonify({"ok": True, "id": entry_id})
    except Exception as e:
        log.error("wiki save error: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/fish/refresh", methods=["POST"])
def api_refresh():
    try:
        from data_fetchers import (
            fetch_usgs_flows,
            fetch_odfw_stocking,
            fetch_usgs_percentiles,
            fetch_usgs_site_catalog,
            fetch_usgs_site_values,
        )
        from fish_passage import fetch_bonneville_passage, fetch_all_dams_passage
        from weather_fetchers import fetch_nws_weather, fetch_nws_marine
        from oregon_gov_data import fetch_ndbc_buoys, fetch_noaa_tides
        from lake_temps import fetch_lake_temps
        from snowpack_fetcher import fetch_snotel_summary, fetch_snotel_data
        from drought_fetcher import fetch_drought_monitor, fetch_drought_by_region
        from water_quality_fetcher import fetch_epa_wqp_multi_param
        from air_quality_fetcher import fetch_airnow_aqi, get_fishing_air_quality_summary
        from inaturalist_fetcher import fetch_inaturalist_summary, fetch_recent_fish_obs
        from web_tools import fetch_reddit_multisub, search_fishing_reports_osint
        from wkcc_fetcher import fetch_wkcc_levels
        from concurrent.futures import ThreadPoolExecutor

        fetch_usgs_flows.clear()
        fetch_usgs_site_catalog.clear()
        fetch_usgs_site_values.clear()
        fetch_wkcc_levels.clear()
        fetch_odfw_stocking.clear()
        fetch_usgs_percentiles.clear()
        fetch_bonneville_passage.clear()
        fetch_all_dams_passage.clear()
        fetch_nws_weather.clear()
        fetch_nws_marine.clear()
        fetch_ndbc_buoys.clear()
        fetch_noaa_tides.clear()
        fetch_lake_temps.clear()
        fetch_snotel_summary.clear()
        fetch_snotel_data.clear()
        fetch_drought_monitor.clear()
        fetch_drought_by_region.clear()
        fetch_epa_wqp_multi_param.clear()
        fetch_airnow_aqi.clear()
        get_fishing_air_quality_summary.clear()
        fetch_inaturalist_summary.clear()
        fetch_recent_fish_obs.clear()
        fetch_reddit_multisub.clear()
        search_fishing_reports_osint.clear()

        with ThreadPoolExecutor(max_workers=8) as ex:
            ex.submit(fetch_usgs_flows)
            ex.submit(fetch_usgs_site_catalog)
            ex.submit(fetch_usgs_percentiles)
            ex.submit(fetch_bonneville_passage)
            ex.submit(fetch_nws_weather)
            ex.submit(fetch_nws_marine)
            ex.submit(fetch_ndbc_buoys)
            ex.submit(fetch_noaa_tides)
            ex.submit(fetch_lake_temps)
            ex.submit(fetch_snotel_summary)
            ex.submit(fetch_drought_by_region)
            ex.submit(get_fishing_air_quality_summary)
            ex.submit(fetch_inaturalist_summary)
            ex.submit(fetch_wkcc_levels)

        return jsonify({"ok": True, "message": "All caches cleared and refreshing"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    import socket

    port = int(os.environ.get("PORT", 5000))
    max_tries = 20

    for offset in range(max_tries):
        attempt = port + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("0.0.0.0", attempt)) != 0:
                port = attempt
                break
    else:
        log.warning("no open ports found in range %d–%d", port, port + max_tries - 1)

    log.info("starting on http://0.0.0.0:%d", port)
    app.run(host="0.0.0.0", port=port, debug=False)
