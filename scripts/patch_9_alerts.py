from pathlib import Path

target_file = Path(r"c:\Users\SNigam2\.gemini\antigravity\scratch\stock_analyzer\pages\9_Alerts_Dispatcher.py")
content = target_file.read_text(encoding="utf-8")

# 1. Fix top imports
old_top = """try:
    st.set_page_config(page_title="Alerts & Morning Dispatcher", page_icon="📱", layout="wide")
except Exception:
    pass

import importlib
import core.alert_dispatcher
importlib.reload(core.alert_dispatcher)

from db.database import get_global_engine, get_session
from core.alert_dispatcher import generate_morning_briefing, send_webhook_alert"""

new_top = """try:
    st.set_page_config(page_title="Alerts & Morning Dispatcher", page_icon="📱", layout="wide")
except Exception:
    pass

import importlib
import core.alert_dispatcher
importlib.reload(core.alert_dispatcher)

from db.database import get_global_engine, get_session
from core.alert_dispatcher import generate_morning_briefing, send_webhook_alert
from core.watchlist_manager import get_recent_alerts
from core.ui_components import render_clean_html, render_empty_defensive_state"""

if old_top in content:
    content = content.replace(old_top, new_top)
    print("Replaced top block.")

# 2. Fix broadcast preview in Tab 1
old_preview = """        st.markdown(f\"\"\"
        <div style="background: #14212d; border-left: 5px solid #00a8ff; padding: 18px; border-radius: 8px; font-family: monospace; white-space: pre-wrap; color: #e0e8f0; line-height: 1.6;">
{briefing['raw_text']}
        </div>
        \"\"\", unsafe_allow_html=True)"""

new_preview = """        render_clean_html(f\"\"\"
        <div style="background: #10141e; border: 1px solid rgba(0,238,252,0.25); border-left: 5px solid #00eefc; padding: 18px; border-radius: 8px; font-family: 'JetBrains Mono', monospace; font-size: 0.88em; white-space: pre-wrap; color: #e0e8f0; line-height: 1.6; box-shadow: 0 4px 16px rgba(0,0,0,0.4);">
{briefing['raw_text']}
        </div>
        \"\"\")"""

if old_preview in content:
    content = content.replace(old_preview, new_preview)
    print("Replaced broadcast preview.")

# 3. Enhance Tab 2 with live alerts if available
old_tab2 = """# ── Tab 2: Real-Time Trade Trigger Alerts ──────────────────────────────────────
with tabs[1]:
    st.subheader("⚡ Real-Time Trade Trigger Alerts")
    st.caption("Live alerts triggered when a champion strategy breaks out or an active position approaches Target / Stop-Loss")

    sample_alert_1 = (
        "🚀 **HIGH-PROBABILITY BUY SIGNAL TRIGGERED**\\n"
        "• **Asset:** `MAHLOG` (Mahindra Logistics)\\n"
        "• **Price:** ₹399.70 | **Score:** 63/100 (Growth Setup)\\n"
        "• **🎯 Target 1:** ₹420.57 (+5.2%) | **🛑 Stop Loss:** ₹382.09 (-4.4%)\\n"
        "• **VSA:** 💎 Institutional Absorption Detected on 1.8x Volume\\n"
        "• **Strategy:** Backtested Champion (EMA Golden Cross)"
    )

    sample_alert_2 = (
        "🎯 **PROFIT TARGET 1 REACHED**\\n"
        "• **Asset:** `RELIANCE`\\n"
        "• **Current Price:** ₹1,420.00 (Hit Target 1 @ ₹1,418.50)\\n"
        "• **Action:** Scale out 33% position (Tranche 1 Profit: +4.8%)\\n"
        "• **Risk Protocol:** Move Stop Loss to Breakeven (₹1,350.00)"
    )

    a_col1, a_col2 = st.columns(2)
    with a_col1:
        st.markdown(f\"\"\"
        <div style="background: #1a2e22; border-left: 4px solid #00c875; padding: 14px; border-radius: 6px; margin-bottom: 10px;">
            {sample_alert_1}
        </div>
        \"\"\", unsafe_allow_html=True)

    with a_col2:
        st.markdown(f\"\"\"
        <div style="background: #1a2530; border-left: 4px solid #00a8ff; padding: 14px; border-radius: 6px; margin-bottom: 10px;">
            {sample_alert_2}
        </div>
        \"\"\", unsafe_allow_html=True)"""

new_tab2 = """# ── Tab 2: Real-Time Trade Trigger Alerts ──────────────────────────────────────
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
        render_clean_html(f\"\"\"
        <div style="background: #111e18; border: 1px solid rgba(0,255,102,0.25); border-left: 4px solid #00ff66; padding: 14px 18px; border-radius: 8px; font-family: 'JetBrains Mono', monospace; font-size: 0.86em; line-height: 1.5; color: #cbd5e1;">
            {sample_alert_1}
        </div>
        \"\"\")

    with a_col2:
        render_clean_html(f\"\"\"
        <div style="background: #101c28; border: 1px solid rgba(0,238,252,0.25); border-left: 4px solid #00eefc; padding: 14px 18px; border-radius: 8px; font-family: 'JetBrains Mono', monospace; font-size: 0.86em; line-height: 1.5; color: #cbd5e1;">
            {sample_alert_2}
        </div>
        \"\"\")"""

if old_tab2 in content:
    content = content.replace(old_tab2, new_tab2)
    print("Replaced Tab 2 with live alerts and retro styling.")

target_file.write_text(content, encoding="utf-8")
print("Updated 9_Alerts_Dispatcher.py successfully.")
