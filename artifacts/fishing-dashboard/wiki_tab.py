import streamlit as st
import pandas as pd
from datetime import date
import database as db


def render_wiki_tab():
    st.subheader("📚 Karpathy Wiki — Your Oregon Fishing Memory")
    st.caption("Everything you know, learned, and want to remember — stored and searchable.")

    tab1, tab2, tab3 = st.tabs(["⚙️ My Preferences", "📓 Fishing Log", "📍 Oregon Spot Wiki"])

    with tab1:
        _render_preferences()
    with tab2:
        _render_fishing_log()
    with tab3:
        _render_spot_wiki()


def _render_preferences():
    st.markdown("### Your Fishing Profile")
    prefs = db.get_preferences()

    with st.form("preferences_form"):
        home_base = st.text_input("Home Base (city)", value=prefs.get("home_base", "Bend, OR"))
        max_drive = st.slider("Max Drive Time (minutes)", 30, 360,
                              int(prefs.get("max_drive_minutes", 120)), step=15)

        favorite_rivers_raw = prefs.get("favorite_rivers") or []
        fav_rivers_str = st.text_area(
            "Favorite Rivers (one per line)",
            value="\n".join(favorite_rivers_raw),
            height=100,
        )

        style_options = ["tenkara", "dry fly", "nymphing", "streamer", "small stream",
                         "stocked trout", "wild trout", "catch-and-release only", "spin fishing"]
        current_styles = prefs.get("preferred_styles") or []
        preferred_styles = st.multiselect("Preferred Fishing Styles", style_options,
                                          default=[s for s in current_styles if s in style_options])

        gear_notes = st.text_area("Gear List / Notes", value=prefs.get("gear_notes", ""), height=80)

        col1, col2 = st.columns(2)
        with col1:
            risk_comfort = st.select_slider(
                "Risk Comfort",
                options=["low", "moderate", "high"],
                value=prefs.get("risk_comfort", "moderate"),
            )
        with col2:
            wading_comfort = st.select_slider(
                "Wading Comfort",
                options=["beginner", "moderate", "expert"],
                value=prefs.get("wading_comfort", "moderate"),
            )

        catch_and_release = st.checkbox("Catch & Release Only", value=bool(prefs.get("catch_and_release", True)))

        submitted = st.form_submit_button("💾 Save Preferences", type="primary")
        if submitted:
            fav_rivers_list = [r.strip() for r in fav_rivers_str.split("\n") if r.strip()]
            db.save_preferences({
                "home_base": home_base,
                "favorite_rivers": fav_rivers_list,
                "preferred_styles": preferred_styles,
                "max_drive_minutes": max_drive,
                "gear_notes": gear_notes,
                "risk_comfort": risk_comfort,
                "wading_comfort": wading_comfort,
                "catch_and_release": catch_and_release,
            })
            st.success("✅ Preferences saved! The Buddy will use these for all future recommendations.")


def _render_fishing_log():
    st.markdown("### Log a Trip")

    with st.form("log_form"):
        col1, col2 = st.columns(2)
        with col1:
            trip_date = st.date_input("Date", value=date.today())
        with col2:
            river = st.text_input("River", placeholder="Deschutes River")

        col3, col4 = st.columns(2)
        with col3:
            spot = st.text_input("Spot / Access Point", placeholder="Bend City Reach below dam")
        with col4:
            fish_caught = st.number_input("Fish Caught", min_value=0, max_value=200, value=0)

        conditions = st.text_input("Conditions", placeholder="Clear, 45°F, flows at 650 CFS, light breeze")
        flies = st.text_input("Flies / Techniques", placeholder="#16 Parachute Adams, tenkara kebari #14")
        notes = st.text_area("Notes", placeholder="What worked, what didn't, access notes, hatches observed...",
                             height=100)

        submitted = st.form_submit_button("📝 Log Trip", type="primary")
        if submitted:
            if not river:
                st.error("Please enter a river name.")
            else:
                log_id = db.add_fishing_log({
                    "trip_date": trip_date.isoformat(),
                    "river": river,
                    "spot": spot,
                    "conditions": conditions,
                    "flies": flies,
                    "fish_caught": fish_caught,
                    "notes": notes,
                })
                st.success(f"✅ Trip logged! Ask the Buddy to analyze your patterns from this log.")
                st.balloons()

    st.divider()
    st.markdown("### 📋 Recent Trips")

    logs = db.get_fishing_logs(limit=20)
    if not logs:
        st.info("No trips logged yet. Log your first trip above!")
        return

    filter_river = st.text_input("Filter by river", placeholder="Deschutes...", key="log_filter")
    if filter_river:
        logs = [l for l in logs if filter_river.lower() in (l.get("river") or "").lower()]

    df_data = []
    for log in logs:
        df_data.append({
            "Date": str(log.get("trip_date", ""))[:10],
            "River": log.get("river", ""),
            "Spot": log.get("spot", ""),
            "Fish": log.get("fish_caught", 0),
            "Flies": (log.get("flies") or "")[:40],
            "Notes": (log.get("notes") or "")[:60],
        })

    df = pd.DataFrame(df_data)
    st.dataframe(df, width="stretch", hide_index=True)

    if st.button("🧠 Ask Buddy to Analyze My Patterns"):
        st.info("Go to the sidebar and ask: 'What patterns do you see in my fishing logs?' — The Buddy will analyze your history.")


