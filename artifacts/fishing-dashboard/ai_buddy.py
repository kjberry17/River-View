import os
import json
import logging
from openai import OpenAI, PermissionDeniedError, RateLimitError, APIStatusError, APITimeoutError, APIConnectionError, BadRequestError

# Structured logger for ai_buddy — no sensitive data (API keys, user messages, full tool payloads)
logger = logging.getLogger("ai_buddy")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S"
    ))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)

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

MODEL_FALLBACK_CHAIN = [
    "deepseek/deepseek-v4-flash:free",
    "minimax/minimax-m2.5:free",
    "z-ai/glm-4.5-air:free",
]

MODELS = {
    "⚡ DeepSeek V4 Flash": MODEL_FALLBACK_CHAIN[0],
    "⚡ DeepSeek V4 Flash (Free)": MODEL_FALLBACK_CHAIN[0],
}

FREE_FALLBACK = MODEL_FALLBACK_CHAIN[0]

SYSTEM_PROMPT = """You are a deeply knowledgeable, seasoned Oregon fly and tenkara fishing guide named "The Fisher".

You have access to:
- Live USGS river data: flow (CFS), water temperature, gage height (feet), and turbidity/clarity (FNU)
- NOAA NDBC ocean buoys: sea surface temp, wave height & period, wind speed/direction
- NOAA tide stations: real-time water level, rising/falling trend, next high/low predictions
- ODFW stocking info, NWS weather forecasts, Bonneville fish passage counts
- Oregon hatchery and lake database
- Karpathy Wiki: user's personal preferences, fishing logs, and spot notes
- **WKCC Oregon Gauge Network**: 176 river gauges statewide with CFS, stage height (ft), water temp, flow trend (↑↓), whitewater class, and status (Low/Okay/Good/High/Flood) — covers tributaries and creeks not in the USGS 33. Available via get_live_data.
- **Dam-aware gauges**: Many Oregon rivers carry gauges both above and below dams. Each gauge in get_live_data is tagged with `hydrology_type`: `"natural"` (above dam — reflects snowmelt, rainfall, spring inputs) or `"controlled"` (below dam — reflects Army Corps of Engineers releases, independent of natural conditions). Also tagged with `dam_position` ("above"/"below") and `dam_name`. When multiple gauges exist on a dam-split river, always identify which gauge applies to the user's target water. If above-dam conditions look good but below-dam releases are cold or blown out (or vice versa), proactively call that out and suggest fishing the better reach. Never assume a below-dam reading represents the natural river — it doesn't.
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

Always use tools before answering fishing questions. Think like a local expert who knows Oregon intimately.

IMPORTANT — CITATIONS: When you use web_search or get_fishing_reports results, cite your sources inline using [1], [2] etc. Place the citation marker immediately after the fact you're citing. I'll render them as clickable footnotes automatically. Example: "The salmonfly hatch is peaking right now [1]." Never cite your own internal knowledge or live data from USGS/NWS/NOAA — only cite web search results.

FORMAT LIKE A PREMIUM FISHING REPORT: Use ## headings for sections (e.g. "## 🌊 River Conditions"), tables for comparing multiple rivers or conditions (with emoji labels in headers), bullet lists for gear recommendations and technique tips, blockquotes for key takeaways and warnings. Use emoji throughout for visual scanning (🌊 flow, 🌡️ temp, 🪲 hatches, 🎣 technique, ⚠️ warnings). Make every response publication-ready — the user can export it as a markdown report."""


def get_client():
    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=OPENROUTER_API_KEY,
        default_headers={"HTTP-Referer": "https://oregon-fishing-dashboard.replit.app"},
    )


def _model_candidates(model_key: str) -> list[str]:
    selected_model = MODELS.get(model_key, FREE_FALLBACK)
    return [model for model in [selected_model, *MODEL_FALLBACK_CHAIN] if model]


def _dedupe_models(models: list[str]) -> list[str]:
    seen = set()
    deduped = []
    for model in models:
        if model not in seen:
            deduped.append(model)
            seen.add(model)
    return deduped


