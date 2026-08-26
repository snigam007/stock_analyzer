"""
Page 5: Trend Forecasts
Prophet ML forecasts for 7D/14D/1M/3M/6M/1Y with confidence bands.
"""
import sys
from pathlib import Path
import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import numpy as np

# Universal Root Directory Finder
_curr = Path(__file__).resolve()
while _curr != _curr.parent:
    if (_curr / "core").exists() and (_curr / "db").exists():
        break
    _curr = _curr.parent
BASE_DIR = _curr
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
st.set_page_config(page_title="Trend Forecasts", page_icon="📉", layout="wide")

from db.database import get_global_engine, get_session
from sqlalchemy import text

engine = get_global_engine()

st.title("📉 Trend Forecasts")
st.caption("ML-powered (Prophet) time-series forecasts with confidence intervals")

@st.cache_data(ttl=30)
def get_forecast_assets(category: str = "Stocks"):
    session = get_session(engine)
    if category == "Indexes":
        result = session.execute(text("""
            SELECT DISTINCT f.symbol, ip.name, 'Index' as sector
            FROM forecasts f
            JOIN index_prices ip ON f.symbol = ip.symbol
            ORDER BY f.symbol
        """)).fetchall()
    elif category == "Commodities":
        result = session.execute(text("""
            SELECT DISTINCT f.symbol, cp.name, 'Commodity' as sector
            FROM forecasts f
            JOIN commodity_prices cp ON f.symbol = cp.symbol
            ORDER BY f.symbol
        """)).fetchall()
    else:
        result = session.execute(text("""
            SELECT DISTINCT f.symbol, s.name, s.sector
            FROM forecasts f JOIN stocks s ON f.symbol = s.symbol
            ORDER BY s.sector, f.symbol
        """)).fetchall()
    session.close()
    return result

@st.cache_data(ttl=30)
def get_forecast_data(symbol: str, category: str = "Stocks"):
    session = get_session(engine)
    forecast = session.execute(text("""
        SELECT * FROM forecasts WHERE symbol=:s ORDER BY generated_date DESC LIMIT 1
    """), {"s": symbol}).mappings().first()

    if category == "Indexes":
        table = "index_prices"
    elif category == "Commodities":
        table = "commodity_prices"
    else:
        table = "daily_prices"

    prices = session.execute(text(f"""
        SELECT date, close FROM {table} WHERE symbol=:s ORDER BY date DESC LIMIT 365
    """), {"s": symbol}).fetchall()

    session.close()
    return dict(forecast) if forecast else {}, prices


COMMODITY_NAMES = {
    "GC=F": "Gold (COMEX / MCX Future)",
    "SI=F": "Silver (COMEX / MCX Future)",
    "CL=F": "Crude Oil (WTI / MCX)",
    "BZ=F": "Brent Crude Oil",
    "HG=F": "Copper (COMEX / MCX)",
    "NG=F": "Natural Gas",
    "PL=F": "Platinum",
    "PA=F": "Palladium",
    "GOLDBEES.NS": "Nippon India Gold ETF (GOLDBEES)",
    "SILVERBEES.NS": "Nippon India Silver ETF (SILVERBEES)",
}

INDEX_NAMES = {
    "^NSEI": "NIFTY 50 (National Stock Exchange)",
    "^BSESN": "BSE SENSEX (Bombay Stock Exchange)",
    "^NSEBANK": "NIFTY BANK (Banking Index)",
    "^CNXIT": "NIFTY IT (Technology Index)",
    "NIFTYBEES.NS": "Nippon India Nifty 50 ETF (NIFTYBEES)",
    "BANKBEES.NS": "Nippon India Nifty Bank ETF (BANKBEES)",
    "ITBEES.NS": "Nippon India Nifty IT ETF (ITBEES)",
    "^GSPC": "S&P 500 (US Benchmark)",
    "^NDX": "Nasdaq 100 (US Tech Benchmark)",
}


def get_display_name(sym: str, raw_name: str = None) -> str:
    if sym in COMMODITY_NAMES:
        return COMMODITY_NAMES[sym]
    if sym in INDEX_NAMES:
        return INDEX_NAMES[sym]
    return raw_name or sym


st.sidebar.title("📉 Trend Forecasts")
category = st.sidebar.radio("Asset Category", ["Stocks", "Indexes", "Commodities"], horizontal=True)

stock_list = get_forecast_assets(category)
if not stock_list:
    st.warning(f"No forecast data available for {category}. Run forecasts to populate.")
    st.stop()

symbols = [s[0] for s in stock_list]
labels = [f"{s[0]} — {get_display_name(s[0], s[1])[:45]}" for s in stock_list]

