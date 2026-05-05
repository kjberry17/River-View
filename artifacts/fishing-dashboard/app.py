import os
import logging
from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = Flask(__name__, static_folder="static")
CORS(app)

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


@app.route("/api/flows")
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


@app.route("/api/passage")
def api_passage():
    try:
        from fish_passage import fetch_bonneville_passage, get_run_timing_calendar, FISH_ICONS, SPECIES_NOTES
        passage = fetch_bonneville_passage()
        calendar = get_run_timing_calendar()
        return jsonify({"passage": passage, "calendar": calendar, "icons": FISH_ICONS, "notes": SPECIES_NOTES})
    except Exception as e:
        log.error("passage error: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/weather")
def api_weather():
    try:
        from weather_fetchers import fetch_nws_weather
        weather = fetch_nws_weather()
        return jsonify(weather)
    except Exception as e:
        log.error("weather error: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/coastal")
def api_coastal():
    try:
        from oregon_gov_data import fetch_ndbc_buoys, fetch_noaa_tides
        buoys = fetch_ndbc_buoys()
        tides = fetch_noaa_tides()
        return jsonify({"buoys": buoys, "tides": tides})
    except Exception as e:
        log.error("coastal error: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/hatcheries")
def api_hatcheries():
    try:
        from hatcheries import OREGON_HATCHERIES, OREGON_LAKES
        return jsonify({"hatcheries": OREGON_HATCHERIES, "lakes": OREGON_LAKES})
    except Exception as e:
        log.error("hatcheries error: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    try:
        from data_fetchers import fetch_usgs_flows, fetch_odfw_stocking
        from fish_passage import fetch_bonneville_passage
        from weather_fetchers import fetch_nws_weather
        from oregon_gov_data import fetch_ndbc_buoys, fetch_noaa_tides
        fetch_usgs_flows.clear()
        fetch_odfw_stocking.clear()
        fetch_bonneville_passage.clear()
        fetch_nws_weather.clear()
        fetch_ndbc_buoys.clear()
        fetch_noaa_tides.clear()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
