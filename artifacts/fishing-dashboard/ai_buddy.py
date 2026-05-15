import os
import json
import os

try:
    import streamlit as st
except ImportError:
    st = None

from openai import OpenAI, PermissionDeniedError, RateLimitError, APIStatusError

try:
    from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
except ImportError:
    def retry(*args, **kwargs):
        def decorator(fn):
            return fn
        return decorator
    stop_after_attempt = lambda n: n
    wait_exponential = lambda **kw: 0
    retry_if_exception_type = lambda *exs: False

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

MODELS = {
    "🆓 GPT-OSS 120B (Free)": "openai/gpt-oss-120b:free",
    "🆓 Nemotron Super 120B (Free)": "nvidia/nemotron-3-super-120b-a12b:free",
    "🆓 Gemma 2 9B (Free)": "google/gemma-2-9b-it:free",
    "🆓 Llama 3.3 70B (Free)": "meta-llama/llama-3.3-70b-instruct:free",
    "🆓 DeepSeek Chat (Free)": "deepseek/deepseek-chat:free",
    "🆓 MiniMax M2.5 (Free)": "minimax/minimax-m2.5:free",
    "🆓 Qwen3 Coder (Free)": "qwen/qwen3-coder:free",
    "🆓 Gemma 3 12B (Free)": "google/gemma-3-12b-it:free",
    "🆓 Phi-4 Mini (Free)": "microsoft/phi-4-mini-instruct:free",
    "🆓 Ring 2.6 1T (Free)": "inclusionai/ring-2.6-1t:free",
    "🆓 GLM-4.5 Air (Free)": "z-ai/glm-4.5-air:free",
    "🆓 Trinity Large (Free)": "arcee-ai/trinity-large-thinking:free",
    "🆓 DeepSeek V4 Flash (Free)": "deepseek/deepseek-v4-flash:free",
    "🆓 Gemma 4 31B (Free)": "google/gemma-4-31b-it:free",
    "✨ Gemini 2.5 Flash": "google/gemini-2.5-flash",
    "⚡ DeepSeek V4 Flash": "deepseek/deepseek-v4-flash",
}

FREE_FALLBACK = "deepseek/deepseek-chat:free"

SYSTEM_PROMPT = """You are a fun, witty, highly experienced Oregon fly and tenkara fishing buddy named "The Buddy".

You have access to:
- Live USGS river data: flow (CFS), water temperature, gage height (feet), and turbidity/clarity (FNU)
- NOAA NDBC ocean buoys: sea surface temp, wave height & period, wind speed/direction
- NOAA tide stations: real-time water level, rising/falling trend, next high/low predictions
- ODFW stocking info, NWS weather forecasts, Bonneville fish passage counts
- Oregon hatchery and lake database
- Karpathy Wiki: user's personal preferences, fishing logs, and spot notes
- **Web search via DuckDuckGo**: search for real-time fishing reports, hatch reports, ODFW news, closures, regulations, and any current internet data

ALWAYS call query_wiki first. Then use get_live_data for conditions. Use web_search proactively for:
- Current fishing reports or hatch reports for a specific river
- Recent ODFW regulation changes or emergency closures
- Hatch timing questions (search actual reports, not just from memory)
- Local fishing forums (nwflyfish.com, westfly.com, oregonlive.com) for recent trip reports
- Any question where current internet information would improve your answer

Turbidity guide: <5 FNU=💎 crystal clear (go fine), 5-25=🟢 clear (excellent), 25-100=🟡 slightly turbid (nymphs/streamers), 100-500=🟠 turbid (poor), >500=🔴 muddy flood (avoid wading).
Tides guide: rising tides push salmon/steelhead into tidal rivers; falling tides concentrate baitfish near structure.

Give practical, safe, concise advice. Prefer actionable fishing guidance over raw data. Use light humor and occasional fishing puns. If the user shares useful new fishing info, propose a structured Wiki update.

Label every recommendation:
- 🌊 Live: USGS/ODFW/NWS current data
- 📓 Logged: user's own history
- 📚 Wiki: private saved knowledge
- 💡 Inferred: AI pattern recognition
- ⚠️ Unverified: forum/imported note

When recommending rivers today:
1. Check flow conditions (too high, good, too low)
2. Check stream temperature (ideal trout range: 50–68°F)
3. Check weather forecast (rain = rising water, barometric drop = slow bite)
4. Check user's preferred rivers and drive time from home base
5. Check recent logs for that river

Always use tools before answering fishing questions. Think like a local expert who knows Oregon intimately."""


