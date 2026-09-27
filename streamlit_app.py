"""
Main Streamlit App — Indian Stock Market Analyzer & Institutional Powerhouse
Single Master Entrypoint with Modern Workspace Navigation (st.navigation)
Runs identically on Local and Streamlit Community Cloud.
"""
import sys
from pathlib import Path
import streamlit as st

# Configure Root Paths
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from config.settings import APP_TITLE, APP_VERSION, DISCLAIMER
from db.database import create_all_tables, get_global_engine

# ─── Ensure Database Schema ───────────────────────────────────────────────────
@st.cache_resource
def _ensure_db_tables():
    create_all_tables(get_global_engine())
    return True

_ensure_db_tables()

# ─── Global Page Configuration ────────────────────────────────────────────────
st.set_page_config(
    page_title=APP_TITLE,
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "About": f"{APP_TITLE} v{APP_VERSION} — Institutional Quantitative Intelligence",
    },
)

from config.retro_theme import inject_retro_terminal_theme, render_arcade_badge

# ─── Retro Terminal Quant Theme Injection ─────────────────────────────────────
inject_retro_terminal_theme()

# ─── Sidebar Branding & Info ──────────────────────────────────────────────────
with st.sidebar:
    st.markdown(f"""
    <div style="background-color: #171b26; border: 3px solid #00ff66; box-shadow: 4px 4px 0px 0px #030712; padding: 12px 14px; margin-bottom: 16px;">
        <div style="display: flex; align-items: center; justify-content: space-between;">
            <span style="font-family: 'Space Grotesk', sans-serif; font-weight: 800; font-size: 1.15rem; color: #f8fafc; letter-spacing: 0.08em;">
                🕹️ RETRO QUANT
            </span>
            <span style="font-family: 'JetBrains Mono', monospace; font-size: 0.75rem; background: #00ff66; color: #030712; padding: 2px 6px; font-weight: 700; box-shadow: 2px 2px 0px #030712;">
                1UP
            </span>
        </div>
        <div style="font-family: 'JetBrains Mono', monospace; font-size: 0.75rem; color: #00eefc; margin-top: 6px;">
            > HIGH-SCORE ALGO TERMINAL
        </div>
        <div style="font-family: 'JetBrains Mono', monospace; font-size: 0.7rem; color: #849581; margin-top: 2px;">
            VER: {APP_VERSION} · READY
        </div>
    </div>
    """, unsafe_allow_html=True)

# ─── Navigation Workspace Hierarchy ───────────────────────────────────────────
workspaces = {
    "🏛️ Market Pulse & Macro": [
        st.Page(BASE_DIR / "pages/0_Overview.py", title="Market Overview", icon="🏠", default=True),
        st.Page(BASE_DIR / "pages/1_Dashboard.py", title="Live Dashboard", icon="📈"),
        st.Page(BASE_DIR / "pages/10_360_Asset_Summary.py", title="360° Macro & Multi-Asset", icon="🌐"),
    ],
    "🔍 Asset Intelligence": [
        st.Page(BASE_DIR / "pages/2_Stock_Analysis.py", title="Stock Deep-Dive", icon="🔍"),
        st.Page(BASE_DIR / "pages/3_Sector_Analysis.py", title="Sector Analysis & Rotation", icon="🏭"),
        st.Page(BASE_DIR / "pages/5_Trends.py", title="Trend & AI Forecasts", icon="📉"),
        st.Page(BASE_DIR / "pages/17_Mutual_Funds_Radar.py", title="Mutual Funds Radar", icon="📊"),
    ],
    "⚡ Opportunities & Screeners": [
        st.Page(BASE_DIR / "pages/4_Daily_Top_Stocks.py", title="Daily Top Picks (Quantum Swing)", icon="🏆"),
        st.Page(BASE_DIR / "pages/16_Monthly_SIP_and_Sell_Radar.py", title="Monthly SIP & Sell Radar (Quantum Dynamic SIP)", icon="💰"),
        st.Page(BASE_DIR / "pages/12_Trading_Terminal_Matrix.py", title="Trading Terminal Matrix", icon="⚡"),
        st.Page(BASE_DIR / "pages/15_Institutional_Deals_and_Calendar.py", title="Deals & Macro Calendar", icon="🏦"),
    ],
    "💼 Portfolio & Wealth Lab": [
        st.Page(BASE_DIR / "pages/11_Portfolio_Advisor.py", title="Portfolio Advisor & Audit", icon="💼"),
        st.Page(BASE_DIR / "pages/8_Portfolio_Optimizer.py", title="Portfolio Optimizer & Frontier", icon="⚖️"),
        st.Page(BASE_DIR / "pages/14_Watchlist_and_Alerts.py", title="Watchlists & 52W Radar", icon="⭐"),
    ],
    "🧪 Quant Lab & Operations": [
        st.Page(BASE_DIR / "pages/18_Quantum_Engine.py", title="Quantum Lab & Bayesian Auditor", icon="⚛️"),
        st.Page(BASE_DIR / "pages/7_Backtesting.py", title="Strategy Backtesting Engine", icon="🧪"),
        st.Page(BASE_DIR / "pages/6_Strategies.py", title="Algorithmic Strategy Library", icon="📜"),
        st.Page(BASE_DIR / "pages/9_Alerts_Dispatcher.py", title="Alerts & Notifications", icon="🔔"),
        st.Page(BASE_DIR / "pages/13_Data_Refresh_Status.py", title="Data Health & Pipeline Sync", icon="🔄"),
    ]
}

# ─── Router Execution ─────────────────────────────────────────────────────────
pg = st.navigation(workspaces)

# Render Sidebar Footer
with st.sidebar:
    st.markdown(f'''
    <div style="background-color: #111827; border: 2px solid #313540; border-left: 4px solid #ffd700; box-shadow: 3px 3px 0px 0px #030712; padding: 10px; font-family: 'JetBrains Mono', monospace; font-size: 0.72rem; color: #b9ccb5;">
        <span style="color: #ffd700; font-weight: 700;">[ RISK NOTICE ]</span> {DISCLAIMER[:120]}...
    </div>
    ''', unsafe_allow_html=True)

# Run Selected Page
pg.run()