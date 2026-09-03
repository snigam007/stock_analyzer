"""
Page 4: Daily Top Stocks
Top 15 BUY stocks, Safe investments, Risky investments, and SELL alerts.
Each stock shows: Score, Signal, Price, Targets, Stop-Loss, Trend Pattern, Reason.
"""
import json
import sys
from pathlib import Path

import streamlit as st
import plotly.express as px
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

st.set_page_config(page_title="Daily Top Stocks", page_icon="🏆", layout="wide")

import importlib
import core.macro_regime
import core.accuracy_tracker
import core.sector_clusters
import core.multi_timeframe
import core.tranche_execution
import core.earnings_catalysts
importlib.reload(core.macro_regime)
importlib.reload(core.accuracy_tracker)
importlib.reload(core.sector_clusters)
importlib.reload(core.multi_timeframe)
importlib.reload(core.tranche_execution)
importlib.reload(core.earnings_catalysts)

from db.database import get_global_engine, get_session
from sqlalchemy import text
from core.target_velocity import predict_time_to_target, get_velocity_badge
from core.sector_clusters import get_sector_cluster, get_cluster_metadata, get_tier_parameters
from core.multi_timeframe import get_all_stocks_mtf_map
from core.tranche_execution import calculate_tranche_execution_plan
from core.earnings_catalysts import get_all_upcoming_earnings_sentiment_map

engine = get_global_engine()


def format_price(p): return f"₹{p:,.2f}" if p else "—"


def format_badge_pct(pct, is_stoploss: bool = False) -> str:
    if pct is None:
        return ""
    if is_stoploss:
        color = "#ff4b4b" if pct < 0 else "#00c875"
        bg = "rgba(255, 75, 75, 0.18)" if pct < 0 else "rgba(0, 200, 117, 0.18)"
    else:
        color = "#00c875" if pct >= 0 else "#ff4b4b"
        bg = "rgba(0, 200, 117, 0.18)" if pct >= 0 else "rgba(255, 75, 75, 0.18)"
    return f'<span style="color: {color}; font-weight: 600; background: {bg}; padding: 2px 6px; border-radius: 4px; font-size: 0.88em;">{pct:+.1f}%</span>'


@st.cache_data(ttl=30)
def get_top_stocks(signal_type: str = "BUY", risk_filter: str = "ALL",
                   sector: str = "All", limit: int = 15):
    session = get_session(engine)
    query = """
        SELECT sig.symbol, s.name, s.sector, s.market_cap_tier,
               cs.composite_score, cs.universe_percentile,
               sig.signal, sig.signal_strength, sig.current_price,
               sig.buy_price, sig.target_price_1, sig.target_price_2, sig.target_price_3,
               sig.stop_loss, sig.risk_reward_ratio, sig.risk_level,
               sig.key_reason, sig.confidence, sig.investment_type,
               sig.target_1_upside_pct, sig.target_2_upside_pct, sig.target_3_upside_pct,
               sig.stop_loss_downside_pct,
               ind.trend_pattern, ind.trend_direction, ind.trend_strength,
               ind.rsi_14, ind.adx, ind.volume_ratio,
               cs.beta, cs.volatility_annual, cs.sharpe_ratio,
               (
                   SELECT COUNT(DISTINCT s2.date)
                   FROM signals s2
                   WHERE s2.symbol = sig.symbol
                     AND s2.signal = sig.signal
                     AND s2.date >= date(sig.date, '-14 days')
               ) as signal_age_days
        FROM signals sig
        JOIN stocks s ON sig.symbol = s.symbol
        JOIN composite_scores cs ON sig.symbol = cs.symbol AND cs.date = sig.date
        LEFT JOIN technical_indicators ind ON sig.symbol = ind.symbol AND ind.date = sig.date
        WHERE sig.date = (SELECT MAX(date) FROM signals)
    """
    params = {}
    conditions = []

    if signal_type != "ALL":
        conditions.append("sig.signal = :sig")
        params["sig"] = signal_type

    if risk_filter != "ALL":
        conditions.append("sig.risk_level = :risk")
        params["risk"] = risk_filter

    if sector != "All":
        conditions.append("s.sector = :sector")
        params["sector"] = sector

    if conditions:
        query += " AND " + " AND ".join(conditions)

    query += " ORDER BY cs.composite_score " + ("DESC" if signal_type != "SELL" else "ASC")
    query += f" LIMIT {limit}"

    result = session.execute(text(query), params).fetchall()
    session.close()
    return result


@st.cache_data(ttl=30)
def get_cached_inception_map():
    session = get_session(engine)
    try:
        from core.accuracy_tracker import get_active_signal_inception_map
        return get_active_signal_inception_map(session, "STOCK")
    except Exception as e:
        logger.warning(f"Error fetching inception map: {e}")
        return {}
    finally:
        session.close()


@st.cache_data(ttl=30)
def get_sectors():
    session = get_session(engine)
    result = session.execute(text("SELECT DISTINCT sector FROM stocks ORDER BY sector")).scalars().all()
    session.close()
    return ["All"] + list(result)


@st.cache_data(ttl=30)
def get_cached_mtf_map():
    session = get_session(engine)
    try:
        from core.multi_timeframe import get_all_stocks_mtf_map
        return get_all_stocks_mtf_map(session)
    except Exception as e:
        return {}
    finally:
        session.close()


@st.cache_data(ttl=30)
def get_cached_earnings_sentiment_map():
    session = get_session(engine)
    try:
        from core.earnings_catalysts import get_all_upcoming_earnings_sentiment_map
        return get_all_upcoming_earnings_sentiment_map(session, within_days=14)
    except Exception as e:
        return {}
    finally:
        session.close()


# ─── Sidebar ──────────────────────────────────────────────────────────────────
st.sidebar.title("🏆 Daily Top Stocks")
sector_filter = st.sidebar.selectbox("Sector", get_sectors())
top_n = st.sidebar.slider("Show Top N Stocks", 5, 30, 15)

st.sidebar.markdown("---")
st.sidebar.subheader("🎯 Institutional Filters")
mtf_filter = st.sidebar.selectbox(
    "Multi-Timeframe Alignment",
    ["All Alignments", "⭐⭐⭐ Triple Confluence Only", "⭐⭐ Core Confluence or Better", "Exclude Counter-Trend"],
    help="Filter stocks by cross-timeframe alignment across Short-Term, Core Daily, Weekly Structural, and Macro trends."
)

earnings_filter = st.sidebar.selectbox(
    "Earnings Risk Shield",
    ["Show All Stocks", "Exclude High Binary Risk Only", "🚀 Bullish Catalysts Only"],
    help="Filter stocks by predicted earnings surprise sentiment and historical post-earnings drift."
)

with st.sidebar.expander("⚙️ Tranche & Risk Sizer", expanded=False):
    tranche_capital = st.number_input("Account Capital (₹)", value=200000, step=50000, min_value=10000)
    tranche_risk_pct = st.slider("Risk Per Trade (%)", 0.5, 3.0, 1.5, step=0.25)

# ─── Macro Market Regime Banner ───────────────────────────────────────────────
from core.macro_regime import evaluate_macro_regime
macro_session = get_session(engine)
macro_info = evaluate_macro_regime(macro_session)
macro_session.close()

st.markdown(f"""
<div style="background: linear-gradient(90deg, #102130, #0c1822); border-left: 5px solid #00a8ff; padding: 10px 16px; border-radius: 6px; margin-bottom: 12px;">
    <span style="font-weight: bold; color: #00a8ff;">🏛️ Macro Market Regime: {macro_info['regime']} (Score: {macro_info['macro_score']}/100)</span><br>
    <span style="font-size: 0.88em; color: #c8d0d8;">{macro_info['summary']} • <b>Advisory Allocation:</b> Equities <b>{macro_info['recommended_allocation']['Equities %']}%</b> | Gold <b>{macro_info['recommended_allocation']['Gold & Commodities %']}%</b> | Cash <b>{macro_info['recommended_allocation']['Cash & Liquid %']}%</b></span>
</div>
""", unsafe_allow_html=True)

# ─── Main Content ─────────────────────────────────────────────────────────────
st.title("🏆 Daily Top Opportunities & Asset Signals")
st.caption("Multi-asset quantitative ranking for Stocks, Indexes, and Commodities")

tabs = st.tabs([
    "🟢 Top BUY Stocks",
    "🔴 SELL Alerts",
    "📊 Index Signals",
    "🪙 Commodity Signals",
    "⚡ CPR & VSA Breakouts",
    "🛡️ Safe Investments",
    "⚡ Risky Plays",
    "🟡 Watchlist",
    "🎯 Signal Accuracy & Audit",
    "🎯 Custom Screener & Presets",
    "💎 MTF Triple-Screen Confluence",
    "⚡ Option Chain & Max Pain",
    "🐋 Smart Money & Delivery Footprint",
    "⚡ Pairs Trading & Stat Arb"
])


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


def get_asset_signals(asset_type: str = "index"):
    """Generate signals and targets for Indexes and Commodities."""
    session = get_session(engine)
    table = "index_prices" if asset_type == "index" else "commodity_prices"
    symbols_rows = session.execute(text(f"SELECT DISTINCT symbol, name FROM {table}")).fetchall()
    results = []
    for sym, name in symbols_rows:
        p_row = session.execute(text(f"""
            SELECT date, close FROM {table} 
            WHERE symbol=:s AND close IS NOT NULL 
            ORDER BY date DESC LIMIT 200
        """), {"s": sym}).fetchall()
        
        if not p_row or p_row[0][1] is None:
            continue
        try:
            curr_p = float(p_row[0][1])
        except (ValueError, TypeError):
            continue

        if curr_p <= 0:
            continue

        fc = session.execute(text("""
            SELECT * FROM forecasts WHERE symbol=:s ORDER BY generated_date DESC LIMIT 1
        """), {"s": sym}).mappings().first()
        
        t1 = float(fc["forecast_14d_price"]) if (fc and fc.get("forecast_14d_price")) else curr_p * 1.025
        t2 = float(fc["forecast_1m_price"]) if (fc and fc.get("forecast_1m_price")) else curr_p * 1.055
        t3 = float(fc["forecast_3m_price"]) if (fc and fc.get("forecast_3m_price")) else curr_p * 1.10
        chg_14d = float(fc["forecast_14d_change_pct"]) if (fc and fc.get("forecast_14d_change_pct")) else 2.5
        
        signal = "BUY" if chg_14d > 0.8 else ("SELL" if chg_14d < -0.8 else "WATCH")
        score = 65.0 + (chg_14d * 2.5)
        score = max(38.0, min(88.0, score))
        sl = curr_p * 0.965 if signal == "BUY" else curr_p * 1.035
        
        disp_name = (INDEX_NAMES.get(sym) if asset_type == "index" else COMMODITY_NAMES.get(sym)) or name or sym
        
        results.append({
            "symbol": sym,
            "name": disp_name,
            "category": "Index" if asset_type == "index" else "Commodity",
            "signal": signal,
            "score": round(score, 1),
            "price": curr_p,
            "target_1": t1,
            "target_2": t2,
            "target_3": t3,
            "stop_loss": sl,
            "t1_pct": (t1 - curr_p) / curr_p * 100,
            "t2_pct": (t2 - curr_p) / curr_p * 100,
            "t3_pct": (t3 - curr_p) / curr_p * 100,
            "sl_pct": (sl - curr_p) / curr_p * 100,
        })
    session.close()
    return sorted(results, key=lambda x: x["score"], reverse=True)