def get_client():
    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=OPENROUTER_API_KEY,
        default_headers={"HTTP-Referer": "https://oregon-fishing-dashboard.replit.app"},
    )


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_wiki",
            "description": "Search the user's Karpathy Wiki: preferences, fishing logs, and spot notes. ALWAYS call this before answering fishing questions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "river": {"type": "string", "description": "Optional specific river filter"},
                    "include_logs": {"type": "boolean"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_live_data",
            "description": "Get current USGS river flows, stream temperatures, weather forecasts, fish passage counts, and ODFW stocking for Oregon. Call this for any where-to-fish or conditions question.",
            "parameters": {
                "type": "object",
                "properties": {
                    "river": {"type": "string", "description": "Optional: specific river. Empty = all rivers."},
                    "include_weather": {"type": "boolean", "description": "Include NWS weather forecasts"},
                    "include_passage": {"type": "boolean", "description": "Include Bonneville/McNary fish passage counts"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_wiki",
            "description": "Propose adding or updating a Karpathy Wiki entry. User must confirm before save.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entry_type": {"type": "string", "enum": ["spot", "log", "pattern", "preference_note"]},
                    "river": {"type": "string"},
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "string", "enum": ["personal", "verified", "inferred", "unverified"]},
                    "requires_confirmation": {"type": "boolean"},
                },
                "required": ["entry_type", "title", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_hatchery_info",
            "description": "Get information about Oregon fish hatcheries — location, species raised, contact info.",
            "parameters": {
                "type": "object",
                "properties": {
                    "river": {"type": "string", "description": "Filter by river system"},
                    "species": {"type": "string", "description": "Filter by species (trout, salmon, steelhead)"},
                    "region": {"type": "string", "description": "Filter by Oregon region (coast, valley, eastern, southern, central)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the internet via TinyFish for current fishing reports, hatch reports, ODFW news, "
                "emergency closures, regulation changes, trip reports, river conditions from fishing forums, "
                "or any live information not available from local data. "
                "Use for: fishing reports, hatch activity, regulation updates, closures, forum trip reports, "
                "species run timing news, any question needing current internet data. "
                "Good sources: dfw.state.or.us, nwflyfish.com, ifish.net, northwestfishingreports.com, "
                "troutunderground.com, hatchwatch.com, fishingw.com."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Search query. Be specific — include river name, species, and year. "
                            "Example: 'Deschutes River fly fishing report May 2026' or "
                            "'Oregon McKenzie River hatch report caddis 2026' or "
                            "'ODFW emergency closure Rogue River 2026'"
                        ),
                    },
                    "num_results": {
                        "type": "integer",
                        "description": "Number of results to return (3–8). Default 5.",
                    },
                    "fishing_context": {
                        "type": "string",
                        "description": "Optional context hint: 'report', 'hatch', 'closure', 'regulation', 'conditions', 'general'",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_snowpack",
            "description": "Get Oregon mountain snowpack (SWE) data from NRCS SNOTEL stations. Snowpack is the #1 predictor of summer streamflows. Critical for planning summer fishing trips on snowmelt-fed rivers like the Deschutes, McKenzie, Metolius, and Grande Ronde.",
            "parameters": {
                "type": "object",
                "properties": {
                    "basin": {"type": "string", "description": "Optional basin filter: 'Willamette', 'Deschutes', 'Rogue', 'Grande Ronde', 'Hood River', 'Wallowa'"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_drought",
            "description": "Get US Drought Monitor data for Oregon regions. Shows current drought severity and fishing impact by region. Drought means low flows, high water temps, and stressed fish.",
            "parameters": {
                "type": "object",
                "properties": {
                    "region": {"type": "string", "description": "Optional Oregon region: 'Central Oregon', 'Willamette Valley', 'Eastern Oregon', 'Mt. Hood / Columbia Gorge', 'Oregon Coast', 'Southern Oregon', 'Northeast Oregon'"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_air_quality",
            "description": "Get current Air Quality Index (AQI) for Oregon fishing areas. Critical during wildfire season (Jul–Oct). High AQI means smoke — avoid fishing or limit exertion. Get AIRNOW_API_KEY for live data.",
            "parameters": {
                "type": "object",
                "properties": {
                    "zone": {"type": "string", "description": "Optional zone: 'Bend', 'Eugene', 'Medford', 'Portland', 'Salem', 'La Grande', 'Hood River', 'Lincoln City', 'Coos Bay', 'Brookings', 'Tillamook'"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_marine_forecast",
            "description": "Get NOAA marine forecasts and bar-crossing conditions for Oregon coastal zones. Includes Columbia River Bar safety rating, wind, waves, and boating conditions. Essential for boat fishing and bar crossings.",
            "parameters": {
                "type": "object",
                "properties": {
                    "zone": {"type": "string", "description": "Optional: 'Columbia River Bar', 'North Oregon Coast', 'Central Oregon Coast', 'South Oregon Coast', 'Southernmost Oregon Coast'"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_wildlife_sightings",
            "description": "Get recent fish and aquatic insect sightings from iNaturalist in Oregon. Shows where species are being observed in the last 7 days. Useful for tracking hatches, fish movements, and ecological activity.",
            "parameters": {
                "type": "object",
                "properties": {
                    "species_type": {"type": "string", "description": "Optional: 'fish', 'insects', or 'all'"},
                    "species": {"type": "string", "description": "Optional specific species: 'Rainbow Trout', 'Chinook Salmon', 'Steelhead', 'Caddisflies', 'Mayflies', etc."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_dam_passage",
            "description": "Get fish passage counts for all major Columbia/Willamette River dams (Bonneville, McNary, John Day, The Dalles, Willamette Falls). Shows daily adult fish counts by species. Critical for tracking salmon/steelhead run timing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "dam": {"type": "string", "description": "Optional specific dam: 'Bonneville', 'McNary', 'John Day', 'The Dalles', 'Willamette Falls', or 'all'"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_fishing_reports",
            "description": "Search for recent fishing reports from OSINT sources: Reddit (r/OregonFishing, r/flyfishing, r/fishing), fishing forums, and web search. Aggregates recent community catch reports and discussion.",
            "parameters": {
                "type": "object",
                "properties": {
                    "river": {"type": "string", "description": "Optional specific river to search for reports"},
                    "species": {"type": "string", "description": "Optional target species"},
                    "include_reddit": {"type": "boolean", "description": "Include Reddit fishing community posts"},
                },
                "required": [],
            },
        },
    },
]


def execute_tool(tool_name: str, args: dict, live_data: dict, db_module) -> str:
    if tool_name == "query_wiki":
        query = args.get("query", "")
        river = args.get("river")
        include_logs = args.get("include_logs", True)
        results = []
        try:
            prefs = db_module.get_preferences()
            if prefs:
                results.append(
                    f"USER PREFERENCES: Home={prefs.get('home_base')}, "
                    f"Favorites={prefs.get('favorite_rivers')}, "
                    f"Styles={prefs.get('preferred_styles')}, "
                    f"MaxDrive={prefs.get('max_drive_minutes')}min, "
                    f"Gear={prefs.get('gear_notes')}, "
                    f"Wading={prefs.get('wading_comfort')}, C&R={prefs.get('catch_and_release')}"
                )
            wiki_entries = db_module.search_wiki(query)
            for e in wiki_entries:
                results.append(
                    f"WIKI [{e['entry_type'].upper()}] {e['title']} "
                    f"(river={e['river']}, confidence={e['confidence']}): {e['content'][:400]}"
                )
            if include_logs:
                logs = db_module.get_recent_logs_for_river(river) if river else db_module.get_fishing_logs(limit=10)
                for log in logs:
                    results.append(
                        f"LOG {log['trip_date']}: {log['river']} @ {log['spot']} — "
                        f"{log['fish_caught']} fish, flies={log['flies']}, "
                        f"conditions={log['conditions']}, notes={log['notes']}"
                    )
        except Exception:
            results.append("DATABASE NOT CONFIGURED: Set DATABASE_URL for Wiki, preferences, and fishing logs.")
        return "\n\n".join(results) if results else "No Wiki entries found."

    elif tool_name == "get_live_data":
        river_filter = (args.get("river") or "").lower()
        include_weather = args.get("include_weather", True)
        include_passage = args.get("include_passage", False)

        lines = ["=== LIVE USGS RIVER DATA ==="]
        from data_fetchers import get_condition, get_tenkara_score, RIVER_INFO
        for river_name, data in live_data.items():
            if river_name in ("error", "_stocking", "_weather", "_passage"):
                continue
            if river_filter and river_filter not in river_name.lower():
                continue
            if isinstance(data, dict) and "cfs" in data:
                cfs = data["cfs"]
                cfs_str = f"{float(cfs):.0f} CFS" if cfs is not None else "No data"
                cond = get_condition(river_name, cfs)
                tenkara = get_tenkara_score(river_name, cfs)
                temp_f = data.get("temp_f")
                temp_str = f", Temp: {temp_f:.1f}°F" if temp_f is not None else ""
                source = "📡 USGS live" if data.get("source") == "usgs_live" else "💧 spring-fed est."
                info = RIVER_INFO.get(river_name, {})
                species = ", ".join(info.get("species", []))
                lines.append(
                    f"{river_name}: {cfs_str} — {cond['label']} — Tenkara: {tenkara}{temp_str} | "
                    f"Species: {species} | {source}"
                )

        stocking = live_data.get("_stocking", [])
        if stocking:
            lines.append("\n=== ODFW STOCKING (seasonal patterns) ===")
            for s in stocking:
                loc = s.get('location') or s.get('region', '')
                sp = s.get('species') or ', '.join(s.get('species_list', []))
                size = s.get('size', '')
                lines.append(f"🐟 {s.get('river','?')} @ {loc}: {sp} {size}".rstrip())

        if include_weather:
            weather = live_data.get("_weather", {})
            if weather:
                lines.append("\n=== WEATHER BY FISHING ZONE ===")
                for zone, w in weather.items():
                    if isinstance(w, dict) and not w.get("error"):
                        lines.append(
                            f"📍 {zone}: {w.get('temp_f', '?')}°F, {w.get('short_forecast', 'Unknown')}, "
                            f"Wind: {w.get('wind_speed', '?')}, Precip: {w.get('precip_chance', 0)}%"
                        )

        if include_passage:
            passage = live_data.get("_passage", {})
            if passage:
                lines.append("\n=== BONNEVILLE DAM FISH PASSAGE (recent) ===")
                for species, count in passage.items():
                    lines.append(f"🐟 {species}: {count:,} adults/day (daily avg)")

        try:
            from oregon_gov_data import fetch_ndbc_buoys
            buoys = fetch_ndbc_buoys()
            if buoys:
                lines.append("\n=== NOAA COASTAL BUOYS ===")
                for name, b in list(buoys.items())[:3]:
                    if not b.get("error"):
                        sst = f"{b['sst_f']:.1f}°F" if b.get("sst_f") else "N/A"
                        waves = f"{b['wave_height_ft']:.1f} ft" if b.get("wave_height_ft") else "N/A"
                        lines.append(f"📡 {name}: SST {sst}, Waves {waves}, Wind {b.get('wind_speed_kts','?')} kts {b.get('wind_dir_str','')}")
        except Exception as e:
            lines.append(f"\n[Coastal data unavailable: {e}]")

        turbidity_rivers = []
        for river_name, data in live_data.items():
            if isinstance(data, dict) and data.get("turbidity_fnu") is not None:
                fnu = data["turbidity_fnu"]
                clarity = data.get("clarity", {})
                turbidity_rivers.append(f"{river_name}: {fnu:.1f} FNU — {clarity.get('label','?')} | {clarity.get('fishing','')}")
        if turbidity_rivers:
            lines.append("\n=== USGS WATER CLARITY (Turbidity FNU) ===")
            lines.extend(turbidity_rivers)

        stage_rivers = []
        for river_name, data in live_data.items():
            if isinstance(data, dict) and data.get("stage_ft") is not None:
                stage_rivers.append(f"{river_name}: {data['stage_ft']:.2f} ft gage height")
        if stage_rivers:
            lines.append("\n=== USGS GAGE HEIGHT (Stage in Feet) ===")
            lines.extend(stage_rivers)

        return "\n".join(lines)

    elif tool_name == "update_wiki":
        return json.dumps({
            "proposed": True,
            "entry_type": args.get("entry_type"),
            "river": args.get("river"),
            "title": args.get("title"),
            "content": args.get("content"),
            "tags": args.get("tags", []),
            "confidence": args.get("confidence", "personal"),
            "requires_confirmation": args.get("requires_confirmation", True),
        })

    elif tool_name == "get_hatchery_info":
        from hatcheries import OREGON_HATCHERIES
        river_f = (args.get("river") or "").lower()
        species_f = (args.get("species") or "").lower()
        region_f = (args.get("region") or "").lower()
        results = []
        for h in OREGON_HATCHERIES:
            if river_f and river_f not in h.get("river_system", "").lower():
                continue
            if species_f and not any(species_f in s.lower() for s in h.get("species", [])):
                continue
            if region_f and region_f not in h.get("region", "").lower():
                continue
            results.append(
                f"🏭 {h['name']} ({h['region']}): {', '.join(h['species'])} | "
                f"River: {h['river_system']} | {h.get('notes', '')}"
            )
        return "\n".join(results) if results else "No hatcheries found matching criteria."

    elif tool_name == "web_search":
        return _execute_web_search(args)

    elif tool_name == "get_snowpack":
        return _execute_snowpack(args)

    elif tool_name == "get_drought":
        return _execute_drought(args)

    elif tool_name == "get_air_quality":
        return _execute_air_quality(args)

    elif tool_name == "get_marine_forecast":
        return _execute_marine_forecast(args)

    elif tool_name == "get_wildlife_sightings":
        return _execute_wildlife(args)

    elif tool_name == "get_dam_passage":
        return _execute_dam_passage(args)

    elif tool_name == "get_fishing_reports":
        return _execute_fishing_reports(args)

    return f"Unknown tool: {tool_name}"


def _show_tool_status(tool_name: str, args: dict):
    if st is None:
        return
    icons = {
        "query_wiki": "📚",
        "get_live_data": "📡",
        "update_wiki": "✏️",
        "get_hatchery_info": "🏭",
        "web_search": "🔍",
        "get_snowpack": "❄️",
        "get_drought": "🌵",
        "get_air_quality": "💨",
        "get_marine_forecast": "🌊",
        "get_wildlife_sightings": "🐟",
        "get_dam_passage": "🏗️",
        "get_fishing_reports": "📰",
    }
    labels = {
        "query_wiki": "Reading your Wiki",
        "get_live_data": "Fetching live river & ocean data",
        "update_wiki": "Preparing Wiki update",
        "get_hatchery_info": "Looking up hatcheries",
        "web_search": f"Searching: {args.get('query', '')[:60]}",
        "get_snowpack": f"Checking snowpack",
        "get_drought": f"Checking drought conditions",
        "get_air_quality": f"Checking air quality",
        "get_marine_forecast": f"Fetching marine forecast",
        "get_wildlife_sightings": f"Checking recent wildlife sightings",
        "get_dam_passage": f"Fetching dam fish counts",
        "get_fishing_reports": f"Searching fishing reports",
    }
    icon = icons.get(tool_name, "⚙️")
    label = labels.get(tool_name, tool_name)
    try:
        st.markdown(
            f'<div style="display:inline-block; background:#1a2a3a; border:1px solid #2a4a6a; '
            f'border-radius:20px; padding:3px 10px; font-size:11px; color:#6baed6; margin:2px 0;">'
            f'{icon} {label}…</div>',
            unsafe_allow_html=True,
        )
    except Exception:
        pass


def _execute_web_search(args: dict) -> str:
    query = args.get("query", "").strip()
    if not query:
        return "No search query provided."

    num_results = min(max(int(args.get("num_results", 5)), 2), 8)
    context = args.get("fishing_context", "general")

    fishing_keywords = ["fishing", "fish", "hatch", "closure", "ODFW", "river", "stream",
                        "steelhead", "salmon", "trout", "fly", "tenkara", "angling"]
    if not any(kw.lower() in query.lower() for kw in fishing_keywords):
        query = f"Oregon fishing {query}"

    try:
        from web_tools import tinyfish_search
        result = tinyfish_search(query, max_results=num_results)
        if result.get("error"):
            return f"Web search error: {result.get('error')}"

        data = result.get("data")
        if not data:
            return f"No results found for: '{query}'"

        results_list = data if isinstance(data, list) else data.get("results", [])
        if not results_list:
            return f"No results found for: '{query}'"

        lines = [f"Web search: **{query}**", f"Found {len(results_list)} results:"]
        for i, r in enumerate(results_list, 1):
            if isinstance(r, dict):
                title = r.get("title", r.get("snippet", "No title"))[:150]
                url = r.get("url", r.get("link", ""))
                snippet = r.get("snippet", r.get("body", ""))[:300]
                lines.append(f"**{i}. {title}**")
                if url:
                    lines.append(f"   {url}")
                if snippet:
                    lines.append(f"   {snippet}")
                lines.append("")

        lines.append(f"_Search via TinyFish · {context} context_")
        return "\n".join(lines)

    except Exception as e:
        return f"Web search error: {str(e)[:120]}"


def _execute_snowpack(args: dict) -> str:
    basin_filter = (args.get("basin") or "").lower()
    try:
        from snowpack_fetcher import fetch_snotel_summary
        summary = fetch_snotel_summary()
        lines = ["=== OREGON SNOTEL SNOWPACK (SWE) ==="]
        for basin, data in summary.get("basins", {}).items():
            if basin_filter and basin_filter not in basin.lower():
                continue
            swe = data.get("current_swe_in", data.get("swe_inches", 0))
            peak = data.get("peak_swe_in", 0)
            pct = data.get("pct_of_peak", 0)
            impact = data.get("fishing_impact", {}).get("label", "")
            lines.append(f"❄️ {basin}: {swe:.1f}\" SWE (peak was {peak:.1f}\", {pct:.0f}%) — {impact}")
        if not summary.get("basins"):
            for station, data in summary.get("stations", {}).items():
                if basin_filter and basin_filter not in station.lower():
                    continue
                swe = data.get("swe_inches", 0)
                elev = data.get("elevation_ft", 0)
                lines.append(f"❄️ {station} ({elev}ft): {swe:.1f}\" SWE | {data.get('note', '')}")
        return "\n".join(lines)
    except Exception as e:
        return f"Snowpack error: {e}"


def _execute_drought(args: dict) -> str:
    region_filter = (args.get("region") or "").lower()
    try:
        from drought_fetcher import fetch_drought_by_region
        regions = fetch_drought_by_region()
        lines = ["=== US DROUGHT MONITOR — OREGON FISHING ==="]
        for region, data in regions.items():
            if region_filter and region_filter not in region.lower():
                continue
            label = data.get("label", {}).get("label", "Unknown")
            impact = data.get("fishing_impact", {})
            rivers_list = []
            for county, cd in data.get("counties", {}).items():
                rivers_list.append(f"{county}: {cd.get('label',{}).get('label','?')}")
            lines.append(f"🌵 {region}: {label} — {impact.get('label','')}")
            lines.append(f"   {impact.get('notes','')}")
            lines.append(f"   Counties: {', '.join(rivers_list[:3])}")
        return "\n".join(lines)
    except Exception as e:
        return f"Drought error: {e}"


def _execute_air_quality(args: dict) -> str:
    zone_filter = (args.get("zone") or "").lower()
    try:
        from air_quality_fetcher import get_fishing_air_quality_summary
        summary = get_fishing_air_quality_summary()
        lines = ["=== OREGON AIR QUALITY (AQI) — FISHING IMPACT ==="]
        for item in summary:
            if zone_filter and zone_filter not in item["zone"].lower():
                continue
            est_mark = "⚠️ ESTIMATED " if item.get("estimated") else ""
            lines.append(f"💨 {item['zone']}: {est_mark}AQI {item.get('aqi','?')} — {item['status']}")
            lines.append(f"   {item['fishing_advice']}")
            lines.append(f"   Rivers: {', '.join(item.get('rivers', []))}")
        return "\n".join(lines)
    except Exception as e:
        return f"Air quality error: {e}"


def _execute_marine_forecast(args: dict) -> str:
    zone_filter = (args.get("zone") or "").lower()
    try:
        from weather_fetchers import fetch_nws_marine
        marine = fetch_nws_marine()
        lines = ["=== OREGON COASTAL MARINE FORECASTS ==="]
        for zone, data in marine.items():
            if zone_filter and zone_filter not in zone.lower():
                continue
            if data.get("error"):
                lines.append(f"🌊 {zone}: Error — {data['error'][:80]}")
                continue
            bar = data.get("bar_safety", {})
            boat = data.get("boat_rating", {})
            lines.append(f"🌊 {zone}: {data.get('temp_f','?')}°F, {data.get('short_forecast','Unknown')}")
            lines.append(f"   Wind: {data.get('wind_speed','?')} {data.get('wind_dir','')}")
            lines.append(f"   Bar Safety: {bar.get('label','?')} — {bar.get('notes','')}")
            lines.append(f"   Boating: {boat.get('label','?')}")
            lines.append(f"   Rivers: {', '.join(data.get('rivers',[]))}")
        return "\n".join(lines)
    except Exception as e:
        return f"Marine forecast error: {e}"


def _execute_wildlife(args: dict) -> str:
    species_type = args.get("species_type", "all")
    species_filter = (args.get("species") or "").lower()
    try:
        from inaturalist_fetcher import fetch_inaturalist_summary, fetch_recent_fish_obs, fetch_aquatic_insect_obs
        lines = ["=== iNATURALIST RECENT OBSERVATIONS — OREGON ==="]

        fish_data = {}
        if species_type in ("fish", "all"):
            fish_data = fetch_recent_fish_obs(days_back=7)
        insect_data = {}
        if species_type in ("insects", "all"):
            insect_data = fetch_aquatic_insect_obs(days_back=14)

        if fish_data:
            lines.append("🐟 RECENT FISH OBSERVATIONS (7 days):")
            for name, obs in fish_data.items():
                if species_filter and species_filter not in name.lower():
                    continue
                results = obs.get("results", [])
                if results:
                    locations = set(r.get("location", "").replace(", Oregon, USA", "").replace(", OR, USA", "")
                                    for r in results[:5] if r.get("location"))
                    lines.append(f"  {name}: {len(results)} obs | {', '.join(sorted(locations))}")

        if insect_data:
            lines.append("\n🪰 RECENT AQUATIC INSECT OBSERVATIONS (14 days):")
            for name, obs in insect_data.items():
                if species_filter and species_filter not in name.lower():
                    continue
                results = obs.get("results", [])
                if results:
                    locations = set(r.get("location", "").replace(", Oregon, USA", "").replace(", OR, USA", "")
                                    for r in results[:5] if r.get("location"))
                    lines.append(f"  {name}: {len(results)} obs | {', '.join(sorted(locations))}")

        if not fish_data and not insect_data:
            lines.append("No recent observations found.")
        return "\n".join(lines)
    except Exception as e:
        return f"Wildlife sightings error: {e}"


def _execute_dam_passage(args: dict) -> str:
    dam_filter = (args.get("dam") or "").lower()
    try:
        from fish_passage import fetch_all_dams_passage
        all_dams = fetch_all_dams_passage()
        lines = ["=== COLUMBIA RIVER DAM FISH PASSAGE (Recent) ==="]
        for dam, species_data in all_dams.items():
            if dam_filter and dam_filter not in dam.lower() and dam_filter != "all":
                continue
            lines.append(f"🐟 {dam}:")
            for species, data in species_data.items():
                if isinstance(data, dict):
                    rec = data.get("recent", "?")
                    note = data.get("note", "")
                    lines.append(f"  {species}: {rec:,}/day — {note}")
        return "\n".join(lines)
    except Exception as e:
        return f"Dam passage error: {e}"


def _execute_fishing_reports(args: dict) -> str:
    river = args.get("river")
    species = args.get("species")
    include_reddit = args.get("include_reddit", True)
    try:
        from web_tools import extract_relevant_osint, fetch_reddit_multisub
        lines = []
        query_parts = []
        if river:
            query_parts.append(river)
        if species:
            query_parts.append(species)
        if not query_parts:
            query_parts.append("Oregon fishing")

        query = " ".join(query_parts)
        osint_result = extract_relevant_osint(query)

        if osint_result and osint_result != "No OSINT data found for this query.":
            lines.append(osint_result)

        if include_reddit:
            posts = fetch_reddit_multisub()
            if posts:
                lines.append("\n**Reddit Fishing Community:**")
                for p in posts[:8]:
                    lines.append(f"r/{p.get('source_sub','?')} | {p['title'][:120]} | {p['score']} pts, {p['num_comments']} comments | u/{p['author']}")

        return "\n".join(lines) if lines else "No recent OSINT fishing reports found."
    except Exception as e:
        return f"Fishing reports error: {e}"


def chat_with_buddy(
    user_message: str,
    conversation_history: list,
    live_data: dict,
    db_module,
    model_key: str = "⚡ DeepSeek V4 Flash",
) -> tuple[str, list]:
    client = get_client()
    model = MODELS.get(model_key, FREE_FALLBACK)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(conversation_history[-14:])
    messages.append({"role": "user", "content": user_message})

    pending_wiki_proposals = []
    max_iterations = 6

    try:
        for _ in range(max_iterations):
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                max_tokens=1200,
            )
            choice = response.choices[0]
            msg = choice.message

            if choice.finish_reason == "tool_calls" and msg.tool_calls:
                messages.append({
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                        for tc in msg.tool_calls
                    ],
                })
                for tc in msg.tool_calls:
                    args = json.loads(tc.function.arguments)
                    # Show a visual status pill for each tool call
                    _show_tool_status(tc.function.name, args)
                    result = execute_tool(tc.function.name, args, live_data, db_module)
                    if tc.function.name == "update_wiki":
                        parsed = json.loads(result)
                        if parsed.get("proposed"):
                            pending_wiki_proposals.append(parsed)
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
            else:
                return msg.content or "No response generated.", pending_wiki_proposals

    except PermissionDeniedError:
        if model != FREE_FALLBACK:
            try:
                messages[-1]["content"] = user_message
                resp2 = client.chat.completions.create(
                    model=FREE_FALLBACK,
                    messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_message}],
                    max_tokens=800,
                )
                return resp2.choices[0].message.content + f"\n\n*(Fell back to free model — {model} requires credits)*", []
            except Exception as e2:
                return f"⚠️ AI unavailable: {e2}", []
        return "⚠️ The selected model requires OpenRouter credits. Switch to a 'Free' model in the dropdown.", []

    except RateLimitError:
        return "⚠️ Rate limit hit. Wait 30 seconds and try again, or switch to a different free model.", []

    except APIStatusError as e:
        return f"⚠️ OpenRouter API error ({e.status_code}): {e.message[:200]}", []

    except Exception as e:
        return f"⚠️ The Buddy stumbled: {str(e)[:300]}", []

    return "I got turned around in the current. Could you rephrase that?", pending_wiki_proposals
