# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Oregon Fly/Tenkara OSINT fishing dashboard. The primary app lives in `artifacts/fishing-dashboard/` — a Flask API backend (`app.py`) serving a single-page vanilla JS frontend (`static/index.html`). The repo root's `main.py` is a compatibility shim that `chdir`s into the dashboard directory and imports `app.py`.

## Running Locally

```bash
# Install deps
pip install -r artifacts/fishing-dashboard/requirements.txt

# Run dev server (from repo root)
cd artifacts/fishing-dashboard && python app.py

# Or via gunicorn (prod-style)
PORT=5000 bash artifacts/fishing-dashboard/start.sh
```

Health check: `curl http://localhost:5000/_stcore/health`

## Environment Variables

| Variable | Required | Purpose |
|---|---|---|
| `OPENROUTER_API_KEY` | Yes | AI Buddy chat (OpenRouter gateway) |
| `DATABASE_URL` | Optional | PostgreSQL — wiki entries, fishing logs, preferences |
| `AIRNOW_API_KEY` | Optional | Live AQI; falls back to estimated guidance without it |

## Architecture

### Backend (`artifacts/fishing-dashboard/`)

**`app.py`** — Flask entrypoint. Defines all `/fish/*` REST routes (flows, passage, weather, lakes, snowpack, drought, water quality, AQI, iNaturalist, Reddit, WKCC levels, AI chat, wiki, fishing log, preferences, map, location). Each route imports its fetcher module lazily. `/fish/refresh` clears all caches and re-warms in parallel via `ThreadPoolExecutor`.

**`cache_utils.py`** — `@ttl_cache(seconds)` decorator. Thread-safe in-process dict cache. Each cached function gets a `.clear()` method used by `/fish/refresh`. Default TTL varies per module (5–30 min).

**`database.py`** — PostgreSQL via psycopg2. Tables: `preferences`, `fishing_logs`, `wiki_entries`. Required only when `DATABASE_URL` is set; app boots without it.

**`ai_buddy.py`** — AI chat via OpenRouter. Model list defined at top of file. Uses a tool-calling loop: `get_live_data` (aggregates all fetchers), `query_wiki` (searches DB wiki), `web_search` (DuckDuckGo via `ddgs`), `save_to_wiki`, `log_trip`, `get_fishing_log`. System prompt persona is "The Fisher" Oregon fishing guide.

**Data fetcher modules** (all use `@ttl_cache`):
- `data_fetchers.py` — USGS river flows, ODFW stocking, site catalog
- `fish_passage.py` — Bonneville/other dam fish counts + run timing calendar
- `weather_fetchers.py` — NWS point forecasts + marine forecasts
- `oregon_gov_data.py` — NDBC ocean buoys, NOAA tide stations
- `lake_temps.py` — Oregon lake temperature data
- `snowpack_fetcher.py` — SNOTEL snowpack/SWE data
- `drought_fetcher.py` — US Drought Monitor by region
- `water_quality_fetcher.py` — EPA Water Quality Portal multi-param
- `air_quality_fetcher.py` — AirNow AQI + fishing-context summary
- `inaturalist_fetcher.py` — iNaturalist recent fish observations
- `web_tools.py` — DuckDuckGo search, Reddit multi-sub scrape
- `wkcc_fetcher.py` — Scrapes levels.wkcc.org (176 Oregon gauges not in USGS)
- `hatcheries.py`, `location_api.py`, `map_view.py` — static/processed data

### Frontend (`artifacts/fishing-dashboard/static/index.html`)

Single self-contained HTML file. Dark OSINT theme (`--bg: #050b18`). Tab-based layout with tabs for: Rivers, Ocean/Coast, Weather, Snow/Drought, Fish Passage, Lakes, Water Quality, AQI, Wildlife, WKCC Levels, Map, AI Buddy, Wiki, Reports.

Uses **ECharts** for charts, **Leaflet** for maps, **marked.js** for AI response markdown rendering. All data loaded via `fetch()` against the Flask API. Charts are responsive — horizontal bar charts on mobile, vertical on desktop.

## Key Patterns

- All external HTTP calls go through `@ttl_cache` — never hit external APIs twice within the TTL window.
- The `/fish/refresh` endpoint is the canonical way to force-refresh all data; it calls `.clear()` on every cached function then re-warms in parallel.
- AI tool calls in `ai_buddy.py` aggregate live data on-demand by calling the fetcher functions directly (not via HTTP).
- WKCC data is HTML-scraped (not an API) — see `wkcc_fetcher.py` for the HTMLParser approach.
- River metadata (species, gear, access, regulations, drive times) lives as a static dict in `data_fetchers.py` (`RIVER_INFO`).
