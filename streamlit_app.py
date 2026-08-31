"""
Indian Stock Market Analyzer & Institutional Powerhouse
Streamlit Community Cloud Master Entry Point
"""
import sys
from pathlib import Path
import streamlit as st

# Configure Root Paths
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

# Page Configuration
st.set_page_config(
    page_title="Indian Stock Analyzer | Institutional Intelligence",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS Theme Styling
st.markdown("""
<style>
    /* Main Background */
    [data-testid="stSidebar"] { background-color: #0d1117; }
    .main { background-color: #0e1117; }

    /* Metric Cards */
    div[data-testid="metric-container"] {
        background-color: #161b22;
        border: 1px solid #30363d;
        border-radius: 8px;
        padding: 12px 16px;
    }
</style>
""", unsafe_allow_html=True)

# Import Database & Core Modules
from db.database import get_global_engine, get_session
from core.macro_regime import evaluate_macro_regime
from core.global_markets import analyze_global_market_spillovers
from core.news_sentiment import get_market_news_sentiment
from core.data_status import get_database_status_summary

engine = get_global_engine()
session = get_session(engine)

# Evaluate Live Regimes & DB Freshness
macro = evaluate_macro_regime(session)
global_mkt = analyze_global_market_spillovers(session)
news_sent = get_market_news_sentiment()
db_status = get_database_status_summary(session)
session.close()

# ── Title & Institutional Banner ──────────────────────────────────────────────
st.title("🏛️ Indian Stock Market Analyzer & Institutional Powerhouse")
st.caption("AI-Powered Quantitative Multi-Model Forecasting, Strategy Backtesting & Portfolio Optimization")

# Live Data Refresh Banner
st.markdown(f"""
<div style="background: linear-gradient(90deg, #0e271f, #0c1822); border-left: 5px solid #00c875; padding: 12px 18px; border-radius: 6px; margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap;">
    <div>
        <span style="font-size: 1.1em; font-weight: bold; color: #00c875;">📅 Data Refresh Date: {db_status['max_date']} (Latest Market Session)</span> • 
        <span style="color: #c8d0d8; font-size: 0.95em;"><b>{db_status['status_badge']}</b></span><br>
        <span style="font-size: 0.88em; color: #a0aec0;">Universe Covered: <b>{db_status['stock_count']} Equities</b> • <b>{db_status['index_count']} Indexes</b> • <b>{db_status['commodity_count']} Commodities</b> ({db_status['total_assets']} Total Assets | {db_status['total_bars']:,} Historical Bars)</span>
    </div>
    <div style="margin-top: 4px;">
        <span style="background-color: #1f6feb; color: white; padding: 4px 10px; border-radius: 12px; font-size: 0.8em; font-weight: 600;">⚡ Scheduled: 08:00 AM IST</span>
    </div>
</div>
""", unsafe_allow_html=True)

# Macro Regime Banner
st.markdown(f"""
<div style="background: linear-gradient(90deg, #102130, #0c1822); border-left: 5px solid #00a8ff; padding: 12px 18px; border-radius: 6px; margin-bottom: 12px;">
    <span style="font-size: 1.1em; font-weight: bold; color: #00a8ff;">🏛️ Macro Market Regime: {macro['regime']} (Macro Score: {macro['macro_score']}/100)</span><br>
    <span style="font-size: 0.9em; color: #c8d0d8;">{macro['summary']}</span><br>
    <span style="font-size: 0.88em; color: #00e5ff;"><b>Advisory Asset Allocation:</b> Equities <b>{macro['recommended_allocation']['Equities %']}%</b> | Gold & Commodities <b>{macro['recommended_allocation']['Gold & Commodities %']}%</b> | Cash & Liquid <b>{macro['recommended_allocation']['Cash & Liquid %']}%</b></span>
</div>
""", unsafe_allow_html=True)

# News Sentiment & Global Markets Ticker
st.markdown(f"""
<div style="background: #14212d; border-left: 4px solid #00c875; padding: 10px 16px; border-radius: 6px; margin-bottom: 16px;">
    <span style="font-weight: bold; color: #00c875;">📰 Real-Time Financial News Sentiment: {news_sent['overall_sentiment_score']:+.1f}/100 ({news_sent['overall_sentiment_verdict']})</span> • 
    <span style="color: #00a8ff; font-weight: bold;">Global Overnight Sentiment: {global_mkt['global_sentiment_index']:+.1f}/100 ({global_mkt['sentiment_verdict']})</span>
</div>
""", unsafe_allow_html=True)

# Overview Quick Cards
c1, c2, c3, c4 = st.columns(4)
c1.metric("Universe Tracked", f"{db_status['total_assets']} Assets", f"{db_status['stock_count']} Stocks • {db_status['index_count']} Indexes • {db_status['commodity_count']} Cmd")
c2.metric("Macro Regime", macro['regime'].split(' ')[1] if ' ' in macro['regime'] else macro['regime'], f"Score: {macro['macro_score']:.1f}/100")
c3.metric("Global Sentiment", f"{global_mkt['global_sentiment_index']:+.1f}", global_mkt['sentiment_verdict'].split(' ')[1] if ' ' in global_mkt['sentiment_verdict'] else global_mkt['sentiment_verdict'])
c4.metric("News Sentiment", f"{news_sent['overall_sentiment_score']:+.1f}", news_sent['overall_sentiment_verdict'].split(' ')[1] if ' ' in news_sent['overall_sentiment_verdict'] else news_sent['overall_sentiment_verdict'])

st.markdown("---")

# ── Platform Navigation Hub ───────────────────────────────────────────────────
st.subheader("🧭 Platform Navigation Hub")
st.caption("Select any module from the sidebar navigation or explore the capabilities below:")

nav_col1, nav_col2, nav_col3 = st.columns(3)

with nav_col1:
    st.markdown("""
    ### 📊 Market & Stock Analysis
    - **1. 📊 Market Dashboard**: Macro regime, market breadth, and sector heatmap.
    - **2. 🔍 Asset Deep-Dive**: 349 assets search, 5-Model ML ensemble, F&O profile, CPR, and 1-Click Advisory PDF.
    - **3. 🏭 Sector Analysis**: Sector breadth, 50/200 EMA leadership, and RS ranking.
    - **13. 🔄 Data Refresh Status**: Daily stock counts, max refresh date, and searchable universe catalog.
    """)

with nav_col2:
    with st.container():
        st.markdown("""
        ### ⚡ Signals & Predictive AI
        - **4. 🏆 Daily Top Opportunities**: Top BUY/SELL rankings, Index & Commodity signals, and CPR & VSA Breakouts.
        - **5. 📈 Trend Forecasts**: 5-Model ML Ensemble vs Champion Trajectory projections.
        - **6. ⚡ Strategies & Rules**: Algorithmic technical setups and scorecards.
        """)

with nav_col3:
    with st.container():
        st.markdown("""
        ### 💼 Institutional Portfolio & Alerts
        - **7. 🧪 Strategy Backtester**: Walk-forward equity curves, win rates, and alpha metrics.
        - **8. 💼 Portfolio Optimizer**: Markowitz MPT Efficient Frontier (4,000 paths) and Live Paper Trading.
        - **9. 📱 Alerts & Dispatcher**: 8:45 AM Pre-Market Morning Intelligence & Webhook dispatching.
        - **14. ⭐ Watchlists & 52W Radar**: Multi-watchlist targets, stop-losses, and proximity breakdown alerts.
        - **15. 🏦 Institutional Deals & Calendar**: Official NSE bulk/block whale flows and RBI/F&O macro calendar.
        """)

st.markdown("---")
st.info("👈 **Use the left sidebar** to switch between pages and explore any section.")