"""
Page 9: Automated Alerts & Morning Intelligence Dispatcher
- 8:45 AM Pre-Market Institutional Morning Intelligence Briefing
- Instant Webhook Broadcasts to Telegram Bot API & Discord Channels
- Live Trade Trigger & Stop Loss Notifications
"""
import sys
from pathlib import Path
import streamlit as st
import pandas as pd

# Universal Root Directory Finder
_curr = Path(__file__).resolve()
while _curr != _curr.parent:
    if (_curr / "core").exists() and (_curr / "db").exists():
        break
    _curr = _curr.parent
BASE_DIR = _curr
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
try:
    st.set_page_config(page_title="Alerts & Morning Dispatcher", page_icon="📱", layout="wide")
except Exception:
    pass

import importlib
import core.alert_dispatcher
importlib.reload(core.alert_dispatcher)

from db.database import get_global_engine, get_session
from core.alert_dispatcher import generate_morning_briefing, send_webhook_alert
from core.watchlist_manager import get_recent_alerts
from core.ui_components import render_clean_html, render_empty_defensive_state

engine = get_global_engine()

st.title("📱 Automated Alerts & Morning Dispatcher")
st.caption("Broadcast institutional morning intelligence briefings and real-time trade signals to Telegram & Discord")

tabs = st.tabs([
    "☀️ Morning Intelligence Briefing (8:45 AM)",
    "⚡ Real-Time Trade Trigger Alerts",
    "⚙️ Webhook Configuration & Testing",
])

# ── Tab 1: Morning Briefing ───────────────────────────────────────────────────
with tabs[0]:
    st.subheader("☀️ Daily Pre-Market Morning Intelligence Briefing")
    st.caption("Automatically generated at 8:45 AM IST synthesizing overnight global markets, macro risk regime, and top high-probability stock setups")

    session_b = get_session(engine)
    briefing = generate_morning_briefing(session_b)
    session_b.close()

    # Audio Podcast Player
    from core.audio_briefing import generate_audio_podcast_script, render_audio_player_html
    import streamlit.components.v1 as components

    podcast_script = generate_audio_podcast_script(briefing)
    audio_html = render_audio_player_html(podcast_script, "🎙️ 60-Second Spoken Morning Intelligence Podcast")
    components.html(audio_html, height=125)

    m_col1, m_col2 = st.columns([2, 1])

    with m_col1:
        st.markdown("### 📋 Broadcast Preview")
        render_clean_html(f"""
        <div style="background: #10141e; border: 1px solid rgba(0,238,252,0.25); border-left: 5px solid #00eefc; padding: 18px; border-radius: 8px; font-family: 'JetBrains Mono', monospace; font-size: 0.88em; white-space: pre-wrap; color: #e0e8f0; line-height: 1.6; box-shadow: 0 4px 16px rgba(0,0,0,0.4);">
{briefing['raw_text']}
        </div>
        """)

    with m_col2:
        st.markdown("### 📤 Dispatch Actions")
        st.info("💡 You can copy this briefing directly or broadcast it to your team's Discord / Telegram channel.")

        webhook_url = st.text_input("Destination Webhook URL", placeholder="https://discord.com/api/webhooks/...", key="wh_morning")
        platform = st.selectbox("Broadcast Platform", ["Discord", "Telegram", "Slack"], key="plat_morning")

        if st.button("🚀 Broadcast Morning Briefing Now", type="primary", use_container_width=True):
            if not webhook_url:
                st.warning("Please enter a valid Webhook URL below or configure it in Tab 3.")
            else:
                with st.spinner("Dispatching broadcast payload..."):
                    res = send_webhook_alert(webhook_url, briefing["raw_text"], platform)
                    if res["status"] == "SUCCESS":
                        st.success("✅ Morning briefing broadcasted successfully!")
                    else:
                        st.error(f"Dispatch failed: {res['message']}")


