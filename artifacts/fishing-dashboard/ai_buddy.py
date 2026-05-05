import os
import json
import streamlit as st
from openai import OpenAI, PermissionDeniedError, RateLimitError, APIStatusError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# DuckDuckGo search — free, no API key required
try:
    from ddgs import DDGS as _DDGS
    _SEARCH_LIB = "ddgs"
except ImportError:
    try:
        from duckduckgo_search import DDGS as _DDGS
        _SEARCH_LIB = "duckduckgo_search"
    except ImportError:
        _DDGS = None
        _SEARCH_LIB = None

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

MODELS = {
    # ── Default ──────────────────────────────────────────────────────────────
    "⚡ DeepSeek V4 Flash": "deepseek/deepseek-v4-flash",
    # ── Top Free Models ──────────────────────────────────────────────────────
    "🆓 Gemini 2.5 Flash (Free · 1M ctx)": "google/gemini-2.5-flash-preview:free",
    "🆓 Llama 4 Maverick (Free · 131K ctx)": "meta-llama/llama-4-maverick:free",
    "🆓 Llama 4 Scout (Free · 512K ctx)": "meta-llama/llama-4-scout:free",
    "🆓 Llama 3.3 70B (Free · 128K ctx)": "meta-llama/llama-3.3-70b-instruct:free",
    "🆓 Qwen3 235B MoE (Free · 128K ctx)": "qwen/qwen3-235b-a22b:free",
    "🆓 Qwen3 30B MoE (Free · 128K ctx)": "qwen/qwen3-30b-a3b:free",
    "🆓 DeepSeek R1 Reasoning (Free · 164K ctx)": "deepseek/deepseek-r1:free",
    "🆓 DeepSeek V3 (Free · 64K ctx)": "deepseek/deepseek-chat:free",
    "🆓 Trinity Large Preview (Free · 131K ctx)": "arcee-ai/trinity-large-preview:free",
    "🆓 Mistral Small 3.1 24B (Free · 128K ctx)": "mistralai/mistral-small-3.1-24b-instruct:free",
    "🆓 Gemma 3 27B (Free · 96K ctx)": "google/gemma-3-27b-it:free",
    "🆓 Mistral 7B (Free · 32K ctx)": "mistralai/mistral-7b-instruct:free",
    # ── Premium ──────────────────────────────────────────────────────────────
    "💎 Trinity Large Thinking (Reasoning)": "arcee-ai/trinity-large-thinking",
    "💎 Claude 3.5 Sonnet": "anthropic/claude-3.5-sonnet",
    "💎 Gemini Flash 1.5": "google/gemini-flash-1.5",
}

FREE_FALLBACK = "meta-llama/llama-4-scout:free"

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
                "Search the internet via DuckDuckGo for current fishing reports, hatch reports, ODFW news, "
                "emergency closures, regulation changes, trip reports, river conditions from fishing forums, "
                "or any live information not available from local data. "
                "Use for: fishing reports, hatch activity, regulation updates, closures, forum trip reports, "
                "species run timing news, any question needing current internet data. "
                "Good sources to target: dfw.state.or.us, nwflyfish.com, westfly.com, oregonlive.com, "
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
]


def execute_tool(tool_name: str, args: dict, live_data: dict, db_module) -> str:
    if tool_name == "query_wiki":
        query = args.get("query", "")
        river = args.get("river")
        include_logs = args.get("include_logs", True)
        results = []
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
                cond = get_condition(river_name, cfs)
                tenkara = get_tenkara_score(river_name, cfs)
                temp_str = ""
                if data.get("temp_f"):
                    temp_str = f", Temp: {data['temp_f']:.1f}°F"
                source = "📡 USGS live" if data.get("source") == "usgs_live" else "💧 spring-fed est."
                info = RIVER_INFO.get(river_name, {})
                species = ", ".join(info.get("species", []))
                lines.append(
                    f"{river_name}: {cfs:.0f} CFS — {cond['label']} — Tenkara: {tenkara}{temp_str} | "
                    f"Species: {species} | {source}"
                )

        stocking = live_data.get("_stocking", [])
        if stocking:
            lines.append("\n=== ODFW STOCKING (seasonal patterns) ===")
            for s in stocking:
                lines.append(f"🐟 {s['river']} @ {s['location']}: {s['species']} {s['size']}")

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
            from oregon_gov_data import get_coastal_summary
            lines.append("\n" + get_coastal_summary())
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

    return f"Unknown tool: {tool_name}"


def _show_tool_status(tool_name: str, args: dict):
    """Render a subtle inline status pill showing which tool the AI is calling."""
    icons = {
        "query_wiki": "📚",
        "get_live_data": "📡",
        "update_wiki": "✏️",
        "get_hatchery_info": "🏭",
        "web_search": "🔍",
    }
    labels = {
        "query_wiki": "Reading your Wiki",
        "get_live_data": "Fetching live river & ocean data",
        "update_wiki": "Preparing Wiki update",
        "get_hatchery_info": "Looking up hatcheries",
        "web_search": f"Searching: {args.get('query', '')[:60]}",
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
    """Run a DuckDuckGo search and return formatted results for the AI."""
    if _DDGS is None:
        return "❌ Web search unavailable: ddgs library not installed."

    query = args.get("query", "").strip()
    if not query:
        return "❌ No search query provided."

    num_results = min(max(int(args.get("num_results", 5)), 2), 8)
    context = args.get("fishing_context", "general")

    # Automatically add Oregon fishing context to queries if not already present
    fishing_keywords = ["fishing", "fish", "hatch", "closure", "ODFW", "river", "stream",
                        "steelhead", "salmon", "trout", "fly", "tenkara", "angling"]
    if not any(kw.lower() in query.lower() for kw in fishing_keywords):
        query = f"Oregon fishing {query}"

    try:
        with _DDGS() as ddg:
            raw_results = list(ddg.text(query, max_results=num_results))

        if not raw_results:
            return f"🔍 No results found for: '{query}'"

        lines = [f"🔍 Web search: **{query}**", f"Found {len(raw_results)} results:\n"]
        for i, r in enumerate(raw_results, 1):
            title = r.get("title", "No title")
            url = r.get("href", "")
            body = r.get("body", "")[:300].strip()
            # Truncate body at sentence boundary for cleaner output
            if len(body) == 300 and ". " in body[200:]:
                body = body[:200 + body[200:].rfind(". ") + 1]
            lines.append(f"**{i}. {title}**")
            lines.append(f"   🔗 {url}")
            lines.append(f"   {body}")
            lines.append("")

        lines.append(f"_Search performed via DuckDuckGo · {context} context_")
        return "\n".join(lines)

    except Exception as e:
        err = str(e)[:120]
        return (
            f"⚠️ Web search encountered an issue: {err}\n"
            f"This may be a temporary rate limit. Try rephrasing the query or retry in a moment."
        )


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
