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
    signal: str = "BUY"
) -> Dict:
    """
    Computes institutional tranche exits, position size, and capital risk.
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

    # Tranche 1: 50%
    t1_shares = max(1, math.floor(total_shares * 0.50)) if total_shares >= 2 else total_shares
    t1_gain_share = abs(t1 - entry_price)
    t1_gain_pct = (t1_gain_share / entry_price) * 100.0
    t1_profit = t1_shares * t1_gain_share
    be_sl = round(entry_price * (1.002 if signal == "BUY" else 0.998), 2)

    # Tranche 2: 25%
    remaining_after_t1 = total_shares - t1_shares
    t2_shares = math.floor(total_shares * 0.25) if remaining_after_t1 >= 2 else remaining_after_t1
    t2_gain_share = abs(t2 - entry_price)
    t2_gain_pct = (t2_gain_share / entry_price) * 100.0
    t2_profit = t2_shares * t2_gain_share

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
        f'<span style="font-weight: 700; color: {color_accent}; font-size: 0.95em;">⚡ 3-Stage Profit Tranche Execution Plan</span>'
        f'<span style="font-size: 0.85em; color: #8b949e;">Blended R:R: <b style="color: #58a6ff;">1 : {blended_rr}</b> &nbsp;|&nbsp; Max Risk: <b style="color: #ff4b4b;">₹{worst_case_loss:,.0f} ({risk_pct}%)</b></span>'
        f'</div>'
        f'<div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; font-size: 0.86em;">'
        f'<div style="background: rgba(0, 200, 117, 0.08); border-left: 3px solid #00c875; padding: 8px; border-radius: 4px;">'
        f'<div style="color: #00c875; font-weight: 700;">Stage 1: 50% Size ({t1_shares} Qty)</div>'
        f'<div style="color: #e2e8f0; margin-top: 2px;">Target: <b>₹{t1:,.2f}</b> (+{t1_gain_pct:.1f}%)</div>'
        f'<div style="color: #00c875; font-weight: 600;">Lock Profit: +₹{t1_profit:,.0f}</div>'
        f'<div style="color: #94a3b8; font-size: 0.85em; margin-top: 4px;">🛡️ <i>Action:</i> Ratchet SL to <b>₹{be_sl:,.2f}</b> (100% Risk Free).</div>'
        f'</div>'
        f'<div style="background: rgba(31, 111, 235, 0.08); border-left: 3px solid #1f6feb; padding: 8px; border-radius: 4px;">'
        f'<div style="color: #58a6ff; font-weight: 700;">Stage 2: 25% Size ({t2_shares} Qty)</div>'
        f'<div style="color: #e2e8f0; margin-top: 2px;">Target: <b>₹{t2:,.2f}</b> (+{t2_gain_pct:.1f}%)</div>'
        f'<div style="color: #58a6ff; font-weight: 600;">Lock Profit: +₹{t2_profit:,.0f}</div>'
        f'<div style="color: #94a3b8; font-size: 0.85em; margin-top: 4px;">🔒 <i>Action:</i> Trail Stop to <b>₹{t1:,.2f}</b> (Lock Stage 1 Gain).</div>'
        f'</div>'
        f'<div style="background: rgba(168, 85, 247, 0.08); border-left: 3px solid #a855f7; padding: 8px; border-radius: 4px;">'
        f'<div style="color: #c084fc; font-weight: 700;">Stage 3: 25% Runner ({t3_shares} Qty)</div>'
        f'<div style="color: #e2e8f0; margin-top: 2px;">Target: <b>₹{t3:,.2f}</b> (+{t3_gain_pct:.1f}%)</div>'
        f'<div style="color: #c084fc; font-weight: 600;">Lock Profit: +₹{t3_profit:,.0f}</div>'
        f'<div style="color: #94a3b8; font-size: 0.85em; margin-top: 4px;">🚀 <i>Action:</i> Trail with 20 EMA until trend reversal.</div>'
        f'</div>'
        f'</div>'
        f'<div style="display: flex; justify-content: space-between; align-items: center; margin-top: 8px; padding-top: 6px; border-top: 1px solid #1e2633; font-size: 0.82em; color: #8b949e;">'
        f'<span>Total Allocation: <b>₹{capital_allocated:,.0f}</b> ({total_shares} Shares)</span>'
        f'<span>Total Realized Profit if T1–T3 Achieved: <b style="color: #00c875;">+₹{total_expected_profit:,.0f} ({blended_gain_pct:+.1f}%)</b></span>'
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
        "tranche_1": {
            "shares": t1_shares,
            "target": t1,
            "gain_pct": t1_gain_pct,
            "cash_profit": t1_profit,
            "ratchet_sl": be_sl,
            "rule": f"Exit 50% @ ₹{t1:,.2f} -> Move SL to Breakeven (₹{be_sl:,.2f})"
        },
        "tranche_2": {
            "shares": t2_shares,
            "target": t2,
            "gain_pct": t2_gain_pct,
            "cash_profit": t2_profit,
            "ratchet_sl": t1,
            "rule": f"Exit 25% @ ₹{t2:,.2f} -> Trail SL to T1 (₹{t1:,.2f})"
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