# ── Tab 2: Real-Time Trade Trigger Alerts ──────────────────────────────────────
with tabs[1]:
    st.subheader("⚡ Real-Time Trade Trigger Alerts")
    st.caption("Live alerts triggered when a champion strategy breaks out or an active position approaches Target / Stop-Loss")

    sess_al = get_session(engine)
    live_alerts = get_recent_alerts(sess_al, limit=20)
    sess_al.close()

    if live_alerts:
        st.markdown("##### 🔔 Recent Live Signal & Target Alerts")
        df_al = pd.DataFrame(live_alerts)
        st.dataframe(
            df_al[["symbol", "alert_type", "condition_value", "current_value", "message", "triggered_at"]].rename(columns={
                "symbol": "Ticker", "alert_type": "Alert Event",
                "condition_value": "Trigger Level (₹)", "current_value": "Execution Price (₹)",
                "message": "Notification Payload", "triggered_at": "Timestamp"
            }),
            use_container_width=True,
            height=280,
            hide_index=True
        )

    st.markdown("##### 🎯 Telemetry Signal Card Archetypes")
    sample_alert_1 = (
        "🚀 <b>HIGH-PROBABILITY BUY SIGNAL TRIGGERED</b><br>"
        "• <b>Asset:</b> <code style='color:#00ff66;'>MAHLOG</code> (Mahindra Logistics)<br>"
        "• <b>Price:</b> ₹399.70 | <b>Score:</b> 63/100 (Growth Setup)<br>"
        "• <b>🎯 Target 1:</b> ₹420.57 (+5.2%) | <b>🛑 Stop Loss:</b> ₹382.09 (-4.4%)<br>"
        "• <b>VSA:</b> 💎 Institutional Absorption Detected on 1.8x Volume<br>"
        "• <b>Strategy:</b> Backtested Champion (EMA Golden Cross)"
    )

    sample_alert_2 = (
        "🎯 <b>PROFIT TARGET 1 REACHED</b><br>"
        "• <b>Asset:</b> <code style='color:#00eefc;'>RELIANCE</code><br>"
        "• <b>Current Price:</b> ₹1,420.00 (Hit Target 1 @ ₹1,418.50)<br>"
        "• <b>Action:</b> Scale out 33% position (Tranche 1 Profit: +4.8%)<br>"
        "• <b>Risk Protocol:</b> Move Stop Loss to Breakeven (₹1,350.00)"
    )

    a_col1, a_col2 = st.columns(2)
    with a_col1:
        render_clean_html(f"""
        <div style="background: #111e18; border: 1px solid rgba(0,255,102,0.25); border-left: 4px solid #00ff66; padding: 14px 18px; border-radius: 8px; font-family: 'JetBrains Mono', monospace; font-size: 0.86em; line-height: 1.5; color: #cbd5e1;">
            {sample_alert_1}
        </div>
        """)

    with a_col2:
        render_clean_html(f"""
        <div style="background: #101c28; border: 1px solid rgba(0,238,252,0.25); border-left: 4px solid #00eefc; padding: 14px 18px; border-radius: 8px; font-family: 'JetBrains Mono', monospace; font-size: 0.86em; line-height: 1.5; color: #cbd5e1;">
            {sample_alert_2}
        </div>
        """)


# ── Tab 3: Webhook Configuration & Testing ────────────────────────────────────
with tabs[2]:
    st.subheader("⚙️ Webhook Configuration & Live Ping Test")
    st.caption("Configure automated integrations for instant signal dispatching")

    c1, c2 = st.columns(2)
    with c1:
        wh_input = st.text_input("Primary Webhook URL", placeholder="https://discord.com/api/webhooks/...", key="test_wh")
        wh_type = st.radio("Platform Type", ["Discord", "Telegram", "Slack"], horizontal=True, key="test_type")
        test_msg = st.text_area("Test Message Content", "🔔 Test notification from Indian Stock Analyzer Institutional Engine: Connection Verified!")

        if st.button("🧪 Send Live Test Ping", type="primary", use_container_width=True):
            with st.spinner("Pinging webhook..."):
                test_res = send_webhook_alert(wh_input, test_msg, wh_type)
                if test_res["status"] == "SUCCESS":
                    st.success("✅ Test message received successfully by webhook server!")
                else:
                    st.error(f"Ping failed: {test_res['message']}")

    with c2:
        st.info("""
        **How to set up webhooks:**
        - **Discord:** Server Settings → Integrations → Webhooks → New Webhook → Copy Webhook URL.
        - **Telegram:** Create bot with `@BotFather`, get Token, and create channel webhook.
        - **Slack:** Apps → Incoming WebHooks → Activate and copy Webhook URL.
        """)