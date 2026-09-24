"""
core/tax_harvesting.py
Automated Tax-Loss & Section 112A LTCG Exemption Harvesting Engine
- Section 112A Annual LTCG Exemption Optimizer (Rs. 1,25,000 tax-free profit per fiscal year)
- Tax-Free Step-Up Rebalance Order Formulator ("Bed & Breakfast" Cost Basis Reset)
- Short-Term Capital Loss (STCL) Harvesting to offset 20.0% STCG tax liability
- Fiscal Year Calendar Awareness (April 1 to March 31 with Q4 February-March urgency alerts)
"""

import math
import logging
from typing import Dict, List, Optional, Tuple, Any
from datetime import date, datetime, timedelta
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

# Statutory Indian Capital Gains Tax Parameters (Finance Act 2024 / FY 2024-25+)
ANNUAL_LTCG_EXEMPTION_LIMIT_INR = 125000.0  # Sec 112A tax-free LTCG cap per financial year
STCG_TAX_RATE = 0.20                       # 20.0% on equity held <= 365 days
LTCG_TAX_RATE = 0.125                      # 12.5% on equity held > 365 days


def get_current_financial_year(as_of_date: Optional[date] = None) -> Tuple[str, date, date, int]:
    """
    Returns (fy_label, fy_start_date, fy_end_date, days_remaining_in_fy).
    Example: FY 2024-25 runs from 2024-04-01 to 2025-03-31.
    """
    d = as_of_date or date.today()
    if d.month >= 4:
        fy_start_year = d.year
        fy_end_year = d.year + 1
    else:
        fy_start_year = d.year - 1
        fy_end_year = d.year

    fy_start = date(fy_start_year, 4, 1)
    fy_end = date(fy_end_year, 3, 31)
    days_left = max(0, (fy_end - d).days)
    fy_label = f"FY {fy_start_year}-{str(fy_end_year)[-2:]}"

    return fy_label, fy_start, fy_end, days_left


