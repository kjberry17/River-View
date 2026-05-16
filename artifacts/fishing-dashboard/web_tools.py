import json
import time
import re
from datetime import datetime, timedelta
from cache_utils import ttl_cache

try:
    from ddgs import DDGS
    _DDG_AVAILABLE = True
except ImportError:
    try:
        from duckduckgo_search import DDGS
        _DDG_AVAILABLE = True
    except ImportError:
        _DDG_AVAILABLE = False
        DDGS = None

DDG_RATE_DELAY = 2.0  # seconds between any DDG queries to avoid rate limiting
DDG_MAX_RESULTS = 5   # hard cap per search — enough signal, avoids context bloat
_ddg_last_call = 0.0  # global timestamp of last DDG call


@ttl_cache(ttl=1800)
def ddg_search(query, max_results=DDG_MAX_RESULTS, retries=2):
    global _ddg_last_call
    if not _DDG_AVAILABLE:
        return {"error": "DuckDuckGo search unavailable — install ddgs: pip install ddgs", "results": []}

    # Enforce minimum gap between real network calls (cache hits bypass this entirely)
    elapsed = time.time() - _ddg_last_call
    if elapsed < DDG_RATE_DELAY:
        time.sleep(DDG_RATE_DELAY - elapsed)

    max_results = min(max_results, DDG_MAX_RESULTS)
    last_err = ""
    for attempt in range(retries + 1):
        try:
            with DDGS() as ddg:
                results = list(ddg.text(query, max_results=max_results))
            _ddg_last_call = time.time()
            return {"success": True, "count": len(results), "results": results}
        except Exception as e:
            last_err = str(e)[:200]
            if attempt < retries:
                time.sleep(DDG_RATE_DELAY * (attempt + 1))
            continue

    _ddg_last_call = time.time()
    return {"error": last_err or "DDG search failed after retries", "results": []}


@ttl_cache(ttl=1800)
def fetch_reddit_fishing(subreddit="OregonFishing", limit=25):
    url = f"https://www.reddit.com/r/{subreddit}/new.json?limit={limit}"
    try:
        import requests
        headers = {"User-Agent": "OregonFishingDashboard/4.0 (by /u/fishing_bot)"}
        resp = requests.get(url, headers=headers, timeout=15)
        if not resp.ok:
            return {"error": f"HTTP {resp.status_code}", "posts": []}

        data = resp.json()
        posts = []
        for child in (data.get("data", {}).get("children", []) or [])[:limit]:
            d = child.get("data", {})
            title = d.get("title", "")
            selftext = d.get("selftext", "")
            posts.append({
                "title": title[:200],
                "text": selftext[:500],
                "url": d.get("url", ""),
                "permalink": f"https://reddit.com{d.get('permalink', '')}",
                "author": d.get("author", "unknown"),
                "score": d.get("score", 0),
                "num_comments": d.get("num_comments", 0),
                "created_utc": d.get("created_utc", 0),
                "flair": d.get("link_flair_text", ""),
            })

        return {"success": True, "subreddit": f"r/{subreddit}", "count": len(posts), "posts": posts}
    except Exception as e:
        return {"error": str(e)[:120], "posts": []}


@ttl_cache(ttl=1800)
def fetch_reddit_multisub(subreddits=None):
    if subreddits is None:
        subreddits = ["OregonFishing", "flyfishing", "fishing", "Portland"]
    all_posts = []
    for sub in subreddits:
        result = fetch_reddit_fishing(subreddit=sub, limit=10)
        posts = result.get("posts", [])
        for p in posts:
            p["source_sub"] = sub
        all_posts.extend(posts)
    all_posts.sort(key=lambda x: x.get("score", 0), reverse=True)
    return all_posts


@ttl_cache(ttl=7200)
def search_fishing_reports_for_river(river_name=None, species=None, max_results=5):
    parts = []
    if river_name:
        parts.append(river_name)
    if species:
        parts.append(species)
    parts.append("Oregon fishing report 2026")
    query = " ".join(parts)
    return ddg_search(query, max_results=max_results)


@ttl_cache(ttl=7200)
def search_fishing_reports_osint(zone_name=None, species=None):
    queries = []

    if zone_name and species:
        queries.append(f"{zone_name} {species} fishing report Oregon")
    elif zone_name:
        queries.append(f"{zone_name} fishing report Oregon 2026")
    elif species:
        queries.append(f"Oregon {species} fishing report 2026")

    queries.append("Oregon fishing conditions report 2026")
    queries.append("site:ifish.net Oregon fishing report")
    queries.append("site:northwestfishingreports.com Oregon")

    all_results = []
    for i, q in enumerate(queries):
        if i > 0:
            time.sleep(DDG_RATE_DELAY)
        r = ddg_search(q, max_results=3)
        if r.get("results"):
            for item in r["results"]:
                if isinstance(item, dict) and item not in all_results:
                    all_results.append(item)

    return {"success": True, "results": all_results}


def format_reddit_for_ai_buddy(posts):
    if not posts:
        return "No recent Reddit posts found about Oregon fishing."
    lines = ["Recent Oregon fishing Reddit posts:"]
    for p in posts[:15]:
        src = p.get("source_sub", "")
        lines.append(
            f"r/{src} | {p['title']} | "
            f"{p['score']} pts, {p['num_comments']} comments | "
            f"u/{p['author']}"
        )
    return "\n".join(lines)


def extract_relevant_osint(query, max_sources=8):
    web_results = search_fishing_reports_osint()
    reddit_results = (
        fetch_reddit_multisub([query.lower().replace(" ", "")])
        if query
        else []
    )

    parts = []
    if web_results.get("results"):
        parts.append("**Web search results (DuckDuckGo):**")
        for r in web_results["results"][:max_sources]:
            title = r.get("title", r.get("snippet", ""))[:120]
            url = r.get("href", r.get("url", r.get("link", "")))
            body = r.get("body", "")[:200]
            parts.append(f"- {title}")
            if url:
                parts.append(f"  {url}")
            if body:
                parts.append(f"  {body}")

    if reddit_results:
        parts.append("\n**Reddit discussions:**")
        for p in reddit_results[:5]:
            parts.append(
                f"- r/{p.get('source_sub', '?')} | {p['title'][:100]} | "
                f"{p['score']} pts, {p['num_comments']} comments"
            )

    return "\n".join(parts) if parts else "No OSINT data found for this query."
