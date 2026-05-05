# Oregon Fly/Tenkara OSINT Dashboard

## Overview

A Streamlit-based real-time Oregon fly/tenkara fishing dashboard with:
- Live USGS river flow map (Folium + streamlit-folium)
- ODFW stocking schedule data
- AI Fishing Buddy powered by OpenRouter
- Karpathy Wiki — persistent PostgreSQL memory system (preferences, fishing logs, spot wiki)

## Stack

- **Monorepo tool**: pnpm workspaces (Node.js artifacts) + Python (Streamlit artifact)
- **Frontend**: Streamlit (Python 3.11) — `artifacts/fishing-dashboard/`
- **Database**: PostgreSQL + psycopg2 (schema initialized on first run)
- **AI**: OpenRouter API (OpenAI-compatible client), tool-calling loop
- **Map**: Folium + streamlit-folium, CartoDB dark basemap
- **API codegen**: Orval (from OpenAPI spec, for Node.js services)

## Key Commands

- **Run dashboard**: `cd artifacts/fishing-dashboard && streamlit run app.py --server.port 5000 --server.headless true`
- `pnpm run typecheck` — full typecheck across Node.js packages
- `pnpm run build` — typecheck + build all Node.js packages
- `pnpm --filter @workspace/api-spec run codegen` — regenerate API hooks and Zod schemas

## Fishing Dashboard Files (`artifacts/fishing-dashboard/`)

| File | Purpose |
|---|---|
| `app.py` | Main Streamlit entry point, sidebar AI Buddy, tab routing |
| `database.py` | PostgreSQL schema, CRUD for preferences/logs/wiki/chat |
| `data_fetchers.py` | USGS flow API, ODFW stocking (cached with st.cache_data) |
| `ai_buddy.py` | OpenRouter AI with tool-calling loop (query_wiki, get_live_data, update_wiki) |
| `map_view.py` | Folium map tab with color-coded river pins |
| `live_data_tab.py` | Flow cards, tenkara ranking, stocking table |
| `wiki_tab.py` | Preferences editor, fishing log, spot wiki |

## Secrets Required

- `OPENROUTER_API_KEY` — for AI Fishing Buddy (OpenRouter)
- `DATABASE_URL` — PostgreSQL connection (auto-provisioned by Replit)

## Karpathy Wiki — DB Tables

- `preferences` — user home base, favorite rivers, style, gear, drive limits
- `fishing_logs` — dated trip logs with river/spot/flies/fish/notes
- `wiki_entries` — spot knowledge, patterns, access notes (confidence + privacy labels)
- `wiki_audit_log` — every AI write is logged for transparency
- `river_gage_map` — Oregon river→USGS gage mapping (10 rivers pre-seeded)
- `chat_history` — persistent conversation history

## Oregon Rivers Pre-Seeded

Deschutes, McKenzie, Metolius, Crooked, North Santiam, Sandy, North Umpqua, Rogue, Wilson, Willamette

## AI Tools Implemented

1. `query_wiki` — searches preferences + logs + wiki entries before answering
2. `get_live_data` — fetches USGS flow snapshot for model context
3. `update_wiki` — proposes wiki entries (requires user confirmation for preferences/secret spots)

## Workflow

- `Oregon Fishing Dashboard` — runs Streamlit on port 5000

See the `pnpm-workspace` skill for Node.js workspace structure details.
