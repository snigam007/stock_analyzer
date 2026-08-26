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
st.set_page_config(page_title="Alerts & Morning Dispatcher", page_icon="📱", layout="wide")

import importlib
import core.alert_dispatcher
importlib.reload(core.alert_dispatcher)

from db.database import get_global_engine, get_session
from core.alert_dispatcher import generate_morning_briefing, send_webhook_alert

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

    m_col1, m_col2 = st.columns([2, 1])

    with m_col1:
        st.markdown("### 📋 Broadcast Preview")
        st.markdown(f"""
        <div style="background: #14212d; border-left: 5px solid #00a8ff; padding: 18px; border-radius: 8px; font-family: monospace; white-space: pre-wrap; color: #e0e8f0; line-height: 1.6;">
{briefing['raw_text']}
        </div>
        """, unsafe_allow_html=True)

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

    sample_alert_1 = (
        "🚀 **HIGH-PROBABILITY BUY SIGNAL TRIGGERED**\n"
        "• **Asset:** `MAHLOG` (Mahindra Logistics)\n"
        "• **Price:** ₹399.70 | **Score:** 63/100 (Growth Setup)\n"
        "• **🎯 Target 1:** ₹420.57 (+5.2%) | **🛑 Stop Loss:** ₹382.09 (-4.4%)\n"
        "• **VSA:** 💎 Institutional Absorption Detected on 1.8x Volume\n"
        "• **Strategy:** Backtested Champion (EMA Golden Cross)"
    )

    sample_alert_2 = (
        "🎯 **PROFIT TARGET 1 REACHED**\n"
        "• **Asset:** `RELIANCE`\n"
        "• **Current Price:** ₹1,420.00 (Hit Target 1 @ ₹1,418.50)\n"
        "• **Action:** Scale out 33% position (Tranche 1 Profit: +4.8%)\n"
        "• **Risk Protocol:** Move Stop Loss to Breakeven (₹1,350.00)"
    )

    a_col1, a_col2 = st.columns(2)
    with a_col1:
        st.markdown(f"""
        <div style="background: #1a2e22; border-left: 4px solid #00c875; padding: 14px; border-radius: 6px; margin-bottom: 10px;">
            {sample_alert_1}
        </div>
        """, unsafe_allow_html=True)

    with a_col2:
        st.markdown(f"""
        <div style="background: #1a2530; border-left: 4px solid #00a8ff; padding: 14px; border-radius: 6px; margin-bottom: 10px;">
            {sample_alert_2}
        </div>
        """, unsafe_allow_html=True)


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