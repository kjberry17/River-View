import streamlit as st
import pandas as pd
from datetime import datetime
from data_fetchers import (
    fetch_usgs_flows, fetch_odfw_stocking, build_river_summary,
    get_condition, get_tenkara_score, get_temp_condition, get_data_freshness_info,
    rank_tenkara, TYPICAL_RANGES, TENKARA_RIVERS, RIVER_INFO,
)


def render_live_data_tab():
    st.subheader("📊 Live Oregon River & Fishing Data")

    col1, col2 = st.columns([4, 1])
    with col2:
        if st.button("🔄 Refresh All", key="live_refresh"):
            fetch_usgs_flows.clear()
            fetch_odfw_stocking.clear()
            try:
                from weather_fetchers import fetch_nws_weather
                fetch_nws_weather.clear()
            except Exception:
                pass
            try:
                from fish_passage import fetch_bonneville_passage
                fetch_bonneville_passage.clear()
            except Exception:
                pass
            st.rerun()

    with st.spinner("Loading live data..."):
        flows = fetch_usgs_flows()
        stocking = fetch_odfw_stocking()
        river_summary = build_river_summary(flows, stocking)
        freshness = get_data_freshness_info(flows)

    if "error" in flows:
        st.warning(f"⚠️ USGS API issue: {flows['error']}. Some data may be stale.")

    _render_freshness_banner(freshness)

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "💧 River Flows",
        "🌡️ Stream Temps",
        "🌤️ Weather by Zone",
        "🐟 Fish Passage",
        "🎣 Stocking",
    ])

    with tab1:
        _render_usgs_section(flows, river_summary)
        st.divider()
        _render_tenkara_ranking(river_summary)

    with tab2:
        _render_temperature_section(river_summary)

    with tab3:
        _render_weather_section()

    with tab4:
        _render_fish_passage_section()

    with tab5:
        _render_stocking_section(stocking)


def _render_freshness_banner(freshness: dict):
    with st.expander("🕐 Data Sources & Freshness — When does this data update?", expanded=False):
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.markdown("**🌊 USGS Stream Flow & Temp**")
            st.caption(f"Latest reading: **{freshness['usgs_sensor_time']}**")
            st.caption(f"📡 {freshness['live_river_count']}/{freshness['total_rivers']} rivers live")
            st.caption(freshness["usgs_sensor_cadence"])
            st.caption(freshness["app_cache_ttl"])
            st.caption(freshness["gage_reset_note"])
        with col2:
            st.markdown("**🌤️ NWS Weather**")
            st.caption(freshness["weather_note"])
            st.markdown("[NWS Oregon →](https://www.weather.gov/pqr/)")
        with col3:
            st.markdown("**🐟 Fish Passage**")
            st.caption(freshness["passage_note"])
            st.markdown("[DART System →](https://www.cbr.washington.edu/dart/)")
        with col4:
            st.markdown("**📚 Karpathy Wiki**")
            st.caption(freshness["wiki_db_note"])
            st.caption("✅ Never resets — persistent PostgreSQL.")


def _render_usgs_section(flows: dict, river_summary: list):
    st.markdown("### 💧 USGS Stream Flow — 33 Oregon Rivers")
    st.caption("Live from USGS Water Services · Sensors update every 15 min · App caches 5 min")

    col_filter, col_region, col_status = st.columns([2, 2, 2])
    with col_filter:
        search = st.text_input("Search river", placeholder="Deschutes...", key="flow_search")
    with col_region:
        regions = sorted(set(r.get("region", "Oregon") for r in river_summary))
        region_filter = st.selectbox("Region", ["All Regions"] + regions, key="flow_region")
    with col_status:
        status_filter = st.selectbox("Status", ["All", "Good", "Fair", "Caution", "Poor"], key="flow_status")

    filtered = river_summary
    if search:
        filtered = [r for r in filtered if search.lower() in r["river"].lower()]
    if region_filter != "All Regions":
        filtered = [r for r in filtered if r.get("region") == region_filter]
    if status_filter != "All":
        s_map = {"Good": "good", "Fair": "fair", "Caution": "caution", "Poor": "poor"}
        filtered = [r for r in filtered if r["condition"]["status"] == s_map.get(status_filter)]

    rows = []
    for r in filtered:
        cfs = r["cfs"]
        cond = r["condition"]
        temp_str = f"{r['temp_f']:.0f}°F" if r.get("temp_f") else "—"
        rows.append({
            "River": r["river"],
            "Region": r.get("region", "—"),
            "Status": f"{cond['emoji']} {cond['label']}",
            "CFS": f"{cfs:.0f}" if cfs else "—",
            "Temp": temp_str,
            "Tenkara": r["tenkara_score"] if r["is_tenkara"] else "—",
            "Stocked": "🐟" if r["is_stocked"] else "",
            "Top Species": ", ".join(r.get("species", [])[:2]),
        })

    if rows:
        df = pd.DataFrame(rows)
        st.dataframe(df, width="stretch", hide_index=True, height=400)

    st.markdown("#### River Detail Cards")
    card_cols = st.columns(2)
    for i, river in enumerate(filtered):
        with card_cols[i % 2]:
            _render_flow_card(river)


