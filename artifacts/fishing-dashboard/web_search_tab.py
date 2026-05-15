"""
Web Search Tab — DuckDuckGo live search interface
Searches the open internet for fishing reports, hatch activity, ODFW news,
regulations, closures, and anything else fishing-related.
"""
import streamlit as st

try:
    from ddgs import DDGS
    _AVAILABLE = True
except ImportError:
    try:
        from duckduckgo_search import DDGS
        _AVAILABLE = True
    except ImportError:
        _AVAILABLE = False
        DDGS = None


SEARCH_CATEGORIES = {
    "🎣 Fishing Reports": {
        "suffix": "fishing report conditions",
        "color": "#2ecc71",
        "sites": "nwflyfish.com OR westfly.com OR oregonflyfishingblog.com OR flyfishersplace.com OR finandfire.com",
        "desc": "Trip reports and current river conditions from Oregon fishing forums and fly shops",
    },
    "🪲 Hatch Reports": {
        "suffix": "hatch report fly fishing Oregon",
        "color": "#f39c12",
        "sites": "oregonflyfishingblog.com OR westfly.com OR nwflyfish.com OR flyfishfinder.com",
        "desc": "Current hatch activity — caddis, PMD, salmonfly, stonefly, mayfly",
    },
    "⚖️ ODFW Regulations": {
        "suffix": "site:dfw.state.or.us OR site:myodfw.com",
        "color": "#e74c3c",
        "sites": "dfw.state.or.us OR myodfw.com",
        "desc": "Official ODFW regulations, emergency closures, and news",
    },
    "🚨 Closures & News": {
        "suffix": "closure emergency order Oregon fish wildlife 2026",
        "color": "#e67e22",
        "sites": "dfw.state.or.us OR oregonlive.com OR kgw.com",
        "desc": "Emergency closures, regulation changes, and fishing news",
    },
    "🏔️ River Conditions": {
        "suffix": "river conditions water level Oregon fishing",
        "color": "#3498db",
        "sites": "waterdata.usgs.gov OR nwflyfish.com OR westfly.com",
        "desc": "Current water conditions, flows, and access reports",
    },
    "🐟 Species & Runs": {
        "suffix": "run timing forecast Oregon 2026",
        "color": "#9b59b6",
        "sites": "dfw.state.or.us OR cbr.washington.edu OR fisheries.noaa.gov",
        "desc": "Salmon, steelhead, trout run forecasts and timing",
    },
    "🔓 General Search": {
        "suffix": "",
        "color": "#95a5a6",
        "sites": "",
        "desc": "Open search — no category filter applied",
    },
}

QUICK_SEARCHES = [
    "Deschutes River fishing report this week",
    "McKenzie River caddis hatch 2026",
    "Oregon salmonfly hatch timing 2026",
    "Rogue River steelhead run 2026",
    "Metolius River conditions May 2026",
    "ODFW emergency closure 2026",
    "North Umpqua fly fishing report",
    "Oregon coastal rockfish regulations 2026",
    "Willamette River shad run 2026",
    "Crane Prairie reservoir fishing 2026",
    "Upper Klamath Lake fishing conditions",
    "Sandy River winter steelhead 2026",
]


@st.cache_data(ttl=300)
def _cached_search(query: str, num_results: int) -> list:
    if not _AVAILABLE:
        return []
    try:
        with DDGS() as ddg:
            return list(ddg.text(query, max_results=num_results))
    except Exception as e:
        return [{"_error": str(e)}]