def evaluate_tax_harvesting_opportunities(
    open_positions: List[Dict[str, Any]],
    realized_stcg_this_fy: float = 0.0,
    realized_ltcg_this_fy: float = 0.0,
    annual_exemption_remaining: float = ANNUAL_LTCG_EXEMPTION_LIMIT_INR,
    as_of_date: Optional[date] = None
) -> Dict[str, Any]:
    """
    Evaluates open portfolio holdings for tax harvesting opportunities.

    Categories:
    1. 🏆 Long-Term Gain Step-Up (Section 112A Tax-Free Reset):
       - Stocks held > 365 days with unrealized profit.
       - Recommends selling and immediately re-buying to lock in up to Rs. 1.25 Lakh
         of LTCG tax-free, raising cost basis and saving 12.5% on future exits.
    2. 🛑 Short-Term Loss Harvesting (STCL Shield):
       - Stocks held <= 365 days with unrealized loss.
       - Recommends booking loss to offset 20.0% STCG liability from realized winning trades.
    3. ⚡ Urgency Level:
       - HIGH in Q4 (January - March), especially March before fiscal year cutoff.

    Returns comprehensive harvesting plan, actionable trade orders, and tax alpha saved.
    """
    d = as_of_date or date.today()
    fy_label, fy_start, fy_end, days_left = get_current_financial_year(d)

    # Urgency assessment
    if d.month in [2, 3]:
        urgency = "HIGH (Fiscal Year End Deadline Approaching)"
        urgency_color = "#ef4444"
    elif d.month in [12, 1]:
        urgency = "MEDIUM (Q4 Year-End Planning Window)"
        urgency_color = "#f59e0b"
    else:
        urgency = "LOW (Mid-Year Monitoring)"
        urgency_color = "#10b981"

    # Analyze open holdings
    ltcg_harvest_candidates = []
    stcl_harvest_candidates = []
    total_unrealized_ltcg = 0.0
    total_unrealized_stcl = 0.0

    for pos in open_positions:
        sym = pos.get("symbol", "")
        name = pos.get("name", sym)
        sh = pos.get("shares", 0)
        cost_basis = pos.get("cost_basis", 0.0)
        curr_price = pos.get("current_price", 0.0)
        entry_date = pos.get("entry_date")

        if sh <= 0 or curr_price <= 0:
            continue

        curr_val = round(sh * curr_price, 2)
        unrealized_pnl = round(curr_val - cost_basis, 2)
        gain_pct = round((unrealized_pnl / max(1.0, cost_basis)) * 100.0, 2)

        # Parse holding days
        holding_days = 0
        if isinstance(entry_date, str):
            try:
                dt_obj = datetime.strptime(entry_date, "%Y-%m-%d").date()
                holding_days = (d - dt_obj).days
            except Exception:
                holding_days = 180
        elif isinstance(entry_date, date):
            holding_days = (d - entry_date).days

        is_long_term = (holding_days > 365)

        if is_long_term and unrealized_pnl > 0:
            # Eligible for Section 112A Tax-Free Step-Up
            total_unrealized_ltcg += unrealized_pnl
            ltcg_harvest_candidates.append({
                "symbol": sym,
                "name": name,
                "shares": sh,
                "cost_basis": cost_basis,
                "current_price": curr_price,
                "current_value": curr_val,
                "unrealized_pnl": unrealized_pnl,
                "gain_pct": gain_pct,
                "holding_days": holding_days,
                "action": "STEP_UP_LTCG",
                "recommended_action": f"Sell & Re-buy {sh} shares to reset cost basis from Rs.{cost_basis/sh:,.1f} to Rs.{curr_price:,.1f} tax-free"
            })
        elif not is_long_term and unrealized_pnl < 0:
            # Eligible for Short-Term Loss Harvesting
            total_unrealized_stcl += abs(unrealized_pnl)
            stcl_harvest_candidates.append({
                "symbol": sym,
                "name": name,
                "shares": sh,
                "cost_basis": cost_basis,
                "current_price": curr_price,
                "current_value": curr_val,
                "unrealized_pnl": unrealized_pnl,
                "loss_pct": gain_pct,
                "holding_days": holding_days,
                "action": "HARVEST_STCL",
                "recommended_action": f"Book short-term loss of Rs.{abs(unrealized_pnl):,.1f} to offset 20% STCG tax liability"
            })

    # Sort candidates: highest LTCG profit first for step-up, largest STCL loss first for loss harvesting
    ltcg_harvest_candidates.sort(key=lambda x: x["unrealized_pnl"], reverse=True)
    stcl_harvest_candidates.sort(key=lambda x: x["unrealized_pnl"])

    # 1. Optimize Section 112A Tax-Free LTCG Step-Up Allocation
    # Cap total harvested gains to annual_exemption_remaining
    rem_exemption = max(0.0, annual_exemption_remaining)
    step_up_plan = []
    total_ltcg_stepped_up = 0.0

    for c in ltcg_harvest_candidates:
        if rem_exemption <= 0:
            break
        allocatable_gain = min(c["unrealized_pnl"], rem_exemption)
        # Proportion of position to step up
        ratio = allocatable_gain / max(0.01, c["unrealized_pnl"])
        shares_to_step_up = max(1, int(math.floor(c["shares"] * ratio)))
        realized_gain = round(shares_to_step_up * (c["current_price"] - (c["cost_basis"] / c["shares"])), 2)

        rem_exemption -= realized_gain
        total_ltcg_stepped_up += realized_gain

        step_up_plan.append({
            "symbol": c["symbol"],
            "name": c["name"],
            "shares_to_rebalance": shares_to_step_up,
            "current_price": c["current_price"],
            "order_value": round(shares_to_step_up * c["current_price"], 2),
            "tax_free_gain_booked": realized_gain,
            "tax_saved": round(realized_gain * LTCG_TAX_RATE, 2),
            "step_up_instruction": f"Sell {shares_to_step_up} shs @ Rs.{c['current_price']:,.2f} & Re-buy immediately (books Rs.{realized_gain:,.2f} tax-free profit)"
        })

    tax_saved_ltcg = round(total_ltcg_stepped_up * LTCG_TAX_RATE, 2)

    # 2. Optimize Short-Term Capital Loss Harvesting against realized STCG
    total_stcl_harvested = 0.0
    stcl_plan = []
    needed_loss_offset = max(0.0, realized_stcg_this_fy)

    for c in stcl_harvest_candidates:
        if needed_loss_offset <= 0:
            break
        loss_val = abs(c["unrealized_pnl"])
        offset_val = min(loss_val, needed_loss_offset)
        needed_loss_offset -= offset_val
        total_stcl_harvested += offset_val

        stcl_plan.append({
            "symbol": c["symbol"],
            "name": c["name"],
            "shares_to_sell": c["shares"],
            "current_price": c["current_price"],
            "harvested_loss": offset_val,
            "stcg_tax_saved": round(offset_val * STCG_TAX_RATE, 2),
            "harvest_instruction": f"Book Rs.{offset_val:,.2f} loss to erase Rs.{round(offset_val * STCG_TAX_RATE, 2):,.2f} in 20% STCG tax"
        })

    tax_saved_stcl = round(total_stcl_harvested * STCG_TAX_RATE, 2)
    total_tax_alpha_saved = round(tax_saved_ltcg + tax_saved_stcl, 2)

    return {
        "financial_year": fy_label,
        "fy_end_date": str(fy_end),
        "days_remaining_in_fy": days_left,
        "urgency_status": urgency,
        "urgency_color": urgency_color,
        "annual_exemption_cap": ANNUAL_LTCG_EXEMPTION_LIMIT_INR,
        "exemption_limit_utilized": round(total_ltcg_stepped_up, 2),
        "exemption_remaining_after_harvest": max(0.0, round(rem_exemption, 2)),
        "total_unrealized_ltcg_available": round(total_unrealized_ltcg, 2),
        "total_unrealized_stcl_available": round(total_unrealized_stcl, 2),
        "tax_saved_ltcg_step_up": tax_saved_ltcg,
        "tax_saved_stcl_harvesting": tax_saved_stcl,
        "total_tax_alpha_saved_inr": total_tax_alpha_saved,
        "ltcg_step_up_candidates_count": len(ltcg_harvest_candidates),
        "stcl_loss_candidates_count": len(stcl_harvest_candidates),
        "step_up_orders": step_up_plan,
        "stcl_orders": stcl_plan,
        "summary_message": (
            f"🎯 Section 112A Tax Harvesting: Formulated Rs.{total_ltcg_stepped_up:,.0f} tax-free LTCG step-up "
            f"and Rs.{total_stcl_harvested:,.0f} loss offset, locking in Rs.{total_tax_alpha_saved:,.0f} clean tax alpha for {fy_label}."
            if total_tax_alpha_saved > 0 else
            f"No immediate tax harvesting required for {fy_label}. Portfolio tax footprint is currently fully optimized."
        )
    }