def _create_completion_with_fallback(client, model_candidates: list[str], **kwargs):
    candidates = _dedupe_models(model_candidates)
    if not candidates:
        raise ValueError("No model candidates provided for completion")
    failed_models = set()
    last_error = None
    attempt = 0
    while len(failed_models) < len(candidates):
        # Find next untried model
        model = None
        for candidate in candidates:
            if candidate not in failed_models:
                model = candidate
                break
        if model is None:
            break
        attempt += 1
        try:
            result = client.chat.completions.create(model=model, timeout=120, **kwargs)
            logger.info("model_attempt model=%s attempt=%d status=success", model, attempt)
            return result, model
        except (PermissionDeniedError, RateLimitError, APIStatusError, APITimeoutError, APIConnectionError, BadRequestError) as err:
            last_error = err
            failed_models.add(model)
            logger.warning("model_attempt model=%s attempt=%d status=failure error=%s", model, attempt, type(err).__name__)
    if last_error is None:
        raise ValueError("All models failed without producing an error")
    raise last_error


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
                "Search the internet via DuckDuckGo for current fishing reports, hatch reports, ODFW news, "
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
                        "description": "Number of results to return (2–5). Default 5.",
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
    # Log tool call start — args are truncated to avoid PII
    logger.info("tool_call tool=%s args_keys=%s", tool_name, list(args.keys()))
    try:
        return _execute_tool_impl(tool_name, args, live_data, db_module)
    except Exception as e:
        logger.error("tool_call tool=%s status=error error=%s", tool_name, type(e).__name__)
        return f"Tool '{tool_name}' encountered an error: {e}", []