def _render_flow_card(river: dict):
    cfs = river["cfs"]
    cond = river["condition"]
    cfs_display = f"{cfs:.0f} CFS" if cfs is not None else "No data"
    color_css = {
        "green": "#2ecc71", "yellow": "#f1c40f", "orange": "#e67e22",
        "red": "#e74c3c", "purple": "#9b59b6", "gray": "#95a5a6", "blue": "#3498db"
    }.get(cond["color"], "#95a5a6")

    temp_line = ""
    if river.get("temp_f"):
        tc = river["temp_condition"]
        temp_line = f"<br>🌡️ <b>Temp:</b> {tc['label']}"

    tenkara_line = ""
    if river["is_tenkara"]:
        tenkara_line = f"<br>🎣 <b>Tenkara:</b> {river['tenkara_score']}"

    low_ok = high_ok = None
    if river["river"] in TYPICAL_RANGES:
        _, _, low_ok, high_ok = TYPICAL_RANGES[river["river"]]

    range_line = ""
    if low_ok and high_ok:
        range_line = f"<br>📊 <b>Good range:</b> {low_ok:.0f}–{high_ok:.0f} CFS"

    species_str = ", ".join(river.get("species", [])[:3])
    gear_str = ", ".join(river.get("gear", [])[:2])
    access = river.get("access", "")
    regulations = river.get("regulations", "")

    st.markdown(
        f"""<div style="border:1px solid #333; border-radius:8px; padding:12px; margin-bottom:10px; background:#0e1117;">
            <div style="font-size:14px; font-weight:bold;">{cond['emoji']} {river['river']}</div>
            <div style="font-size:10px; color:#888; margin-bottom:4px;">{river.get('region','')}</div>
            <div style="font-size:22px; font-weight:bold; color:{color_css};">{cfs_display}</div>
            <div style="font-size:12px; color:#ccc;">{cond['label']}{tenkara_line}{temp_line}{range_line}</div>
            <div style="font-size:11px; color:#aaa; margin-top:4px;">🐟 {species_str}</div>
            <div style="font-size:11px; color:#aaa;">🎣 {gear_str}</div>
            {f'<div style="font-size:10px; color:#666; margin-top:3px;">📍 {access[:60]}</div>' if access else ''}
            {f'<div style="font-size:10px; color:#e67e22; margin-top:2px;">⚖️ {regulations[:70]}</div>' if regulations else ''}
        </div>""",
        unsafe_allow_html=True,
    )


def _render_tenkara_ranking(river_summary: list):
    st.markdown("### 🎣 Top Tenkara Rivers Right Now")
    ranked = rank_tenkara(river_summary)
    if not ranked:
        st.info("No rivers in tenkara-friendly range right now — flows are running high. Check back as levels drop.")
        return
    cols = st.columns(min(len(ranked), 4))
    for i, r in enumerate(ranked[:4]):
        with cols[i]:
            medals = ["🥇", "🥈", "🥉", "🏅"]
            medal = medals[i] if i < len(medals) else "🎣"
            cfs_str = f"{r['cfs']:.0f} CFS" if r["cfs"] is not None else "N/A"
            temp_str = f" · 🌡️{r['temp_f']:.0f}°F" if r.get("temp_f") else ""
            st.metric(
                f"{medal} {r['river']}",
                r["tenkara_score"],
                delta=f"{cfs_str}{temp_str}",
            )
            species = ", ".join(r.get("species", [])[:2])
            if species:
                st.caption(f"🐟 {species}")
            access = r.get("access", "")
            if access:
                st.caption(f"📍 {access[:50]}")


