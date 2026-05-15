"""
Scrapes live Oregon river levels from levels.wkcc.org
Data updated ~15 min; we cache for 5 min.
"""
import re
import logging
from html.parser import HTMLParser

import requests
from cache_utils import ttl_cache

log = logging.getLogger(__name__)

URL = "https://levels.wkcc.org/?P=Oregon.html"

STATUS_COLOR = {
    "Low":        "#4488ff",
    "Very Low":   "#2255cc",
    "Okay":       "#00cc66",
    "Good":       "#00ff87",
    "Great":      "#00ffcc",
    "High":       "#ffaa00",
    "Very High":  "#ff6600",
    "Flood":      "#ff2222",
    "Danger":     "#ff0000",
    "Unknown":    "#888888",
    "":           "#888888",
}


def _clean(s: str) -> str:
    s = s.strip()
    s = re.sub(r"\s+", " ", s)
    return s


def _parse_value(raw: str):
    """Strip trend arrow, return (value_str, trend)."""
    raw = raw.strip()
    if raw.endswith("↑"):
        return raw[:-1].strip(), "up"
    if raw.endswith("↓"):
        return raw[:-1].strip(), "down"
    return raw, "stable"


class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self._in_body = False
        self._in_tr = False
        self._in_cell = False
        self._cell_buf = ""
        self._row: list[str] = []
        self.rows: list[list[str]] = []
        self._status_style = ""

    def handle_starttag(self, tag, attrs):
        attrs_d = dict(attrs)
        if tag == "tbody":
            self._in_body = True
        elif self._in_body and tag == "tr":
            self._in_tr = True
            self._row = []
            self._status_style = ""
        elif self._in_tr and tag in ("th", "td"):
            self._in_cell = True
            self._cell_buf = ""
            if "style" in attrs_d:
                self._status_style = attrs_d["style"]

    def handle_endtag(self, tag):
        if tag == "tbody":
            self._in_body = False
        elif self._in_tr and tag == "tr":
            self.rows.append(self._row[:])
            self._in_tr = False
        elif self._in_cell and tag in ("th", "td"):
            self._row.append(_clean(self._cell_buf))
            self._in_cell = False

    def handle_data(self, data):
        if self._in_cell:
            self._cell_buf += data


def _parse_html(html: str) -> list[dict]:
    parser = _TableParser()
    parser.feed(html)

    results = []
    for row in parser.rows:
        if len(row) < 8:
            continue
        status = row[0]
        name = row[1]
        location = row[2]
        dt = row[3]
        flow_raw = row[4]
        height_raw = row[5]
        temp_raw = row[6]
        drainage = row[7]
        ww_class = row[8] if len(row) > 8 else ""

        flow_val, flow_trend = _parse_value(flow_raw)
        height_val, _ = _parse_value(height_raw)
        temp_val, temp_trend = _parse_value(temp_raw)

        try:
            flow_cfs = float(flow_val) if flow_val else None
        except ValueError:
            flow_cfs = None

        try:
            height_ft = float(height_val) if height_val else None
        except ValueError:
            height_ft = None

        try:
            temp_f = float(temp_val) if temp_val else None
        except ValueError:
            temp_f = None

        results.append({
            "status": status,
            "status_color": STATUS_COLOR.get(status, STATUS_COLOR[""]),
            "name": name,
            "location": location,
            "datetime": dt,
            "flow_cfs": flow_cfs,
            "flow_cfs_raw": flow_val,
            "flow_trend": flow_trend,
            "height_ft": height_ft,
            "height_ft_raw": height_val,
            "temp_f": temp_f,
            "temp_f_raw": temp_val,
            "temp_trend": temp_trend,
            "drainage": drainage,
            "whitewater_class": ww_class,
        })

    return results


@ttl_cache(ttl=300)
def fetch_wkcc_levels() -> dict:
    try:
        resp = requests.get(URL, timeout=15, headers={"User-Agent": "OregonFishingDashboard/1.0"})
        resp.raise_for_status()
        gauges = _parse_html(resp.text)
        drainages = sorted({g["drainage"] for g in gauges if g["drainage"]})
        statuses = sorted({g["status"] for g in gauges if g["status"]})
        return {
            "source": URL,
            "count": len(gauges),
            "drainages": drainages,
            "statuses": statuses,
            "gauges": gauges,
        }
    except Exception as exc:
        log.error("wkcc fetch failed: %s", exc)
        return {"error": str(exc), "gauges": [], "count": 0}