def get_fiscal_year_info(as_of_date: Optional[date] = None) -> Dict[str, Any]:
    """Returns dictionary of fiscal year attributes, Q4 status, and days remaining."""
    fy_label, fy_start, fy_end, days_left = get_current_financial_year(as_of_date)
    d = as_of_date or date.today()
    is_q4 = d.month in [1, 2, 3]
    return {
        "fiscal_year": fy_label,
        "fy_start": fy_start,
        "fy_end": fy_end,
        "days_remaining_in_fy": days_left,
        "is_q4": is_q4
    }


def calculate_tax_free_step_up_order(
    symbol: str,
    shares_held: int,
    cost_basis_total: float,
    current_price: float,
    remaining_ltcg_exemption: float = ANNUAL_LTCG_EXEMPTION_LIMIT_INR
) -> Dict[str, Any]:
    """Calculates step-up execution details for an individual holding."""
    if shares_held <= 0 or current_price <= 0:
        return {"can_step_up": False}

    current_val = shares_held * current_price
    unrealized_gain = current_val - cost_basis_total
    if unrealized_gain <= 0:
        return {
            "can_step_up": False,
            "reason": "No unrealized gain to step up"
        }

    allocatable_gain = min(unrealized_gain, remaining_ltcg_exemption)
    ratio = allocatable_gain / max(0.01, unrealized_gain)
    shares_to_rebalance = max(1, int(math.floor(shares_held * ratio)))
    gain_booked = round(shares_to_rebalance * (current_price - (cost_basis_total / shares_held)), 2)
    tax_saved = round(gain_booked * LTCG_TAX_RATE, 2)

    return {
        "symbol": symbol,
        "can_step_up": True,
        "shares_to_rebalance": shares_to_rebalance,
        "current_price": current_price,
        "order_value_inr": round(shares_to_rebalance * current_price, 2),
        "tax_free_gain_booked": gain_booked,
        "estimated_tax_saved_inr": tax_saved,
        "original_cost_basis_total": cost_basis_total,
        "new_cost_basis_total": round(cost_basis_total + gain_booked, 2)
    }