def _render_temperature_section(river_summary: list):
    st.markdown("### 🌡️ Stream Temperatures")
    st.caption("USGS parameter 00010 — Temperature sensors not on every river. Ideal for trout: 50–68°F")

    rivers_with_temp = [r for r in river_summary if r.get("temp_f") is not None]
    rivers_no_temp = [r for r in river_summary if r.get("temp_f") is None]

    if rivers_with_temp:
        st.markdown(f"**{len(rivers_with_temp)} rivers reporting temperature:**")
        cols = st.columns(3)
        for i, r in enumerate(sorted(rivers_with_temp, key=lambda x: x["temp_f"])):
            with cols[i % 3]:
                tc = r["temp_condition"]
                st.metric(
                    r["river"],
                    f"{r['temp_f']:.1f}°F",
                    delta=tc["label"].split("—")[1].strip() if "—" in tc["label"] else tc["label"],
                    delta_color="normal",
                )

        with st.expander("🌡️ Temperature & Fish Activity Guide"):
            st.markdown("""
| Temp | Fish Activity | Strategy |
|------|--------------|----------|
| < 35°F | 🥶 Very sluggish | Deep, slow nymphs. Fish at warmest time of day |
| 35–45°F | ❄️ Slow | Nymphs near bottom. Midges. Slow presentation |
| 45–50°F | 🟡 Picking up | Nymphs and wet flies. Small emergers possible |
| 50–60°F | 🟢 **Prime** | Excellent hatch activity. Dries, nymphs all work |
| 60–68°F | 🟢 **Prime** | Peak feeding. Dries, hoppers, big dry-dropper rigs |
| 68–72°F | 🟠 Warm | Fish early/late. Avoid playing fish too long |
| > 72°F | 🔴 Stress | Consider not fishing. Practice C&R carefully |
| > 75°F | ⚠️ Danger | Thermal stress — rest the river |
            """)
    else:
        st.info("No temperature data available right now. USGS temperature sensors update with flow data.")

    if rivers_no_temp:
        with st.expander(f"❓ {len(rivers_no_temp)} rivers without temperature sensors"):
            names = ", ".join(r["river"] for r in rivers_no_temp)
            st.caption(names)
            st.caption("Not all USGS gages include thermistors. Spring-fed rivers (Metolius) maintain ~48°F year-round.")


def _render_weather_section():
    st.markdown("### 🌤️ Weather by Oregon Fishing Zone")
    st.caption("NWS forecasts updated every 30 min — includes barometric trend indicator for fish activity")

    try:
        from weather_fetchers import fetch_nws_weather, get_barometric_trend_note
        with st.spinner("Fetching NWS weather..."):
            weather = fetch_nws_weather()
    except Exception as e:
        st.warning(f"Weather data unavailable: {e}")
        return

    if not weather:
        st.info("Weather data loading...")
        return

    for zone, w in weather.items():
        if isinstance(w, dict) and w.get("error"):
            st.caption(f"⚠️ {zone}: {w['error']}")
            continue
        if not isinstance(w, dict):
            continue

        score = w.get("fishing_score", 50)
        label = w.get("fishing_label", {"label": "Unknown", "emoji": "❓"})
        trend = get_barometric_trend_note(w.get("precip_chance", 0), w.get("max_precip_6h", 0))

        with st.expander(f"{label['emoji']} **{zone}** — {w.get('temp_f','?')}°F, {w.get('short_forecast','?')} | Fishing: **{label['label']}**", expanded=score >= 70):
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Temperature", f"{w.get('temp_f','?')}°F")
                st.caption(f"💨 Wind: {w.get('wind_speed','?')} {w.get('wind_dir','')}")
            with col2:
                st.metric("Precip Chance", f"{w.get('precip_chance',0)}%")
                st.caption(f"6-hr max: {w.get('max_precip_6h',0)}%")
            with col3:
                st.metric("Fishing Score", f"{score}/100")
                st.caption(f"Updated: {w.get('updated','?')}")
            st.info(trend)
            rivers = w.get("rivers", [])
            if rivers:
                st.caption(f"📍 Rivers in this zone: {', '.join(rivers)}")