def _render_spot_wiki():
    st.markdown("### Oregon Spot Wiki")
    st.caption("Build your private knowledge base of rivers, spots, access notes, and seasonal patterns.")

    with st.expander("➕ Add New Wiki Entry", expanded=False):
        with st.form("wiki_entry_form"):
            col1, col2 = st.columns(2)
            with col1:
                entry_type = st.selectbox("Entry Type", ["spot", "pattern", "access", "seasonal", "hatch", "log"])
            with col2:
                river = st.text_input("River", placeholder="Metolius River")

            title = st.text_input("Title", placeholder="Best Tenkara Pools — Upper Metolius")
            content = st.text_area("Content", height=120,
                                   placeholder="Describe the spot, seasonal notes, fly patterns, access details, safety notes...")
            tags_raw = st.text_input("Tags (comma-separated)", placeholder="tenkara, spring, dry-fly, keeper-spot")

            col3, col4 = st.columns(2)
            with col3:
                confidence = st.selectbox("Confidence", ["personal", "verified", "inferred", "unverified"])
            with col4:
                privacy = st.selectbox("Privacy", ["fuzzy", "exact", "private-only"])

            source = st.text_input("Source", value="Personal knowledge", placeholder="Personal scouting, forum tip, guide book...")

            submitted = st.form_submit_button("💾 Save Wiki Entry", type="primary")
            if submitted:
                if not title or not content:
                    st.error("Title and content are required.")
                else:
                    tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
                    db.add_wiki_entry({
                        "entry_type": entry_type,
                        "river": river,
                        "title": title,
                        "content": content,
                        "tags": tags,
                        "confidence": confidence,
                        "privacy": privacy,
                        "source": source,
                    })
                    st.success("✅ Wiki entry saved!")

    st.divider()
    st.markdown("### Search Your Wiki")

    col1, col2 = st.columns([3, 1])
    with col1:
        search_query = st.text_input("Search", placeholder="Search by river, topic, or keyword...", key="wiki_search")
    with col2:
        type_filter = st.selectbox("Type", ["All", "spot", "pattern", "access", "seasonal", "hatch", "log"], key="wiki_type_filter")

    river_filter = st.text_input("Filter by river", placeholder="All rivers", key="wiki_river_filter")

    type_param = None if type_filter == "All" else type_filter
    river_param = river_filter if river_filter else None

    if search_query:
        entries = db.search_wiki(search_query)
    else:
        entries = db.get_wiki_entries(entry_type=type_param, river=river_param)

    if not entries:
        st.info("No wiki entries yet. Add your first one above, or ask the Buddy to save something!")
        _show_example_entries()
        return

    for entry in entries:
        with st.expander(f"📍 {entry['title']} — {entry.get('river', 'General')} [{entry['entry_type']}]"):
            st.write(entry["content"])
            tag_str = " ".join([f"`{t}`" for t in (entry.get("tags") or [])])
            meta = f"**Confidence:** {entry['confidence']} | **Source:** {entry.get('source', 'unknown')} | **Privacy:** {entry.get('privacy', 'fuzzy')} | **Added:** {str(entry.get('created_at', ''))[:10]}"
            st.caption(f"{meta}\n\n{tag_str}")


def _show_example_entries():
    st.markdown("""
    **Example Wiki entries you can add:**
    - *"Upper Deschutes below Bend — Best in June before irrigation demand peaks"*
    - *"Metolius at Camp Sherman — Browns rise to #18 BWOs on overcast afternoons"*
    - *"Crooked River access via Paulina Hwy — park at turnout mile 15, 200yd walk"*
    - *"My tenkara fly box — kebari #12-16, EHC #14, foam beetle #12"*
    """)
