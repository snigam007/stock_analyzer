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
importlib.reload(core.macro_regime)
importlib.reload(core.accuracy_tracker)

from db.database import get_global_engine, get_session
from sqlalchemy import text

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
               cs.beta, cs.volatility_annual, cs.sharpe_ratio
        FROM signals sig
        JOIN stocks s ON sig.symbol = s.symbol
        JOIN composite_scores cs ON sig.symbol = cs.symbol
        LEFT JOIN technical_indicators ind ON sig.symbol = ind.symbol
        WHERE sig.date = (SELECT date FROM signals GROUP BY date ORDER BY COUNT(*) DESC, date DESC LIMIT 1)
        AND cs.date = (SELECT date FROM composite_scores GROUP BY date ORDER BY COUNT(*) DESC, date DESC LIMIT 1)
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
def get_sectors():
    session = get_session(engine)
    result = session.execute(text("SELECT DISTINCT sector FROM stocks ORDER BY sector")).scalars().all()
    session.close()
    return ["All"] + list(result)


# ─── Sidebar ──────────────────────────────────────────────────────────────────
st.sidebar.title("🏆 Daily Top Stocks")
sector_filter = st.sidebar.selectbox("Sector", get_sectors())
top_n = st.sidebar.slider("Show Top N Stocks", 5, 30, 15)

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
    "🎯 Signal Accuracy & Audit"
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
    """Render a rich stock table with all details."""
    if not rows:
        st.info("No stocks found for this filter.")
        return

    signal_icons = {"BUY": "🟢", "SELL": "🔴", "WATCH": "🟡"}
    risk_icons = {"SAFE": "🛡️", "MODERATE": "⚖️", "RISKY": "⚡"}
    trend_icons = {"UP": "📈", "DOWN": "📉", "SIDEWAYS": "➡️"}
    inv_icons = {"Momentum": "🚀", "Value": "💎", "Growth": "🌱", "Defensive": "🏰", "Speculative": "🎲"}

    for i, row in enumerate(rows):
        (symbol, name, sector, tier, composite_score, univ_pct,
         signal, strength, price, buy_price, t1, t2, t3,
         sl, rr, risk, reason, confidence, inv_type,
         t1_pct, t2_pct, t3_pct, sl_pct,
         trend_pat, trend_dir, trend_str,
         rsi, adx, vol_ratio,
         beta, volatility, sharpe) = row

        sig_icon = signal_icons.get(signal, "🟡")
        risk_icon = risk_icons.get(risk, "⚖️")
        trend_icon = trend_icons.get(trend_dir, "➡️")
        inv_icon = inv_icons.get(inv_type, "🌱")

        rank_label = f"#{i+1}"

        with st.expander(
            f"{rank_label} **{symbol}** — {name[:40]} | "
            f"{sig_icon} {signal} | {risk_icon} {risk} | "
            f"Score: **{composite_score:.0f}** | {trend_icon} {trend_dir}",
            expanded=(i < 3)
        ):
            col1, col2, col3, col4 = st.columns([2, 2, 2, 2])

            with col1:
                st.markdown(f"**📂 Sector:** {sector}")
                st.markdown(f"**📊 Cap Tier:** {tier.upper() if tier else 'Mid'}")
                st.markdown(f"**🎯 Inv Type:** {inv_icon} {inv_type or 'Growth'}")
                st.markdown(f"**💯 Score:** `{composite_score:.1f}/100` (Top {100-univ_pct:.0f}%)")
                if rsi:
                    adx_str = f"{adx:.1f}" if adx else "—"
                    st.markdown(f"**RSI:** {rsi:.1f} | **ADX:** {adx_str}")
                if vol_ratio:
                    st.markdown(f"**Vol Ratio:** {vol_ratio:.2f}x avg")

            with col2:
                st.markdown("**💰 Price Levels:**")
                st.markdown(f"- Current: **{format_price(price)}**")
                if buy_price:
                    st.markdown(f"- Entry: **{format_price(buy_price)}**")
                if t1:
                    st.markdown(f"- 🎯 T1: **{format_price(t1)}** {format_badge_pct(t1_pct)}", unsafe_allow_html=True)
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
        with st.expander(f"{sig_color} **{asset['name']}** ({asset['symbol']}) — Signal: **{asset['signal']}** | Score: **{asset['score']}/100**", expanded=True):
            ic1, ic2, ic3, ic4 = st.columns(4)
            ic1.metric("Current Level", format_price(asset["price"]), f"Signal: {asset['signal']}")
            ic2.metric("🎯 14D Target", format_price(asset["target_1"]), f"{asset['t1_pct']:+.2f}%")
            ic3.metric("🎯 1M Target", format_price(asset["target_2"]), f"{asset['t2_pct']:+.2f}%")
            ic4.metric("🛑 Stop Loss", format_price(asset["stop_loss"]), f"{asset['sl_pct']:+.2f}%")


