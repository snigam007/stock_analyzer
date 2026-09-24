"""
Page 0: Market Overview & Institutional Cockpit
Consolidated Executive Summary: Core Indices, Commodities, and Top Multi-Model Signals
"""
import sys
from pathlib import Path
import streamlit as st
import pandas as pd
from sqlalchemy import text

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
    st.set_page_config(page_title="Market Overview", page_icon="🏠", layout="wide")
except Exception:
    pass

import importlib
import core.market_breadth
import core.bellwether_lead_lag
import core.macro_regime
import core.sector_analysis
importlib.reload(core.market_breadth)
importlib.reload(core.bellwether_lead_lag)
importlib.reload(core.macro_regime)
importlib.reload(core.sector_analysis)

from config.settings import APP_TITLE, APP_VERSION, DISCLAIMER
from db.database import get_global_engine, get_session
from core.data_status import get_database_status_summary
from core.macro_regime import evaluate_macro_regime
from core.market_breadth import calculate_market_breadth
from core.bellwether_lead_lag import evaluate_bellwether_lead_lag
from core.sector_analysis import calculate_sector_relative_strength
from core.premarket_briefing import get_cached_premarket_briefing

engine = get_global_engine()
session = get_session(engine)

# ── Header ───────────────────────────────────────────────────────────────────
st.title("🏛️ Market Overview & Executive Cockpit")
st.caption("Institutional Intelligence · Multi-Asset Signals · Macro Regimes · Real-time Analytics")

