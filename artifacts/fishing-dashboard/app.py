import os
import logging
from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = Flask(__name__, static_folder="static")
CORS(app)

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


@app.route("/fish/chat", methods=["POST"])
def api_chat():
    from flask import request as freq
    body = freq.get_json(silent=True) or {}
    user_message = (body.get("message") or "").strip()
    history = body.get("history") or []
    model_key = body.get("model") or "⚡ DeepSeek V4 Flash"

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

        from ai_buddy import chat_with_buddy
        response, wiki_proposals = chat_with_buddy(
            user_message=user_message,
            conversation_history=history,
            live_data=live_data,
            db_module=db,
            model_key=model_key,
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
        from data_fetchers import fetch_usgs_flows, fetch_odfw_stocking
        from fish_passage import fetch_bonneville_passage
        from weather_fetchers import fetch_nws_weather
        from oregon_gov_data import fetch_ndbc_buoys, fetch_noaa_tides
        from lake_temps import fetch_lake_temps
        fetch_usgs_flows.clear()
        fetch_odfw_stocking.clear()
        fetch_bonneville_passage.clear()
        fetch_nws_weather.clear()
        fetch_ndbc_buoys.clear()
        fetch_noaa_tides.clear()
        fetch_lake_temps.clear()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
