"""
Multi-Stage Profit Tranche & Position Sizing Engine ("Let Winners Run")
Institutional trade management blueprint:
  - Tranche 1 (50% size): Lock baseline profit at Target 1 -> Ratchet Stop Loss to Breakeven (+0.2%)
  - Tranche 2 (25% size): Lock secondary profit at Target 2 -> Ratchet Trailing Stop to Target 1
  - Tranche 3 (25% size): Ride Runner to Target 3 or trail with 20 EMA
Calculates exact share allocation and rupee risk from total account capital & portfolio risk %.
"""

import math
from typing import Dict, Optional


def calculate_tranche_execution_plan(
    entry_price: float,
    t1: float,
    t2: Optional[float],
    t3: Optional[float],
    sl: float,
    account_capital: float = 200000.0,
    risk_pct: float = 1.5,
    signal: str = "BUY",
    atr: Optional[float] = None,
    swing_low: Optional[float] = None
) -> Dict:
    """
    Computes institutional tranche exits, position size, and capital risk.
    Incorporate an ATR morning noise cushion (0.45x ATR) and Target 1 retest buffer
    to prevent premature shakeouts during session-opening intraday pullbacks.
    """
    if not entry_price or entry_price <= 0:
        return {}

    signal = signal.upper() if signal else "BUY"
    t1 = float(t1 or (entry_price * 1.03 if signal == "BUY" else entry_price * 0.97))
    t2 = float(t2 or (entry_price * 1.06 if signal == "BUY" else entry_price * 0.94))
    t3 = float(t3 or (entry_price * 1.10 if signal == "BUY" else entry_price * 0.90))
    sl = float(sl or (entry_price * 0.97 if signal == "BUY" else entry_price * 1.03))

    risk_per_share = abs(entry_price - sl)
    if risk_per_share <= 0:
        risk_per_share = entry_price * 0.02

    risk_budget = float(account_capital) * (float(risk_pct) / 100.0)
    raw_shares = risk_budget / risk_per_share
    total_shares = max(1, math.floor(raw_shares))

    capital_allocated = total_shares * entry_price
    capital_allocated_pct = (capital_allocated / account_capital * 100.0) if account_capital > 0 else 0.0
    worst_case_loss = total_shares * risk_per_share

    # Volatility & Morning Noise Cushion (0.45x ATR)
    atr_val = float(atr) if (atr and atr > 0) else round(entry_price * 0.018, 2)
    morning_buffer = round(0.45 * atr_val, 2)
    morning_buffer_pct = round((morning_buffer / entry_price) * 100.0, 2)

    # Tranche 1: 50% Size
    t1_shares = max(1, math.floor(total_shares * 0.50)) if total_shares >= 2 else total_shares
    t1_gain_share = abs(t1 - entry_price)
    t1_gain_pct = (t1_gain_share / entry_price) * 100.0
    t1_profit = t1_shares * t1_gain_share

    # Ratchet SL with Morning Shakeout Cushion
    rem_after_t1 = total_shares - t1_shares
    if signal == "BUY":
        ratchet_sl_1 = round(entry_price - morning_buffer, 2)
        if swing_low and 0 < swing_low < entry_price:
            ratchet_sl_1 = max(ratchet_sl_1, round(swing_low, 2))
        rem_loss_t1 = (entry_price - ratchet_sl_1) * rem_after_t1
    else:
        ratchet_sl_1 = round(entry_price + morning_buffer, 2)
        if swing_low and swing_low > entry_price:
            ratchet_sl_1 = min(ratchet_sl_1, round(swing_low, 2))
        rem_loss_t1 = (ratchet_sl_1 - entry_price) * rem_after_t1

    guaranteed_net_t1 = max(0.0, t1_profit - rem_loss_t1)

    # Tranche 2: 25% Size
    t2_shares = math.floor(total_shares * 0.25) if rem_after_t1 >= 2 else rem_after_t1
    t2_gain_share = abs(t2 - entry_price)
    t2_gain_pct = (t2_gain_share / entry_price) * 100.0
    t2_profit = t2_shares * t2_gain_share

    retest_buffer = round(0.35 * atr_val, 2)
    ratchet_sl_2 = round(t1 - retest_buffer, 2) if signal == "BUY" else round(t1 + retest_buffer, 2)

    # Tranche 3: 25% Runner
    t3_shares = total_shares - t1_shares - t2_shares
    t3_gain_share = abs(t3 - entry_price)
    t3_gain_pct = (t3_gain_share / entry_price) * 100.0
    t3_profit = t3_shares * t3_gain_share

    total_expected_profit = t1_profit + t2_profit + t3_profit
    blended_gain_pct = (total_expected_profit / capital_allocated * 100.0) if capital_allocated > 0 else 0.0
    blended_rr = round(total_expected_profit / worst_case_loss, 2) if worst_case_loss > 0 else 2.5

    # HTML Blueprint Card
    color_accent = "#00c875" if signal == "BUY" else "#ff4b4b"
    blueprint_html = (
        f'<div style="background: #111822; border: 1px solid #2d3748; border-radius: 8px; padding: 12px 14px; margin-top: 8px;">'
        f'<div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #222d3d; padding-bottom: 6px; margin-bottom: 8px;">'
        f'<span style="font-weight: 700; color: {color_accent}; font-size: 0.95em;">'
        f'⚡ 3-Stage Profit Tranche Plan (with Morning Shakeout Buffers)'
        f'</span>'
        f'<span style="font-size: 0.85em; color: #8b949e;">'
        f'Blended R:R: <b style="color: #58a6ff;">1 : {blended_rr}</b> &nbsp;|&nbsp; '
        f'Max Risk: <b style="color: #ff4b4b;">₹{worst_case_loss:,.0f} ({risk_pct}%)</b> &nbsp;|&nbsp; '
        f'1-ATR Cushion: <b style="color: #e2e8f0;">₹{atr_val:,.1f}</b>'
        f'</span>'
        f'</div>'
        f'<div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; font-size: 0.86em;">'
        f'<div style="background: rgba(0, 200, 117, 0.08); border-left: 3px solid #00c875; padding: 8px; border-radius: 4px;">'
        f'<div style="color: #00c875; font-weight: 700;">Stage 1: 50% Size ({t1_shares} Qty)</div>'
        f'<div style="color: #e2e8f0; margin-top: 2px;">Target: <b>₹{t1:,.2f}</b> (+{t1_gain_pct:.1f}%)</div>'
        f'<div style="color: #00c875; font-weight: 600;">Lock Profit: +₹{t1_profit:,.0f}</div>'
        f'<div style="color: #94a3b8; font-size: 0.84em; margin-top: 4px; line-height: 1.35;">'
        f'🛡️ <i>Action:</i> Ratchet SL to <b>₹{ratchet_sl_1:,.2f}</b> '
        f'<span style="color: #a0aec0;">(Breakeven − {morning_buffer_pct}% buffer for 9:15 AM wicks; guaranteed net +₹{guaranteed_net_t1:,.0f}).</span>'
        f'</div>'
        f'</div>'
        f'<div style="background: rgba(31, 111, 235, 0.08); border-left: 3px solid #1f6feb; padding: 8px; border-radius: 4px;">'
        f'<div style="color: #58a6ff; font-weight: 700;">Stage 2: 25% Size ({t2_shares} Qty)</div>'
        f'<div style="color: #e2e8f0; margin-top: 2px;">Target: <b>₹{t2:,.2f}</b> (+{t2_gain_pct:.1f}%)</div>'
        f'<div style="color: #58a6ff; font-weight: 600;">Lock Profit: +₹{t2_profit:,.0f}</div>'
        f'<div style="color: #94a3b8; font-size: 0.84em; margin-top: 4px; line-height: 1.35;">'
        f'🔒 <i>Action:</i> Trail Stop to <b>₹{ratchet_sl_2:,.2f}</b> '
        f'<span style="color: #a0aec0;">(Target 1 − Retest Cushion; protects Stage 1 profit against support retests).</span>'
        f'</div>'
        f'</div>'
        f'<div style="background: rgba(168, 85, 247, 0.08); border-left: 3px solid #a855f7; padding: 8px; border-radius: 4px;">'
        f'<div style="color: #c084fc; font-weight: 700;">Stage 3: 25% Runner ({t3_shares} Qty)</div>'
        f'<div style="color: #e2e8f0; margin-top: 2px;">Target: <b>₹{t3:,.2f}</b> (+{t3_gain_pct:.1f}%)</div>'
        f'<div style="color: #c084fc; font-weight: 600;">Lock Profit: +₹{t3_profit:,.0f}</div>'
        f'<div style="color: #94a3b8; font-size: 0.84em; margin-top: 4px; line-height: 1.35;">'
        f'🚀 <i>Action:</i> Trail with <b>Peak − 1.5× ATR</b> (Chandelier) or <b>20 EMA daily close</b> to let winners compound.'
        f'</div>'
        f'</div>'
        f'</div>'
        f'<div style="display: flex; justify-content: space-between; align-items: center; margin-top: 8px; padding-top: 6px; border-top: 1px solid #1e2633; font-size: 0.82em; color: #8b949e;">'
        f'<span>Total Capital: <b>₹{capital_allocated:,.0f}</b> ({total_shares} Shares)</span>'
        f'<span>Morning Opening Wick Tolerance: <b style="color: #58a6ff;">±{morning_buffer_pct}%</b> &nbsp;|&nbsp; Total Net Profit if T1–T3 hit: <b style="color: #00c875;">+₹{total_expected_profit:,.0f} ({blended_gain_pct:+.1f}%)</b></span>'
        f'</div>'
        f'</div>'
    )

    return {
        "account_capital": account_capital,
        "risk_pct": risk_pct,
        "risk_budget": risk_budget,
        "risk_per_share": risk_per_share,
        "total_shares": total_shares,
        "capital_allocated": capital_allocated,
        "capital_allocated_pct": capital_allocated_pct,
        "worst_case_loss": worst_case_loss,
        "atr": atr_val,
        "morning_buffer": morning_buffer,
        "morning_buffer_pct": morning_buffer_pct,
        "tranche_1": {
            "shares": t1_shares,
            "target": t1,
            "gain_pct": t1_gain_pct,
            "cash_profit": t1_profit,
            "ratchet_sl": ratchet_sl_1,
            "guaranteed_net": guaranteed_net_t1,
            "rule": f"Exit 50% @ ₹{t1:,.2f} -> Move SL to ₹{ratchet_sl_1:,.2f} (Breakeven − {morning_buffer_pct}% Morning Cushion)"
        },
        "tranche_2": {
            "shares": t2_shares,
            "target": t2,
            "gain_pct": t2_gain_pct,
            "cash_profit": t2_profit,
            "ratchet_sl": ratchet_sl_2,
            "rule": f"Exit 25% @ ₹{t2:,.2f} -> Trail SL to ₹{ratchet_sl_2:,.2f} (T1 Retest Buffer)"
        },
        "tranche_3": {
            "shares": t3_shares,
            "target": t3,
            "gain_pct": t3_gain_pct,
            "cash_profit": t3_profit,
            "rule": f"Ride 25% Runner @ ₹{t3:,.2f} / 20 EMA Trail"
        },
        "total_expected_profit": total_expected_profit,
        "blended_gain_pct": blended_gain_pct,
        "blended_rr": blended_rr,
        "blueprint_html": blueprint_html
    }