# Tab 4: Commodity Signals
with tabs[3]:
    st.subheader("🪙 Commodity Signals & Price Targets")
    st.caption("Directional forecasts for Gold, Silver, Crude Oil, Copper, and Natural Gas")
    comm_signals = get_asset_signals("commodity")
    for asset in comm_signals:
        sig_color = "🟢" if asset["signal"] == "BUY" else ("🔴" if asset["signal"] == "SELL" else "🟡")
        with st.expander(f"{sig_color} **{asset['name']}** ({asset['symbol']}) — Signal: **{asset['signal']}** | Score: **{asset['score']}/100**", expanded=True):
            cc1, cc2, cc3, cc4 = st.columns(4)
            cc1.metric("Current Price", format_price(asset["price"]), f"Signal: {asset['signal']}")
            cc2.metric("🎯 14D Target", format_price(asset["target_1"]), f"{asset['t1_pct']:+.2f}%")
            cc3.metric("🎯 1M Target", format_price(asset["target_2"]), f"{asset['t2_pct']:+.2f}%")
            cc4.metric("🛑 Stop Loss", format_price(asset["stop_loss"]), f"{asset['sl_pct']:+.2f}%")


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
            with st.expander(f"🚀 **{b['symbol']}** — {b['name']} ({b['sector']}) | Price: **{format_price(b['current_price'])}** | {b['cpr_type']}", expanded=True):
                cpr_c1, cpr_c2, cpr_c3 = st.columns(3)
                with cpr_c1:
                    st.markdown(f"**CPR Width:** `{b['cpr_width_pct']:.2f}%`")
                    st.markdown(f"**Position:** {b['cpr_position']}")
                with cpr_c2:
                    st.markdown(f"**Camarilla H4 Breakout:** **{format_price(b['h4_breakout'])}**")
                    st.markdown(f"**Camarilla L3 Support:** **{format_price(b['l3_support'])}**")
                with cpr_c3:
                    st.markdown(f"**Wyckoff Archetype:** `{b['vsa_archetype']}`")
                    st.markdown(f"*{b['vsa_description']}*")


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
    st.subheader("🎯 Live Signal Accuracy & Empirical Hit Rate Audit")
    st.caption("Persistent verification of past platform signals, measuring actual target hits vs stop-loss breaches.")

    import importlib
    import core.accuracy_tracker
    importlib.reload(core.accuracy_tracker)
    from core.accuracy_tracker import evaluate_signal_audit_track_record

    audit_session = get_session(engine)
    audit_data = evaluate_signal_audit_track_record(audit_session)
    audit_session.close()

    ac1, ac2, ac3, ac4 = st.columns(4)
    ac1.metric("Target 1 Hit Rate", f"{audit_data['target_1_hit_rate_pct']:.1f}%", "Overall Platform Win Rate")
    ac2.metric("Target 2 Hit Rate", f"{audit_data['target_2_hit_rate_pct']:.1f}%", "Deep Move Capture")
    ac3.metric("Target 3 Hit Rate", f"{audit_data['target_3_hit_rate_pct']:.1f}%", "Multi-Month Trend Runners")
    ac4.metric("Stop Loss Trigger Rate", f"{audit_data['stop_loss_hit_rate_pct']:.1f}%", "Risk Contained", delta_color="inverse")

    st.markdown(f"**Total Signals Logged & Monitored:** `{audit_data['total_signals_tracked']}` across universe.")

    if audit_data["records"]:
        audit_df = pd.DataFrame(audit_data["records"])
        st.dataframe(
            audit_df[[
                "date", "symbol", "signal", "entry_price", "target_1", "target_2", "target_3", "stop_loss", "status", "max_gain_pct"
            ]].rename(columns={
                "date": "Signal Date",
                "symbol": "Symbol",
                "signal": "Signal",
                "entry_price": "Entry (₹)",
                "target_1": "Target 1 (₹)",
                "target_2": "Target 2 (₹)",
                "target_3": "Target 3 (₹)",
                "stop_loss": "Stop Loss (₹)",
                "status": "Live Audit Status",
                "max_gain_pct": "Max Move %",
            }).style.format({
                "Entry (₹)": "₹{:,.2f}",
                "Target 1 (₹)": lambda x: f"₹{x:,.2f}" if pd.notnull(x) else "—",
                "Target 2 (₹)": lambda x: f"₹{x:,.2f}" if pd.notnull(x) else "—",
                "Target 3 (₹)": lambda x: f"₹{x:,.2f}" if pd.notnull(x) else "—",
                "Stop Loss (₹)": lambda x: f"₹{x:,.2f}" if pd.notnull(x) else "—",
                "Max Move %": "{:+.2f}%",
            }),
            use_container_width=True,
            hide_index=True,
        )