def render_web_search_tab():
    st.markdown("### 🔍 Live Web Search — DuckDuckGo")

    # Status badge
    status_color = "#2ecc71" if _AVAILABLE else "#e74c3c"
    status_label = "🟢 Connected — DuckDuckGo (free, no API key)" if _AVAILABLE else "🔴 Search library not available"
    st.markdown(
        f'<div style="display:inline-block; background:#111; border:1px solid {status_color}; '
        f'border-radius:20px; padding:4px 14px; font-size:12px; color:{status_color}; margin-bottom:12px;">'
        f'{status_label}</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Search the live internet for fishing reports, hatch activity, ODFW news, closures, "
        "and anything else. Results update in real time."
    )

    if not _AVAILABLE:
        st.error("Install the `ddgs` package to enable web search: `pip install ddgs`")
        return

    # Category picker
    col_cat, col_num = st.columns([3, 1])
    with col_cat:
        category = st.selectbox(
            "Search category",
            list(SEARCH_CATEGORIES.keys()),
            index=0,
            key="ws_category",
        )
    with col_num:
        num_results = st.selectbox("Results", [5, 8, 12], index=0, key="ws_num")

    cat_info = SEARCH_CATEGORIES[category]
    st.caption(f"📌 {cat_info['desc']}")

    # Search box
    query_input = st.text_input(
        "Search query",
        placeholder="Deschutes River fly fishing report May 2026...",
        key="ws_query",
        label_visibility="collapsed",
    )

    col_search, col_clear = st.columns([4, 1])
    with col_search:
        search_clicked = st.button("🔍 Search", key="ws_search_btn", use_container_width=True, type="primary")
    with col_clear:
        if st.button("✕ Clear", key="ws_clear_btn", use_container_width=True):
            st.session_state["ws_last_query"] = ""
            st.session_state["ws_last_results"] = []
            st.session_state["ws_last_category"] = ""
            st.cache_data.clear()
            st.rerun()

    # Quick search chips
    st.markdown("**Quick searches:**")
    chip_cols = st.columns(4)
    for i, qs in enumerate(QUICK_SEARCHES):
        with chip_cols[i % 4]:
            if st.button(qs, key=f"ws_qs_{i}", use_container_width=True):
                st.session_state["ws_pending_quick"] = qs
                st.rerun()

    # Handle quick search trigger
    pending = st.session_state.pop("ws_pending_quick", None)
    if pending:
        st.session_state["ws_active_query"] = pending
        st.session_state["ws_active_category"] = category
        search_clicked = True
        query_input = pending

    # Run search
    if search_clicked and query_input.strip():
        _run_search(query_input.strip(), category, cat_info, num_results)
    elif st.session_state.get("ws_last_results") and st.session_state.get("ws_last_query"):
        _display_results(
            st.session_state["ws_last_results"],
            st.session_state["ws_last_query"],
            st.session_state.get("ws_last_category", ""),
        )


def _run_search(raw_query: str, category: str, cat_info: dict, num_results: int):
    suffix = cat_info.get("suffix", "")
    full_query = f"{raw_query} {suffix}".strip() if suffix else raw_query

    # For category searches that aren't "General", add Oregon context if missing
    if category != "🔓 General Search":
        oregon_terms = ["oregon", "or ", "deschutes", "mckenzie", "rogue", "umpqua",
                        "willamette", "metolius", "odfw", "santiam"]
        if not any(t in raw_query.lower() for t in oregon_terms):
            full_query = f"Oregon {full_query}"

    with st.spinner(f"🔍 Searching DuckDuckGo for: *{full_query}*"):
        results = _cached_search(full_query, num_results)

    st.session_state["ws_last_query"] = full_query
    st.session_state["ws_last_results"] = results
    st.session_state["ws_last_category"] = category
    _display_results(results, full_query, category)