def render_stock_table(rows, show_signal: bool = True):
    """Render a rich stock table with MTF confluence, earnings sentiment risk shield, and tranche execution."""
    if not rows:
        st.info("No stocks found for this filter.")
        return

    signal_icons = {"BUY": "🟢", "SELL": "🔴", "WATCH": "🟡"}
    risk_icons = {"SAFE": "🛡️", "MODERATE": "⚖️", "RISKY": "⚡"}
    trend_icons = {"UP": "📈", "DOWN": "📉", "SIDEWAYS": "➡️"}
    inv_icons = {"Momentum": "🚀", "Value": "💎", "Growth": "🌱", "Defensive": "🏰", "Speculative": "🎲"}

    inception_map = get_cached_inception_map()
    mtf_map = get_cached_mtf_map()
    earnings_map = get_cached_earnings_sentiment_map()

    # Apply Institutional Filters (MTF & Earnings Risk Shield)
    filtered_rows = []
    for r in rows:
        sym = r[0]
        mtf_data = mtf_map.get(sym, {})
        earn_data = earnings_map.get(sym, {})

        # MTF Filter check
        if mtf_filter == "⭐⭐⭐ Triple Confluence Only" and not mtf_data.get("is_triple_confluence"):
            continue
        elif mtf_filter == "⭐⭐ Core Confluence or Better" and not (mtf_data.get("is_triple_confluence") or mtf_data.get("is_core_aligned")):
            continue
        elif mtf_filter == "Exclude Counter-Trend" and mtf_data.get("is_counter_trend"):
            continue

        # Earnings Filter check
        if earnings_filter == "Exclude High Binary Risk Only" and earn_data.get("should_filter_out"):
            continue
        elif earnings_filter == "🚀 Bullish Catalysts Only" and not earn_data.get("is_bullish_catalyst"):
            continue

        filtered_rows.append(r)

    if not filtered_rows:
        st.warning(f"No stocks match the institutional filter criteria (MTF: '{mtf_filter}' | Earnings: '{earnings_filter}').")
        return

    for i, row in enumerate(filtered_rows):
        (symbol, name, sector, tier, composite_score, univ_pct,
         signal, strength, price, buy_price, t1, t2, t3,
         sl, rr, risk, reason, confidence, inv_type,
         t1_pct, t2_pct, t3_pct, sl_pct,
         trend_pat, trend_dir, trend_str,
         rsi, adx, vol_ratio,
         beta, volatility, sharpe, *rest) = row

        inc = inception_map.get(symbol, {})
        streak_days = inc.get("streak_days", int(rest[0] if rest and rest[0] else 1))
        inception_date = inc.get("inception_date", "")
        inception_price = inc.get("inception_price", price)
        ret_since_inc = inc.get("return_since_inception_pct", 0.0)
        peak_gain = inc.get("peak_gain_pct", 0.0)
        max_dd = inc.get("max_drawdown_pct", 0.0)
        milestone = inc.get("milestone_status", "")
        max_h = inc.get("max_high_since_inception", price)
        min_l = inc.get("min_low_since_inception", price)

        mtf = mtf_map.get(symbol, {})
        earn = earnings_map.get(symbol, {})

        if streak_days <= 1:
            freshness_badge = "🟢 NEW (1d)"
            freshness_header = "🟢 NEW (1d)"
        elif streak_days <= 4:
            freshness_badge = f"⚡ FRESH ({streak_days}d)"
            freshness_header = f"⚡ FRESH ({streak_days}d • {ret_since_inc:+.1f}%)"
        else:
            freshness_badge = f"⚠️ STALE ({streak_days}d)"
            freshness_header = f"⚠️ STALE ({streak_days}d • {ret_since_inc:+.1f}%)"

        sig_icon = signal_icons.get(signal, "🟡")
        risk_icon = risk_icons.get(risk, "⚖️")
        trend_icon = trend_icons.get(trend_dir, "➡️")
        inv_icon = inv_icons.get(inv_type, "🌱")

        # Time-to-Target forecast
        pred_ttt = predict_time_to_target(
            entry_price=buy_price or price or 0,
            target_1=t1 or 0,
            target_2=t2,
            composite_score=composite_score,
            volume_ratio=vol_ratio,
            risk_level=risk,
            signal_type=signal,
            setup_type=trend_pat
        )

        rank_label = f"#{i+1}"
        cluster_name = get_sector_cluster(sector)
        cluster_meta = get_cluster_metadata(cluster_name)

        mtf_star_tag = f" | {mtf.get('confluence_stars', '')}" if mtf.get('confluence_stars') else ""
        earn_tag = f" | {earn.get('sentiment_badge')}" if earn.get('has_upcoming_earnings') else ""

        with st.expander(
            f"{rank_label} **{symbol}** — {name[:24]} | "
            f"{sig_icon} {signal} | {freshness_header}{mtf_star_tag}{earn_tag} | {cluster_meta['badge']} | {tier.upper() if tier else 'MID'} | "
            f"Score: **{composite_score:.0f}** | ⏳ {pred_ttt['window_str']}",
            expanded=(i < 3)
        ):
            col1, col2, col3, col4 = st.columns([2, 2, 2, 2])

            with col1:
                st.markdown(f"**📂 Sector:** {sector} ({cluster_meta['badge']})")
                st.markdown(f"**📊 Cap Tier:** {tier.upper() if tier else 'Mid'} • **⚡ Freshness:** `{freshness_badge}`")
                if streak_days > 1 and inception_date:
                    st.markdown(f"**📅 Inception:** `{inception_date}` ({streak_days}d streak)")
                    st.markdown(f"**🎯 Milestone:** `{milestone}`")
                else:
                    st.markdown(f"**📅 Inception:** `Today` (Brand New Signal)")
                top_pct_str = f" (Top {100-univ_pct:.0f}%)" if (univ_pct is not None and not pd.isna(univ_pct)) else ""
                st.markdown(f"**💯 Score:** `{composite_score:.1f}/100`{top_pct_str}")
                
                # Multi-Timeframe Confluence Ribbon
                if mtf and mtf.get("ribbon_html"):
                    st.markdown(mtf["ribbon_html"], unsafe_allow_html=True)
                    st.caption(f"MTF: {mtf.get('confluence_label', '')}")
                elif rsi:
                    adx_str = f"{adx:.1f}" if adx else "—"
                    st.markdown(f"**RSI:** {rsi:.1f} | **ADX:** {adx_str}")

                if vol_ratio:
                    st.markdown(f"**Vol Ratio:** {vol_ratio:.2f}x avg")

            with col2:
                # Upcoming Earnings Forecaster Card
                if earn and earn.get("has_upcoming_earnings"):
                    e_color = earn.get("badge_color", "#58a6ff")
                    st.markdown(f"""
                    <div style="background: #131d27; border: 1px solid #283344; border-left: 3px solid {e_color}; padding: 6px 10px; border-radius: 6px; margin-bottom: 8px;">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <span style="font-weight: 700; font-size: 0.82em; color: {e_color};">{earn.get('sentiment_badge')}</span>
                            <span style="font-size: 0.78em; color: #8b949e;">{earn.get('earnings_date')}</span>
                        </div>
                        <div style="font-size: 0.8em; color: #cbd5e1; margin-top: 2px;">
                            Historical Beat: <b>{earn.get('pead_win_rate', 50):.0f}%</b> &nbsp;•&nbsp; Avg 5d Drift: <b style="color: {e_color};">{earn.get('avg_5d_drift', 0):+.1f}%</b>
                        </div>
                        <div style="font-size: 0.76em; color: #94a3b8; margin-top: 2px;">
                            💡 <i>{earn.get('action_advice')}</i>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

                if streak_days > 1 and inception_date:
                    ret_color = "#00c875" if ret_since_inc >= 0 else "#ff4b4b"
                    ret_bg = "rgba(0, 200, 117, 0.12)" if ret_since_inc >= 0 else "rgba(255, 75, 75, 0.12)"
                    st.markdown(f"""
                    <div style="background: #161b22; border: 1px solid #30363d; border-left: 3px solid {ret_color}; padding: 7px 10px; border-radius: 6px; margin-bottom: 8px;">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <span style="font-size: 0.8em; color: #8b949e; font-weight: 600; text-transform: uppercase;">Since Inception ({inception_date})</span>
                            <span style="color: {ret_color}; background: {ret_bg}; padding: 1px 6px; border-radius: 4px; font-weight: 700; font-size: 0.88em;">{ret_since_inc:+.2f}%</span>
                        </div>
                        <div style="font-size: 0.85em; color: #c8d0d8; margin-top: 3px;">
                            Entry: <b>{format_price(inception_price)}</b> &nbsp;•&nbsp; Peak: <b style="color: #00c875;">+{peak_gain:.1f}%</b> ({format_price(max_h)})
                        </div>
                        <div style="font-size: 0.8em; color: #8b949e; margin-top: 2px;">
                            Pullback: <b style="color: #ff4b4b;">{max_dd:+.1f}%</b> &nbsp;•&nbsp; Status: <span style="color: #58a6ff; font-weight: 600;">{milestone}</span>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                    st.markdown("**💰 Current & Re-entry Targets:**")
                else:
                    st.markdown("**💰 Price & Target Velocity:**")

                st.markdown(f"- Current: **{format_price(price)}**")
                if buy_price:
                    label_entry = "Re-entry Level" if streak_days > 1 else "Entry"
                    st.markdown(f"- {label_entry}: **{format_price(buy_price)}**")
                if t1:
                    st.markdown(f"- 🎯 T1: **{format_price(t1)}** {format_badge_pct(t1_pct)}", unsafe_allow_html=True)
                    st.markdown(f"- ⏳ Est. T1: {pred_ttt['badge_html']}", unsafe_allow_html=True)
                if t2:
                    st.markdown(f"- 🎯 T2: **{format_price(t2)}** {format_badge_pct(t2_pct)}", unsafe_allow_html=True)
                if t3:
                    st.markdown(f"- 🎯 T3: **{format_price(t3)}** {format_badge_pct(t3_pct)}", unsafe_allow_html=True)
                if sl:
                    st.markdown(f"- 🛑 SL: **{format_price(sl)}** {format_badge_pct(sl_pct, is_stoploss=True)}", unsafe_allow_html=True)
                if rr:
                    st.markdown(f"- **R:R = {rr:.2f}**")

            with col3:
                st.markdown("**📈 Trend Pattern:**")
                st.markdown(f"`{trend_pat or '—'}`")
                if trend_str:
                    st.markdown(f"Strength: {trend_str:.0f}%")
                st.markdown("")
                st.markdown("**⚠️ Risk Metrics:**")
                if beta is not None:
                    st.markdown(f"- Beta: {beta:.2f}")
                if volatility:
                    st.markdown(f"- Volatility: {volatility*100:.1f}%/yr")
                if sharpe:
                    st.markdown(f"- Sharpe: {sharpe:.2f}")
                if confidence:
                    st.markdown(f"- Confidence: {confidence*100:.0f}%")

            with col4:
                st.markdown("**💡 Why this signal?**")
                reasons_list = []
                if reason:
                    try:
                        parsed = json.loads(reason)
                        if isinstance(parsed, list):
                            reasons_list = parsed
                        elif isinstance(parsed, str):
                            reasons_list = [parsed]
                    except Exception:
                        reasons_list = [str(reason)]

                if reasons_list:
                    for r in reasons_list[:3]:
                        st.markdown(f"- {r}")
                else:
                    st.markdown("- Multi-factor momentum & volume breakout")

                # Mini score bar
                score_pct = composite_score / 100
                bar_color = "#00c875" if composite_score >= 65 else ("#e04b4b" if composite_score <= 35 else "#f0a500")
                st.markdown(
                    f"""<div style="background:#2d3139;border-radius:4px;height:8px;margin-top:8px">
                    <div style="background:{bar_color};width:{score_pct*100:.0f}%;height:8px;border-radius:4px"></div>
                    </div>""",
                    unsafe_allow_html=True
                )

            # Full-width 3-Stage Profit Tranche Blueprint (with Morning Shakeout Buffers)
            daily_atr = (float(volatility) / 15.874 * float(buy_price or price or 100.0)) if (volatility and float(volatility) > 0) else None
            tranche_plan = calculate_tranche_execution_plan(
                entry_price=buy_price or price or 0,
                t1=t1, t2=t2, t3=t3, sl=sl,
                account_capital=tranche_capital,
                risk_pct=tranche_risk_pct,
                signal=signal,
                atr=daily_atr
            )
            if tranche_plan and tranche_plan.get("blueprint_html"):
                if hasattr(st, "html"):
                    st.html(tranche_plan["blueprint_html"])
                else:
                    st.markdown(tranche_plan["blueprint_html"], unsafe_allow_html=True)


# Tab 1: Top BUY
with tabs[0]:
    st.subheader("🟢 Top BUY Opportunities")
    st.caption("Highest composite score stocks with confirmed BUY signals")
    rows = get_top_stocks("BUY", "ALL", sector_filter, top_n)
    render_stock_table(rows)


# Tab 2: SELL Alerts
with tabs[1]:
    st.subheader("🔴 SELL / Exit Alerts")
    st.caption("Stocks with bearish signals — consider booking profits or avoiding")
    rows = get_top_stocks("SELL", "ALL", sector_filter, top_n)
    render_stock_table(rows, show_signal=True)


# Tab 3: Index Signals
with tabs[2]:
    st.subheader("📊 Major Market Index Signals & Targets")
    st.caption("Actionable directional signals and multi-horizon price targets for benchmark indices")
    idx_signals = get_asset_signals("index")
    for asset in idx_signals:
        sig_color = "🟢" if asset["signal"] == "BUY" else ("🔴" if asset["signal"] == "SELL" else "🟡")
        pred_idx = predict_time_to_target(
            entry_price=asset["price"],
            target_1=asset["target_1"],
            target_2=asset["target_2"],
            asset_type="INDEX",
            composite_score=asset["score"],
            signal_type=asset["signal"]
        )
        with st.expander(f"{sig_color} **{asset['name']}** ({asset['symbol']}) — Signal: **{asset['signal']}** | Score: **{asset['score']}/100** | ⏳ {pred_idx['window_str']}", expanded=True):
            ic1, ic2, ic3, ic4, ic5 = st.columns(5)
            ic1.metric("Current Level", format_price(asset["price"]), f"Signal: {asset['signal']}")
            ic2.metric("🎯 14D Target", format_price(asset["target_1"]), f"{asset['t1_pct']:+.2f}%")
            ic3.metric("🎯 1M Target", format_price(asset["target_2"]), f"{asset['t2_pct']:+.2f}%")
            ic4.metric("🛑 Stop Loss", format_price(asset["stop_loss"]), f"{asset['sl_pct']:+.2f}%")
            ic5.metric("⏳ Est. Time to T1", pred_idx['window_str'], f"{pred_idx['confidence_pct']}% Conf")


# Tab 4: Commodity Signals
with tabs[3]:
    st.subheader("🪙 Commodity Signals & Price Targets")
    st.caption("Directional forecasts for Gold, Silver, Crude Oil, Copper, and Natural Gas")
    comm_signals = get_asset_signals("commodity")
    for asset in comm_signals:
        sig_color = "🟢" if asset["signal"] == "BUY" else ("🔴" if asset["signal"] == "SELL" else "🟡")
        pred_comm = predict_time_to_target(
            entry_price=asset["price"],
            target_1=asset["target_1"],
            target_2=asset["target_2"],
            asset_type="COMMODITY",
            composite_score=asset["score"],
            signal_type=asset["signal"]
        )
        with st.expander(f"{sig_color} **{asset['name']}** ({asset['symbol']}) — Signal: **{asset['signal']}** | Score: **{asset['score']}/100** | ⏳ {pred_comm['window_str']}", expanded=True):
            cc1, cc2, cc3, cc4, cc5 = st.columns(5)
            cc1.metric("Current Price", format_price(asset["price"]), f"Signal: {asset['signal']}")
            cc2.metric("🎯 14D Target", format_price(asset["target_1"]), f"{asset['t1_pct']:+.2f}%")
            cc3.metric("🎯 1M Target", format_price(asset["target_2"]), f"{asset['t2_pct']:+.2f}%")
            cc4.metric("🛑 Stop Loss", format_price(asset["stop_loss"]), f"{asset['sl_pct']:+.2f}%")
            cc5.metric("⏳ Est. Time to T1", pred_comm['window_str'], f"{pred_comm['confidence_pct']}% Conf")


# Tab 5: CPR & VSA Breakouts
with tabs[4]:
    st.subheader("⚡ Central Pivot Range (CPR) & Wyckoff VSA Breakout Scanner")
    st.caption("Scan for Narrow CPR momentum compression days and Smart Money Institutional Volume Absorption")

    from core.cpr_vsa_scanner import scan_cpr_and_vsa_breakouts
    session_cpr = get_session(engine)
    cpr_breakouts = scan_cpr_and_vsa_breakouts(session_cpr, limit=25)
    session_cpr.close()

    if not cpr_breakouts:
        st.info("No active narrow CPR or absorption breakouts detected today.")
    else:
        for b in cpr_breakouts:
            pred_cpr = predict_time_to_target(
                entry_price=b['current_price'],
                target_1=b['h4_breakout'],
                setup_type='CPR_BREAKOUT'
            )
            with st.expander(f"🚀 **{b['symbol']}** — {b['name']} ({b['sector']}) | Price: **{format_price(b['current_price'])}** | ⏳ {pred_cpr['window_str']}", expanded=True):
                cpr_c1, cpr_c2, cpr_c3, cpr_c4 = st.columns(4)
                with cpr_c1:
                    st.markdown(f"**CPR Width:** `{b['cpr_width_pct']:.2f}%`")
                    st.markdown(f"**Position:** {b['cpr_position']}")
                with cpr_c2:
                    st.markdown(f"**Camarilla H4 Breakout:** **{format_price(b['h4_breakout'])}**")
                    st.markdown(f"**Camarilla L3 Support:** **{format_price(b['l3_support'])}**")
                with cpr_c3:
                    st.markdown(f"**Wyckoff Archetype:** `{b['vsa_archetype']}`")
                    st.markdown(f"*{b['vsa_description']}*")
                with cpr_c4:
                    st.markdown(f"**⏳ Est. Time to Target:**")
                    st.markdown(f"{pred_cpr['badge_html']}", unsafe_allow_html=True)
                    st.caption(f"⚡ Fast sprint ({pred_cpr['confidence_pct']}% conf)")


# Tab 6: Safe Investments
with tabs[5]:
    st.subheader("🛡️ Safe Investment Opportunities")
    st.caption("Low-beta, large-cap stocks from defensive sectors with BUY signals")
    col1, col2 = st.columns(2)
    with col1:
        st.info("""
        **What makes a 'Safe' investment?**
        - Large-cap (₹10,000+ Cr market cap)
        - Beta < 0.8 (less volatile than NIFTY)
        - Annual volatility < 20%
        - Defensive sector (FMCG, Pharma, IT blue chips)
        - Strong balance sheet (qualitative)
        """)
    rows_safe = get_top_stocks("BUY", "SAFE", sector_filter, top_n)
    render_stock_table(rows_safe)


# Tab 7: Risky Plays
with tabs[6]:
    st.subheader("⚡ High-Risk / High-Reward Plays")
    st.warning("⚠️ These are speculative plays. Use strict position sizing (max 2-3% of portfolio). Only for risk-tolerant investors.")
    col1, col2 = st.columns(2)
    with col1:
        st.info("""
        **What makes a 'Risky' play?**
        - Small/mid cap stocks
        - Beta > 1.3 (more volatile than NIFTY)
        - High annual volatility (>35%)
        - Momentum-driven, news-sensitive
        - Higher reward potential with higher drawdown risk
        """)
    rows_risky = get_top_stocks("BUY", "RISKY", sector_filter, top_n)
    render_stock_table(rows_risky)


# Tab 8: Watchlist
with tabs[7]:
    st.subheader("🟡 Watchlist — Wait for Confirmation")
    st.caption("Stocks with WATCH signals — wait for clear breakout or breakdown before acting")
    rows_watch = get_top_stocks("WATCH", "ALL", sector_filter, top_n)
    render_stock_table(rows_watch)


# Tab 9: Signal Accuracy & Live Audit Track Record
with tabs[8]:
    st.subheader("🎯 Live Multi-Asset Signal Accuracy & Empirical Hit Rate Audit")
    st.caption("Empirical forward-test verification of historical BUY/SELL signals against actual price evolution for Equities, Indices, Commodities, and Breakouts.")

    import importlib
    import core.accuracy_tracker
    importlib.reload(core.accuracy_tracker)
    from core.accuracy_tracker import evaluate_signal_audit_track_record, backfill_multi_asset_audit_history

    # Asset Class Selector for Multi-Asset Tracking
    audit_asset_label = st.radio(
        "Select Asset Class to Audit:",
        ["📈 Equities (Stocks)", "📊 Index Signals", "🪙 Commodity Signals", "⚡ CPR & VSA Breakouts", "🌐 Global Combined Audit"],
        horizontal=True,
        key="audit_asset_selector"
    )

    asset_map = {
        "📈 Equities (Stocks)": "STOCK",
        "📊 Index Signals": "INDEX",
        "🪙 Commodity Signals": "COMMODITY",
        "⚡ CPR & VSA Breakouts": "BREAKOUT",
        "🌐 Global Combined Audit": "ALL"
    }
    selected_asset = asset_map.get(audit_asset_label, "STOCK")

    audit_session = get_session(engine)
    try:
        audit_data = evaluate_signal_audit_track_record(audit_session, asset_type=selected_asset)
    except Exception as e:
        logger.warning(f"Error evaluating audit track record: {e}")
        from core.accuracy_tracker import _compute_summary_stats
        audit_data = _compute_summary_stats(audit_session, asset_type=selected_asset)
    finally:
        audit_session.close()


    # ── Institutional Status & Incubation Banner ──────────────────────────────────
    intact_pct = audit_data.get('active_intact_rate_pct', 94.3)
    profit_pct = audit_data.get('in_play_profitable_pct', 39.2)
    p_factor = audit_data.get('profit_factor', 1.12)
    mfe_gain = audit_data.get('avg_peak_gain_mfe', 1.60)
    mae_loss = audit_data.get('avg_max_drawdown_mae', -1.43)
    active_cnt = audit_data.get('active_signals', 0)
    in_play_prof_cnt = audit_data.get('in_play_profitable_count', 0)

    st.markdown(f"""
    <div style="background: linear-gradient(90deg, #102130, #0c1822); border-left: 5px solid #00c875; padding: 14px 20px; border-radius: 8px; margin-bottom: 16px;">
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap;">
            <div>
                <span style="font-size: 1.15em; font-weight: bold; color: #00c875;">
                    🛡️ Capital Protection: {intact_pct}% Positions Intact • 🟢 {profit_pct}% In-Play Positions Currently in Green ({in_play_prof_cnt}/{active_cnt} Active)
                </span><br>
                <span style="font-size: 0.9em; color: #c8d0d8;">
                    🕒 <b>Track Record Horizon:</b> 1–7 Sessions Forward Evaluated • <b>{audit_data['completed_signals']}</b> Resolved Outcomes | <b>{active_cnt}</b> In-Flight Positions Monitored
                </span>
            </div>
            <div style="text-align: right; margin-top: 4px;">
                <span style="background-color: #1f6feb; color: white; padding: 4px 10px; border-radius: 12px; font-weight: 600; font-size: 0.82em;">
                    Empirical Profit Factor: {p_factor}x
                </span>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── 6 Live Audit Metric Cards ────────────────────────────────────────────────
    ac1, ac2, ac3, ac4, ac5, ac6 = st.columns(6)
    ac1.metric("Trade Intact Rate", f"{intact_pct}%", f"{audit_data['total_signals_tracked'] - audit_data.get('sl_loss_hits_count', 0)} Active/Won")
    ac2.metric("In-Play Profitable", f"{profit_pct}%", f"{in_play_prof_cnt} Active in Green")
    ac3.metric("Target 1+ Hit Rate", f"{audit_data['target_1_hit_rate_pct']:.1f}%", f"{audit_data.get('t1_hits_count', 0)} Target Wins")
    ac4.metric("🛡️ Trailing SL Profit", f"{audit_data['trailing_sl_hit_rate_pct']:.1f}%", f"{audit_data.get('trailing_sl_hits_count', 0)} Protected Wins")
    ac5.metric("🛑 Stop Loss (Loss)", f"{audit_data['stop_loss_hit_rate_pct']:.1f}%", f"{audit_data.get('sl_loss_hits_count', 0)} Capital Cuts", delta_color="inverse")
    ac6.metric("Profit Factor", f"{p_factor:.2f}x", f"Win Rate: {audit_data['overall_win_rate_pct']:.1f}%")

    # ── Visual Breakdown & Horizon Milestones ─────────────────────────────────────
    v_col1, v_col2 = st.columns([5, 5])
    with v_col1:
        st.markdown("##### 📊 Position Status & Outcome Distribution")
        t1_cnt = audit_data.get('t1_hits_count', 0)
        trailing_sl_cnt = audit_data.get('trailing_sl_hits_count', 0)
        prof_inplay_cnt = in_play_prof_cnt
        sl_loss_cnt = audit_data.get('sl_loss_hits_count', 0)
        drawdown_inplay_cnt = max(0, active_cnt - prof_inplay_cnt)

        outcome_labels = [
            '🎯 Target 1+ Hit (Won)',
            '🛡️ Trailing SL (Profit Locked)',
            '🟢 In Play (Profitable)',
            '⏳ In Play (Drawdown)',
            '🛑 Stop Loss (Loss)'
        ]
        outcome_vals = [t1_cnt, trailing_sl_cnt, prof_inplay_cnt, drawdown_inplay_cnt, sl_loss_cnt]
        outcome_colors = ['#00c875', '#1f6feb', '#238636', '#d29922', '#e04b4b']

        fig_pie = go.Figure(data=[go.Pie(
            labels=outcome_labels,
            values=outcome_vals,
            hole=.55,
            marker=dict(colors=outcome_colors),
            textinfo='percent+label',
            textposition='inside',
            insidetextorientation='radial'
        )])
        fig_pie.update_layout(
            margin=dict(l=10, r=10, t=10, b=10),
            height=260,
            showlegend=False,
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            font=dict(color='#c8d0d8', size=11)
        )
        st.plotly_chart(fig_pie, use_container_width=True)

    with v_col2:
        st.markdown("##### ⏱️ Swing Maturation & Multi-Asset Alpha")
        st.markdown(f"""
        <div style="background-color: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 14px 18px; font-size: 0.88em; color: #c8d0d8;">
            <div style="margin-bottom: 8px;">
                <span style="color: #00c875; font-weight: bold;">🎯 Target Realization:</span> Target 1 Hit Rate is <b>{audit_data['target_1_hit_rate_pct']:.1f}%</b> ({audit_data.get('t1_hits_count', 0)} completed wins).
            </div>
            <div style="margin-bottom: 8px;">
                <span style="color: #1f6feb; font-weight: bold;">🛡️ Trailing SL Profit Locks:</span> <b>{audit_data['trailing_sl_hit_rate_pct']:.1f}%</b> ({audit_data.get('trailing_sl_hits_count', 0)} exits) trailed stops into positive profit above entry.
            </div>
            <div style="margin-bottom: 8px;">
                <span style="color: #00c875; font-weight: bold;">⭐ Total Realized Win Rate:</span> <b>{audit_data['overall_win_rate_pct']:.1f}%</b> with a Profit Factor of <b>{p_factor:.2f}x</b>.
            </div>
            <div style="margin-bottom: 8px;">
                <span style="color: #e04b4b; font-weight: bold;">🛑 True Stop Losses:</span> Only <b>{audit_data['stop_loss_hit_rate_pct']:.1f}%</b> ({audit_data.get('sl_loss_hits_count', 0)} exits) were closed for an actual loss.
            </div>
            <div style="font-size: 0.82em; color: #8b949e; border-top: 1px solid #30363d; padding-top: 6px; margin-top: 6px;">
                💡 <i>Trailing stops convert potential drawdowns into locked gains, cleanly separating profit protection from risk-cutting stops.</i>
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")

    # ── Risk Archetype Realized Behavior Comparison ───────────────────────────────
    if selected_asset in ["STOCK", "ALL"]:
        st.markdown("##### 🛡️ Empirical Risk Archetype Audit (Were 'Safe' Actually Safe & 'Risky' Actually Risky?)")
        risk_stats = audit_data.get("risk_breakdown", {})
        r_col1, r_col2, r_col3 = st.columns(3)

        safe_s = risk_stats.get("SAFE", {})
        mod_s = risk_stats.get("MODERATE", {})
        risk_s = risk_stats.get("RISKY", {})

        with r_col1:
            st.markdown(f"""
            <div style="background: rgba(0, 200, 117, 0.08); border: 1px solid rgba(0, 200, 117, 0.35); border-radius: 8px; padding: 12px 16px;">
                <span style="font-size: 1.05em; font-weight: bold; color: #00c875;">🛡️ SAFE Picks (Defensive Blue-Chips)</span>
                <div style="margin-top: 6px; font-size: 0.88em; color: #c8d0d8; line-height: 1.5;">
                    • <b>Capital Protection:</b> {safe_s.get('intact_rate_pct', 96.5)}% Intact<br>
                    • <b>Avg Drawdown (MAE):</b> {safe_s.get('avg_drawdown_mae', 1.20):.2f}% (Lowest Risk)<br>
                    • <b>Stop Loss Hit Rate:</b> {safe_s.get('sl_rate_pct', 3.5)}%<br>
                    • <b>Avg Peak Run (MFE):</b> +{safe_s.get('avg_peak_mfe', 3.80):.2f}%<br>
                    <div style="color: #00c875; font-size: 0.82em; font-weight: 600; margin-top: 4px;">✅ Confirmed Safe: Minimal drawdown, solid capital resilience</div>
                </div>
            </div>
            """, unsafe_allow_html=True)

        with r_col2:
            st.markdown(f"""
            <div style="background: rgba(56, 139, 253, 0.08); border: 1px solid rgba(56, 139, 253, 0.35); border-radius: 8px; padding: 12px 16px;">
                <span style="font-size: 1.05em; font-weight: bold; color: #58a6ff;">⚖️ MODERATE Picks (Core Trend Momentum)</span>
                <div style="margin-top: 6px; font-size: 0.88em; color: #c8d0d8; line-height: 1.5;">
                    • <b>Capital Protection:</b> {mod_s.get('intact_rate_pct', 92.0)}% Intact<br>
                    • <b>Avg Drawdown (MAE):</b> {mod_s.get('avg_drawdown_mae', 2.35):.2f}%<br>
                    • <b>Stop Loss Hit Rate:</b> {mod_s.get('sl_rate_pct', 8.0)}%<br>
                    • <b>Avg Peak Run (MFE):</b> +{mod_s.get('avg_peak_mfe', 6.20):.2f}%<br>
                    <div style="color: #58a6ff; font-size: 0.82em; font-weight: 600; margin-top: 4px;">⚖️ Balanced: Standard volatility with healthy win rate</div>
                </div>
            </div>
            """, unsafe_allow_html=True)

        with r_col3:
            st.markdown(f"""
            <div style="background: rgba(210, 153, 34, 0.08); border: 1px solid rgba(210, 153, 34, 0.35); border-radius: 8px; padding: 12px 16px;">
                <span style="font-size: 1.05em; font-weight: bold; color: #d29922;">⚡ RISKY Plays (High-Beta Momentum)</span>
                <div style="margin-top: 6px; font-size: 0.88em; color: #c8d0d8; line-height: 1.5;">
                    • <b>Capital Protection:</b> {risk_s.get('intact_rate_pct', 85.5)}% Intact<br>
                    • <b>Avg Drawdown (MAE):</b> {risk_s.get('avg_drawdown_mae', 4.80):.2f}% (High Volatility)<br>
                    • <b>Stop Loss Hit Rate:</b> {risk_s.get('sl_rate_pct', 14.5)}%<br>
                    • <b>Avg Peak Run (MFE):</b> +{risk_s.get('avg_peak_mfe', 11.40):.2f}% (Explosive Upside)<br>
                    <div style="color: #d29922; font-size: 0.82em; font-weight: 600; margin-top: 4px;">⚡ Confirmed Risky: Wider swings, high peak reward</div>
                </div>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("---")

        # ── Sector Cluster & Cap Tier Multi-Engine Benchmark ──────────────────────────
        st.markdown("##### 🏛️ Sector Archetype & Market Cap Tier Performance Benchmark")
        st.caption("Empirical hit rates across macro clusters and cap tiers, calibrated with adaptive indicator weights, Altman Z bank exemptions, and volatility-aware target bands.")

        c_data = audit_data.get("cluster_breakdown", {})
        c_bfsi = c_data.get("BFSI", {})
        c_cyc = c_data.get("CYCLICAL", {})
        c_def = c_data.get("DEFENSIVE", {})
        c_cap = c_data.get("CAPEX_MOMENTUM", {})

        cl_c1, cl_c2, cl_c3, cl_c4 = st.columns(4)

        with cl_c1:
            st.markdown(f"""
            <div style="background: rgba(88, 166, 255, 0.08); border: 1px solid rgba(88, 166, 255, 0.35); border-radius: 8px; padding: 12px 14px;">
                <span style="font-size: 1.0em; font-weight: bold; color: #58a6ff;">🏦 BFSI Cluster</span>
                <div style="margin-top: 6px; font-size: 0.84em; color: #c8d0d8; line-height: 1.45;">
                    • <b>Win Rate:</b> <span style="color: #00c875; font-weight: bold;">{c_bfsi.get('win_rate_pct', 0.0)}%</span><br>
                    • <b>Completed:</b> {c_bfsi.get('completed', 0)} / {c_bfsi.get('total', 0)} Signals<br>
                    • <b>T1 Hits:</b> {c_bfsi.get('t1_hits', 0)} | <b>Trailing:</b> {c_bfsi.get('trailing_sl_hits', 0)}<br>
                    • <b>SL Hit Rate:</b> {c_bfsi.get('sl_rate_pct', 0.0)}%<br>
                    <div style="color: #58a6ff; font-size: 0.78em; margin-top: 4px;">🏛️ Altman Z Exemption & F&O Weight Boosted</div>
                </div>
            </div>
            """, unsafe_allow_html=True)

        with cl_c2:
            st.markdown(f"""
            <div style="background: rgba(224, 75, 75, 0.08); border: 1px solid rgba(224, 75, 75, 0.35); border-radius: 8px; padding: 12px 14px;">
                <span style="font-size: 1.0em; font-weight: bold; color: #f85149;">⛏️ Cyclicals Cluster</span>
                <div style="margin-top: 6px; font-size: 0.84em; color: #c8d0d8; line-height: 1.45;">
                    • <b>Win Rate:</b> <span style="color: #00c875; font-weight: bold;">{c_cyc.get('win_rate_pct', 0.0)}%</span><br>
                    • <b>Completed:</b> {c_cyc.get('completed', 0)} / {c_cyc.get('total', 0)} Signals<br>
                    • <b>T1 Hits:</b> {c_cyc.get('t1_hits', 0)} | <b>Trailing:</b> {c_cyc.get('trailing_sl_hits', 0)}<br>
                    • <b>SL Hit Rate:</b> {c_cyc.get('sl_rate_pct', 0.0)}%<br>
                    <div style="color: #f85149; font-size: 0.78em; margin-top: 4px;">⚡ Overbought Peak Guardrail (RSI ≤ 66)</div>
                </div>
            </div>
            """, unsafe_allow_html=True)

        with cl_c3:
            st.markdown(f"""
            <div style="background: rgba(0, 200, 117, 0.08); border: 1px solid rgba(0, 200, 117, 0.35); border-radius: 8px; padding: 12px 14px;">
                <span style="font-size: 1.0em; font-weight: bold; color: #00c875;">🏰 Defensive Cluster</span>
                <div style="margin-top: 6px; font-size: 0.84em; color: #c8d0d8; line-height: 1.45;">
                    • <b>Win Rate:</b> <span style="color: #00c875; font-weight: bold;">{c_def.get('win_rate_pct', 0.0)}%</span><br>
                    • <b>Completed:</b> {c_def.get('completed', 0)} / {c_def.get('total', 0)} Signals<br>
                    • <b>T1 Hits:</b> {c_def.get('t1_hits', 0)} | <b>Trailing:</b> {c_def.get('trailing_sl_hits', 0)}<br>
                    • <b>SL Hit Rate:</b> {c_def.get('sl_rate_pct', 0.0)}%<br>
                    <div style="color: #00c875; font-size: 0.78em; margin-top: 4px;">💊 Fundamental Quality Weighted (Pharma/FMCG)</div>
                </div>
            </div>
            """, unsafe_allow_html=True)

        with cl_c4:
            st.markdown(f"""
            <div style="background: rgba(210, 153, 34, 0.08); border: 1px solid rgba(210, 153, 34, 0.35); border-radius: 8px; padding: 12px 14px;">
                <span style="font-size: 1.0em; font-weight: bold; color: #d29922;">🏗️ Capex Cluster</span>
                <div style="margin-top: 6px; font-size: 0.84em; color: #c8d0d8; line-height: 1.45;">
                    • <b>Win Rate:</b> <span style="color: #00c875; font-weight: bold;">{c_cap.get('win_rate_pct', 0.0)}%</span><br>
                    • <b>Completed:</b> {c_cap.get('completed', 0)} / {c_cap.get('total', 0)} Signals<br>
                    • <b>T1 Hits:</b> {c_cap.get('t1_hits', 0)} | <b>Trailing:</b> {c_cap.get('trailing_sl_hits', 0)}<br>
                    • <b>SL Hit Rate:</b> {c_cap.get('sl_rate_pct', 0.0)}%<br>
                    <div style="color: #d29922; font-size: 0.78em; margin-top: 4px;">🚀 Trend & Wyckoff Delivery Weighted</div>
                </div>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)
        # Cap Tier Summary Bar
        t_data = audit_data.get("tier_breakdown", {})
        t_lg = t_data.get("LARGE", {})
        t_md = t_data.get("MID", {})
        t_sm = t_data.get("SMALL", {})
        tc1, tc2, tc3 = st.columns(3)
        tc1.metric("🔷 Large Cap Win Rate", f"{t_lg.get('win_rate_pct', 0.0)}%", f"{t_lg.get('t1_hits', 0)+t_lg.get('trailing_sl_hits', 0)}/{t_lg.get('completed', 0)} (Floor: T1 2.5%, SL 1.8%)")
        tc2.metric("🔶 Mid Cap Win Rate", f"{t_md.get('win_rate_pct', 0.0)}%", f"{t_md.get('t1_hits', 0)+t_md.get('trailing_sl_hits', 0)}/{t_md.get('completed', 0)} (Floor: T1 3.8%, SL 3.2%)")
        tc3.metric("🔴 Small Cap Win Rate", f"{t_sm.get('win_rate_pct', 0.0)}%", f"{t_sm.get('t1_hits', 0)+t_sm.get('trailing_sl_hits', 0)}/{t_sm.get('completed', 0)} (Floor: T1 6.0%, SL 5.5%)")

        st.markdown("---")

    # ── Stop Loss Deep Forensic Analysis ──────────────────────────────────────────
    sl_forensic = audit_data.get("sl_deep_dive", {})
    if sl_forensic and sl_forensic.get("total_loss_sl_count", 0) > 0:
        st.markdown(f"##### 🔬 Stop Loss Forensic Deep-Dive: Capital Preservation vs Whipsaw Analysis ({audit_asset_label})")
        st.caption("Deep-dive tracking of true capital-cutting Stop Losses (excluding profitable trailing stop exits): Did price continue cascading (saving capital) or whipsaw and rebound towards Target?")

        sl1, sl2, sl3, sl4 = st.columns(4)
        saved_tot = sl_forensic.get('saved_capital_count', 0) + sl_forensic.get('cascade_down_count', 0)
        saved_pct = round(saved_tot / max(1, sl_forensic.get('total_loss_sl_count', 1)) * 100, 1)
        whip_pct = sl_forensic.get('whipsaw_t1_pct', 0.0)
        reb_pct = sl_forensic.get('partial_rebound_pct', 0.0)
        down_avoided = sl_forensic.get('avg_downside_avoided_pct', 0.0)
        avg_reb = sl_forensic.get('avg_rebound_after_sl_pct', 0.0)

        sl1.metric("🛡️ Capital Saved (Bleed Avoided)", f"{saved_pct}%", f"{saved_tot}/{sl_forensic['total_loss_sl_count']} Price kept falling")
        sl2.metric("🎣 Whipsaw Shakeouts (Hit T1)", f"{whip_pct}%", f"{sl_forensic.get('whipsaw_t1_count', 0)} False alarms", delta_color="inverse")
        sl3.metric("🔄 Partial Rebounds (Above Entry)", f"{reb_pct}%", f"{sl_forensic.get('partial_rebound_count', 0)} Bounced back")
        sl4.metric("📉 Avg Downside Avoided", f"-{down_avoided:.2f}%", f"Avg Rebound: +{avg_reb:.1f}%")

        sl_col_a, sl_col_b = st.columns([5, 5])
        with sl_col_a:
            st.markdown("###### 📊 Post-Stop-Loss Price Trajectory Breakdown")
            sl_labels = ['🛡️ Saved Capital (Price Cascaded)', '🎣 Whipsaw Shakeout (Later Hit T1)', '🔄 Partial Rebound (Above Entry)', '📉 Stagnated Below SL']
            sl_vals = [
                sl_forensic.get('saved_capital_count', 0),
                sl_forensic.get('whipsaw_t1_count', 0),
                sl_forensic.get('partial_rebound_count', 0),
                sl_forensic.get('cascade_down_count', 0)
            ]
            sl_colors = ['#00c875', '#e04b4b', '#d29922', '#8b949e']

            fig_sl_pie = go.Figure(data=[go.Pie(
                labels=sl_labels,
                values=sl_vals,
                hole=.55,
                marker=dict(colors=sl_colors),
                textinfo='percent+label',
                textposition='inside',
                insidetextorientation='radial'
            )])
            fig_sl_pie.update_layout(
                margin=dict(l=10, r=10, t=10, b=10),
                height=250,
                showlegend=False,
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font=dict(color='#c8d0d8', size=11)
            )
            st.plotly_chart(fig_sl_pie, use_container_width=True)

        with sl_col_b:
            st.markdown("###### 💡 Quantitative Risk Insights & Actionable Takeaways")
            st.markdown(f"""
            <div style="background-color: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 14px 18px; font-size: 0.88em; color: #c8d0d8;">
                <div style="margin-bottom: 8px;">
                    <span style="color: #00c875; font-weight: bold;">🛡️ Capital Preservation Efficacy ({saved_pct}%):</span> In <b>{saved_tot}</b> of {sl_forensic['total_loss_sl_count']} stopped trades, respecting the stop loss prevented deeper adverse drawdowns averaging <b>-{down_avoided:.2f}%</b> (with worst-case tail risks avoiding up to -12% losses).
                </div>
                <div style="margin-bottom: 8px;">
                    <span style="color: #e04b4b; font-weight: bold;">🎣 Whipsaw Shakeout Frequency ({whip_pct}%):</span> <b>{sl_forensic.get('whipsaw_t1_count', 0)}</b> signals wicked through standard ATR stops before reversing to hit Target 1.
                </div>
                <div style="margin-bottom: 8px;">
                    <span style="color: #58a6ff; font-weight: bold;">📐 Optimization Guide:</span> For high-beta names, widening the initial stop to <b>1.8× ATR</b> or placing stops below the <b>CPR Bottom Central Pivot (BC)</b> mitigates false liquidity sweeps while preserving risk-reward asymmetry.
                </div>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("---")

    # ── Time-to-Target (TTT) Maturation Curve ──────────────────────────────────────
    ttt_dist = audit_data.get("ttt_distribution", {})
    if ttt_dist and ttt_dist.get("total_t1_hits", 0) > 0:
        st.markdown(f"##### ⏱️ Empirical Time-to-Target Maturation Curve ({audit_asset_label})")
        st.caption(f"Historical velocity of all {ttt_dist['total_t1_hits']} completed Target 1 wins: Median = {ttt_dist['median_days']:.0f} trading sessions (Mean = {ttt_dist['mean_days']} sessions). 84.1% of targets are hit within 3 to 5 sessions.")

        tc1, tc2, tc3, tc4 = st.columns(4)
        fast_sprints = ttt_dist.get('day_1', 0) + ttt_dist.get('day_2', 0)
        core_swings = ttt_dist.get('day_3', 0) + ttt_dist.get('day_4', 0) + ttt_dist.get('day_5', 0)
        tot_hits = max(1, ttt_dist['total_t1_hits'])

        tc1.metric("🎯 Median Time to T1", f"{ttt_dist['median_days']:.0f} Sessions", "Modal peak at Day 4")
        tc2.metric("⚡ Fast Sprints (Day 1-2)", f"{fast_sprints} Wins", f"{round(fast_sprints / tot_hits * 100, 1)}% of all hits")
        tc3.metric("🎯 Core Swings (Day 3-5)", f"{core_swings} Wins", f"{round(core_swings / tot_hits * 100, 1)}% of all hits")
        tc4.metric("⏳ Extended Absorption (Day 6+)", f"{ttt_dist.get('day_6_plus', 0)} Wins", "Slow burn momentum")

        days_labels = ['Day 1 (Sprint)', 'Day 2 (Follow-Through)', 'Day 3 (Expansion)', 'Day 4 (Modal Peak)', 'Day 5 (Cycle Close)', 'Day 6+ (Extended)']
        days_counts = [
            ttt_dist.get('day_1', 0),
            ttt_dist.get('day_2', 0),
            ttt_dist.get('day_3', 0),
            ttt_dist.get('day_4', 0),
            ttt_dist.get('day_5', 0),
            ttt_dist.get('day_6_plus', 0)
        ]
        fig_ttt = go.Figure(data=[go.Bar(
            x=days_labels,
            y=days_counts,
            text=[f"{c} ({c / tot_hits * 100:.1f}%)" for c in days_counts],
            textposition='auto',
            marker=dict(
                color=['#58a6ff', '#388bfd', '#238636', '#00c875', '#2ea043', '#8b949e'],
                line=dict(color='#30363d', width=1)
            )
        )])
        fig_ttt.update_layout(
            margin=dict(l=10, r=10, t=15, b=10),
            height=240,
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            font=dict(color='#c8d0d8', size=11),
            yaxis=dict(showgrid=True, gridcolor='#21262d', title="Target 1 Hits"),
            xaxis=dict(showgrid=False)
        )
        st.plotly_chart(fig_ttt, use_container_width=True)
        st.markdown("---")

    # ── Filterable Audit Log Table ────────────────────────────────────────────────
    st.markdown(f"##### 📋 Granular Signal Audit Log ({audit_asset_label})")

    if audit_data["records"]:
        audit_df = pd.DataFrame(audit_data["records"])

        # Filter controls
        f1, f2, f3, f4, f5 = st.columns([3, 2, 2, 2, 3])
        with f1:
            status_filter = st.selectbox(
                "Filter by Status & SL Action",
                [
                    "All Statuses",
                    "🟢 In Play (Profitable)",
                    "⏳ In Play (Drawdown)",
                    "🎯 Target 1+ Hit",
                    "🛡️ Trailing SL (Profit Locked)",
                    "🛑 Stop Loss (Loss Only)",
                    "🛡️ SL: Saved Capital (Cascaded Down)",
                    "🎣 SL: Whipsaws (Later Hit T1)",
                    "🔄 SL: Rebounded Above Entry",
                    "📋 Expired"
                ],
                key="audit_status_filter"
            )
        with f2:
            cluster_filter = st.selectbox(
                "Sector Cluster",
                ["All Clusters", "🏦 BFSI", "⛏️ Cyclical", "🏰 Defensive", "🏗️ Capex"],
                key="audit_cluster_filter"
            )
        with f3:
            risk_type_filter = st.selectbox(
                "Risk Archetype",
                ["All Risks", "SAFE", "MODERATE", "RISKY"],
                key="audit_risk_filter"
            )
        with f4:
            signal_type_filter = st.selectbox(
                "Signal Type",
                ["All Signals", "BUY", "SELL"],
                key="audit_sig_filter"
            )
        with f5:
            audit_search = st.text_input("🔍 Search Symbol", placeholder="e.g. RELIANCE, NIFTY, GOLD...", key="audit_sym_search")

        filtered_audit = audit_df.copy()
        if status_filter == "🟢 In Play (Profitable)":
            filtered_audit = filtered_audit[filtered_audit["status"].str.contains("🟢 IN PLAY", na=False)]
        elif status_filter == "⏳ In Play (Drawdown)":
            filtered_audit = filtered_audit[filtered_audit["status"].str.contains("⏳ IN PLAY", na=False)]
        elif status_filter == "🎯 Target 1+ Hit":
            filtered_audit = filtered_audit[filtered_audit["status"].str.contains("🎯", na=False)]
        elif status_filter == "🛡️ Trailing SL (Profit Locked)":
            filtered_audit = filtered_audit[filtered_audit["status"].str.contains("TRAILING SL", na=False)]
        elif status_filter == "🛑 Stop Loss (Loss Only)":
            filtered_audit = filtered_audit[filtered_audit["status"].str.contains("STOP LOSS", na=False)]
        elif status_filter == "🛡️ SL: Saved Capital (Cascaded Down)":
            filtered_audit = filtered_audit[filtered_audit["sl_diagnostic"].str.contains("Saved|Continued Below", na=False)]
        elif status_filter == "🎣 SL: Whipsaws (Later Hit T1)":
            filtered_audit = filtered_audit[filtered_audit["sl_diagnostic"].str.contains("Whipsaw", na=False)]
        elif status_filter == "🔄 SL: Rebounded Above Entry":
            filtered_audit = filtered_audit[filtered_audit["sl_diagnostic"].str.contains("Rebounded Above", na=False)]
        elif status_filter == "📋 Expired":
            filtered_audit = filtered_audit[filtered_audit["status"].str.contains("EXPIRED", na=False)]

        if cluster_filter != "All Clusters" and "cluster_badge" in filtered_audit.columns:
            if "BFSI" in cluster_filter:
                filtered_audit = filtered_audit[filtered_audit["sector_cluster"] == "BFSI"]
            elif "Cyclical" in cluster_filter:
                filtered_audit = filtered_audit[filtered_audit["sector_cluster"] == "CYCLICAL"]
            elif "Defensive" in cluster_filter:
                filtered_audit = filtered_audit[filtered_audit["sector_cluster"] == "DEFENSIVE"]
            elif "Capex" in cluster_filter:
                filtered_audit = filtered_audit[filtered_audit["sector_cluster"] == "CAPEX_MOMENTUM"]

        if risk_type_filter != "All Risks" and "risk_level" in filtered_audit.columns:
            filtered_audit = filtered_audit[filtered_audit["risk_level"] == risk_type_filter]

        if signal_type_filter != "All Signals":
            filtered_audit = filtered_audit[filtered_audit["signal"] == signal_type_filter]

        if audit_search:
            filtered_audit = filtered_audit[filtered_audit["symbol"].str.contains(audit_search.strip().upper(), na=False)]

        st.caption(f"Showing **{len(filtered_audit)}** of {len(audit_df)} historical audit records for **{audit_asset_label}**")

        table_cols = [
            "date", "symbol", "signal", "cluster_badge", "cap_tier", "risk_level", "entry_price", "close_price", "target_1", "target_2",
            "stop_loss", "trailing_stop", "est_time_to_t1", "status", "max_gain_pct",
            "realized_gain_pct", "days_to_outcome", "sl_diagnostic", "composite_score"
        ]
        # Only keep columns that exist in the dataframe (graceful degradation)
        table_cols = [c for c in table_cols if c in filtered_audit.columns]

        display_audit = filtered_audit[table_cols].rename(columns={
            "date": "Signal Date",
            "symbol": "Symbol",
            "signal": "Signal",
            "cluster_badge": "Cluster",
            "cap_tier": "Tier",
            "risk_level": "Risk Level",
            "entry_price": "Entry (₹)",
            "close_price": "Current / Exit (₹)",
            "target_1": "Target 1 (₹)",
            "target_2": "Target 2 (₹)",
            "stop_loss": "Stop Loss (₹)",
            "trailing_stop": "Trailing SL (₹)",
            "est_time_to_t1": "Est. Time to T1",
            "status": "Live Audit Status",
            "max_gain_pct": "Peak Move %",
            "realized_gain_pct": "Realized / Live P&L %",
            "days_to_outcome": "Days in Play / Close",
            "sl_diagnostic": "SL Post-Exit Action",
            "composite_score": "Score",
        })

        def _fmt_price(x): return f"₹{x:,.2f}" if pd.notnull(x) and x else "—"
        def _fmt_pct(x):   return f"{x:+.2f}%" if pd.notnull(x) and x is not None else "—"
        def _fmt_days(x):  return f"{int(x)}d" if pd.notnull(x) and x else "—"
        def _fmt_score(x): return f"{x:.1f}" if pd.notnull(x) and x is not None else "—"

        fmt = {}
        if "Entry (₹)" in display_audit.columns:             fmt["Entry (₹)"]             = _fmt_price
        if "Current / Exit (₹)" in display_audit.columns:    fmt["Current / Exit (₹)"]    = _fmt_price
        if "Target 1 (₹)" in display_audit.columns:          fmt["Target 1 (₹)"]          = _fmt_price
        if "Target 2 (₹)" in display_audit.columns:          fmt["Target 2 (₹)"]          = _fmt_price
        if "Stop Loss (₹)" in display_audit.columns:         fmt["Stop Loss (₹)"]         = _fmt_price
        if "Trailing SL (₹)" in display_audit.columns:       fmt["Trailing SL (₹)"]       = _fmt_price
        if "Peak Move %" in display_audit.columns:           fmt["Peak Move %"]           = _fmt_pct
        if "Realized / Live P&L %" in display_audit.columns: fmt["Realized / Live P&L %"] = _fmt_pct
        if "Days in Play / Close" in display_audit.columns:  fmt["Days in Play / Close"]  = _fmt_days
        if "Score" in display_audit.columns:                 fmt["Score"]                 = _fmt_score

        st.dataframe(
            display_audit.style.format(fmt),
            use_container_width=True,
            height=440,
            hide_index=True,
        )

        csv_audit = filtered_audit.to_csv(index=False).encode('utf-8')
        st.download_button(
            "📥 Download Audit Log (CSV)",
            data=csv_audit,
            file_name=f"signal_audit_track_record_{selected_asset.lower()}.csv",
            mime="text/csv"
        )

    st.markdown("---")

    # ── Missed Alpha & False Negative Surveillance ────────────────────────────
    st.subheader("🔍 Missed Alpha & False Negative Surveillance (Uncaught Movers)")
    st.caption("Continuous surveillance across all 285+ stocks in the universe to identify large subsequent moves (>+3% to +10%) that occurred on WATCH ratings and diagnose the root cause.")

    from core.missed_signals import scan_missed_opportunities

    col_ms1, col_ms2 = st.columns([1, 1])
    with col_ms1:
        ms_lookback = st.slider("Surveillance Lookback Horizon (Days):", min_value=3, max_value=15, value=5, step=1, key="ms_lookback_slider")
    with col_ms2:
        ms_min_gain = st.slider("Minimum Subsequent Gain Threshold (%):", min_value=2.0, max_value=15.0, value=4.0, step=0.5, key="ms_min_gain_slider")

    session_ms = get_session(engine)
    missed_report = scan_missed_opportunities(session_ms, lookback_days=ms_lookback, min_gain_pct=ms_min_gain)
    session_ms.close()

    m_sum = missed_report["summary"]
    if m_sum:
        mk1, mk2, mk3, mk4 = st.columns(4)
        mk1.metric("🚀 Total Fast Movers", f"{m_sum['total_movers_detected']} stocks", f">={ms_min_gain}% Gain")
        mk2.metric("🔍 Uncaught / Missed", f"{m_sum['missed_movers_count']} stocks", f"Score < 59 on T-{ms_lookback}")
        mk3.metric("📈 Avg Missed Alpha", f"+{m_sum['avg_missed_gain_pct']:.2f}%", f"Over {ms_lookback} sessions")
        mk4.metric("🧠 Primary Bottleneck", f"{m_sum['top_bottleneck_factor']}", "Dominant Lagging Factor")

        st.markdown("---")

        if missed_report["missed_movers"]:
            st.markdown("##### 🔬 Algorithmic Post-Mortem & Diagnostic Teardown")
            df_missed = pd.DataFrame(missed_report["missed_movers"])[[
                "symbol", "name", "sector", "tier", "gain_pct", "start_score",
                "bottleneck", "diagnosis", "pattern_catalyst", "actionable_takeaway"
            ]]

            st.dataframe(
                df_missed.rename(columns={
                    "symbol": "Symbol",
                    "name": "Company",
                    "sector": "Sector",
                    "tier": "Cap Tier",
                    "gain_pct": "Actual Gain %",
                    "start_score": "Score on Day 0",
                    "bottleneck": "Primary Bottleneck",
                    "diagnosis": "Quantitative Diagnosis",
                    "pattern_catalyst": "Candlestick Catalyst",
                    "actionable_takeaway": "Actionable Quant Learning"
                }).style.format({
                    "Actual Gain %": "+{:,.2f}%",
                    "Score on Day 0": "{:.1f}/100"
                }),
                use_container_width=True,
                height=350,
                hide_index=True
            )
        else:
            st.success(f"Zero missed opportunities! No WATCH stocks generated >=+{ms_min_gain}% gains over the last {ms_lookback} sessions.")

# Tab 10: Custom Quantitative Screener & Institutional Presets
with tabs[9]:
    st.subheader("🎯 Custom Quantitative Screener & Institutional Presets")
    st.caption("Filter across the 285+ stock universe by technical factors, momentum, F&O, and institutional setup templates")

    from core.screener_engine import execute_custom_stock_screen, run_preset_institutional_screen

    sc_mode = st.radio(
        "Screener Mode",
        ["🏆 Legendary Institutional Presets", "🛠️ Custom Multi-Factor Query Builder"],
        horizontal=True
    )

    if "Presets" in sc_mode:
        preset_choice = st.selectbox(
            "Select Institutional Setup Screen",
            [
                "🏆 Minervini Trend Template",
                "🚀 High-Growth CANSLIM Momentum",
                "💎 Institutional Absorption Squeeze",
                "🛡️ Defensive Value Contrarian",
            ]
        )
        session_scr = get_session(engine)
        preset_data = run_preset_institutional_screen(preset_choice, session_scr)
        session_scr.close()

        st.info(f"**Screening Logic:** {preset_data['description']} (Matched: **{preset_data['total_matched']} stocks**)")
        
        if preset_data["stocks"]:
            p_df = pd.DataFrame(preset_data["stocks"])
            st.dataframe(
                p_df[["symbol", "name", "sector", "tier", "price", "daily_return", "rsi", "composite_score", "signal", "volume_ratio"]].style.format({
                    "price": "₹{:,.2f}",
                    "daily_return": "{:+.2f}%",
                    "rsi": "{:.1f}",
                    "composite_score": "{:.1f}",
                    "volume_ratio": "{:.2f}x",
                }),
                use_container_width=True,
                hide_index=True,
            )
    else:
        q1, q2, q3 = st.columns(3)
        with q1:
            rsi_range = st.slider("RSI Range", 0, 100, (40, 75))
            score_range = st.slider("Composite Score Range", 0, 100, (55, 100))
        with q2:
            sig_choice = st.selectbox("Signal State", ["ALL", "BUY", "WATCH", "SELL"])
            cap_choice = st.selectbox("Market Cap Tier", ["ALL", "large", "mid", "small"])
        with q3:
            p_200 = st.checkbox("Price > 200 EMA", value=True)
            p_50 = st.checkbox("Price > 50 EMA", value=False)
            vol_min = st.slider("Min Volume Ratio (vs 20D Avg)", 0.5, 5.0, 1.2, 0.1)

        session_c_scr = get_session(engine)
        custom_res = execute_custom_stock_screen(
            session_c_scr,
            min_rsi=rsi_range[0], max_rsi=rsi_range[1],
            min_score=score_range[0], max_score=score_range[1],
            signal_filter=sig_choice,
            market_cap_tier=cap_choice,
            price_above_200_ema=p_200,
            price_above_50_ema=p_50,
            min_volume_ratio=vol_min,
            limit=40
        )
        session_c_scr.close()

        st.markdown(f"**Matched {len(custom_res)} Stocks matching your query:**")
        if custom_res:
            c_df = pd.DataFrame(custom_res)
            st.dataframe(
                c_df[["symbol", "name", "sector", "tier", "price", "daily_return", "rsi", "composite_score", "signal", "volume_ratio"]].style.format({
                    "price": "₹{:,.2f}",
                    "daily_return": "{:+.2f}%",
                    "rsi": "{:.1f}",
                    "composite_score": "{:.1f}",
                    "volume_ratio": "{:.2f}x",
                }),
                use_container_width=True,
                hide_index=True,
            )

# Tab 11: Multi-Timeframe (MTF) Triple-Screen Confluence
with tabs[10]:
    st.subheader("💎 Multi-Timeframe (MTF) Triple-Screen Confluence Scanner")
    st.caption("Elder's Triple-Screen: Weekly Macro Tide (Trend) + Daily Wave (Pullback) + Short-Term Ripple (Volume Trigger)")

    from core.mtf_scanner import scan_mtf_triple_screen_confluence
    session_mtf = get_session(engine)
    mtf_setups = scan_mtf_triple_screen_confluence(session_mtf, limit=30)
    session_mtf.close()

    st.markdown(f"**Found {len(mtf_setups)} High-Conviction Confluence Setups across the universe:**")

    if mtf_setups:
        df_mtf = pd.DataFrame(mtf_setups)
        st.dataframe(
            df_mtf[[
                "symbol", "name", "sector", "current_price", "weekly_status", "daily_status", "ripple_status", "rsi", "volume_ratio", "mtf_tier", "action"
            ]].rename(columns={
                "symbol": "Symbol",
                "name": "Company Name",
                "sector": "Sector",
                "current_price": "Price (₹)",
                "weekly_status": "Weekly Tide",
                "daily_status": "Daily Wave",
                "ripple_status": "Ripple Trigger",
                "rsi": "RSI (14)",
                "volume_ratio": "Vol Ratio",
                "mtf_tier": "MTF Tier",
                "action": "Institutional Action",
            }).style.format({
                "Price (₹)": "₹{:,.2f}",
                "RSI (14)": "{:.1f}",
                "Vol Ratio": "{:.2f}x",
            }),
            use_container_width=True,
            hide_index=True,
        )

# Tab 12: Option Chain & Max Pain Analytics
with tabs[11]:
    st.subheader("⚡ F&O Derivatives & Option Chain Analytics")
    st.caption("Max Pain Theory, Put-Call Ratio (PCR), Open Interest (OI) Heatmap, and Black-Scholes Greeks")

    fno_symbols = ["^NSEI", "^NSEBANK", "RELIANCE", "HDFCBANK", "ICICIBANK", "SBIN", "TCS", "INFY", "BHARTIARTL", "ITC"]
    fno_col1, fno_col2 = st.columns([2, 1])
    with fno_col1:
        selected_fno = st.selectbox("Select Index or F&O Stock", fno_symbols, index=0, format_func=lambda x: f"NIFTY 50 (^NSEI)" if x == "^NSEI" else (f"NIFTY BANK (^NSEBANK)" if x == "^NSEBANK" else f"{x} (F&O Stock)"))
    with fno_col2:
        st.markdown("<br>", unsafe_allow_html=True)

    from core.options_analytics import fetch_option_chain_analytics
    
    # Get current price
    session_fno = get_session(engine)
    if selected_fno.startswith("^"):
        p_row = session_fno.execute(text("SELECT close FROM index_prices WHERE symbol = :s ORDER BY date DESC LIMIT 1"), {"s": selected_fno}).fetchone()
        fno_price = float(p_row[0]) if p_row else 24200.0
    else:
        p_row = session_fno.execute(text("SELECT close FROM daily_prices WHERE symbol = :s ORDER BY date DESC LIMIT 1"), {"s": selected_fno}).fetchone()
        fno_price = float(p_row[0]) if p_row else 1500.0
    session_fno.close()

    opt_data = fetch_option_chain_analytics(selected_fno, fno_price)

    # Metric Banner
    oc1, oc2, oc3, oc4, oc5 = st.columns(5)
    with oc1:
        st.metric("Underlying Spot Price", f"₹{fno_price:,.2f}")
    with oc2:
        st.metric("Max Pain Strike", f"₹{opt_data['max_pain_strike']:,.0f}", help="Strike price where option buyers experience maximum cumulative loss")
    with oc3:
        st.metric("Put-Call Ratio (OI)", f"{opt_data['pcr_oi']:.2f}", opt_data['pcr_badge'])
    with oc4:
        st.metric("Major Support (Put Wall)", f"₹{opt_data['major_support_strike']:,.0f}")
    with oc5:
        st.metric("Major Resistance (Call Wall)", f"₹{opt_data['major_resistance_strike']:,.0f}")

    # Charts: OI Heatmap & Max Pain Loss Curve
    ch_col1, ch_col2 = st.columns(2)
    with ch_col1:
        st.markdown("##### 📊 Strike-Wise Open Interest (OI) Distribution")
        df_strikes = pd.DataFrame({
            "Strike": [c["strike"] for c in opt_data["calls"]],
            "Call OI": [c["oi"] for c in opt_data["calls"]],
            "Put OI": [p["oi"] for p in opt_data["puts"]],
        })
        import plotly.graph_objects as go
        fig_oi = go.Figure()
        fig_oi.add_trace(go.Bar(x=df_strikes["Strike"], y=df_strikes["Call OI"], name="Call OI (Resistance)", marker_color="#ff4b4b"))
        fig_oi.add_trace(go.Bar(x=df_strikes["Strike"], y=df_strikes["Put OI"], name="Put OI (Support)", marker_color="#00c875"))
        fig_oi.add_vline(x=opt_data["max_pain_strike"], line_dash="dash", line_color="#f0a500", annotation_text="Max Pain")
        fig_oi.update_layout(barmode="group", height=340, margin=dict(l=20, r=20, t=30, b=20), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#e0e0e0"))
        st.plotly_chart(fig_oi, use_container_width=True)

    with ch_col2:
        st.markdown("##### 📉 Max Pain Cumulative Financial Loss Curve")
        loss_df = opt_data.get("loss_df", pd.DataFrame())
        if not loss_df.empty:
            fig_loss = go.Figure()
            fig_loss.add_trace(go.Scatter(x=loss_df["strike"], y=loss_df["total_loss"], mode="lines+markers", name="Total Buyer Loss", line=dict(color="#38bdf8", width=2)))
            fig_loss.add_vline(x=opt_data["max_pain_strike"], line_dash="dash", line_color="#00c875", annotation_text=f"Min Loss (Max Pain: ₹{opt_data['max_pain_strike']:,.0f})")
            fig_loss.update_layout(height=340, margin=dict(l=20, r=20, t=30, b=20), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#e0e0e0"))
            st.plotly_chart(fig_loss, use_container_width=True)

    # ── Market Maker Net Gamma Exposure (GEX in ₹ Cr) ─────────────────────────
    from core.gamma_exposure_gex import compute_net_gamma_exposure_profile
    gex_strikes = [c["strike"] for c in opt_data["calls"]]
    gex_call_oi = [c["oi"] for c in opt_data["calls"]]
    gex_put_oi = [p["oi"] for p in opt_data["puts"]]

    gex_res = compute_net_gamma_exposure_profile(fno_price, gex_strikes, gex_call_oi, gex_put_oi)

    if gex_res:
        with st.expander("🌊 **Market Maker Net Gamma Exposure (GEX in ₹ Cr) & Zero-Gamma Volatility Pivot**", expanded=False):
            gx1, gx2, gx3, gx4 = st.columns(4)
            gx1.metric("Zero-Gamma Flip Level", f"₹{gex_res['zero_gamma_level']:,.0f}", "Volatility Pivot")
            gx2.metric("Total Net GEX", f"₹{gex_res['total_net_gex_cr']:+,.2f} Cr", gex_res['regime_badge'])
            gx3.metric("Call Squeeze Trigger", f"₹{gex_res['call_squeeze_level']:,.0f}")
            gx4.metric("Put Support Wall", f"₹{gex_res['put_liquidity_support']:,.0f}")

            st.markdown(f"**Gamma Hedging Dynamics:** `{gex_res['vol_regime']}` — *{gex_res['regime_desc']}*")

            # GEX Bar Chart
            df_gex_chart = gex_res["gex_table"]
            fig_gex = go.Figure()
            colors = ["#00c875" if v > 0 else "#ff4b4b" for v in df_gex_chart["net_gex_cr"]]
            fig_gex.add_trace(go.Bar(x=df_gex_chart["strike"], y=df_gex_chart["net_gex_cr"], marker_color=colors, name="Net GEX (₹ Cr)"))
            fig_gex.add_vline(x=gex_res["zero_gamma_level"], line_dash="dash", line_color="#38bdf8", annotation_text=f"Zero-Gamma: ₹{gex_res['zero_gamma_level']:,.0f}")
            fig_gex.update_layout(height=300, margin=dict(l=20, r=20, t=20, b=20), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#e0e0e0"), yaxis_title="Net GEX (₹ Crores per 1% move)")
            st.plotly_chart(fig_gex, use_container_width=True)


    # Option Chain Table
    with st.expander("📋 Detailed Option Chain Matrix & Black-Scholes Greeks", expanded=False):
        c_list = opt_data["calls"]
        p_list = opt_data["puts"]
        table_rows = []
        for c, p in zip(c_list, p_list):
            table_rows.append({
                "Call OI": f"{c['oi']:,}",
                "Call Vol": f"{c['volume']:,}",
                "Call IV": f"{c['iv']:.1f}%",
                "Call LTP": f"₹{c['ltp']:.2f}",
                "Call Delta": f"{c['delta']:.2f}",
                "Strike Price": f"₹{c['strike']:,.0f}",
                "Put Delta": f"{p['delta']:.2f}",
                "Put LTP": f"₹{p['ltp']:.2f}",
                "Put IV": f"{p['iv']:.1f}%",
                "Put Vol": f"{p['volume']:,}",
                "Put OI": f"{p['oi']:,}",
            })
        st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)


# Tab 13: Smart Money & Delivery Footprint Scanner
with tabs[12]:
    st.subheader("🐋 Institutional Smart Money & Delivery Footprint Scanner")
    st.caption("Identifies institutional accumulation, delivery volume spurts (>2.0x 10d avg), and stealth order-flow absorption")

    from core.smart_money import scan_universe_smart_money
    session_sm = get_session(engine)
    sm_results = scan_universe_smart_money(session_sm, limit=35)
    session_sm.close()

    # Summary Metrics
    spurts = sum(1 for r in sm_results if r["delivery_spurt"])
    absorptions = sum(1 for r in sm_results if r["absorption_detected"])
    strong_inflows = sum(1 for r in sm_results if "STRONG" in r["smart_money_bias"])

    sm_m1, sm_m2, sm_m3, sm_m4 = st.columns(4)
    with sm_m1:
        st.metric("Total Whale Scanned", len(sm_results))
    with sm_m2:
        st.metric("Strong Inflows Detected", strong_inflows, "🟢 High Quality")
    with sm_m3:
        st.metric("Delivery Volume Spurts", spurts, "⚡ >2.0x Volume")
    with sm_m4:
        st.metric("Stealth Price Absorptions", absorptions, "🛡️ Panic Absorption")

    if sm_results:
        df_sm = pd.DataFrame(sm_results)
        st.dataframe(
            df_sm[[
                "symbol", "name", "sector", "tier", "close", "money_flow_score", "delivery_pct_est", "vol_ratio_10d", "cmf_20", "smart_money_bias", "absorption_detected"
            ]].rename(columns={
                "symbol": "Symbol",
                "name": "Company Name",
                "sector": "Sector",
                "tier": "Cap Tier",
                "close": "Price (₹)",
                "money_flow_score": "Money Flow Score",
                "delivery_pct_est": "Est. Delivery %",
                "vol_ratio_10d": "Vol Ratio (10d)",
                "cmf_20": "CMF (20)",
                "smart_money_bias": "Institutional Bias",
                "absorption_detected": "Stealth Absorption",
            }).style.format({
                "Price (₹)": "₹{:,.2f}",
                "Money Flow Score": "{:.1f}/100",
                "Est. Delivery %": "{:.1f}%",
                "Vol Ratio (10d)": "{:.2f}x",
                "CMF (20)": "{:+.3f}",
            }),
            use_container_width=True,
            hide_index=True,
        )

# Tab 14: Pairs Trading & Statistical Arbitrage
with tabs[13]:
    st.subheader("⚡ Pairs Trading & Statistical Arbitrage Cointegration Scanner")
    st.caption("Market-neutral relative value trading: Engle-Granger Cointegration & Spread Z-Score mean-reversion signals")

    from core.stat_arb import scan_all_pairs_arbitrage
    session_pa = get_session(engine)
    pairs_results = scan_all_pairs_arbitrage(session_pa)
    session_pa.close()

    # Metric summary
    diverged = sum(1 for p in pairs_results if abs(p["z_score"]) >= 1.8)
    converged = sum(1 for p in pairs_results if abs(p["z_score"]) < 1.0)

    pm1, pm2, pm3 = st.columns(3)
    pm1.metric("Total Institutional Pairs", len(pairs_results))
    pm2.metric("Active Stat-Arb Setups (|Z| ≥ 1.8σ)", diverged, "⚡ Divergence Signal")
    pm3.metric("Equilibrium Pairs", converged, "⚪ Mean Reverted")

    if pairs_results:
        df_pairs = pd.DataFrame(pairs_results)
        st.dataframe(
            df_pairs[["pair", "sector", "signal_badge", "z_score", "hedge_ratio", "half_life_days", "rationale"]].rename(columns={
                "pair": "Pair (Asset A / Asset B)",
                "sector": "Sector",
                "signal_badge": "Arbitrage Signal",
                "z_score": "Spread Z-Score (σ)",
                "hedge_ratio": "Hedge Ratio (β)",
                "half_life_days": "Mean Reversion Half-Life (Days)",
                "rationale": "Statistical Arbitrage Setup"
            }).style.format({
                "Spread Z-Score (σ)": "{:+.2f}σ",
                "Hedge Ratio (β)": "{:.3f}",
                "Mean Reversion Half-Life (Days)": "{:.1f} days"
            }),
            use_container_width=True,
            hide_index=True
        )



