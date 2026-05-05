import os
import json
import streamlit as st
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

MODELS = {
    "Auto (Free)": "openrouter/auto",
    "Fast (Mistral)": "mistralai/mistral-7b-instruct",
    "Pro (Claude 3.5)": "anthropic/claude-3.5-sonnet",
    "Smart (Gemini Flash)": "google/gemini-flash-1.5",
}

SYSTEM_PROMPT = """You are a fun, witty, highly experienced Oregon fly and tenkara fishing buddy named "The Buddy". 

You have access to live USGS flow data, ODFW stocking info, and a personal Karpathy Wiki containing user preferences, fishing logs, and spot knowledge. Always use the Wiki and live data before answering.

Give practical, safe, concise advice. Prefer actionable fishing guidance over raw data. Use light humor and occasional fishing puns. If the user shares useful new fishing info, propose a structured Wiki update.

Label the basis of every recommendation:
- 🌊 Live: USGS/ODFW current data
- 📓 Logged: user's own history  
- 📚 Wiki: private saved knowledge
- 💡 Inferred: AI pattern recognition
- ⚠️ Unverified: user/forum/imported note

Available tools:
- query_wiki: search preferences, logs, Wiki entries
- get_live_data: get current USGS flows and ODFW stocking
- update_wiki: propose adding or updating a Wiki entry (requires user confirmation for preferences/secret spots)

Always use tools before answering. Think like a local expert who knows the rivers personally."""


def get_client():
    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=OPENROUTER_API_KEY,
    )


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_wiki",
            "description": "Search the user's Karpathy Wiki including preferences, fishing logs, and spot notes. Always call this before answering fishing questions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query for the wiki"},
                    "river": {"type": "string", "description": "Optional: specific river name to filter"},
                    "include_logs": {"type": "boolean", "description": "Whether to include fishing logs"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_live_data",
            "description": "Get current USGS river flow data and ODFW stocking schedule for Oregon rivers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "river": {"type": "string", "description": "Optional: specific river name. If empty, returns all rivers."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_wiki",
            "description": "Propose adding or updating a Karpathy Wiki entry. The user must confirm before it is saved. Use for trip logs, spot notes, and learned patterns.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entry_type": {"type": "string", "enum": ["spot", "log", "pattern", "preference_note"], "description": "Type of wiki entry"},
                    "river": {"type": "string", "description": "River name this entry is about"},
                    "title": {"type": "string", "description": "Short descriptive title"},
                    "content": {"type": "string", "description": "Full wiki entry content"},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags like ['tenkara', 'spring', 'dry-fly']"},
                    "confidence": {"type": "string", "enum": ["personal", "verified", "inferred", "unverified"]},
                    "requires_confirmation": {"type": "boolean", "description": "True if this is a preference change, secret spot, or potentially sensitive"},
                },
                "required": ["entry_type", "title", "content"],
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
            results.append(f"USER PREFERENCES: Home base={prefs.get('home_base')}, "
                           f"Favorite rivers={prefs.get('favorite_rivers')}, "
                           f"Styles={prefs.get('preferred_styles')}, "
                           f"Max drive={prefs.get('max_drive_minutes')}min, "
                           f"C&R={prefs.get('catch_and_release')}")
        wiki_entries = db_module.search_wiki(query)
        if wiki_entries:
            for e in wiki_entries:
                results.append(f"WIKI [{e['entry_type'].upper()}] {e['title']} (river={e['river']}, "
                               f"confidence={e['confidence']}, source={e['source']}): {e['content'][:300]}")
        if include_logs:
            if river:
                logs = db_module.get_recent_logs_for_river(river, limit=5)
            else:
                logs = db_module.get_fishing_logs(limit=10)
            for log in logs:
                results.append(f"FISHING LOG {log['trip_date']}: {log['river']} at {log['spot']} — "
                               f"{log['fish_caught']} fish, flies={log['flies']}, "
                               f"conditions={log['conditions']}, notes={log['notes']}")
        return "\n\n".join(results) if results else "No Wiki entries found for this query."

    elif tool_name == "get_live_data":
        river_filter = args.get("river", "").lower()
        if "error" in live_data:
            return f"USGS API error: {live_data['error']}. Data may be stale."
        lines = []
        for river_name, data in live_data.items():
            if river_filter and river_filter not in river_name.lower():
                continue
            if isinstance(data, dict) and "cfs" in data:
                from data_fetchers import get_condition, get_tenkara_score
                cfs = data["cfs"]
                cond = get_condition(river_name, cfs)
                tenkara = get_tenkara_score(river_name, cfs)
                lines.append(f"{river_name}: {cfs} CFS — {cond['label']} — Tenkara: {tenkara} (updated: {data.get('datetime', 'N/A')[:16]})")
        return "\n".join(lines) if lines else "No live flow data available."

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

    return f"Unknown tool: {tool_name}"


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=4))
def chat_with_buddy(
    user_message: str,
    conversation_history: list,
    live_data: dict,
    db_module,
    model_key: str = "Auto (Free)",
) -> tuple[str, list]:
    client = get_client()
    model = MODELS.get(model_key, "openrouter/auto")

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(conversation_history[-12:])
    messages.append({"role": "user", "content": user_message})

    pending_wiki_proposals = []
    max_iterations = 6

    for _ in range(max_iterations):
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            max_tokens=1024,
        )
        choice = response.choices[0]
        msg = choice.message

        if choice.finish_reason == "tool_calls" and msg.tool_calls:
            messages.append({"role": "assistant", "content": msg.content or "", "tool_calls": [
                {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls
            ]})
            for tc in msg.tool_calls:
                args = json.loads(tc.function.arguments)
                result = execute_tool(tc.function.name, args, live_data, db_module)
                if tc.function.name == "update_wiki":
                    parsed = json.loads(result)
                    if parsed.get("proposed"):
                        pending_wiki_proposals.append(parsed)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })
        else:
            final_content = msg.content or "I had trouble generating a response. Try again!"
            return final_content, pending_wiki_proposals

    return "I got a bit tangled in my waders. Could you rephrase that?", pending_wiki_proposals
