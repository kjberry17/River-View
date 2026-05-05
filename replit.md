# Oregon Fly/Tenkara OSINT Dashboard

## Overview

A real-time Oregon fly/tenkara fishing dashboard rebuilt from Streamlit → Flask + vanilla JS + ECharts + Leaflet. Dark glassmorphism UI with 7 interactive tabs.

## Stack

- **Monorepo tool**: pnpm workspaces (Node.js artifacts) + Python (Flask artifact)
- **Frontend**: Single-page HTML/JS with ECharts 5.5, Leaflet 1.9 — `artifacts/fishing-dashboard/static/index.html`
- **Backend**: Flask (Python 3.11) — `artifacts/fishing-dashboard/app.py`
- **Cache**: Custom TTL cache (`cache_utils.py`) replacing Streamlit's `@st.cache_data`
- **Map**: Leaflet with CartoDB dark tiles, color-coded river pins
- **Charts**: ECharts — gauge, bar, line, heatmap, scatter
- **API codegen**: Orval (from OpenAPI spec, for Node.js services)

## Key Commands

- **Run dashboard**: `cd artifacts/fishing-dashboard && pip install -q flask flask-cors requests && PORT=5000 python app.py`
- `pnpm run typecheck` — full typecheck across Node.js packages
- `pnpm run build` — typecheck + build all Node.js packages
- `pnpm --filter @workspace/api-spec run codegen` — regenerate API hooks and Zod schemas

## Fishing Dashboard Files (`artifacts/fishing-dashboard/`)

| File | Purpose |
|---|---|
| `app.py` | Flask entry point; serves static/index.html and all /api/* routes |
| `static/index.html` | Full SPA: ECharts + Leaflet, 7-tab dark dashboard |
| `cache_utils.py` | TTL cache decorator (replaces st.cache_data) |
| `data_fetchers.py` | USGS flow API, ODFW stocking (34 Oregon rivers) |
| `fish_passage.py` | DART Bonneville passage counts, run timing calendar |
| `weather_fetchers.py` | NWS forecast zones (8 Oregon weather zones) |
| `oregon_gov_data.py` | NDBC buoys (3) + NOAA tides (4 stations) |
| `hatcheries.py` | ODFW hatchery + stocked lake static data |

## API Endpoints

| Route | Description |
|---|---|
| `GET /` | Serves index.html |
| `GET /api/flows` | USGS river flows + conditions for 34 rivers |
| `GET /api/passage` | Bonneville Dam fish passage counts + run calendar |
| `GET /api/weather` | NWS forecast for 8 Oregon zones |
| `GET /api/coastal` | NDBC buoy data + NOAA tide predictions |
| `GET /api/hatcheries` | ODFW hatchery and stocked lake info |
| `POST /api/refresh` | Clear all caches and force re-fetch |

## Dashboard Tabs

1. **Map** — Leaflet map with color-coded river pins (condition + flow)
2. **Rivers** — ECharts gauge + bar charts, condition cards for 34 rivers
3. **Temps** — Tenkara suitability by temperature range
4. **Fish Passage** — Bonneville Dam passage counts (heatmap + species breakdown)
5. **Coastal** — NDBC buoy data + NOAA tide charts
6. **Weather** — NWS forecasts by region
7. **Hatcheries** — ODFW hatchery locations and stocked lakes

## Workflow

- `Oregon Fishing Dashboard` — runs Flask on port 5000

See the `pnpm-workspace` skill for Node.js workspace structure details.
