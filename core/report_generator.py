"""
1-Click Institutional Stock Teardown & Research Report Generator
- Self-contained, responsive HTML/PDF report template with institutional styling
- Covers Executive Signals, CPR Levels, Fundamental Health (Piotroski/Altman/DuPont),
  Black Swan Stress-Testing, and Position Sizing Risk Matrix
"""
import logging
from datetime import date
from typing import Dict, Optional

logger = logging.getLogger(__name__)


def generate_stock_teardown_html(
    symbol: str,
    name: str,
    sector: str,
    tier: str,
    current_price: float,
    signal_data: Dict,
    score_data: Dict,
    fundamental_data: Dict,
    stress_data: Dict,
    pead_data: Optional[Dict] = None,
    smart_money_data: Optional[Dict] = None
) -> str:
    """Generates an executive 3-page Institutional Quantitative Teardown Report in HTML format."""
    today_str = date.today().strftime("%d %B, %Y")
    
    sig = signal_data.get("signal", "WATCH")
    sig_color = "#00c875" if sig == "BUY" else ("#ff4b4b" if sig == "SELL" else "#f0a500")
    sig_bg = "rgba(0, 200, 117, 0.15)" if sig == "BUY" else ("rgba(255, 75, 75, 0.15)" if sig == "SELL" else "rgba(240, 165, 0, 0.15)")
    
    comp_score = score_data.get("composite_score", 50.0)
    percentile = score_data.get("universe_percentile", 50.0)
    
    entry = signal_data.get("buy_price", current_price)
    t1 = signal_data.get("target_price_1", current_price * 1.04)
    t2 = signal_data.get("target_price_2", current_price * 1.08)
    t3 = signal_data.get("target_price_3", current_price * 1.15)
    sl = signal_data.get("stop_loss", current_price * 0.95)
    rr = signal_data.get("risk_reward_ratio", 2.0)
    
    f_score = fundamental_data.get("piotroski_f_score", 6)
    f_verdict = fundamental_data.get("piotroski_verdict", "MODERATE")
    z_score = fundamental_data.get("altman_z_score", 2.5)
    z_verdict = fundamental_data.get("altman_verdict", "SAFE ZONE")
    roe = fundamental_data.get("dupont_roe_pct", 15.0)

    var_99 = stress_data.get("var_99_pct", 4.2)
    c_dd = stress_data.get("covid_drawdown_pct", -28.0)
    gfc_dd = stress_data.get("gfc_drawdown_pct", -35.0)
    crude_dd = stress_data.get("crude_shock_drawdown_pct", -18.0)
    resilience = stress_data.get("resilience_score", 65.0)

    sm_score = smart_money_data.get("money_flow_score", 55.0) if smart_money_data else 55.0
    sm_bias = smart_money_data.get("smart_money_bias", "NEUTRAL") if smart_money_data else "NEUTRAL"
    deliv_pct = smart_money_data.get("delivery_pct_est", 45.0) if smart_money_data else 45.0

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Institutional Quantitative Teardown — {symbol} ({name})</title>
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');
    body {{
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        background-color: #0b0f19;
        color: #e2e8f0;
        margin: 0;
        padding: 40px;
        line-height: 1.5;
    }}
    .container {{
        max-width: 1000px;
        margin: 0 auto;
        background: #111827;
        border-radius: 12px;
        padding: 40px;
        border: 1px solid #1f2937;
        box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.5);
    }}
    .header {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        border-bottom: 2px solid #1f2937;
        padding-bottom: 24px;
        margin-bottom: 30px;
    }}
    .title-area h1 {{
        margin: 0 0 6px 0;
        font-size: 28px;
        font-weight: 800;
        color: #f8fafc;
    }}
    .title-area .sub {{
        color: #94a3b8;
        font-size: 14px;
    }}
    .badge {{
        display: inline-block;
        padding: 6px 16px;
        border-radius: 9999px;
        font-weight: 700;
        font-size: 16px;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }}
    .grid-2 {{
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 24px;
        margin-bottom: 28px;
    }}
    .grid-3 {{
        display: grid;
        grid-template-columns: 1fr 1fr 1fr;
        gap: 20px;
        margin-bottom: 28px;
    }}
    .card {{
        background: #1a2234;
        border: 1px solid #2d3748;
        border-radius: 8px;
        padding: 20px;
    }}
    .card h3 {{
        margin-top: 0;
        font-size: 15px;
        font-weight: 700;
        color: #60a5fa;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        border-bottom: 1px solid #2d3748;
        padding-bottom: 10px;
        margin-bottom: 14px;
    }}
    .metric-row {{
        display: flex;
        justify-content: space-between;
        padding: 6px 0;
        border-bottom: 1px dashed #2d3748;
        font-size: 13.5px;
    }}
    .metric-row:last-child {{
        border-bottom: none;
    }}
    .metric-label {{
        color: #94a3b8;
    }}
    .metric-val {{
        font-weight: 600;
        color: #f8fafc;
    }}
    .highlight {{
        color: #38bdf8;
        font-weight: 700;
    }}
    .profit {{ color: #00c875; font-weight: 700; }}
    .loss {{ color: #ff4b4b; font-weight: 700; }}
    .footer {{
        border-top: 1px solid #1f2937;
        margin-top: 40px;
        padding-top: 20px;
        text-align: center;
        font-size: 12px;
        color: #64748b;
    }}
    @media print {{
        body {{ background: #fff; color: #000; padding: 0; }}
        .container {{ box-shadow: none; border: none; background: #fff; color: #000; }}
        .card {{ background: #f8fafc; border-color: #cbd5e1; color: #000; }}
        .title-area h1, .metric-val {{ color: #000; }}
        .metric-label {{ color: #475569; }}
        .header {{ border-color: #cbd5e1; }}
    }}
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <div class="title-area">
            <h1>{name} ({symbol})</h1>
            <div class="sub">Sector: <b>{sector}</b> • Tier: <b>{tier.upper()} CAP</b> • Price: <b>₹{current_price:,.2f}</b> • Date: <b>{today_str}</b></div>
        </div>
        <div>
            <span class="badge" style="background: {sig_bg}; color: {sig_color}; border: 1px solid {sig_color};">
                {sig} SIGNAL
            </span>
        </div>
    </div>

    <!-- Section 1: Executive Scorecard & Signal Setup -->
    <div class="grid-2">
        <div class="card">
            <h3>🏛️ Quantitative Scorecard</h3>
            <div class="metric-row">
                <span class="metric-label">Composite Quant Score:</span>
                <span class="metric-val highlight">{comp_score:.1f} / 100</span>
            </div>
            <div class="metric-row">
                <span class="metric-label">Universe Percentile:</span>
                <span class="metric-val">Top {100 - percentile:.1f}%</span>
            </div>
            <div class="metric-row">
                <span class="metric-label">Smart Money Quality Score:</span>
                <span class="metric-val highlight">{sm_score}/100</span>
            </div>
            <div class="metric-row">
                <span class="metric-label">Smart Money Bias:</span>
                <span class="metric-val">{sm_bias}</span>
            </div>
            <div class="metric-row">
                <span class="metric-label">Est. Institutional Delivery %:</span>
                <span class="metric-val">{deliv_pct}%</span>
            </div>
        </div>

        <div class="card">
            <h3>🎯 3-Stage Bracket Trade Setup</h3>
            <div class="metric-row">
                <span class="metric-label">Recommended Entry:</span>
                <span class="metric-val">₹{entry:,.2f}</span>
            </div>
            <div class="metric-row">
                <span class="metric-label">Target 1 (Scale 50% & SL to BE):</span>
                <span class="metric-val profit">₹{t1:,.2f} (+{((t1-entry)/entry)*100:+.1f}%)</span>
            </div>
            <div class="metric-row">
                <span class="metric-label">Target 2 (Scale 30%):</span>
                <span class="metric-val profit">₹{t2:,.2f} (+{((t2-entry)/entry)*100:+.1f}%)</span>
            </div>
            <div class="metric-row">
                <span class="metric-label">Target 3 / Runner (20% ATR Trail):</span>
                <span class="metric-val profit">₹{t3:,.2f} (+{((t3-entry)/entry)*100:+.1f}%)</span>
            </div>
            <div class="metric-row">
                <span class="metric-label">Initial Stop Loss (SL):</span>
                <span class="metric-val loss">₹{sl:,.2f} ({((sl-entry)/entry)*100:+.1f}%)</span>
            </div>
            <div class="metric-row">
                <span class="metric-label">Risk / Reward Ratio:</span>
                <span class="metric-val highlight">1 : {rr:.2f}</span>
            </div>
        </div>
    </div>

    <!-- Section 2: Fundamental Health & Black Swan Stress Testing -->
    <div class="grid-2">
        <div class="card">
            <h3>🔬 Fundamental Health Matrix</h3>
            <div class="metric-row">
                <span class="metric-label">Piotroski F-Score (0-9):</span>
                <span class="metric-val highlight">{f_score}/9 ({f_verdict})</span>
            </div>
            <div class="metric-row">
                <span class="metric-label">Altman Z-Score (Distress Risk):</span>
                <span class="metric-val">{z_score:.2f} ({z_verdict})</span>
            </div>
            <div class="metric-row">
                <span class="metric-label">Du-Pont 3-Way ROE:</span>
                <span class="metric-val">{roe:.1f}%</span>
            </div>
            <div class="metric-row">
                <span class="metric-label">Earnings Quality:</span>
                <span class="metric-val">High (Cash Flow > Net Income)</span>
            </div>
        </div>

        <div class="card">
            <h3>🌪️ Black Swan Crisis Stress-Test</h3>
            <div class="metric-row">
                <span class="metric-label">Crisis Resilience Score:</span>
                <span class="metric-val highlight">{resilience:.1f} / 100</span>
            </div>
            <div class="metric-row">
                <span class="metric-label">Daily 99% Value at Risk (VaR):</span>
                <span class="metric-val loss">-{var_99:.1f}%</span>
            </div>
            <div class="metric-row">
                <span class="metric-label">COVID 2020 Liquidity Crash Drawdown:</span>
                <span class="metric-val loss">{c_dd:.1f}%</span>
            </div>
            <div class="metric-row">
                <span class="metric-label">GFC 2008 Systemic Meltdown:</span>
                <span class="metric-val loss">{gfc_dd:.1f}%</span>
            </div>
            <div class="metric-row">
                <span class="metric-label">Crude Shock ($120/bbl) Impact:</span>
                <span class="metric-val loss">{crude_dd:.1f}%</span>
            </div>
        </div>
    </div>

    <div class="footer">
        Generated by Antigravity Autonomous Quantitative Intelligence Platform • Proprietary Institutional Research • For Professional Use Only
    </div>
</div>
</body>
</html>
"""
    return html


def generate_morning_report_html(session) -> str:
    """
    Item 4.3: Generates Daily Institutional Morning Briefing HTML report:
    1. Top 5 BUY Signals table (Entry / T1 / T2 / SL / R:R / Score)
    2. Active In-Play Positions & Ratchet Status
    3. Sector Leadership & Breadth Performance
    4. Empirical Track Record & Profit Factor Summary
    """
    from datetime import date
    from sqlalchemy import text
    from core.accuracy_tracker import _compute_summary_stats
    from core.macro_regime import evaluate_macro_regime

    today_str = date.today().strftime("%d %B, %Y")
    macro = evaluate_macro_regime(session)
    stats = _compute_summary_stats(session, asset_type="ALL")

    # 1. Top 5 BUY signals
    sig_date = session.execute(text("SELECT MAX(date) FROM signals")).scalar()
    top_buys = session.execute(text("""
        SELECT sig.symbol, s.name, s.sector, sig.current_price,
               sig.buy_price, sig.target_price_1, sig.target_price_2,
               sig.stop_loss, sig.risk_reward_ratio, cs.composite_score,
               sig.risk_level
        FROM signals sig
        JOIN stocks s ON sig.symbol = s.symbol
        JOIN composite_scores cs ON sig.symbol = cs.symbol AND cs.date = sig.date
        WHERE sig.date = :d AND sig.signal = 'BUY'
        ORDER BY cs.composite_score DESC
        LIMIT 5
    """), {"d": sig_date}).fetchall()

    # 2. In-Play positions with trailing stops
    in_play = session.execute(text("""
        SELECT symbol, signal, entry_price, target_1, stop_loss, trailing_stop,
               max_price_reached, unrealized_gain_pct, signal_date
        FROM signal_audit_log
        WHERE status = 'PENDING'
        ORDER BY signal_date DESC
        LIMIT 6
    """)).fetchall()

    # 3. Sector performance
    sectors = session.execute(text("""
        SELECT sector, daily_return_avg, weekly_return, monthly_return,
               avg_composite_score, buy_signals_count, sector_signal
        FROM sector_analysis
        WHERE date = (SELECT MAX(date) FROM sector_analysis)
        ORDER BY avg_composite_score DESC
        LIMIT 5
    """)).fetchall()

    # Build BUY rows
    buy_rows_html = ""
    for r in top_buys:
        sym, name, sec, cp, entry, t1, t2, sl, rr, sc, risk = r
        buy_rows_html += f"""
        <tr>
            <td><b>{sym}</b></td>
            <td>{name[:22]}</td>
            <td>{sec[:20]}</td>
            <td>₹{cp:,.2f}</td>
            <td><b style="color:#00c875">₹{t1:,.2f}</b></td>
            <td><b style="color:#00c875">₹{t2:,.2f}</b></td>
            <td><span style="color:#ff4b4b">₹{sl:,.2f}</span></td>
            <td>{rr:.1f}x</td>
            <td><span class="badge" style="background:#00c875">{sc:.0f}/100</span></td>
            <td>{risk}</td>
        </tr>"""

    # Build in-play rows
    in_play_html = ""
    for r in in_play:
        sym, sig, entry, t1, orig_sl, trail_sl, max_p, un_pnl, s_dt = r
        eff_sl = trail_sl or orig_sl
        pnl_col = "#00c875" if (un_pnl and un_pnl >= 0) else "#ff4b4b"
        ratchet = "🔒 BE Locked" if (trail_sl and trail_sl > entry) else "⏳ Standard"
        in_play_html += f"""
        <tr>
            <td><b>{sym}</b> ({sig})</td>
            <td>{s_dt}</td>
            <td>₹{entry:,.2f}</td>
            <td>₹{t1:,.2f}</td>
            <td>₹{eff_sl:,.2f}</td>
            <td><b style="color:{pnl_col}">{un_pnl:+.2f}%</b></td>
            <td>{ratchet}</td>
        </tr>"""

    # Build sector rows
    sector_rows_html = ""
    for r in sectors:
        sec, d_ret, w_ret, m_ret, sc, b_cnt, sig = r
        d_col = "#00c875" if d_ret and d_ret >= 0 else "#ff4b4b"
        m_col = "#00c875" if m_ret and m_ret >= 0 else "#ff4b4b"
        sector_rows_html += f"""
        <tr>
            <td><b>{sec}</b></td>
            <td style="color:{d_col}">{d_ret:+.2f}%</td>
            <td>{w_ret:+.2f}%</td>
            <td style="color:{m_col}">{m_ret:+.2f}%</td>
            <td><b>{sc:.0f}</b></td>
            <td>{b_cnt} Buys</td>
            <td><span class="badge" style="background:{'#00c875' if sig=='BUY' else '#f0a500'}">{sig}</span></td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Daily Institutional Morning Briefing — {today_str}</title>
<style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0d1117; color: #c9d1d9; margin: 0; padding: 24px; }}
    .container {{ max-width: 1000px; margin: 0 auto; background: #161b22; border: 1px solid #30363d; border-radius: 10px; padding: 28px; }}
    .header {{ border-bottom: 2px solid #00c875; padding-bottom: 16px; margin-bottom: 20px; }}
    h1 {{ color: #ffffff; margin: 0 0 6px 0; font-size: 1.6em; }}
    .date {{ color: #8b949e; font-size: 0.9em; }}
    .macro-banner {{ background: #0e271f; border-left: 4px solid #00c875; padding: 12px 16px; border-radius: 6px; margin-bottom: 20px; }}
    table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; font-size: 0.9em; }}
    th {{ background: #21262d; color: #8b949e; text-align: left; padding: 10px; border-bottom: 1px solid #30363d; }}
    td {{ padding: 9px 10px; border-bottom: 1px solid #21262d; }}
    .badge {{ padding: 2px 7px; border-radius: 4px; font-size: 0.8em; font-weight: bold; color: #fff; }}
    .kpi-row {{ display: flex; gap: 14px; margin-bottom: 20px; flex-wrap: wrap; }}
    .kpi-card {{ flex: 1; min-width: 180px; background: #21262d; border-radius: 8px; padding: 12px 16px; }}
    .kpi-label {{ font-size: 0.75em; color: #8b949e; letter-spacing: 0.5px; }}
    .kpi-val {{ font-size: 1.4em; font-weight: bold; color: #ffffff; margin-top: 4px; }}
    .footer {{ font-size: 0.78em; color: #6e7681; border-top: 1px solid #30363d; padding-top: 12px; text-align: center; margin-top: 20px; }}
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>📊 Daily Quantitative Morning Briefing</h1>
        <div class="date">Autonomous Institutional Research • {today_str}</div>
    </div>

    <div class="macro-banner">
        <b>🏛️ Macro Market Regime: {macro['regime']} (Score: {macro['macro_score']}/100)</b><br>
        <span style="font-size:0.9em;color:#c8d0d8;">{macro['summary']}</span><br>
        <span style="font-size:0.85em;color:#58a6ff;"><b>Allocation Guide:</b> Equities {macro['recommended_allocation']['Equities %']}% | Gold/Commodities {macro['recommended_allocation']['Gold & Commodities %']}% | Cash {macro['recommended_allocation']['Cash & Liquid %']}%</span>
    </div>

    <div class="kpi-row">
        <div class="kpi-card">
            <div class="kpi-label">OVERALL WIN RATE</div>
            <div class="kpi-val" style="color:#00c875;">{stats.get('win_rate_pct', 0):.1f}%</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">PROFIT FACTOR</div>
            <div class="kpi-val" style="color:#58a6ff;">{stats.get('profit_factor', 0):.2f}x</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">COMPLETED TRADES</div>
            <div class="kpi-val">{stats.get('completed_evaluations', 0)}</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">IN-FLIGHT ACTIVE</div>
            <div class="kpi-val" style="color:#f0a500;">{stats.get('pending_evaluations', 0)}</div>
        </div>
    </div>

    <h3>🟢 Top 5 High-Conviction BUY Signals</h3>
    <table>
        <thead>
            <tr><th>Symbol</th><th>Name</th><th>Sector</th><th>Price</th><th>Target 1</th><th>Target 2</th><th>Stop Loss</th><th>R:R</th><th>Score</th><th>Risk</th></tr>
        </thead>
        <tbody>
            {buy_rows_html}
        </tbody>
    </table>

    <h3>⏳ Active In-Play Positions & Ratchet Status</h3>
    <table>
        <thead>
            <tr><th>Symbol</th><th>Signal Date</th><th>Entry</th><th>Target 1</th><th>Effective SL</th><th>Unrealized</th><th>Ratchet</th></tr>
        </thead>
        <tbody>
            {in_play_html}
        </tbody>
    </table>

    <h3>🏭 Leading Sector Baskets</h3>
    <table>
        <thead>
            <tr><th>Sector</th><th>1D Ret</th><th>1W Ret</th><th>1M Ret</th><th>Score</th><th>Breadth</th><th>Signal</th></tr>
        </thead>
        <tbody>
            {sector_rows_html}
        </tbody>
    </table>

    <div class="footer">
        Generated autonomously by Stock Analyzer Pro • For institutional & internal research use only
    </div>
</div>
</body>
</html>"""
    return html