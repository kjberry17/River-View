import streamlit as st
import json
from datetime import datetime

st.set_page_config(
    page_title="Oregon Fly/Tenkara Dashboard",
    page_icon="🎣",
    layout="wide",
    initial_sidebar_state="expanded",
)

import database as db
import ai_buddy
from map_view import render_map_tab
from live_data_tab import render_live_data_tab
from wiki_tab import render_wiki_tab
from data_fetchers import fetch_usgs_flows, fetch_odfw_stocking


def init_session():
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "pending_wiki_proposals" not in st.session_state:
        st.session_state.pending_wiki_proposals = []
    if "model_key" not in st.session_state:
        st.session_state.model_key = "Auto (Free)"
    if "db_initialized" not in st.session_state:
        try:
            db.init_db()
            st.session_state.db_initialized = True
        except Exception as e:
            st.session_state.db_initialized = False
            st.session_state.db_error = str(e)


def render_sidebar():
    with st.sidebar:
        st.title("🎣 AI Fishing Buddy")
        st.caption("Powered by OpenRouter + Your Karpathy Wiki")

        st.session_state.model_key = st.selectbox(
            "Model",
            list(ai_buddy.MODELS.keys()),
            index=0,
            help="Auto is free. Pro gives better reasoning for complex questions.",
        )

        if not ai_buddy.OPENROUTER_API_KEY:
            st.warning("⚠️ OPENROUTER_API_KEY not set. AI Buddy is disabled.")
            return

        st.divider()
        st.markdown("**Chat with The Buddy**")
        st.caption("Ask anything — where to fish, fly selection, trip planning, log a trip...")

        for msg in st.session_state.messages:
            role_icon = "🎣" if msg["role"] == "assistant" else "🧑"
            with st.chat_message(msg["role"]):
                st.markdown(f"{msg['content']}")

        if st.session_state.pending_wiki_proposals:
            _render_wiki_proposals()

        user_input = st.chat_input("Where should I fish this weekend?")
        if user_input:
            _handle_chat(user_input)

        st.divider()

        with st.expander("💡 Quick Prompts"):
            quick_prompts = [
                "Where should I fish today?",
                "Best tenkara rivers right now?",
                "What flies should I bring to the Deschutes?",
                "Is the McKenzie fishable this week?",
                "Log a trip to the Crooked River — 3 fish on kebari #14",
                "What patterns do you see in my fishing logs?",
                "Build me a Saturday plan within 2 hours of Bend",
                "Which rivers are currently stocked?",
            ]
            for prompt in quick_prompts:
                if st.button(prompt, key=f"quick_{prompt[:20]}", use_container_width=True):
                    _handle_chat(prompt)

        if st.button("🗑️ Clear Chat", use_container_width=True):
            st.session_state.messages = []
            st.session_state.pending_wiki_proposals = []
            st.rerun()


def _handle_chat(user_input: str):
    st.session_state.messages.append({"role": "user", "content": user_input})

    with st.sidebar:
        with st.spinner("The Buddy is thinking..."):
            try:
                flows = fetch_usgs_flows()
                stocking = fetch_odfw_stocking()
                live_data = {**flows, "_stocking": stocking}

                history = [
                    {"role": m["role"], "content": m["content"]}
                    for m in st.session_state.messages[:-1]
                ]

                response, proposals = ai_buddy.chat_with_buddy(
                    user_input,
                    history,
                    flows,
                    db,
                    st.session_state.model_key,
                )
                st.session_state.messages.append({"role": "assistant", "content": response})

                if proposals:
                    st.session_state.pending_wiki_proposals.extend(proposals)

                try:
                    db.save_chat_message("user", user_input)
                    db.save_chat_message("assistant", response)
                except Exception:
                    pass

            except Exception as e:
                err_msg = f"⚠️ The Buddy ran into trouble: {str(e)[:200]}"
                st.session_state.messages.append({"role": "assistant", "content": err_msg})

    st.rerun()


def _render_wiki_proposals():
    st.markdown("---")
    st.markdown("**📝 Wiki Update Proposals**")
    st.caption("The Buddy wants to save the following. Confirm or dismiss each one.")

    remaining = []
    for i, proposal in enumerate(st.session_state.pending_wiki_proposals):
        with st.expander(f"💾 {proposal.get('title', 'New Entry')} [{proposal.get('entry_type', 'note')}]"):
            st.write(proposal.get("content", ""))
            river = proposal.get("river", "")
            if river:
                st.caption(f"River: {river}")
            col1, col2 = st.columns(2)
            with col1:
                if st.button("✅ Save", key=f"save_proposal_{i}"):
                    try:
                        db.add_wiki_entry({
                            "entry_type": proposal.get("entry_type", "note"),
                            "river": proposal.get("river"),
                            "title": proposal.get("title"),
                            "content": proposal.get("content"),
                            "tags": proposal.get("tags", []),
                            "confidence": proposal.get("confidence", "personal"),
                            "source": "ai_buddy",
                        })
                        db.log_audit("ai_save", proposal.get("entry_type"), json.dumps(proposal))
                        st.success("Saved!")
                    except Exception as e:
                        st.error(f"Save failed: {e}")
                    continue
            with col2:
                if st.button("❌ Dismiss", key=f"dismiss_proposal_{i}"):
                    continue
            remaining.append(proposal)

    st.session_state.pending_wiki_proposals = remaining


def main():
    init_session()

    if not st.session_state.get("db_initialized"):
        err = st.session_state.get("db_error", "Unknown DB error")
        st.error(f"⚠️ Database connection failed: {err}")
        st.info("Make sure DATABASE_URL is set in your environment secrets.")

    render_sidebar()

    st.title("🎣 Oregon Fly/Tenkara Dashboard")
    st.caption("Real-time OSINT · Karpathy Wiki · AI Fishing Buddy  |  two dog seeds  |  v2.1")

    tab1, tab2, tab3 = st.tabs(["🗺️ Map", "📊 Live Data", "📚 Karpathy Wiki"])

    with tab1:
        clicked_river = render_map_tab()
        if clicked_river:
            st.session_state["map_selected_river"] = clicked_river
            st.info(f"💬 You clicked **{clicked_river}**. Ask the Buddy about it in the sidebar!")

    with tab2:
        render_live_data_tab()

    with tab3:
        render_wiki_tab()

    st.markdown(
        """
        <div style="text-align:center; color:#666; font-size:12px; margin-top:40px; padding:10px 0;">
        Oregon Fly/Tenkara Dashboard v2.1 · two dog seeds<br>
        Live data: USGS Water Services · Stocking: ODFW · AI: OpenRouter<br>
        ⚠️ Always check local regulations, water conditions, and access before fishing.
        </div>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
