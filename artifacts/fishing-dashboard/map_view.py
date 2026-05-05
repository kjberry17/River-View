import folium
import streamlit as st
from streamlit_folium import st_folium
from data_fetchers import (
    build_river_summary, fetch_usgs_flows, fetch_odfw_stocking,
    rank_tenkara, RIVER_INFO
)
from hatcheries import OREGON_HATCHERIES, OREGON_LAKES

COLOR_MAP = {
    "green": "#2ecc71",
    "yellow": "#f1c40f",
    "orange": "#e67e22",
    "red": "#e74c3c",
    "purple": "#9b59b6",
    "gray": "#95a5a6",
    "blue": "#3498db",
}

REGION_COLORS = {
    "Central Oregon": "#e67e22",
    "Willamette Valley": "#27ae60",
    "Southern Oregon": "#c0392b",
    "Oregon Coast": "#2980b9",
    "Eastern Oregon": "#8e44ad",
    "Mt. Hood / Portland": "#16a085",
    "Columbia Gorge": "#d35400",
    "Southern Oregon Coast": "#1abc9c",
    "Southern Oregon (Klamath Basin)": "#e74c3c",
    "Mt. Hood / Sandy": "#16a085",
}


def render_map_tab():
    st.subheader("🗺️ Live Oregon Fishing Map")

    ctrl_cols = st.columns([2, 1, 1, 1, 1])
    with ctrl_cols[0]:
        st.caption("Color = flow condition · Size = data quality · Click pins for details")
    with ctrl_cols[1]:
        show_hatcheries = st.checkbox("🏭 Hatcheries", value=True, key="show_hatch")
    with ctrl_cols[2]:
        show_lakes = st.checkbox("💧 Lakes", value=True, key="show_lakes")
    with ctrl_cols[3]:
        show_regions = st.checkbox("📍 Regions", value=False, key="show_regions")
    with ctrl_cols[4]:
        if st.button("🔄 Refresh", key="map_refresh"):
            fetch_usgs_flows.clear()
            fetch_odfw_stocking.clear()
            st.rerun()

    with st.spinner("Fetching live USGS data..."):
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
        _add_river_marker(m, river)

    if show_hatcheries:
        for h in OREGON_HATCHERIES:
            _add_hatchery_marker(m, h)

    if show_lakes:
        for lake in OREGON_LAKES:
            _add_lake_marker(m, lake)

    if show_regions:
        _add_region_labels(m)

    map_data = st_folium(m, width="100%", height=540,
                         returned_objects=["last_object_clicked_tooltip"])

    clicked = None
    if map_data and map_data.get("last_object_clicked_tooltip"):
        tip = map_data["last_object_clicked_tooltip"]
        if tip:
            for r in river_summary:
                if r["river"] in tip:
                    clicked = r["river"]
                    break

    st.divider()
    _render_tenkara_row(river_summary)
    st.divider()
    _render_region_cards(river_summary)

    return clicked