selected_idx = st.sidebar.selectbox("Select Asset", range(len(labels)), format_func=lambda i: labels[i])
selected_symbol = symbols[selected_idx]

forecast, prices = get_forecast_data(selected_symbol, category)

if not forecast:
    st.warning(f"No forecast available for {selected_symbol}.")
    st.stop()

stock_info = next((s for s in stock_list if s[0] == selected_symbol), None)
asset_name = get_display_name(selected_symbol, stock_info[1] if stock_info else None)
asset_sector = stock_info[2] if (stock_info and stock_info[2]) else category
st.header(f"📈 {selected_symbol} — {asset_name}")
st.caption(f"📂 Category: {asset_sector}")

current_price_row = prices[0] if prices else None
current_price = current_price_row[1] if current_price_row else 0

horizons = [
    ("7 Days", "7d"), ("14 Days", "14d"), ("1 Month", "1m"),
    ("3 Months", "3m"), ("6 Months", "6m"), ("1 Year", "1y"),
]

# ── Prediction Model Intelligence View Toggle ─────────────────────────────────
from core.ml_models import compute_ml_ensemble_consensus
from core.trade_optimizer import compute_empirical_strategy_projections
from core.backtester import find_champion_strategy

session = get_session(engine)
champion_data = find_champion_strategy(selected_symbol, session, years=3)
session.close()

model_view = st.radio(
    "Forecast Intelligence Engine",
    [
        "📊 Multi-Horizon Price Forecasts",
        "🧠 5-Model ML Ensemble Consensus (GBM + RF + Ridge + HW + MC)",
        "🏆 Backtested Champion Strategy Trajectory",
        "⚖️ Head-to-Head Comparison",
    ],
    horizontal=True,
    help="Toggle between statistical multi-horizon forecasts, 5-model ML ensemble consensus, and empirical champion trajectory."
)

champ_data_obj = champion_data.get("champion") if (champion_data and "champion" in champion_data) else None
emp_proj = compute_empirical_strategy_projections(current_price, champ_data_obj) if champ_data_obj else None

if prices:
    price_df_temp = pd.DataFrame(prices, columns=["date", "close"]).sort_values("date")
    price_df_temp["date"] = pd.to_datetime(price_df_temp["date"])
    price_df_temp.set_index("date", inplace=True)
    price_df_temp["open"] = price_df_temp["close"]
    price_df_temp["high"] = price_df_temp["close"] * 1.002
    price_df_temp["low"] = price_df_temp["close"] * 0.998
    price_df_temp["volume"] = 100000.0
    ml_ens = compute_ml_ensemble_consensus(price_df_temp)
else:
    ml_ens = None

if "Head-to-Head" in model_view or "Ensemble" in model_view:
    if ml_ens:
        st.markdown(f"""
        <div style="background: #142330; border-left: 5px solid #00a8ff; padding: 12px 16px; border-radius: 6px; margin-bottom: 12px;">
            <span style="font-size: 1.1em; font-weight: bold; color: #00a8ff;">🧠 5-Model ML Consensus: {ml_ens['consensus_label']} ({ml_ens['ensemble_confidence_pct']}% Bullish Confidence)</span><br>
            <span style="font-size: 0.9em; color: #d0d0d0;">{ml_ens['consensus_description']}</span>
        </div>
        """, unsafe_allow_html=True)
        with st.expander("🔬 **View 5-Algorithm Breakdown (GBM, RF, Ridge, HW, Monte Carlo)**", expanded=False):
            st.dataframe(pd.DataFrame(ml_ens["models"]), use_container_width=True, hide_index=True)

if "Head-to-Head" in model_view or "Champion" in model_view:
    if emp_proj:
        st.markdown(f"**🔮 Champion Empirical Forward Trajectory ({emp_proj['strategy_name']}):**")
        ep1, ep2, ep3, ep4, ep5 = st.columns(5)
        ep_data = [
            ("14 Days", emp_proj["proj_14d_price"], emp_proj["proj_14d_pct"]),
            ("1 Month", emp_proj["proj_1m_price"], emp_proj["proj_1m_pct"]),
            ("3 Months", emp_proj["proj_3m_price"], emp_proj["proj_3m_pct"]),
            ("6 Months", emp_proj["proj_6m_price"], emp_proj["proj_6m_pct"]),
            ("1 Year", emp_proj["proj_1y_price"], emp_proj["proj_1y_pct"]),
        ]
        for col, (horiz, pr, p_pct) in zip([ep1, ep2, ep3, ep4, ep5], ep_data):
            col.metric(horiz, f"₹{pr:,.2f}" if pr < 1000 else f"₹{pr:,.1f}", f"{p_pct:+.2f}%", delta_color="normal" if p_pct > 0 else "inverse")
        st.markdown("---")

