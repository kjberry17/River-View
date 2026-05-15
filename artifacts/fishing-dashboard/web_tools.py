import subprocess
import json
import time
import re
from datetime import datetime, timedelta
from cache_utils import ttl_cache

TIMEOUT_SHORT = 12
TIMEOUT_MEDIUM = 25
TIMEOUT_LONG = 45
TINYFISH_BIN = "/opt/homebrew/bin/tinyfish"


def _run_tinyfish(args, timeout=TIMEOUT_MEDIUM):

    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout,
            env={**__import__("os").environ, "CI": "true", "NO_COLOR": "true"},
        )
        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()

        if result.returncode != 0:
            return {"error": f"exit={result.returncode}", "stderr": stderr[:300]}

        try:
            data = json.loads(stdout)
            return {"success": True, "data": data, "raw": stdout}
        except json.JSONDecodeError:
            return {"success": True, "text": stdout}

    except subprocess.TimeoutExpired:
        return {"error": "timeout", "stderr": ""}
    except FileNotFoundError:
        return {"error": "tinyfish not found at " + TINYFISH_BIN, "stderr": ""}
    except Exception as e:
        return {"error": str(e)[:120], "stderr": ""}


@ttl_cache(ttl=7200)
def tinyfish_search(query, max_results=8, domain_filter=None):
    args = [
        TINYFISH_BIN, "search", f"'{query}'",
        "--max-results", str(max_results),
    ]
    if domain_filter:
        args.extend(["--domain", domain_filter])
    return _run_tinyfish(args, timeout=TIMEOUT_SHORT)


@ttl_cache(ttl=3600)
def tinyfish_fetch(url, extract="main"):
    args = [TINYFISH_BIN, "fetch", url, "--extract", extract]
    return _run_tinyfish(args, timeout=TIMEOUT_MEDIUM)


@ttl_cache(ttl=7200)
def tinyfish_agent(instruction, url=None, max_steps=5):
    args = [TINYFISH_BIN, "agent", f"'{instruction}'", "--max-steps", str(max_steps)]
    if url:
        args.extend(["--url", url])
    return _run_tinyfish(args, timeout=TIMEOUT_LONG)


@ttl_cache(ttl=7200)
def search_oregon_fishing(query, domain_filter=None):
    full_query = f"Oregon fishing {query} 2025 2026"
    return tinyfish_search(full_query, domain_filter=domain_filter)


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
def search_fishing_reports_osint(zone_name=None, species=None):
    queries = []
    if zone_name and species:
        queries.append(f"{zone_name} {species} fishing report")
    elif zone_name:
        queries.append(f"{zone_name} fishing report 2025")
    elif species:
        queries.append(f"Oregon {species} fishing report")

    queries.append(("site:ifish.net fishing report Oregon", "ifish.net"))
    queries.append(("site:northwestfishingreports.com Oregon", None))
    queries.append(("Oregon fishing conditions 2025 OR fishing report", None))

    all_results = []
    for query_spec in queries:
        if isinstance(query_spec, tuple):
            q, domain = query_spec
        else:
            q, domain = query_spec, None

        r = tinyfish_search(q, max_results=3, domain_filter=domain)
        if r.get("success") and r.get("data"):
            items = r["data"] if isinstance(r["data"], list) else r["data"].get("results", [])
            for item in items:
                if isinstance(item, dict):
                    all_results.append(item)

    return {"success": True, "results": all_results}


@ttl_cache(ttl=21600)
def scrape_odfw_weekly_report_agent():
    instruction = (
        "Go to https://myodfw.com/recreation-report/fishing-report and get this week's fishing report. "
        "Extract: 1) All zones with current fishing conditions and species being caught. "
        "2) Any emergency regulations or closures mentioned. "
        "3) Stocking updates or hatchery releases. "
        "Return the information as structured data: zone name, conditions summary, "
        "key species, best techniques, any closures or alerts."
    )
    return tinyfish_agent(instruction, url="https://myodfw.com/recreation-report/fishing-report", max_steps=6)


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
    reddit_results = fetch_reddit_multisub([query.lower().replace(" ", "")]) if query else []

    parts = []
    if web_results.get("results"):
        parts.append("**Web search results:**")
        for r in web_results["results"][:max_sources]:
            title = r.get("title", r.get("snippet", ""))[:120]
            url = r.get("url", r.get("link", ""))
            parts.append(f"- {title}")
            if url:
                parts.append(f"  {url}")

    if reddit_results:
        parts.append("\n**Reddit discussions:**")
        for p in reddit_results[:5]:
            parts.append(f"- r/{p.get('source_sub', '?')} | {p['title'][:100]} | {p['score']} pts, {p['num_comments']} comments")

    return "\n".join(parts) if parts else "No OSINT data found for this query."
