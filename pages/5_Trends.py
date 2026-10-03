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
try:
    st.set_page_config(page_title="Trend Forecasts", page_icon="📉", layout="wide")
except Exception:
    pass

from db.database import get_global_engine, get_session
from sqlalchemy import text
from core.ui_components import render_clean_html, fmt_inr
from core.ml_models import compute_ml_ensemble_consensus
from core.trade_optimizer import compute_empirical_strategy_projections
from core.backtester import find_champion_strategy

engine = get_global_engine()

st.title("📉 Trend Forecasts & Predictive Intelligence")
st.caption("Institutional Multi-Horizon Forecasting: Facebook Prophet Time-Series, 5-Algorithm ML Ensemble, and Empirical Champion Trajectories.")

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

# Header Card
render_clean_html(f"""
<div style="background: linear-gradient(135deg, #10141e, #171b26); border: 1px solid #1e293b; border-left: 5px solid #00eefc; padding: 14px 20px; border-radius: 8px; margin-bottom: 16px;">
    <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap;">
        <div>
            <span style="font-size: 1.4em; font-weight: 800; color: #ffffff; font-family: 'Space Grotesk', sans-serif;">{selected_symbol}</span>
            <span style="font-size: 1.1em; color: #00eefc; margin-left: 8px; font-weight: 600;">{asset_name}</span>
            <div style="font-size: 0.85em; color: #94a3b8; margin-top: 4px;">📂 Sector / Category: <b style="color: #e0e8f0;">{asset_sector}</b></div>
        </div>
        <div style="text-align: right;">
            <span style="font-size: 0.85em; color: #94a3b8;">Primary Model</span><br>
            <span style="background: rgba(0, 238, 252, 0.15); color: #00eefc; padding: 4px 10px; border-radius: 4px; font-weight: 700; font-size: 0.9em; border: 1px solid rgba(0, 238, 252, 0.3);">
                {forecast.get('model_used', 'Prophet')}
            </span>
        </div>
    </div>
</div>
""")

current_price_row = prices[0] if prices else None
current_price = current_price_row[1] if current_price_row else 0

horizons = [
    ("7 Days", "7d"), ("14 Days", "14d"), ("1 Month", "1m"),
    ("3 Months", "3m"), ("6 Months", "6m"), ("1 Year", "1y"),
]

# Precompute Champion and ML Ensemble before tabs
session = get_session(engine)
try:
    champion_data = find_champion_strategy(selected_symbol, session, years=3)
finally:
    session.close()

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

