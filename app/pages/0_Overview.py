"""
Page 0: Market Overview & Institutional Cockpit
Consolidated Executive Summary: Core Indices, Commodities, and Top Multi-Model Signals
"""
import sys
from pathlib import Path
import streamlit as st
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

from config.settings import APP_TITLE, APP_VERSION, DISCLAIMER
from db.database import get_global_engine, get_session
from core.data_status import get_database_status_summary
from core.macro_regime import evaluate_macro_regime

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
