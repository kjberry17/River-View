import folium
import streamlit as st
from streamlit_folium import st_folium
from data_fetchers import build_river_summary, fetch_usgs_flows, fetch_odfw_stocking, rank_tenkara

COLOR_MAP = {
    "green": "#2ecc71",
    "yellow": "#f1c40f",
    "orange": "#e67e22",
    "red": "#e74c3c",
    "purple": "#9b59b6",
    "gray": "#95a5a6",
}

ICON_MAP = {
    "good": ("check-circle", "green"),
    "fair": ("exclamation-circle", "orange"),
    "caution": ("exclamation-triangle", "orange"),
    "poor": ("times-circle", "red"),
    "unknown": ("question-circle", "gray"),
}


def render_map_tab():
    st.subheader("Live Oregon River Map")

    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        st.caption("Color-coded by current flow conditions")
    with col3:
        if st.button("🔄 Refresh Data", key="map_refresh"):
            fetch_usgs_flows.clear()
            fetch_odfw_stocking.clear()
            st.rerun()

    with st.spinner("Fetching live USGS flow data..."):
        flows = fetch_usgs_flows()
        stocking = fetch_odfw_stocking()
        river_summary = build_river_summary(flows, stocking)

    _render_legend()

    m = folium.Map(
        location=[44.2, -121.5],
        zoom_start=7,
        tiles="CartoDB dark_matter",
        prefer_canvas=True,
    )

    for river in river_summary:
        cfs_str = f"{river['cfs']:.0f} CFS" if river['cfs'] is not None else "No data"
        color = COLOR_MAP.get(river["condition"]["color"], "#95a5a6")
        stocked_badge = " 🐟 STOCKED" if river["is_stocked"] else ""
        tenkara_badge = " 🎣 Tenkara OK" if river["tenkara_score"] in ("Excellent", "Fishable") else ""

        popup_html = f"""
        <div style="font-family: sans-serif; min-width: 200px;">
            <b style="font-size:14px;">{river['river']}</b><br>
            <span style="color:{color}; font-weight:bold;">{river['condition']['label']}</span><br>
            <b>Flow:</b> {cfs_str}<br>
            <b>Tenkara:</b> {river['tenkara_score']}{tenkara_badge}{stocked_badge}<br>
            <small style="color:#888;">Updated: {str(river['last_updated'])[:16]}</small>
        </div>
        """

        folium.CircleMarker(
            location=[river["lat"], river["lon"]],
            radius=12 if river["condition"]["status"] == "good" else 9,
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.8,
            popup=folium.Popup(popup_html, max_width=250),
            tooltip=f"{river['river']} — {river['condition']['emoji']} {cfs_str}",
        ).add_to(m)

        if river["is_stocked"]:
            folium.Marker(
                location=[river["lat"] + 0.03, river["lon"] + 0.03],
                icon=folium.DivIcon(
                    html='<div style="font-size:16px;">🐟</div>',
                    icon_size=(20, 20),
                    icon_anchor=(10, 10),
                ),
                tooltip=f"{river['river']} — Recently Stocked",
            ).add_to(m)

    map_data = st_folium(m, width="100%", height=520, returned_objects=["last_object_clicked_tooltip"])

    clicked_river = None
    if map_data and map_data.get("last_object_clicked_tooltip"):
        tip = map_data["last_object_clicked_tooltip"]
        if tip and "—" in tip:
            clicked_river = tip.split("—")[0].strip()

    st.divider()
    _render_river_cards(river_summary, stocking)

    tenkara_ranked = rank_tenkara(river_summary)
    if tenkara_ranked:
        st.subheader("🎣 Best Today for Tenkara")
        cols = st.columns(min(len(tenkara_ranked), 3))
        for i, r in enumerate(tenkara_ranked[:3]):
            with cols[i]:
                cfs_str = f"{r['cfs']:.0f} CFS" if r['cfs'] is not None else "N/A"
                st.metric(
                    r["river"],
                    r["tenkara_score"],
                    delta=cfs_str,
                )

    return clicked_river


def _render_legend():
    st.markdown(
        """
        <div style="display:flex; gap:16px; flex-wrap:wrap; margin-bottom:8px; font-size:13px;">
            <span>🟢 Good Conditions</span>
            <span>🟡 Fair</span>
            <span>🟠 High — Caution</span>
            <span>🔴 Too High/Dangerous</span>
            <span>🟣 Too Low</span>
            <span>⚫ No Data</span>
            <span>🐟 Recently Stocked</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_river_cards(river_summary: list, stocking: list):
    stocked_map = {s["river"]: s for s in stocking}
    st.subheader("River Conditions At a Glance")
    cols = st.columns(2)
    for i, river in enumerate(river_summary):
        with cols[i % 2]:
            cfs_str = f"{river['cfs']:.0f} CFS" if river['cfs'] is not None else "No data"
            stocked_info = stocked_map.get(river["river"])
            stocked_str = f" | 🐟 {stocked_info['species']}" if stocked_info else ""
            tenkara_str = f" | 🎣 Tenkara: {river['tenkara_score']}" if river['is_tenkara'] else ""
            st.markdown(
                f"""
                <div style="border:1px solid #333; border-radius:8px; padding:10px; margin-bottom:8px;">
                    <b>{river['condition']['emoji']} {river['river']}</b><br>
                    <span style="font-size:13px;">{river['condition']['label']} — {cfs_str}{tenkara_str}{stocked_str}</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