def _render_fish_passage_section():
    st.markdown("### 🐟 Bonneville Dam Fish Passage")
    st.caption("Adult fish passage counts at Bonneville Dam (Columbia River) via DART — Columbia Basin Research")

    try:
        from fish_passage import fetch_bonneville_passage, get_run_timing_calendar, FISH_ICONS, SPECIES_NOTES
        with st.spinner("Fetching fish passage data..."):
            passage = fetch_bonneville_passage()
    except Exception as e:
        st.warning(f"Fish passage data unavailable: {e}")
        return

    st.markdown("#### Recent Counts at Bonneville Dam")
    if not passage:
        st.info("ℹ️ Live DART data unavailable — showing seasonal estimates based on current month.")
        from fish_passage import _bonneville_fallback
        from datetime import datetime as _dt
        passage = _bonneville_fallback(_dt.now())
    cols = st.columns(min(len(passage), 3))
    for i, (species, data) in enumerate(passage.items()):
        with cols[i % min(len(passage), 3)]:
            icon = FISH_ICONS.get(species, "🐟")
            recent = data.get("recent", 0)
            avg = data.get("avg_7d", 0)
            delta_val = recent - avg
            note = data.get("note", "")
            st.metric(
                f"{icon} {species}",
                f"{recent:,}/day",
                delta=f"{delta_val:+,} vs 7d avg",
            )
            if note:
                st.caption(note)
            if species in SPECIES_NOTES:
                st.caption(SPECIES_NOTES[species][:80])

    st.divider()
    st.markdown("#### 📅 Oregon Fish Run Timing Calendar")
    try:
        calendar = get_run_timing_calendar()
        from datetime import datetime
        current_month = datetime.now().month
        current_runs = []
        upcoming_runs = []
        for run_name, run_data in calendar.items():
            peak = run_data.get("peak_months", [])
            if current_month in peak:
                current_runs.append((run_name, run_data))
            elif any(m == (current_month % 12) + 1 or m == (current_month % 12) + 2 for m in peak):
                upcoming_runs.append((run_name, run_data))

        if current_runs:
            st.markdown("**🟢 Active Runs Right Now:**")
            for run_name, run_data in current_runs:
                rivers_str = ", ".join(run_data["rivers"][:3])
                st.markdown(f"- {run_data['icon']} **{run_name}** — {rivers_str}")

        if upcoming_runs:
            st.markdown("**🟡 Coming Up Soon:**")
            for run_name, run_data in upcoming_runs:
                rivers_str = ", ".join(run_data["rivers"][:3])
                st.markdown(f"- {run_data['icon']} **{run_name}** — {rivers_str}")

        with st.expander("📋 Full Annual Run Calendar"):
            for run_name, run_data in calendar.items():
                months_str = " ".join(
                    f"**[{['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][m-1]}]**"
                    if current_month == m else
                    f"[{['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][m-1]}]"
                    for m in run_data["peak_months"]
                )
                rivers_str = ", ".join(run_data["rivers"][:4])
                st.markdown(f"{run_data['icon']} **{run_name}**: {months_str}  \n&nbsp;&nbsp;&nbsp;*{rivers_str}*")
    except Exception as e:
        st.caption(f"Calendar unavailable: {e}")

    st.markdown("[📊 View Full DART Data →](https://www.cbr.washington.edu/dart/query/adult_annual)")
    st.markdown("[🔬 Columbia Basin Research →](https://www.cbr.washington.edu/)")


def _render_stocking_section(stocking: list):
    st.markdown("### 🐟 ODFW Stocking Schedule")
    if not stocking:
        st.info("No stocking data. Check [myodfw.com](https://myodfw.com) for the latest.")
        return

    st.caption("⚠️ Shown data is based on seasonal patterns. Check ODFW for real-time stocking truck locations.")

    df = pd.DataFrame(stocking)
    if not df.empty:
        display_cols = [c for c in ["river", "location", "species", "size", "date", "note"] if c in df.columns]
        st.dataframe(df[display_cols], width="stretch", hide_index=True)

    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### 📋 ODFW Stocking Resources")
        st.markdown("""
- [🐟 Real-Time Stocking Schedule](https://myodfw.com/articles/where-fish-odfw-stocking-schedule)
- [📍 ODFW Stocking Tracker App](https://myodfw.com/articles/odfw-mobile-app)
- [📞 Stocking Hotline: 503-947-6000](tel:5039476000)
- [🗺️ Stocking Location Map](https://myodfw.com/fishing/species/trout-fishing/stocking-schedule)
        """)
    with col2:
        st.markdown("#### ⚖️ Hatchery Fish Rules")
        st.markdown("""
- Hatchery fish: fin-clipped (adipose fin removed)
- Wild fish: C&R required on most waters
- Check ODFW emergency orders weekly — regs change
- Hatchery fish CAN be retained (where allowed)
- Always check current sport regs before fishing
        """)