def _execute_tool_impl(tool_name: str, args: dict, live_data: dict, db_module) -> str:
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
        logger.info("tool_call tool=%s status=success result_chars=%d", tool_name, len("\n\n".join(results) if results else "No Wiki entries found."))
        return "\n\n".join(results) if results else "No Wiki entries found.", []

    elif tool_name == "get_live_data":
        river_filter = (args.get("river") or "").lower()
        include_weather = args.get("include_weather", True)
        include_passage = args.get("include_passage", False)

        lines = ["=== LIVE RIVER DATA (USGS + WKCC) ==="]
        from data_fetchers import get_condition, get_tenkara_score, RIVER_INFO
        for river_name, data in live_data.items():
            if river_name in ("error", "_stocking", "_weather", "_passage", "_wkcc_gauges"):
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
                if data.get("source") == "usgs_live":
                    source = "📡 USGS live"
                elif data.get("source") == "wkcc_live":
                    source = "📡 WKCC live"
                else:
                    source = "💧 spring-fed est."
                info = RIVER_INFO.get(river_name, {})
                species = ", ".join(info.get("species", []))
                lines.append(
                    f"{river_name}: {cfs_str} — {cond['label']} — Tenkara: {tenkara}{temp_str} | "
                    f"Species: {species} | {source}"
                )
                # Surface dam-split gauges so the AI can reason about them
                gauges = data.get("gauges", [])
                dam_gauges = [g for g in gauges if g.get("dam_position")]
                if dam_gauges:
                    for g in dam_gauges:
                        pos = "▲ ABOVE" if g["dam_position"] == "above" else "▼ BELOW"
                        htype = "natural" if g["hydrology_type"] == "natural" else "controlled/Army Corps"
                        g_cfs = f"{g['flow_cfs']:.0f} CFS" if g.get("flow_cfs") is not None else "—"
                        g_temp = f", {g['temp_f']:.1f}°F" if g.get("temp_f") is not None else ""
                        dam_label = g.get("dam_name") or "dam"
                        lines.append(
                            f"  └ {pos} {dam_label} ({htype}): {g_cfs}{g_temp} — {g.get('name', g.get('location',''))}"
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

        wkcc_gauges = live_data.get("_wkcc_gauges", [])
        if wkcc_gauges:
            filtered = [g for g in wkcc_gauges if not river_filter or river_filter in g.get("name", "").lower() or river_filter in g.get("location", "").lower() or river_filter in g.get("drainage", "").lower()]
            if filtered:
                lines.append(f"\n=== WKCC GAUGE NETWORK ({len(wkcc_gauges)} stations statewide) ===")
                for g in filtered:
                    parts = [f"{g['name']} @ {g['location']}"]
                    if g.get("flow_cfs") is not None:
                        trend = "↑" if g.get("flow_trend") == "up" else ("↓" if g.get("flow_trend") == "down" else "")
                        parts.append(f"{g['flow_cfs']:,.0f} CFS{trend}")
                    if g.get("height_ft") is not None:
                        parts.append(f"{g['height_ft']:.2f} ft stage")
                    if g.get("temp_f") is not None:
                        parts.append(f"{g['temp_f']:.1f}°F")
                    if g.get("status"):
                        parts.append(f"[{g['status']}]")
                    if g.get("whitewater_class"):
                        parts.append(f"Class {g['whitewater_class']}")
                    if g.get("drainage"):
                        parts.append(f"({g['drainage']} basin)")
                    lines.append("  " + " | ".join(parts))

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

        result_str = "\n".join(lines)
        logger.info("tool_call tool=%s status=success result_chars=%d", tool_name, len(result_str))
        return result_str, []

    elif tool_name == "update_wiki":
        result_json = json.dumps({
            "proposed": True,
            "entry_type": args.get("entry_type"),
            "river": args.get("river"),
            "title": args.get("title"),
            "content": args.get("content"),
            "tags": args.get("tags", []),
            "confidence": args.get("confidence", "personal"),
            "requires_confirmation": args.get("requires_confirmation", True),
        })
        logger.info("tool_call tool=%s status=success result_chars=%d", tool_name, len(result_json))
        return result_json, []

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
        result = "\n".join(results) if results else "No hatcheries found matching criteria."
        logger.info("tool_call tool=%s status=success result_chars=%d", tool_name, len(result))
        return result, []

    elif tool_name == "web_search":
        result, sources = _execute_web_search(args)
        logger.info("tool_call tool=%s status=success result_chars=%d", tool_name, len(result))
        return result, sources

    elif tool_name == "get_snowpack":
        result = _execute_snowpack(args)
        logger.info("tool_call tool=%s status=success result_chars=%d", tool_name, len(result))
        return result, []

    elif tool_name == "get_drought":
        result = _execute_drought(args)
        logger.info("tool_call tool=%s status=success result_chars=%d", tool_name, len(result))
        return result, []

    elif tool_name == "get_air_quality":
        result = _execute_air_quality(args)
        logger.info("tool_call tool=%s status=success result_chars=%d", tool_name, len(result))
        return result, []

    elif tool_name == "get_marine_forecast":
        result = _execute_marine_forecast(args)
        logger.info("tool_call tool=%s status=success result_chars=%d", tool_name, len(result))
        return result, []

    elif tool_name == "get_wildlife_sightings":
        result = _execute_wildlife(args)
        logger.info("tool_call tool=%s status=success result_chars=%d", tool_name, len(result))
        return result, []

    elif tool_name == "get_dam_passage":
        result = _execute_dam_passage(args)
        logger.info("tool_call tool=%s status=success result_chars=%d", tool_name, len(result))
        return result, []

    elif tool_name == "get_fishing_reports":
        result, sources = _execute_fishing_reports(args)
        logger.info("tool_call tool=%s status=success result_chars=%d", tool_name, len(result))
        return result, sources

    return f"Unknown tool: {tool_name}", []


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


def _execute_web_search(args: dict) -> tuple:
    query = args.get("query", "").strip()
    if not query:
        return "No search query provided.", []

    num_results = min(max(int(args.get("num_results", 5)), 2), 5)
    context = args.get("fishing_context", "general")

    fishing_keywords = ["fishing", "fish", "hatch", "closure", "ODFW", "river", "stream",
                        "steelhead", "salmon", "trout", "fly", "tenkara", "angling"]
    if not any(kw.lower() in query.lower() for kw in fishing_keywords):
        query = f"Oregon fishing {query}"

    sources = []
    try:
        from web_tools import ddg_search
        result = ddg_search(query, max_results=num_results)
        if result.get("error"):
            return f"Web search error: {result.get('error')}", []

        results_list = result.get("results", [])
        if not results_list:
            return f"No results found for: '{query}'", []

        lines = [f"Web search: **{query}**", f"Found {len(results_list)} results:"]
        for i, r in enumerate(results_list, 1):
            if isinstance(r, dict):
                title = r.get("title", "")[:150]
                url = r.get("href", r.get("link", ""))
                snippet = r.get("body", "")[:300]
                lines.append(f"**{i}. {title}**")
                if url:
                    lines.append(f"   {url}")
                if snippet:
                    lines.append(f"   {snippet}")
                lines.append("")
                if title and url:
                    sources.append({"title": title, "url": url})

        lines.append(f"_Search via DuckDuckGo · {context} context_")
        return "\n".join(lines), sources

    except Exception as e:
        return f"Web search error: {str(e)[:120]}", []


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
            swe_str = f"{swe:.1f}" if isinstance(swe, (int, float)) else str(swe)
            peak_str = f"{peak:.1f}" if isinstance(peak, (int, float)) else str(peak)
            pct_str = f"{pct:.0f}" if isinstance(pct, (int, float)) else str(pct)
            lines.append(f"❄️ {basin}: {swe_str}\" SWE (peak was {peak_str}\", {pct_str}%) — {impact}")
        if not summary.get("basins"):
            for station, data in summary.get("stations", {}).items():
                if basin_filter and basin_filter not in station.lower():
                    continue
                swe = data.get("swe_inches", 0)
                elev = data.get("elevation_ft", 0)
                swe_str2 = f"{swe:.1f}" if isinstance(swe, (int, float)) else str(swe)
                elev_str = f"{elev}" if isinstance(elev, (int, float)) else str(elev)
                lines.append(f"❄️ {station} ({elev_str}ft): {swe_str2}\" SWE | {data.get('note', '')}")
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
                    rec_str = f"{rec:,}" if isinstance(rec, (int, float)) else str(rec) if rec else "?"
                    note = data.get("note", "")
                    lines.append(f"  {species}: {rec_str}/day — {note}")
        return "\n".join(lines)
    except Exception as e:
        return f"Dam passage error: {e}"


def _execute_fishing_reports(args: dict) -> tuple:
    river = args.get("river")
    species = args.get("species")
    include_reddit = args.get("include_reddit", True)
    sources = []
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
                    if p.get("permalink"):
                        sources.append({"title": p.get("title", "")[:120], "url": p["permalink"]})

        return ("\n".join(lines) if lines else "No recent OSINT fishing reports found."), sources
    except Exception as e:
        return f"Fishing reports error: {e}", []


def chat_with_buddy(
    user_message: str,
    conversation_history: list,
    live_data: dict,
    db_module,
    model_key: str = "⚡ DeepSeek V4 Flash (Free)",
    session_cache: dict = None,
) -> tuple[str, list]:
    client = get_client()
    model_candidates = _model_candidates(model_key)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(conversation_history[-14:])
    messages.append({"role": "user", "content": user_message})

    pending_wiki_proposals = []
    max_iterations = 6

    try:
        for _ in range(max_iterations):
            response, _model = _create_completion_with_fallback(
                client,
                model_candidates,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                max_tokens=2000,
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
                    # Guard against malformed tool call objects from the model
                    try:
                        tool_name = tc.function.name if tc.function and tc.function.name else "unknown_tool"
                        raw_args = tc.function.arguments if tc.function else "{}"
                        args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
                    except (json.JSONDecodeError, TypeError, AttributeError) as parse_err:
                        result = f"Tool call had malformed arguments: {parse_err}"
                        tool_id = getattr(tc, 'id', 'unknown')
                        messages.append({"role": "tool", "tool_call_id": tool_id, "content": result})
                        continue
                    _show_tool_status(tool_name, args)
                    try:
                        result, _tool_sources = execute_tool(tool_name, args, live_data, db_module)
                    except Exception as tool_err:
                        result = f"Tool '{tool_name}' error: {tool_err}"
                    if tool_name == "update_wiki":
                        try:
                            parsed = json.loads(result)
                            if parsed.get("proposed"):
                                pending_wiki_proposals.append(parsed)
                        except Exception:
                            pass
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
            else:
                logger.info("chat_response path=text_response")
                return msg.content or "No response generated.", pending_wiki_proposals

    except PermissionDeniedError:
        logger.warning("chat_response path=permission_denied")
        return "⚠️ All configured OpenRouter models were denied. Try again in a minute or check OpenRouter model availability.", []

    except RateLimitError:
        logger.warning("chat_response path=rate_limited")
        return "⚠️ All configured OpenRouter fallback models are rate-limited. Wait 30 seconds and try again.", []

    except APIStatusError as e:
        logger.error("chat_response path=api_status_error status_code=%s", e.status_code)
        return f"⚠️ OpenRouter API error after trying all fallback models ({e.status_code}): {e.message[:200]}", []

    except Exception as e:
        logger.error("chat_response path=exception error=%s", type(e).__name__)
        return f"⚠️ The Fisher encountered an issue: {str(e)[:300]}", []

    logger.warning("chat_response path=loop_exhausted")
    return "I got turned around in the current. Could you rephrase that?", pending_wiki_proposals


TOOL_ICONS = {
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

TOOL_LABELS = {
    "query_wiki": "Reading your Wiki",
    "get_live_data": "Fetching live river & ocean data",
    "update_wiki": "Preparing Wiki update",
    "get_hatchery_info": "Looking up hatcheries",
    "web_search": "Searching the web",
    "get_snowpack": "Checking snowpack",
    "get_drought": "Checking drought conditions",
    "get_air_quality": "Checking air quality",
    "get_marine_forecast": "Fetching marine forecast",
    "get_wildlife_sightings": "Checking wildlife sightings",
    "get_dam_passage": "Fetching dam fish counts",
    "get_fishing_reports": "Searching fishing reports",
}


def chat_with_buddy_stream(
    user_message: str,
    conversation_history: list,
    live_data: dict,
    db_module,
    model_key: str = "⚡ DeepSeek V4 Flash (Free)",
    session_cache: dict = None,
):
    client = get_client()
    model_candidates = _model_candidates(model_key)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(conversation_history[-14:])

    # Inject prior web search results from this session so the model can reuse them
    if session_cache:
        prior = session_cache.get("web_searches", [])
        if prior:
            context = "**Web search data already retrieved this session — use this before searching again:**\n"
            for s in prior[-5:]:
                context += f"\n---\nQuery: {s['query']}\n{s['result']}\n"
            messages.append({"role": "user", "content": context})
            messages.append({"role": "assistant", "content": "Understood — I have that search data from our session and will use it."})

    messages.append({"role": "user", "content": user_message})

    pending_wiki_proposals = []
    all_sources = []
    max_iterations = 6
    web_search_count = 0
    MAX_WEB_SEARCHES = 2

    try:
        for iteration in range(max_iterations):
            is_last = iteration == max_iterations - 1
            # Remove web_search from available tools once limit is reached
            active_tools = [t for t in TOOLS if not (web_search_count >= MAX_WEB_SEARCHES and t["function"]["name"] == "web_search")]
            response, _model = _create_completion_with_fallback(
                client,
                model_candidates,
                messages=messages,
                tools=active_tools,
                # Force a text response on the last iteration — no more tool calls
                tool_choice="none" if is_last else "auto",
                max_tokens=2000,
            )
            choice = response.choices[0]
            msg = choice.message

            if choice.finish_reason == "tool_calls" and msg.tool_calls and not is_last:
                messages.append({
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                        for tc in msg.tool_calls
                    ],
                })
                for tc in msg.tool_calls:
                    # Guard against malformed tool call objects from the model
                    try:
                        tool_name = tc.function.name if tc.function and tc.function.name else "unknown_tool"
                        raw_args = tc.function.arguments if tc.function else "{}"
                        args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
                    except (json.JSONDecodeError, TypeError, AttributeError) as parse_err:
                        result = f"Tool call had malformed arguments: {parse_err}"
                        tool_id = getattr(tc, 'id', 'unknown')
                        messages.append({"role": "tool", "tool_call_id": tool_id, "content": result})
                        yield {"type": "tool_start", "tool": "error", "icon": "⚠️", "label": f"Malformed tool call"}
                        yield {"type": "tool_end", "tool": "error", "icon": "⚠️", "label": "Error parsing arguments"}
                        continue
                    tool_label = TOOL_LABELS.get(tool_name, tool_name)
                    tool_icon = TOOL_ICONS.get(tool_name, "⚙️")
                    query_hint = args.get("query", "")[:60] or args.get("river", "")[:60] or ""
                    label = f"{tool_label}{': ' + query_hint if query_hint else ''}"

                    yield {"type": "tool_start", "tool": tool_name, "icon": tool_icon, "label": label}

                    # Hard gate: block web_search beyond the per-turn limit regardless of tool list
                    if tool_name == "web_search" and web_search_count >= MAX_WEB_SEARCHES:
                        result = "Web search limit reached for this response."
                        tool_sources = []
                    else:
                        if tool_name == "web_search":
                            web_search_count += 1
                        try:
                            result, tool_sources = execute_tool(tool_name, args, live_data, db_module)
                        except Exception as tool_err:
                            result = f"Tool '{tool_name}' error: {tool_err}"
                            tool_sources = []

                        # Persist successful web search results to session cache
                        if tool_name == "web_search" and session_cache is not None and not result.startswith("Web search error"):
                            import time as _t
                            session_cache.setdefault("web_searches", []).append({
                                "query": args.get("query", ""),
                                "result": result[:600],
                                "timestamp": _t.time(),
                            })
                            session_cache["web_searches"] = session_cache["web_searches"][-5:]

                    for src in tool_sources:
                        if src not in all_sources:
                            all_sources.append(src)

                    yield {"type": "tool_end", "tool": tool_name, "icon": tool_icon, "label": label}

                    if tool_name == "update_wiki":
                        try:
                            parsed = json.loads(result)
                            if parsed.get("proposed"):
                                pending_wiki_proposals.append(parsed)
                        except Exception:
                            pass
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
            else:
                content = msg.content or "I have the data but had trouble forming a response — please try again."
                logger.info("chat_stream_response path=text_response")
                yield {"type": "response", "content": content}
                yield {"type": "done", "sources": all_sources, "wiki_proposals": pending_wiki_proposals}
                return

        # Safety net: loop exhausted without a text response — force one final call
        fallback, _model = _create_completion_with_fallback(
            client,
            model_candidates,
            messages=messages,
            tool_choice="none",
            max_tokens=2000,
        )
        content = fallback.choices[0].message.content or "I gathered the data but ran out of space to respond. Try asking a more specific question."
        logger.info("chat_stream_response path=fallback_response")
        yield {"type": "response", "content": content}
        yield {"type": "done", "sources": all_sources, "wiki_proposals": pending_wiki_proposals}

    except PermissionDeniedError:
        logger.warning("chat_stream_response path=permission_denied")
        yield {"type": "response", "content": "⚠️ All configured OpenRouter models were denied. Try again in a minute or check OpenRouter model availability."}
        yield {"type": "done", "sources": [], "wiki_proposals": []}

    except RateLimitError:
        logger.warning("chat_stream_response path=rate_limited")
        yield {"type": "response", "content": "⚠️ All configured OpenRouter fallback models are rate-limited. Wait 30 seconds and try again."}
        yield {"type": "done", "sources": [], "wiki_proposals": []}

    except APIStatusError as e:
        logger.error("chat_stream_response path=api_status_error status_code=%s", e.status_code)
        yield {"type": "response", "content": f"⚠️ OpenRouter API error after trying all fallback models ({e.status_code}): {e.message[:200]}"}
        yield {"type": "done", "sources": [], "wiki_proposals": []}

    except Exception as e:
        logger.error("chat_stream_response path=exception error=%s", type(e).__name__)
        yield {"type": "response", "content": f"⚠️ The Fisher encountered an issue: {str(e)[:300]}"}
        yield {"type": "done", "sources": [], "wiki_proposals": []}