def _add_river_marker(m, river: dict):
    cfs_str = f"{river['cfs']:.0f} CFS" if river['cfs'] is not None else "No USGS data"
    color = COLOR_MAP.get(river["condition"]["color"], "#95a5a6")
    stocked_badge = " | 🐟 STOCKED" if river["is_stocked"] else ""
    tenkara_badge = " | 🎣 Tenkara OK" if river["tenkara_score"] in ("Excellent", "Fishable") else ""
    temp_str = f" | 🌡️ {river['temp_f']:.0f}°F" if river.get("temp_f") else ""
    species_str = ", ".join(river.get("species", [])[:3])
    gear_str = ", ".join(river.get("gear", [])[:3])
    season_str = river.get("season_note", "")
    regulations_str = river.get("regulations", "Check ODFW regs.")

    popup_html = f"""
    <div style="font-family:sans-serif; min-width:240px; max-width:300px;">
        <b style="font-size:15px;">{river['river']}</b>
        <div style="font-size:11px; color:#888; margin-bottom:4px;">{river.get('region','Oregon')}</div>
        <div style="font-weight:bold; color:{color}; font-size:13px;">{river['condition']['emoji']} {river['condition']['label']}</div>
        <div style="font-size:13px;"><b>Flow:</b> {cfs_str}{tenkara_badge}{stocked_badge}</div>
        {f'<div style="font-size:12px;"><b>Temp:</b> {river["temp_condition"]["emoji"]} {river["temp_condition"]["label"]}</div>' if river.get("temp_f") else ''}
        <div style="font-size:12px; margin-top:4px;"><b>🐟 Species:</b> {species_str}</div>
        <div style="font-size:12px;"><b>🎣 Gear:</b> {gear_str}</div>
        <div style="font-size:11px; color:#aaa; margin-top:4px;"><i>{season_str}</i></div>
        <div style="font-size:10px; color:#e67e22; margin-top:3px;">⚖️ {regulations_str[:80]}</div>
        <div style="font-size:10px; color:#666; margin-top:3px;">Updated: {str(river['last_updated'])[:16]}</div>
        {f'<div style="font-size:10px; color:#9b59b6;">💧 {river["source_note"][:80]}</div>' if river.get("is_estimated") else ''}
    </div>
    """

    radius = 13 if river["condition"]["status"] == "good" else 10 if river["condition"]["status"] == "fair" else 9
    if river.get("is_estimated"):
        radius = 8

    folium.CircleMarker(
        location=[river["lat"], river["lon"]],
        radius=radius,
        color=color,
        fill=True,
        fill_color=color,
        fill_opacity=0.85,
        popup=folium.Popup(popup_html, max_width=310),
        tooltip=f"{river['river']} — {river['condition']['emoji']} {cfs_str}{temp_str}",
    ).add_to(m)

    if river["is_stocked"]:
        folium.Marker(
            location=[river["lat"] + 0.025, river["lon"] + 0.025],
            icon=folium.DivIcon(
                html='<div style="font-size:14px; text-shadow:0 0 3px black;">🐟</div>',
                icon_size=(20, 20),
                icon_anchor=(10, 10),
            ),
            tooltip=f"{river['river']} — Recently Stocked",
        ).add_to(m)

    if river["tenkara_score"] in ("Excellent",):
        folium.Marker(
            location=[river["lat"] - 0.025, river["lon"] - 0.025],
            icon=folium.DivIcon(
                html='<div style="font-size:13px;">🎣</div>',
                icon_size=(18, 18),
                icon_anchor=(9, 9),
            ),
            tooltip=f"{river['river']} — Tenkara Excellent",
        ).add_to(m)


def _add_hatchery_marker(m, h: dict):
    species_str = ", ".join(h["species"][:3])
    popup_html = f"""
    <div style="font-family:sans-serif; min-width:210px;">
        <b>🏭 {h['name']}</b><br>
        <div style="font-size:11px; color:#e67e22;">{h['region']}</div>
        <div style="font-size:12px;"><b>River:</b> {h['river_system']}</div>
        <div style="font-size:12px;"><b>Species:</b> {species_str}</div>
        <div style="font-size:11px; color:#aaa; margin-top:3px;"><i>{h.get('notes','')[:100]}</i></div>
    </div>
    """
    folium.Marker(
        location=[h["lat"], h["lon"]],
        icon=folium.DivIcon(
            html='<div style="font-size:16px; background:rgba(0,0,0,0.5); border-radius:50%; width:22px; height:22px; display:flex; align-items:center; justify-content:center;">🏭</div>',
            icon_size=(22, 22),
            icon_anchor=(11, 11),
        ),
        popup=folium.Popup(popup_html, max_width=250),
        tooltip=f"🏭 {h['name']} — {', '.join(h['species'][:2])}",
    ).add_to(m)


def _add_lake_marker(m, lake: dict):
    species_str = ", ".join(lake["species"][:3])
    popup_html = f"""
    <div style="font-family:sans-serif; min-width:210px;">
        <b>💧 {lake['name']}</b><br>
        <div style="font-size:11px; color:#3498db;">{lake['region']}</div>
        <div style="font-size:12px;"><b>Species:</b> {species_str}</div>
        <div style="font-size:11px; color:#f1c40f;"><b>Regs:</b> {lake['regulations'][:80]}</div>
        <div style="font-size:11px; color:#aaa; margin-top:3px;"><i>{lake['notes'][:100]}</i></div>
    </div>
    """
    folium.Marker(
        location=[lake["lat"], lake["lon"]],
        icon=folium.DivIcon(
            html='<div style="font-size:15px; background:rgba(0,50,100,0.6); border-radius:50%; width:22px; height:22px; display:flex; align-items:center; justify-content:center;">💧</div>',
            icon_size=(22, 22),
            icon_anchor=(11, 11),
        ),
        popup=folium.Popup(popup_html, max_width=250),
        tooltip=f"💧 {lake['name']} — {species_str[:40]}",
    ).add_to(m)


