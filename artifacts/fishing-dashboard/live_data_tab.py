import streamlit as st
import pandas as pd
from datetime import datetime
from data_fetchers import (
    fetch_usgs_flows, fetch_odfw_stocking, build_river_summary,
    get_condition, get_tenkara_score, rank_tenkara, TYPICAL_RANGES, TENKARA_RIVERS
)


def render_live_data_tab():
    st.subheader("Live Oregon River & Stocking Data")

    col1, col2 = st.columns([4, 1])
    with col2:
        if st.button("🔄 Refresh", key="live_refresh"):
            fetch_usgs_flows.clear()
            fetch_odfw_stocking.clear()
            st.rerun()

    with st.spinner("Loading live data from USGS & ODFW..."):
        flows = fetch_usgs_flows()
        stocking = fetch_odfw_stocking()
        river_summary = build_river_summary(flows, stocking)

    last_updated = "Just now"
    for river_name, data in flows.items():
        if isinstance(data, dict) and data.get("datetime"):
            try:
                dt = datetime.fromisoformat(data["datetime"].replace("Z", "+00:00"))
                last_updated = dt.strftime("%b %d, %Y %I:%M %p UTC")
            except Exception:
                pass
            break

    if "error" in flows:
        st.warning(f"⚠️ USGS API issue: {flows['error']}. Showing cached or fallback data.")

    st.caption(f"Data last updated: {last_updated}")

    _render_usgs_section(flows, river_summary)
    st.divider()
    _render_tenkara_ranking(river_summary)
    st.divider()
    _render_stocking_section(stocking)


def _render_usgs_section(flows: dict, river_summary: list):
    st.markdown("### 💧 USGS Stream Flow — Oregon Rivers")
    st.caption("Flow data refreshes every 5 minutes. Green = fishable, Red = dangerous.")

    rows = []
    for r in river_summary:
        cfs = r["cfs"]
        cond = r["condition"]
        rows.append({
            "River": r["river"],
            "Status": f"{cond['emoji']} {cond['label']}",
            "Flow (CFS)": f"{cfs:.0f}" if cfs is not None else "—",
            "Tenkara": r["tenkara_score"] if r["is_tenkara"] else "—",
            "Stocked": "🐟 Yes" if r["is_stocked"] else "No",
        })

    if rows:
        df = pd.DataFrame(rows)
        st.dataframe(df, width="stretch", hide_index=True)

    st.markdown("#### Individual River Cards")
    cols = st.columns(2)
    for i, r in enumerate(river_summary):
        with cols[i % 2]:
            _render_flow_card(r)


def _render_flow_card(river: dict):
    cfs = river["cfs"]
    cond = river["condition"]
    cfs_display = f"{cfs:.0f} CFS" if cfs is not None else "No data"
    color = cond["color"]

    low_ok = high_ok = None
    if river["river"] in TYPICAL_RANGES:
        _, _, low_ok, high_ok = TYPICAL_RANGES[river["river"]]

    tenkara_line = ""
    if river["is_tenkara"]:
        tenkara_line = f"<br>🎣 <b>Tenkara:</b> {river['tenkara_score']}"

    normal_range = ""
    if low_ok and high_ok:
        normal_range = f"<br>📊 <b>Normal range:</b> {low_ok:.0f}–{high_ok:.0f} CFS"

    st.markdown(
        f"""<div style="border:1px solid #333; border-radius:8px; padding:12px; margin-bottom:10px; background:#1a1a2e;">
            <div style="font-size:15px; font-weight:bold;">{cond['emoji']} {river['river']}</div>
            <div style="font-size:22px; font-weight:bold; color:{'#2ecc71' if color=='green' else '#e74c3c' if color=='red' else '#e67e22' if color=='orange' else '#f1c40f' if color=='yellow' else '#9b59b6' if color=='purple' else '#95a5a6'};">{cfs_display}</div>
            <div style="font-size:13px; color:#aaa;">{cond['label']}{tenkara_line}{normal_range}</div>
        </div>""",
        unsafe_allow_html=True,
    )


def _render_tenkara_ranking(river_summary: list):
    st.markdown("### 🎣 Best Today for Tenkara")
    ranked = rank_tenkara(river_summary)
    if not ranked:
        st.info("No rivers currently in tenkara-friendly flow range. Check back after water levels drop.")
        return

    for rank, r in enumerate(ranked, 1):
        cfs_str = f"{r['cfs']:.0f} CFS" if r['cfs'] is not None else "N/A"
        medal = "🥇" if rank == 1 else "🥈" if rank == 2 else "🥉" if rank == 3 else f"#{rank}"
        st.markdown(f"**{medal} {r['river']}** — {r['tenkara_score']} ({cfs_str})")

    with st.expander("ℹ️ How Tenkara Scores Work"):
        st.write("""
        - **Excellent**: Flow is in the lower 60% of the good range — tight, accessible seams and pockets.
        - **Fishable**: Flow is within good range but pushing higher — wading may be tricky.
        - **Too High**: Flow exceeds comfortable wading or presentation limits for a fixed-line rod.
        - Rivers not suited for tenkara style (large mainstem rivers) are excluded from ranking.
        """)


def _render_stocking_section(stocking: list):
    st.markdown("### 🐟 ODFW Stocking Schedule")
    if not stocking:
        st.info("No stocking data available. Check [myodfw.com](https://myodfw.com) for the latest schedule.")
        return

    st.caption("⚠️ Stocking data shown is based on seasonal schedule patterns. Check ODFW for real-time truck locations.")

    df = pd.DataFrame(stocking)
    if not df.empty:
        st.dataframe(df[["river", "location", "species", "size", "date"]],
                     use_container_width=True, hide_index=True)

    with st.expander("📋 About ODFW Stocking Data"):
        st.write("""
        ODFW (Oregon Department of Fish & Wildlife) stocks hatchery trout, salmon, and steelhead
        throughout Oregon on a seasonal schedule. Stocked locations change weekly.

        For real-time stocking information:
        - Visit [myodfw.com/articles/where-fish-odfw-stocking-schedule](https://myodfw.com/articles/where-fish-odfw-stocking-schedule)
        - Call the ODFW hotline for your region
        - Check the ODFW Mobile App

        Hatchery fish must be kept (can't be released) at most locations — check regulations.
        """)
