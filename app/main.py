"""
Main Streamlit App — Indian Stock Market Analyzer & Institutional Powerhouse
Single Master Entrypoint with Modern Workspace Navigation (st.navigation)
"""
import sys
from pathlib import Path
import streamlit as st

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from config.settings import APP_TITLE, APP_VERSION, DISCLAIMER

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

# ─── Modern Design System CSS ─────────────────────────────────────────────────
st.markdown("""
<style>
    /* Dark Modern Theme Backgrounds */
    [data-testid="stSidebar"] {
        background-color: #0b0f19;
        border-right: 1px solid #1e293b;
    }
    .main {
        background-color: #0a0e17;
    }

    /* Metric Cards */
    div[data-testid="metric-container"] {
        background-color: #111827;
        border: 1px solid #1f2937;
        border-radius: 10px;
        padding: 12px 18px;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
    }

    /* Signal badges */
    .signal-buy {
        background-color: rgba(0, 200, 117, 0.15);
        color: #00c875;
        border: 1px solid rgba(0, 200, 117, 0.3);
        padding: 4px 12px; border-radius: 20px;
        font-weight: 700; font-size: 0.85em;
    }
    .signal-sell {
        background-color: rgba(239, 68, 68, 0.15);
        color: #ef4444;
        border: 1px solid rgba(239, 68, 68, 0.3);
        padding: 4px 12px; border-radius: 20px;
        font-weight: 700; font-size: 0.85em;
    }
    .signal-watch {
        background-color: rgba(245, 158, 11, 0.15);
        color: #f59e0b;
        border: 1px solid rgba(245, 158, 11, 0.3);
        padding: 4px 12px; border-radius: 20px;
        font-weight: 700; font-size: 0.85em;
    }

    /* Navigation styling */
    [data-testid="stSidebarNav"] span {
        font-weight: 500;
        font-size: 0.92em;
    }
    [data-testid="stSidebarNav"] div[data-testid="stSidebarNavSeparator"] {
        border-top: 1px solid #1e293b;
        margin: 8px 0;
    }

    /* Disclaimer container */
    .disclaimer-pill {
        background-color: #111827;
        border-left: 3px solid #f59e0b;
        padding: 8px 12px;
        border-radius: 6px;
        font-size: 0.75em;
        color: #94a3b8;
        line-height: 1.4;
    }
</style>
""", unsafe_allow_html=True)

# ─── Sidebar Branding & Info ──────────────────────────────────────────────────
with st.sidebar:
    st.markdown(f"""
    <div style="display: flex; align-items: center; gap: 10px; padding: 4px 0 10px 0;">
        <span style="font-size: 1.8em;">🏛️</span>
        <div>
            <div style="font-weight: 800; font-size: 1.1em; color: #f8fafc; letter-spacing: 0.5px;">STOCK ANALYZER</div>
            <div style="font-size: 0.75em; color: #38bdf8; font-weight: 600;">INSTITUTIONAL ADVISORY · v{APP_VERSION}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

# ─── Navigation Workspace Hierarchy ───────────────────────────────────────────
workspaces = {
    "🏛️ Market Pulse & Macro": [
        st.Page("pages/0_Overview.py", title="Market Overview", icon="🏠", default=True),
        st.Page("pages/1_Dashboard.py", title="Live Dashboard", icon="📈"),
        st.Page("pages/10_360_Asset_Summary.py", title="360° Macro & Multi-Asset", icon="🌐"),
    ],
    "🔍 Asset Intelligence": [
        st.Page("pages/2_Stock_Analysis.py", title="Stock Deep-Dive", icon="🔍"),
        st.Page("pages/3_Sector_Analysis.py", title="Sector Analysis & Rotation", icon="🏭"),
        st.Page("pages/5_Trends.py", title="Trend & AI Forecasts", icon="📉"),
        st.Page("pages/17_Mutual_Funds_Radar.py", title="Mutual Funds Radar", icon="📊"),
    ],
    "⚡ Opportunities & Screeners": [
        st.Page("pages/4_Daily_Top_Stocks.py", title="Daily Top Picks", icon="🏆"),
        st.Page("pages/12_Trading_Terminal_Matrix.py", title="Trading Terminal Matrix", icon="⚡"),
        st.Page("pages/16_Monthly_SIP_and_Sell_Radar.py", title="Monthly SIP & Sell Radar", icon="💰"),
        st.Page("pages/15_Institutional_Deals_and_Calendar.py", title="Deals & Macro Calendar", icon="🏦"),
    ],
    "💼 Portfolio & Wealth Lab": [
        st.Page("pages/11_Portfolio_Advisor.py", title="Portfolio Advisor & Audit", icon="💼"),
        st.Page("pages/8_Portfolio_Optimizer.py", title="Portfolio Optimizer & Frontier", icon="⚖️"),
        st.Page("pages/14_Watchlist_and_Alerts.py", title="Watchlists & 52W Radar", icon="⭐"),
    ],
    "🧪 Quant Lab & Operations": [
        st.Page("pages/7_Backtesting.py", title="Strategy Backtesting Engine", icon="🧪"),
        st.Page("pages/6_Strategies.py", title="Algorithmic Strategy Library", icon="📜"),
        st.Page("pages/9_Alerts_Dispatcher.py", title="Alerts & Notifications", icon="🔔"),
        st.Page("pages/13_Data_Refresh_Status.py", title="Data Health & Pipeline Sync", icon="🔄"),
    ]
}

# ─── Router Execution ─────────────────────────────────────────────────────────
pg = st.navigation(workspaces)

# Render Sidebar Footer
with st.sidebar:
    st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
    st.markdown(f'<div class="disclaimer-pill">{DISCLAIMER[:120]}...</div>', unsafe_allow_html=True)

# Run Selected Page
pg.run()