# ── Forecast Summary Cards ────────────────────────────────────────────────────
if "Multi-Horizon" in model_view or "Head-to-Head" in model_view:
    st.subheader("🎯 Multi-Horizon Statistical Forecasts")
    cols = st.columns(6)
    for col, (label, key) in zip(cols, horizons):
        price = forecast.get(f"forecast_{key}_price")
        chg = forecast.get(f"forecast_{key}_change_pct")
        upper = forecast.get(f"forecast_{key}_upper")
        lower = forecast.get(f"forecast_{key}_lower")

        if price:
            delta_color = "normal" if (chg or 0) > 0 else "inverse"
            price_str = f"₹{price:,.2f}" if price < 1000 else f"₹{price:,.1f}"
            col.metric(
                label,
                price_str,
                f"{chg:+.2f}%" if chg else None,
                delta_color=delta_color,
            )
            if lower and upper:
                col.caption(f"₹{lower:,.1f} – ₹{upper:,.1f}")
        else:
            col.metric(label, "N/A")

st.markdown("---")

# ── Trend Chart with Forecast ─────────────────────────────────────────────────
if prices:
    price_df = pd.DataFrame(prices, columns=["date", "close"])
    price_df["date"] = pd.to_datetime(price_df["date"])
    price_df = price_df.sort_values("date")

    fig = go.Figure()

    # Historical prices
    fig.add_trace(go.Scatter(
        x=price_df["date"], y=price_df["close"],
        name="Historical Price",
        line=dict(color="#4fc3f7", width=2),
        mode="lines",
    ))

    # Forecast points
    last_date = price_df["date"].max()
    forecast_points = []
    for label, key in horizons:
        days_map = {"7d": 7, "14d": 14, "1m": 30, "3m": 90, "6m": 180, "1y": 365}
        days = days_map[key]
        fc_date = last_date + pd.Timedelta(days=days)
        fc_price = forecast.get(f"forecast_{key}_price")
        fc_upper = forecast.get(f"forecast_{key}_upper")
        fc_lower = forecast.get(f"forecast_{key}_lower")
        if fc_price:
            forecast_points.append((fc_date, fc_price, fc_upper, fc_lower, label))

    if forecast_points:
        fc_df = pd.DataFrame(forecast_points, columns=["date", "price", "upper", "lower", "label"])

        # Confidence band
        if fc_df["upper"].notna().any():
            fig.add_trace(go.Scatter(
                x=pd.concat([fc_df["date"], fc_df["date"][::-1]]),
                y=pd.concat([fc_df["upper"], fc_df["lower"][::-1]]),
                fill="toself",
                fillcolor="rgba(255, 193, 7, 0.15)",
                line=dict(color="rgba(255, 193, 7, 0)"),
                name="Confidence Interval (80%)",
            ))

        # Forecast line
        # Add a bridging point from last historical to first forecast
        bridge_x = [last_date] + list(fc_df["date"])
        bridge_y = [float(price_df["close"].iloc[-1])] + list(fc_df["price"])

        fig.add_trace(go.Scatter(
            x=bridge_x, y=bridge_y,
            name="ML Forecast",
            line=dict(color="#f0a500", width=2, dash="dash"),
            mode="lines+markers",
            marker=dict(size=8),
        ))

        # Label each forecast point
        for _, row in fc_df.iterrows():
            fig.add_annotation(
                x=row["date"], y=row["price"],
                text=f"₹{row['price']:,.0f}",
                showarrow=True, arrowhead=2, arrowsize=1,
                arrowcolor="#f0a500",
                font=dict(size=10, color="#f0a500"),
                ax=0, ay=-30,
            )

    # Vertical line at "today"
    fig.add_vline(x=last_date, line_dash="dot", line_color="#666", annotation_text="Today")

    fig.update_layout(
        title=f"{selected_symbol} — Price History & ML Forecast",
        height=550,
        paper_bgcolor="#0e1117", plot_bgcolor="#1a1d23",
        font=dict(color="#e0e0e0"),
        legend=dict(orientation="h"),
        yaxis_title="Price (₹)",
        xaxis_title="Date",
    )
    fig.update_yaxes(gridcolor="#2d3139")
    fig.update_xaxes(gridcolor="#2d3139")
    st.plotly_chart(fig, use_container_width=True)

# ── Model Info ────────────────────────────────────────────────────────────────
st.caption(
    f"Model: **{forecast.get('model_used', 'Prophet')}** | "
    f"Training data: **{forecast.get('data_points_used', '—')} days** | "
    f"Generated: **{forecast.get('generated_date', '—')}**"
)
st.warning("⚠️ Forecasts are probabilistic estimates, not guarantees. Use with other analysis.")