def _add_region_labels(m):
    region_centers = {
        "Central OR": (44.3, -121.3),
        "Willamette Valley": (44.5, -123.1),
        "Southern OR": (42.5, -122.8),
        "Oregon Coast": (44.5, -124.0),
        "Eastern OR": (44.5, -118.5),
        "Columbia Gorge": (45.6, -121.8),
    }
    for name, coords in region_centers.items():
        folium.Marker(
            location=coords,
            icon=folium.DivIcon(
                html=f'<div style="font-size:10px; color:#ffffff99; font-weight:bold; text-shadow:1px 1px 2px black; white-space:nowrap;">{name}</div>',
                icon_size=(100, 20),
                icon_anchor=(50, 10),
            ),
        ).add_to(m)


def _render_legend():
    st.markdown(
        """
        <div style="display:flex; gap:12px; flex-wrap:wrap; margin-bottom:8px; font-size:12px; align-items:center;">
            <span><b>Rivers:</b></span>
            <span>🟢 Good</span><span>🟡 Fair</span><span>🟠 High</span>
            <span>🔴 Dangerous</span><span>🟣 Too Low</span><span>⚫ No Data</span>
            <span>💧 Spring-fed</span>
            <span style="margin-left:8px;"><b>Overlays:</b></span>
            <span>🐟 Stocked</span><span>🎣 Tenkara✓</span>
            <span>🏭 Hatchery</span><span>💧 Lake/Reservoir</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_tenkara_row(river_summary: list):
    st.markdown("### 🎣 Best Today for Tenkara")
    ranked = rank_tenkara(river_summary)
    if not ranked:
        st.info("No rivers currently in tenkara-friendly range. Flows are running high across Oregon — check back as levels drop.")
        return
    cols = st.columns(min(len(ranked), 4))
    for i, r in enumerate(ranked[:4]):
        with cols[i]:
            cfs_str = f"{r['cfs']:.0f} CFS" if r['cfs'] is not None else "N/A"
            medal = ["🥇", "🥈", "🥉", "🏅"][i]
            temp_str = f"\n🌡️ {r['temp_f']:.0f}°F" if r.get("temp_f") else ""
            st.metric(
                f"{medal} {r['river']}",
                r["tenkara_score"],
                delta=f"{cfs_str}{temp_str}",
            )
            species = ", ".join(r.get("species", [])[:2])
            if species:
                st.caption(f"🐟 {species}")


def _render_region_cards(river_summary: list):
    st.markdown("### 📍 Rivers by Region")
    from data_fetchers import get_region_summary
    regions = get_region_summary(river_summary)

    region_order = [
        "Central Oregon", "Willamette Valley", "Southern Oregon",
        "Oregon Coast", "Eastern Oregon", "Mt. Hood / Portland",
        "Columbia Gorge", "Southern Oregon Coast", "Southern Oregon (Klamath Basin)",
        "Mt. Hood / Sandy",
    ]

    cols = st.columns(2)
    col_idx = 0
    for region in region_order:
        if region not in regions:
            continue
        data = regions[region]
        with cols[col_idx % 2]:
            good = data["good_count"]
            total = data["total"]
            pct = int(good / total * 100) if total else 0
            color = "🟢" if pct >= 60 else "🟡" if pct >= 30 else "🔴"
            with st.expander(f"{color} {region} — {good}/{total} fishable"):
                for r in sorted(data["rivers"], key=lambda x: x["condition"]["status"]):
                    cfs_str = f"{r['cfs']:.0f} CFS" if r['cfs'] is not None else "—"
                    temp_s = f" | 🌡️{r['temp_f']:.0f}°F" if r.get("temp_f") else ""
                    st.markdown(
                        f"**{r['condition']['emoji']} {r['river']}** — {cfs_str}{temp_s}  \n"
                        f"<small style='color:#aaa;'>🐟 {', '.join(r.get('species',[])[:2])}</small>",
                        unsafe_allow_html=True
                    )
        col_idx += 1