try:
    db_status = get_database_status_summary(session)
    macro_info = evaluate_macro_regime(session)
    stock_count = db_status['stock_count']
    price_count = db_status['total_bars']
    signal_count = db_status['latest_signals_count']
    last_date = db_status['max_date']

    if stock_count == 0:
        st.warning("⚠️ Database not initialized. Please run `python initialize.py` first.")
        st.code("python initialize.py", language="bash")
        st.stop()

    # ── Executive Pulse Bar ───────────────────────────────────────────────────
    st.markdown(f"""
    <div style="background: linear-gradient(135deg, #111827 0%, #0f172a 100%); border: 1px solid #1e293b; border-left: 4px solid #00c875; border-radius: 10px; padding: 14px 20px; margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px;">
        <div>
            <span style="font-size: 1.15em; font-weight: 700; color: #f8fafc;">📅 Market Session: {last_date}</span>
            <span style="margin-left: 10px; background: rgba(0, 200, 117, 0.15); color: #00c875; padding: 3px 10px; border-radius: 20px; font-size: 0.85em; font-weight: 600;">{db_status['status_badge']}</span><br>
            <span style="font-size: 0.88em; color: #94a3b8;">Coverage: <b>{stock_count}</b> Equities · <b>{db_status['index_count']}</b> Indexes · <b>{db_status['commodity_count']}</b> Commodities ({price_count:,} Historical Bars)</span>
        </div>
        <div style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap;">
            <span style="background: rgba(56, 189, 248, 0.15); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.3); padding: 5px 12px; border-radius: 8px; font-size: 0.85em; font-weight: 600;">
                🏛️ {macro_info['regime']} ({macro_info['macro_score']}/100)
            </span>
            <span style="background: #1e293b; color: #cbd5e1; padding: 5px 12px; border-radius: 8px; font-size: 0.85em; font-weight: 600;">
                ⚡ Daily Cron: 08:00 AM IST
            </span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Pre-Market Top-3 Sniper Setups Briefing ───────────────────────────────
    try:
        briefing = get_cached_premarket_briefing(session)
    except Exception:
        briefing = {}

    if briefing and briefing.get("sniper_setups"):
        snipers = briefing["sniper_setups"]
        surv = briefing.get("surveillance_alerts", [])
        
        with st.expander(f"🌅 **Today's Pre-Market Top-3 Sniper Briefing** (08:00 AM IST · 5.03x Historical Profit Factor)", expanded=True):
            st.caption(f"⚡ Empirical Quantitative Edge: Top 3 daily sniper setups deliver +1.55% avg return with 5.03x Profit Factor vs 1.89x for broader signals. Market Session: {briefing.get('market_session_date')}")
            
            s_cols = st.columns(3)
            rank_medals = ["🥇 #1 Top Sniper Pick", "🥈 #2 High-Conviction", "🥉 #3 Momentum Leader"]
            
            for idx, s_data in enumerate(snipers[:3]):
                with s_cols[idx]:
                    st.markdown(f"""
                    <div style="background: #0f172a; border: 1px solid #1e3a5f; border-left: 4px solid #38bdf8; border-radius: 8px; padding: 14px; margin-bottom: 8px;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                            <span style="font-weight: 700; color: #38bdf8; font-size: 0.88em;">{rank_medals[idx]}</span>
                            <span style="background: rgba(0, 200, 117, 0.15); color: #00c875; font-weight: 700; padding: 2px 8px; border-radius: 10px; font-size: 0.78em;">Score: {s_data['composite_score']}</span>
                        </div>
                        <div style="font-weight: 800; font-size: 1.15em; color: #f8fafc; margin-bottom: 2px;">{s_data['symbol']}</div>
                        <div style="font-size: 0.8em; color: #94a3b8; margin-bottom: 10px;">{s_data['name'][:24]} · {s_data['sector']} ({s_data['sector_badge']})</div>
                        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 6px; font-size: 0.85em; margin-bottom: 8px;">
                            <div>Entry: <b>₹{s_data['current_price']:,.2f}</b></div>
                            <div style="color: #00c875; font-weight: 600;">T1: <b>₹{s_data['target_1']:,.2f}</b> (+{s_data['target_1_upside_pct']:.1f}%)</div>
                            <div style="color: #f43f5e;">SL: <b>₹{s_data['stop_loss']:,.2f}</b> (-{s_data['stop_loss_downside_pct']:.1f}%)</div>
                            <div style="color: #c084fc; font-weight: 600;">R:R: <b>{s_data['risk_reward_ratio']:.2f}x</b></div>
                        </div>
                        <div style="font-size: 0.78em; color: #cbd5e1; border-top: 1px solid #1e293b; padding-top: 6px;">
                            💡 {s_data['key_reason'][:95]}
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

            if surv:
                st.markdown("<div style='font-size: 0.82em; font-weight: 700; color: #cbd5e1; margin-top: 6px;'>🔔 Active Position Surveillance Alerts:</div>", unsafe_allow_html=True)
                for alert in surv[:3]:
                    st.info(f"**{alert['symbol']}**: {alert['badge']} — {alert['message']}")

    # ── Key Indices Snapshot ──────────────────────────────────────────────────
    st.markdown("#### 🌐 Benchmark Indices")
    idx_cols = st.columns(4)
    indexes = [
        ("^NSEI", "NIFTY 50", "NSE Benchmark"),
        ("^BSESN", "SENSEX", "BSE Benchmark"),
        ("^NSEBANK", "BANK NIFTY", "Banking Sector"),
        ("^CNXIT", "NIFTY IT", "Tech Sector"),
    ]

    for col, (sym, name, desc) in zip(idx_cols, indexes):
        with col:
            res = session.execute(text("""
                SELECT close, daily_return FROM index_prices
                WHERE symbol = :s ORDER BY date DESC LIMIT 1
            """), {"s": sym}).fetchone()
            if res and res[0] is not None:
                close, ret = res
                delta = f"{ret:+.2f}%" if ret is not None else None
                st.metric(label=f"{name}", value=f"₹{close:,.1f}", delta=delta, help=desc)
            else:
                st.metric(label=name, value="—", delta=None)

    st.markdown("---")

    # ── Market Breadth & Leading Bellwether Radar ──────────────────────────────
    st.markdown("#### ⚡ Market Breadth & Leading Bellwether Radar")
    b_info = macro_info.get("breadth_info") or macro_info.get("breadth_details") or {}
    if not b_info or not b_info.get("pct_above_20_ema"):
        try:
            b_info = calculate_market_breadth(session)
        except Exception:
            pass

    bell_info = macro_info.get("bellwether_info") or macro_info.get("bellwether_details") or {}
    if not bell_info or not bell_info.get("heavyweight_anchors"):
        try:
            bell_info = evaluate_bellwether_lead_lag(session)
        except Exception:
            pass

    pct_20 = float(b_info.get('pct_above_20_ema') if b_info.get('pct_above_20_ema') is not None else macro_info.get('market_breadth_above_20_ema_pct', 0.0))
    pct_50 = float(b_info.get('pct_above_50_ema') if b_info.get('pct_above_50_ema') is not None else macro_info.get('market_breadth_above_50_ema_pct', 0.0))
    pct_200 = float(b_info.get('pct_above_200_ema') if b_info.get('pct_above_200_ema') is not None else macro_info.get('market_breadth_above_200_ema_pct', 0.0))
    thrust_badge = b_info.get('breadth_thrust_badge') or b_info.get('thrust_badge') or macro_info.get('breadth_thrust_badge') or '⚪ NORMAL'
    assessment = b_info.get('assessment') or b_info.get('thrust_note') or macro_info.get('thrust_note') or 'Breadth analytics tracking 322 active NSE equities.'

    rc1, rc2 = st.columns([1, 1])
    with rc1:
        st.markdown(f"""
        <div style="background: #111827; border: 1px solid #1e293b; border-radius: 10px; padding: 16px; min-height: 175px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                <span style="font-weight: 700; color: #f8fafc; font-size: 1.05em;">📡 Institutional Market Breadth</span>
                <span style="font-size: 0.82em; font-weight: 700; padding: 3px 10px; border-radius: 12px; background: rgba(56, 189, 248, 0.15); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.3);">
                    {thrust_badge}
                </span>
            </div>
            <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; text-align: center; margin-bottom: 12px;">
                <div style="background: #1e293b; padding: 8px; border-radius: 6px;">
                    <div style="color: #94a3b8; font-size: 0.78em;">> 20-Day EMA</div>
                    <div style="font-size: 1.2em; font-weight: 700; color: {'#00c875' if pct_20 >= 50 else '#f43f5e'};">
                        {pct_20:.1f}%
                    </div>
                </div>
                <div style="background: #1e293b; padding: 8px; border-radius: 6px;">
                    <div style="color: #94a3b8; font-size: 0.78em;">> 50-Day EMA</div>
                    <div style="font-size: 1.2em; font-weight: 700; color: {'#00c875' if pct_50 >= 50 else '#f43f5e'};">
                        {pct_50:.1f}%
                    </div>
                </div>
                <div style="background: #1e293b; padding: 8px; border-radius: 6px;">
                    <div style="color: #94a3b8; font-size: 0.78em;">> 200-Day EMA</div>
                    <div style="font-size: 1.2em; font-weight: 700; color: {'#00c875' if pct_200 >= 50 else '#f43f5e'};">
                        {pct_200:.1f}%
                    </div>
                </div>
            </div>
            <div style="font-size: 0.83em; color: #cbd5e1; line-height: 1.4;">
                {assessment}
            </div>
        </div>
        """, unsafe_allow_html=True)

    with rc2:
        anchors = bell_info.get("heavyweight_anchors") or {}
        bell_dir = bell_info.get("forecast_direction") or macro_info.get("bellwether_forecast") or "⚪ NEUTRAL"
        bell_conf = float(bell_info.get("forecast_confidence_pct") or bell_info.get("confidence_pct") or macro_info.get("bellwether_confidence_pct") or 50.0)
        mode_label = macro_info.get("active_strategy_mode") or "CAPITAL_PRESERVATION_HEDGE"
        mode_badges = {
            "HIGH_BETA_MOMENTUM": "🚀 High-Beta Momentum (75% Eq / 15% Gold / 10% Cash)",
            "MEAN_REVERSION_SUPPORT": "⚖️ Support Mean-Reversion (50% Eq / 30% Gold / 20% Cash)",
            "CAPITAL_PRESERVATION_HEDGE": "🛡️ Capital Preservation Hedge (25% Eq / 50% Gold / 25% Cash)"
        }
        mode_badge = mode_badges.get(mode_label, f"🛡️ {mode_label}")
        
        pill_html = ""
        for s_code, a_data in anchors.items():
            s_bias = a_data.get("bias", "NEUTRAL")
            s_color = "#00c875" if s_bias == "BULLISH" else ("#f43f5e" if s_bias == "BEARISH" else "#94a3b8")
            pill_html += f'<span style="background: #1e293b; border: 1px solid {s_color}44; color: {s_color}; padding: 2px 7px; border-radius: 5px; font-size: 0.74em; font-weight: 600;">{s_code} ({a_data.get("ret_1d", 0):+.1f}%)</span> '

        if not pill_html:
            pill_html = '<span style="color: #64748b; font-size: 0.8em;">Tracking ICICIBANK, HDFCBANK, RELIANCE, BHARTIARTL, SBIN</span>'

        st.markdown(f"""
        <div style="background: #111827; border: 1px solid #1e293b; border-radius: 10px; padding: 16px; min-height: 175px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                <span style="font-weight: 700; color: #f8fafc; font-size: 1.05em;">🧭 Bellwether Consensus & Strategy Routing</span>
                <span style="font-size: 0.82em; font-weight: 700; padding: 3px 10px; border-radius: 12px; background: rgba(168, 85, 247, 0.15); color: #c084fc; border: 1px solid rgba(168, 85, 247, 0.3);">
                    {bell_dir} ({bell_conf:.0f}% Conf)
                </span>
            </div>
            <div style="margin-bottom: 8px;">
                <div style="font-size: 0.78em; color: #94a3b8; margin-bottom: 4px;">Heavyweight Anchor Direction (42% Nifty Weight):</div>
                <div style="display: flex; gap: 4px; flex-wrap: wrap;">{pill_html}</div>
            </div>
            <div style="background: #1e293b; border-left: 3px solid #38bdf8; padding: 7px 10px; border-radius: 6px; margin-top: 6px;">
                <div style="font-size: 0.75em; color: #38bdf8; font-weight: 600;">ACTIVE STRATEGY ROUTING</div>
                <div style="font-size: 0.83em; font-weight: 700; color: #f8fafc;">{mode_badge}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")

    # ── Sector Relative Strength & Leadership Flow ───────────────────────────
    st.markdown("#### 🏆 Sector Relative Strength (RS) & Leadership Flow")
    try:
        sec_rs_data = calculate_sector_relative_strength(session)
    except Exception:
        sec_rs_data = {}

    if sec_rs_data:
        sorted_secs = sorted(sec_rs_data.values(), key=lambda x: x.get("rs_20d", 0.0), reverse=True)
        sec_kpi1, sec_kpi2, sec_kpi3, sec_kpi4 = st.columns(4)
        with sec_kpi1:
            best_sec = sorted_secs[0] if sorted_secs else {}
            st.metric(
                label="🥇 Leading Sector",
                value=best_sec.get("sector", "N/A")[:16],
                delta=f"{best_sec.get('rs_20d', 0.0):+.1f}% vs NIFTY",
                help=f"20D Return: {best_sec.get('ret_20d', 0.0):+.1f}% | 50D Return: {best_sec.get('ret_50d', 0.0):+.1f}%"
            )
        with sec_kpi2:
            runner_up = sorted_secs[1] if len(sorted_secs) > 1 else {}
            st.metric(
                label="🥈 Momentum Chaser",
                value=runner_up.get("sector", "N/A")[:16],
                delta=f"{runner_up.get('rs_20d', 0.0):+.1f}% vs NIFTY",
                help=f"20D Return: {runner_up.get('ret_20d', 0.0):+.1f}%"
            )
        with sec_kpi3:
            gated_count = sum(1 for s in sorted_secs if s.get("is_gated"))
            st.metric(
                label="🛡️ RS Guardrail Gated",
                value=f"{gated_count} Sectors",
                delta=f"-{gated_count} Filtered" if gated_count > 0 else "0 Filtered",
                delta_color="inverse" if gated_count > 0 else "normal",
                help="Sectors in chronic multi-month downtrends gated from new BUY capital allocation unless score >= 75."
            )
        with sec_kpi4:
            worst_sec = sorted_secs[-1] if sorted_secs else {}
            st.metric(
                label="⚠️ Deepest Laggard",
                value=worst_sec.get("sector", "N/A")[:16],
                delta=f"{worst_sec.get('rs_20d', 0.0):+.1f}% vs NIFTY",
                delta_color="inverse",
                help=f"20D Return: {worst_sec.get('ret_20d', 0.0):+.1f}% | Classification: {worst_sec.get('classification')}"
            )

        with st.expander("📊 Complete Sector Relative Strength (RS) Matrix & Gating Status", expanded=False):
            sec_rows = []
            for s in sorted_secs:
                gate_str = "🛑 Gated (Filtered)" if s.get("is_gated") else "🟢 Approved"
                sec_rows.append({
                    "Sector": s.get("sector"),
                    "Status": s.get("badge"),
                    "20D Return": s.get("ret_20d", 0.0),
                    "50D Return": s.get("ret_50d", 0.0),
                    "Excess vs Nifty (20D)": s.get("rs_20d", 0.0),
                    "Excess vs Nifty (50D)": s.get("rs_50d", 0.0),
                    "Equities": s.get("stock_count", 0),
                    "Allocation Guardrail": gate_str
                })
            df_sec = pd.DataFrame(sec_rows)
            st.dataframe(
                df_sec.style.format({
                    "20D Return": "{:+.2f}%",
                    "50D Return": "{:+.2f}%",
                    "Excess vs Nifty (20D)": "{:+.2f}%",
                    "Excess vs Nifty (50D)": "{:+.2f}%",
                    "Equities": "{:,}"
                }),
                use_container_width=True,
                hide_index=True
            )

    st.markdown("---")

    # ── High-Conviction Signals ───────────────────────────────────────────────
    st.markdown("#### 🎯 Today's High-Conviction Alpha Signals")
    sig_tab1, sig_tab2 = st.tabs(["🟢 Top BUY Signals (Apex Long)", "🔴 Top SELL Signals (Risk Reduction)"])

    def format_price(p): return f"₹{p:,.2f}" if p else "—"

    with sig_tab1:
        top_buys = session.execute(text("""
            SELECT sig.symbol, s.name, s.sector, sig.current_price,
                   sig.target_price_1, sig.stop_loss, sig.risk_level, sig.key_reason,
                   cs.composite_score, ind.trend_pattern
            FROM signals sig
            JOIN stocks s ON sig.symbol = s.symbol
            JOIN composite_scores cs ON sig.symbol = cs.symbol AND sig.date = cs.date
            LEFT JOIN technical_indicators ind ON sig.symbol = ind.symbol AND sig.date = ind.date
            WHERE sig.signal = 'BUY'
            AND sig.date = (SELECT MAX(date) FROM signals)
            ORDER BY cs.composite_score DESC
            LIMIT 6
        """)).fetchall()

        if top_buys:
            buy_cols = st.columns(3)
            for i, row in enumerate(top_buys):
                sym, name, sector, price, t1, sl, risk, reason, score, trend = row
                with buy_cols[i % 3]:
                    upside = ((t1 - price) / price * 100) if price and t1 else 0
                    st.markdown(f"""
                    <div style="background: #131d2a; border: 1px solid #1e2d3d; border-radius: 8px; padding: 14px; margin-bottom: 12px;">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <span style="font-weight: 700; color: #f8fafc; font-size: 1.05em;">{sym}</span>
                            <span style="background: rgba(0, 200, 117, 0.2); color: #00c875; font-weight: 700; padding: 2px 8px; border-radius: 12px; font-size: 0.8em;">Score: {score:.0f}</span>
                        </div>
                        <div style="color: #94a3b8; font-size: 0.82em; margin-bottom: 8px;">{name[:28]} · {sector}</div>
                        <div style="display: flex; justify-content: space-between; font-size: 0.9em; margin-bottom: 4px;">
                            <span style="color: #cbd5e1;">Price: <b>{format_price(price)}</b></span>
                            <span style="color: #00c875; font-weight: 600;">Target: {format_price(t1)} (+{upside:.1f}%)</span>
                        </div>
                        <div style="display: flex; justify-content: space-between; font-size: 0.82em; color: #64748b;">
                            <span>Stop-Loss: {format_price(sl)}</span>
                            <span>{trend or 'Trending'}</span>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
        else:
            st.info("No active BUY signals today.")

    with sig_tab2:
        top_sells = session.execute(text("""
            SELECT sig.symbol, s.name, s.sector, sig.current_price,
                   sig.target_price_1, sig.stop_loss, sig.risk_level, sig.key_reason,
                   cs.composite_score, ind.trend_pattern
            FROM signals sig
            JOIN stocks s ON sig.symbol = s.symbol
            JOIN composite_scores cs ON sig.symbol = cs.symbol AND sig.date = cs.date
            LEFT JOIN technical_indicators ind ON sig.symbol = ind.symbol AND sig.date = ind.date
            WHERE sig.signal = 'SELL'
            AND sig.date = (SELECT MAX(date) FROM signals)
            ORDER BY cs.composite_score ASC
            LIMIT 6
        """)).fetchall()

        if top_sells:
            sell_cols = st.columns(3)
            for i, row in enumerate(top_sells):
                sym, name, sector, price, t1, sl, risk, reason, score, trend = row
                with sell_cols[i % 3]:
                    downside = ((t1 - price) / price * 100) if price and t1 else 0
                    st.markdown(f"""
                    <div style="background: #201518; border: 1px solid #3d2024; border-radius: 8px; padding: 14px; margin-bottom: 12px;">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <span style="font-weight: 700; color: #f8fafc; font-size: 1.05em;">{sym}</span>
                            <span style="background: rgba(239, 68, 68, 0.2); color: #ef4444; font-weight: 700; padding: 2px 8px; border-radius: 12px; font-size: 0.8em;">Score: {score:.0f}</span>
                        </div>
                        <div style="color: #94a3b8; font-size: 0.82em; margin-bottom: 8px;">{name[:28]} · {sector}</div>
                        <div style="display: flex; justify-content: space-between; font-size: 0.9em; margin-bottom: 4px;">
                            <span style="color: #cbd5e1;">Price: <b>{format_price(price)}</b></span>
                            <span style="color: #ef4444; font-weight: 600;">Down Target: {format_price(t1)} ({downside:.1f}%)</span>
                        </div>
                        <div style="display: flex; justify-content: space-between; font-size: 0.82em; color: #64748b;">
                            <span>Exit SL: {format_price(sl)}</span>
                            <span>{trend or 'Weakening'}</span>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
        else:
            st.info("No active SELL alerts today.")

    st.markdown("---")

    # ── Global Commodities Matrix ─────────────────────────────────────────────
    st.markdown("#### 🪙 Global Commodities & Currency Benchmarks")
    comm_cols = st.columns(6)
    commodities = [
        ("GC=F", "Gold", "$"), ("SI=F", "Silver", "$"), ("CL=F", "Crude Oil", "$"),
        ("NG=F", "Natural Gas", "$"), ("HG=F", "Copper", "$"), ("GOLDBEES.NS", "Gold ETF", "₹")
    ]
    for col, (sym, name, cur) in zip(comm_cols, commodities):
        with col:
            res = session.execute(text("""
                SELECT close, daily_return FROM commodity_prices
                WHERE symbol=:s ORDER BY date DESC LIMIT 1
            """), {"s": sym}).fetchone()
            if res and res[0] is not None:
                c_val, c_ret = res
                ret_str = f"{c_ret:+.2f}%" if c_ret is not None else None
                st.metric(name, f"{cur}{c_val:,.1f}", ret_str)
            else:
                st.metric(name, "—", None)

finally:
    session.close()