# Master Tabs
t_prophet, t_ensemble, t_champion, t_comparison = st.tabs([
    "📊 Multi-Horizon Prophet Forecast",
    "🧠 5-Model ML Ensemble Consensus",
    "🏆 Empirical Champion Trajectory",
    "⚖️ Head-to-Head Model Comparison"
])

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1: Multi-Horizon Prophet Forecast
# ═══════════════════════════════════════════════════════════════════════════════
with t_prophet:
    st.subheader("🎯 Multi-Horizon Statistical Projections")
    cols = st.columns(6)
    for col, (label, key) in zip(cols, horizons):
        price = forecast.get(f"forecast_{key}_price")
        chg = forecast.get(f"forecast_{key}_change_pct")
        upper = forecast.get(f"forecast_{key}_upper")
        lower = forecast.get(f"forecast_{key}_lower")

        if price:
            delta_color = "normal" if (chg or 0) > 0 else "inverse"
            col.metric(
                label,
                fmt_inr(price),
                f"{chg:+.2f}%" if chg is not None else None,
                delta_color=delta_color,
            )
            if lower and upper:
                col.caption(f"{fmt_inr(lower)} – {fmt_inr(upper)}")
        else:
            col.metric(label, "N/A")

    st.markdown("---")

    # Interactive Trend Chart
    if prices:
        price_df = pd.DataFrame(prices, columns=["date", "close"])
        price_df["date"] = pd.to_datetime(price_df["date"])
        price_df = price_df.sort_values("date")

        fig = go.Figure()

        # Historical line
        fig.add_trace(go.Scatter(
            x=price_df["date"], y=price_df["close"],
            name="Historical Price",
            line=dict(color="#00eefc", width=2),
            mode="lines",
        ))

        # Forecast points
        last_date = price_df["date"].max()
        forecast_points = []
        days_map = {"7d": 7, "14d": 14, "1m": 30, "3m": 90, "6m": 180, "1y": 365}
        for label, key in horizons:
            days = days_map[key]
            fc_date = last_date + pd.Timedelta(days=days)
            fc_price = forecast.get(f"forecast_{key}_price")
            fc_upper = forecast.get(f"forecast_{key}_upper")
            fc_lower = forecast.get(f"forecast_{key}_lower")
            if fc_price:
                forecast_points.append((fc_date, fc_price, fc_upper, fc_lower, label))

        if forecast_points:
            fc_df = pd.DataFrame(forecast_points, columns=["date", "price", "upper", "lower", "label"])

            # 80% Confidence band
            if fc_df["upper"].notna().any():
                fig.add_trace(go.Scatter(
                    x=pd.concat([fc_df["date"], fc_df["date"][::-1]]),
                    y=pd.concat([fc_df["upper"], fc_df["lower"][::-1]]),
                    fill="toself",
                    fillcolor="rgba(245, 158, 11, 0.15)",
                    line=dict(color="rgba(245, 158, 11, 0)"),
                    name="Confidence Band (80%)",
                ))

            # Forecast line
            bridge_x = [last_date] + list(fc_df["date"])
            bridge_y = [float(price_df["close"].iloc[-1])] + list(fc_df["price"])

            fig.add_trace(go.Scatter(
                x=bridge_x, y=bridge_y,
                name="Prophet Trend Trajectory",
                line=dict(color="#f59e0b", width=2.5, dash="dash"),
                mode="lines+markers",
                marker=dict(size=8, color="#f59e0b"),
            ))

            for _, row in fc_df.iterrows():
                fig.add_annotation(
                    x=row["date"], y=row["price"],
                    text=f"₹{row['price']:,.0f}",
                    showarrow=True, arrowhead=2, arrowsize=1,
                    arrowcolor="#f59e0b",
                    font=dict(size=10, color="#f59e0b", family="JetBrains Mono"),
                    ax=0, ay=-28,
                )

        fig.add_vline(x=last_date, line_dash="dot", line_color="#94a3b8", annotation_text="Present")

        fig.update_layout(
            title=f"📈 {selected_symbol} — Historical Price Action vs Multi-Horizon Forward Cone",
            height=500,
            paper_bgcolor="#10141e", plot_bgcolor="#171b26",
            font=dict(color="#e0e8f0"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            yaxis_title="Price (₹)",
            xaxis_title="Date",
        )
        fig.update_yaxes(gridcolor="#1e293b")
        fig.update_xaxes(gridcolor="#1e293b")
        st.plotly_chart(fig, use_container_width=True)

    st.caption(
        f"Model: **{forecast.get('model_used', 'Prophet')}** | "
        f"Training Sample: **{forecast.get('data_points_used', '—')} days** | "
        f"Generated: **{forecast.get('generated_date', '—')}**"
    )

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2: 5-Model ML Ensemble Consensus
# ═══════════════════════════════════════════════════════════════════════════════
with t_ensemble:
    st.subheader("🧠 5-Algorithm Machine Learning Ensemble")
    st.caption("Consensus of Gradient Boosting Machine (GBM), Random Forest, Ridge Regression, Holt-Winters Exponential Smoothing, and Monte Carlo Drift.")

    if ml_ens:
        conf_pct = ml_ens.get("ensemble_confidence_pct", 50)
        badge_color = "#00ff66" if conf_pct >= 60 else ("#ff2a5f" if conf_pct <= 40 else "#f59e0b")
        render_clean_html(f"""
        <div style="background: #171b26; border: 1px solid #1e293b; border-left: 5px solid {badge_color}; padding: 16px 20px; border-radius: 8px; margin-bottom: 16px;">
            <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap;">
                <div>
                    <span style="font-size: 1.15em; font-weight: 800; color: #ffffff;">5-Model Consensus Verdict:</span>
                    <span style="font-size: 1.15em; font-weight: 800; color: {badge_color}; margin-left: 6px;">{ml_ens['consensus_label']}</span>
                    <div style="font-size: 0.9em; color: #94a3b8; margin-top: 6px;">{ml_ens['consensus_description']}</div>
                </div>
                <div style="text-align: right;">
                    <span style="font-size: 0.85em; color: #94a3b8;">Directional Conviction</span><br>
                    <span style="font-size: 1.4em; font-weight: 800; color: {badge_color}; font-family: 'JetBrains Mono';">{conf_pct}%</span>
                </div>
            </div>
        </div>
        """)

        st.markdown("##### 🔬 Individual Algorithm Diagnostic Breakdown")
        df_models = pd.DataFrame(ml_ens["models"])
        st.dataframe(df_models, use_container_width=True, hide_index=True)
    else:
        st.info("Historical price series insufficient to calculate 5-model ensemble.")

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 3: Empirical Champion Strategy Trajectory
# ═══════════════════════════════════════════════════════════════════════════════
with t_champion:
    st.subheader("🏆 Backtested Alpha Champion Forward Trajectory")
    st.caption("Extrapolates returns using empirical win-rate, profit factor, and CAGR from the top-performing backtested strategy over 3 years.")

    if emp_proj:
        st.markdown(f"**Strategy Architecture:** `{emp_proj['strategy_name']}`")
        ep1, ep2, ep3, ep4, ep5 = st.columns(5)
        ep_data = [
            ("14 Days", emp_proj["proj_14d_price"], emp_proj["proj_14d_pct"]),
            ("1 Month", emp_proj["proj_1m_price"], emp_proj["proj_1m_pct"]),
            ("3 Months", emp_proj["proj_3m_price"], emp_proj["proj_3m_pct"]),
            ("6 Months", emp_proj["proj_6m_price"], emp_proj["proj_6m_pct"]),
            ("1 Year", emp_proj["proj_1y_price"], emp_proj["proj_1y_pct"]),
        ]
        for col, (horiz, pr, p_pct) in zip([ep1, ep2, ep3, ep4, ep5], ep_data):
            col.metric(horiz, fmt_inr(pr), f"{p_pct:+.2f}%", delta_color="normal" if p_pct > 0 else "inverse")

        if champ_data_obj:
            st.markdown("---")
            st.markdown("##### 🛡️ Champion Backtest Performance Metrics")
            bk1, bk2, bk3, bk4 = st.columns(4)
            bk1.metric("3Y Strategy CAGR", f"{champ_data_obj.get('cagr', 0)*100:.1f}%")
            bk2.metric("Win Rate", f"{champ_data_obj.get('win_rate', 0)*100:.1f}%")
            bk3.metric("Profit Factor", f"{champ_data_obj.get('profit_factor', 1.0):.2f}")
            bk4.metric("Max Drawdown", f"{champ_data_obj.get('max_drawdown', 0)*100:.1f}%", delta_color="inverse")
    else:
        st.info(f"No active champion strategy backtest available for {selected_symbol}.")

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 4: Head-to-Head Model Comparison
# ═══════════════════════════════════════════════════════════════════════════════
with t_comparison:
    st.subheader("⚖️ Head-to-Head Forecasting Matrix")
    st.caption("Compares Prophet trend projections against empirical champion strategy targets to identify model alignment.")

    comp_rows = []
    for label, key in [("14 Days", "14d"), ("1 Month", "1m"), ("3 Months", "3m"), ("6 Months", "6m"), ("1 Year", "1y")]:
        p_price = forecast.get(f"forecast_{key}_price")
        p_pct = forecast.get(f"forecast_{key}_change_pct")
        
        c_price = emp_proj.get(f"proj_{key}_price") if emp_proj else None
        c_pct = emp_proj.get(f"proj_{key}_pct") if emp_proj else None

        # Check alignment
        if p_pct is not None and c_pct is not None:
            if (p_pct > 0 and c_pct > 0) or (p_pct < 0 and c_pct < 0):
                verdict = "🟢 Strong Model Consensus"
            else:
                verdict = "🟡 Model Divergence"
        else:
            verdict = "ℹ️ Partial Data"

        comp_rows.append({
            "Horizon": label,
            "Prophet Target": fmt_inr(p_price) if p_price else "—",
            "Prophet Return": f"{p_pct:+.2f}%" if p_pct is not None else "—",
            "Champion Target": fmt_inr(c_price) if c_price else "—",
            "Champion Return": f"{c_pct:+.2f}%" if c_pct is not None else "—",
            "Synthesis Verdict": verdict
        })

    st.dataframe(pd.DataFrame(comp_rows), use_container_width=True, hide_index=True)
    st.warning("⚠️ Forecasts are probabilistic estimates, not financial guarantees. Combine with quantitative risk management and trailing stop losses.")