def _display_results(results: list, query: str, category: str):
    if not results:
        st.warning(f"No results found for: **{query}**")
        return

    if results and results[0].get("_error"):
        st.error(f"Search error: {results[0]['_error']}")
        st.info("DuckDuckGo may be rate-limiting. Wait 30 seconds and try again.")
        return

    cat_info = SEARCH_CATEGORIES.get(category, SEARCH_CATEGORIES["🔓 General Search"])
    border_color = cat_info.get("color", "#444")

    st.markdown(
        f'<div style="font-size:12px; color:#888; margin-bottom:12px;">'
        f'🔍 Results for: <b>{query}</b> · {len(results)} found · via DuckDuckGo</div>',
        unsafe_allow_html=True,
    )

    for i, r in enumerate(results):
        if r.get("_error"):
            continue
        title = r.get("title", "No title")
        url = r.get("href", "#")
        body = r.get("body", "")[:400].strip()

        # Truncate cleanly at sentence boundary
        if len(body) >= 380 and ". " in body[200:]:
            body = body[:200 + body[200:].rfind(". ") + 1]

        # Extract domain for display
        domain = ""
        try:
            from urllib.parse import urlparse
            domain = urlparse(url).netloc.replace("www.", "")
        except Exception:
            pass

        # Color-tag known reliable fishing sources
        source_badge = ""
        trusted = {
            "dfw.state.or.us": ("🏛️ ODFW Official", "#e74c3c"),
            "myodfw.com": ("🏛️ ODFW Official", "#e74c3c"),
            "nwflyfish.com": ("🎣 NW Fly Fish Forum", "#2ecc71"),
            "westfly.com": ("🎣 WestFly", "#2ecc71"),
            "oregonflyfishingblog.com": ("🎣 OR Fly Blog", "#27ae60"),
            "flyfishersplace.com": ("🎣 Fly Fisher's Place", "#27ae60"),
            "finandfire.com": ("🎣 Fin & Fire", "#27ae60"),
            "flyfishfinder.com": ("🎣 FlyFishFinder", "#3498db"),
            "waterdata.usgs.gov": ("📡 USGS", "#3498db"),
            "cbr.washington.edu": ("📡 DART/CBR", "#9b59b6"),
            "fisheries.noaa.gov": ("📡 NOAA Fisheries", "#9b59b6"),
            "oregonlive.com": ("📰 OregonLive", "#f39c12"),
            "troutunderground.com": ("🎣 Trout Underground", "#2ecc71"),
        }
        if domain in trusted:
            badge_label, badge_color = trusted[domain]
            source_badge = (
                f'<span style="background:{badge_color}22; color:{badge_color}; '
                f'border:1px solid {badge_color}55; border-radius:10px; '
                f'padding:1px 7px; font-size:10px; margin-left:6px;">{badge_label}</span>'
            )

        # Send-to-buddy button key
        buddy_key = f"ws_to_buddy_{i}_{hash(url)}"

        st.markdown(
            f"""<div style="border:1px solid #2a2a2a; border-left:3px solid {border_color};
                border-radius:8px; padding:12px 14px; margin-bottom:10px; background:#0d1117;">
                <div style="font-size:14px; font-weight:600; margin-bottom:4px;">
                    <a href="{url}" target="_blank" style="color:#58a6ff; text-decoration:none;">
                        {title}
                    </a>{source_badge}
                </div>
                <div style="font-size:10px; color:#555; margin-bottom:6px;">
                    🔗 <a href="{url}" target="_blank" style="color:#444;">{url[:80]}{'…' if len(url)>80 else ''}</a>
                    &nbsp;·&nbsp; {domain}
                </div>
                <div style="font-size:12px; color:#aaa; line-height:1.5;">{body}</div>
            </div>""",
            unsafe_allow_html=True,
        )

        # Send-to-buddy button below each result
        if st.button(
            f"💬 Ask The Fisher about this →",
            key=buddy_key,
            help=f"Send this result to The Fisher: {title[:60]}",
        ):
            prompt = (
                f"I found this web result about fishing: \"{title}\" from {domain}.\n\n"
                f"Content: {body[:300]}\n\n"
                f"Source: {url}\n\n"
                f"What do you make of this? Does it affect where I should fish?"
            )
            if "messages" not in st.session_state:
                st.session_state.messages = []
            st.session_state.messages.append({"role": "user", "content": prompt})
            st.session_state["ws_buddy_pending"] = prompt
            st.info("✅ Sent to The Fisher in the sidebar! Scroll up to see the response.")

    st.divider()
    st.caption(
        "Results via DuckDuckGo · No API key required · "
        "Always verify fishing regulations and conditions directly with ODFW before fishing."
    )
