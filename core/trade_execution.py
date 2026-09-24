"""
Advanced Order Execution Simulator & Dynamic Trailing Bracket Rules
- Multi-Stage Scaling: 50% at Target 1 (Moves SL to Breakeven) -> 30% at Target 2 -> 20% ATR Trailing Runner
- Square-Root Market Impact & Liquidity Slippage Model
- ATR Dynamic Trailing Stop-Loss Engine
"""
import logging
from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def calculate_slippage(
    order_value: float,
    adv: float,
    daily_volatility: float = 0.02,
    gamma: float = 0.1
) -> float:
    """
    Square-Root Market Impact Model:
    Slippage % = gamma * daily_volatility * sqrt(order_value / ADV)
    """
    if adv <= 0:
        return 0.001
    participation_rate = min(0.5, max(0.0001, order_value / adv))
    impact_pct = gamma * daily_volatility * np.sqrt(participation_rate)
    return float(np.clip(impact_pct, 0.0005, 0.025))


def simulate_bracket_trade_execution(
    entry_price: float,
    target_1: float,
    target_2: float,
    target_3: float,
    initial_stop_loss: float,
    forward_candles: List[Tuple[str, float, float, float]], # List of (date, high, low, close)
    position_size_qty: int = 100,
    daily_adv: float = 50000000.0,
    daily_volatility: float = 0.02,
    signal_type: str = "BUY",
    scaling_tiers: int = 3,              # 3 = 1/3 at T1, 1/3 at T2, 1/3 runner at T3; 2 = 50% at T1, 30% at T2, 20% at T3
    enable_pyramiding: bool = True,       # Jesse Livermore Winner Pyramiding: expand allocation by 50% at +4.0% gain
    time_stop_days: int = 6,              # Inactivity guardrail: exit if gain < 1.5% in N days
    min_gain_for_breakeven: float = 4.5,  # Noise filter: no BE ratchet on moves < 4.5%
) -> Dict:
    """
    Simulates institutional 3-stage bracket execution with optional Jesse Livermore Pyramiding:
    - 3-Tier Scaling (1/3 at Target 1, 1/3 at Target 2, 1/3 at Target 3 / Super-Runner).
    - Winner Pyramiding: When gain >= +4.0%, expands position by +50% and ratchets SL to Breakeven.
    - Noise-Proof Trailing: Only ratchets stop to breakeven on genuine moves (>= 4.5%).
    - Inactivity Guardrail: Exits stagnant trades held >= 6 days with peak gain < 1.5%.
    """
    if not forward_candles or entry_price <= 0 or position_size_qty <= 0:
        return {
            "realized_pnl": 0.0,
            "realized_return_pct": 0.0,
            "exit_reason": "NO_DATA",
            "trades": [],
            "days_held": 0,
            "slippage_cost": 0.0,
        }

    # Slippage at initial entry
    entry_slip = calculate_slippage(position_size_qty * entry_price, daily_adv, daily_volatility)
    effective_entry = entry_price * (1.0 + entry_slip if signal_type == "BUY" else 1.0 - entry_slip)

    qty_remaining = position_size_qty
    if scaling_tiers == 3:
        t1_qty = int(position_size_qty // 3)
        t2_qty = int(position_size_qty // 3)
    else:
        t1_qty = int(position_size_qty * 0.50)
        t2_qty = int(position_size_qty * 0.30)
    runner_qty = position_size_qty - t1_qty - t2_qty

    current_sl = initial_stop_loss
    t1_filled = False
    t2_filled = False
    t3_filled = False
    pyramided = False
    max_high_reached = entry_price
    min_low_reached = entry_price
    exit_reason = "ACTIVE_IN_PLAY"
    exit_date = forward_candles[-1][0]
    total_realized_pnl = 0.0
    total_slippage_cost = position_size_qty * entry_price * entry_slip
    initial_capital = position_size_qty * entry_price
    total_invested_capital = initial_capital
    trade_logs = []

    for day_idx, (dt, h, l, c) in enumerate(forward_candles):
        if qty_remaining <= 0:
            break

        # 1. Check Stop-Loss against established stop level from entry / prior bar
        effective_sl = current_sl
        sl_breached = (l <= effective_sl) if signal_type == "BUY" else (h >= effective_sl)
        if sl_breached:
            exit_slip = calculate_slippage(qty_remaining * effective_sl, daily_adv, daily_volatility)
            fill_sl = effective_sl * (1.0 - exit_slip if signal_type == "BUY" else 1.0 + exit_slip)
            pnl_sl = (fill_sl - effective_entry) * qty_remaining if signal_type == "BUY" else (effective_entry - fill_sl) * qty_remaining
            total_realized_pnl += pnl_sl
            total_slippage_cost += qty_remaining * effective_sl * exit_slip
            is_be = (effective_sl >= effective_entry) if signal_type == "BUY" else (effective_sl <= effective_entry)
            trade_logs.append({
                "stage": "STOP_LOSS / TRAIL_EXIT",
                "date": dt,
                "qty": qty_remaining,
                "fill_price": round(fill_sl, 2),
                "pnl": round(pnl_sl, 2),
                "is_breakeven": is_be
            })
            if abs(effective_sl - effective_entry) / effective_entry < 0.008:
                exit_reason = "BREAKEVEN_SL_HIT"
            elif is_be:
                exit_reason = "TRAILING_SL_HIT"
            else:
                exit_reason = "STOP_LOSS_TRIGGERED"
            qty_remaining = 0
            exit_date = dt
            break

        max_high_reached = max(max_high_reached, h)
        min_low_reached = min(min_low_reached, l)
        cur_peak_pct = (max_high_reached - effective_entry) / effective_entry * 100.0 if signal_type == "BUY" else (effective_entry - min_low_reached) / effective_entry * 100.0

        # Inactivity Time Stop Guardrail
        if time_stop_days > 0 and day_idx >= time_stop_days and cur_peak_pct < 1.5:
            exit_slip = calculate_slippage(qty_remaining * c, daily_adv, daily_volatility)
            fill_c = c * (1.0 - exit_slip if signal_type == "BUY" else 1.0 + exit_slip)
            pnl_c = (fill_c - effective_entry) * qty_remaining if signal_type == "BUY" else (effective_entry - fill_c) * qty_remaining
            total_realized_pnl += pnl_c
            total_slippage_cost += qty_remaining * c * exit_slip
            trade_logs.append({
                "stage": "TIME_STOP_INACTIVITY",
                "date": dt,
                "qty": qty_remaining,
                "fill_price": round(fill_c, 2),
                "pnl": round(pnl_c, 2),
                "action": f"Inactivity cutoff after {day_idx + 1} days (gain < 1.5%) to preserve capital."
            })
            exit_reason = "TIME_STOP_INACTIVITY"
            qty_remaining = 0
            exit_date = dt
            break

        # 2. Check Target 1 (1/3 or 50% scale-out & Move SL to Breakeven)
        if not t1_filled and t1_qty > 0:
            t1_hit = (h >= target_1) if signal_type == "BUY" else (l <= target_1)
            if t1_hit:
                slip = calculate_slippage(t1_qty * target_1, daily_adv, daily_volatility)
                fill = target_1 * (1.0 - slip if signal_type == "BUY" else 1.0 + slip)
                pnl = (fill - effective_entry) * t1_qty if signal_type == "BUY" else (effective_entry - fill) * t1_qty
                total_realized_pnl += pnl
                total_slippage_cost += t1_qty * target_1 * slip
                qty_remaining -= t1_qty
                t1_filled = True
                current_sl = max(current_sl, round(effective_entry * 1.005, 2)) if signal_type == "BUY" else min(current_sl, round(effective_entry * 0.995, 2))
                stage_label = f"TARGET_1_SCALE_OUT ({'33%' if scaling_tiers == 3 else '50%'})"
                trade_logs.append({
                    "stage": stage_label,
                    "date": dt,
                    "qty": t1_qty,
                    "fill_price": round(fill, 2),
                    "pnl": round(pnl, 2),
                    "action": "Stop-Loss moved to Breakeven (+0.5%)"
                })

        # 3. Check Target 2 (1/3 or 30% scale-out)
        if t1_filled and not t2_filled and t2_qty > 0:
            t2_hit = (h >= target_2) if signal_type == "BUY" else (l <= target_2)
            if t2_hit:
                slip = calculate_slippage(t2_qty * target_2, daily_adv, daily_volatility)
                fill = target_2 * (1.0 - slip if signal_type == "BUY" else 1.0 + slip)
                pnl = (fill - effective_entry) * t2_qty if signal_type == "BUY" else (effective_entry - fill) * t2_qty
                total_realized_pnl += pnl
                total_slippage_cost += t2_qty * target_2 * slip
                qty_remaining -= t2_qty
                t2_filled = True
                # Move SL to Target 1 price level to lock profit
                current_sl = max(current_sl, target_1) if signal_type == "BUY" else min(current_sl, target_1)
                stage_label = f"TARGET_2_SCALE_OUT ({'33%' if scaling_tiers == 3 else '30%'})"
                trade_logs.append({
                    "stage": stage_label,
                    "date": dt,
                    "qty": t2_qty,
                    "fill_price": round(fill, 2),
                    "pnl": round(pnl, 2),
                    "action": "Stop-Loss locked at Target 1 price"
                })

        # 4. Check Target 3 / Super-Runner Exit (remaining position)
        if t2_filled and not t3_filled and qty_remaining > 0:
            t3_hit = (h >= target_3) if signal_type == "BUY" else (l <= target_3)
            if t3_hit:
                slip = calculate_slippage(qty_remaining * target_3, daily_adv, daily_volatility)
                fill = target_3 * (1.0 - slip if signal_type == "BUY" else 1.0 + slip)
                pnl = (fill - effective_entry) * qty_remaining if signal_type == "BUY" else (effective_entry - fill) * qty_remaining
                total_realized_pnl += pnl
                total_slippage_cost += qty_remaining * target_3 * slip
                trade_logs.append({
                    "stage": f"TARGET_3_RUNNER_EXIT ({'34%' if scaling_tiers == 3 else '20%'})",
                    "date": dt,
                    "qty": qty_remaining,
                    "fill_price": round(fill, 2),
                    "pnl": round(pnl, 2),
                    "action": "Full target runner completed"
                })
                qty_remaining = 0
                t3_filled = True
                exit_reason = "FULL_TARGET_3_CAPTURED"
                exit_date = dt
                break

        # Noise-Proof Trailing Ratchets (Rule 1: no breakeven on minor intraday noise < 4.5%)
        if cur_peak_pct >= min_gain_for_breakeven:
            current_sl = max(current_sl, round(effective_entry * 1.005, 2)) if signal_type == "BUY" else min(current_sl, round(effective_entry * 0.995, 2))
        if cur_peak_pct >= 8.0:
            current_sl = max(current_sl, round(max_high_reached * 0.965, 2)) if signal_type == "BUY" else min(current_sl, round(min_low_reached * 1.035, 2))
        if cur_peak_pct >= 14.0:
            current_sl = max(current_sl, round(max_high_reached * 0.940, 2)) if signal_type == "BUY" else min(current_sl, round(min_low_reached * 1.060, 2))

        # Check Pyramiding Opportunity (+50% size at +4.0% gain, lock stop to breakeven for subsequent bars)
        if enable_pyramiding and cur_peak_pct >= 4.0 and not pyramided and not t1_filled:
            extra_qty = int(position_size_qty * 0.50)
            if extra_qty > 0:
                pyr_price = c
                pyr_slip = calculate_slippage(extra_qty * pyr_price, daily_adv, daily_volatility)
                pyr_fill = pyr_price * (1.0 + pyr_slip if signal_type == "BUY" else 1.0 - pyr_slip)
                pyr_cost = extra_qty * pyr_fill

                # Blend entry price
                blended_entry = ((effective_entry * qty_remaining) + pyr_cost) / (qty_remaining + extra_qty)
                effective_entry = blended_entry
                qty_remaining += extra_qty
                total_invested_capital += extra_qty * pyr_price
                total_slippage_cost += extra_qty * pyr_price * pyr_slip
                pyramided = True

                # Adjust tranche allocations proportionally
                if scaling_tiers == 3:
                    t1_qty = int(qty_remaining // 3)
                    t2_qty = int(qty_remaining // 3)
                else:
                    t1_qty = int(qty_remaining * 0.50)
                    t2_qty = int(qty_remaining * 0.30)

                # Move Stop-Loss to Breakeven (+0.2% above blended entry) -> Zero incremental risk for subsequent bars!
                current_sl = max(current_sl, round(blended_entry * 1.002, 2)) if signal_type == "BUY" else min(current_sl, round(blended_entry * 0.998, 2))
                trade_logs.append({
                    "stage": "WINNER_PYRAMID_ADD (+50%)",
                    "date": dt,
                    "qty": extra_qty,
                    "fill_price": round(pyr_fill, 2),
                    "blended_entry": round(blended_entry, 2),
                    "action": "Expanded allocation on confirmed +4.0% breakout. Stop ratcheted to Breakeven."
                })

    # If position is still open at the end of data, calculate mark-to-market
    if qty_remaining > 0 and forward_candles:
        last_c = forward_candles[-1][3]
        unrealized = (last_c - effective_entry) * qty_remaining if signal_type == "BUY" else (effective_entry - last_c) * qty_remaining
        total_realized_pnl += unrealized
        exit_reason = "OPEN_MARK_TO_MARKET"

    realized_ret_pct = round((total_realized_pnl / max(1.0, total_invested_capital)) * 100.0, 2)

    return {
        "entry_price": round(entry_price, 2),
        "effective_entry": round(effective_entry, 2),
        "invested_capital": round(total_invested_capital, 2),
        "realized_pnl": round(total_realized_pnl, 2),
        "realized_return_pct": realized_ret_pct,
        "exit_reason": exit_reason,
        "exit_date": exit_date,
        "days_held": len(forward_candles),
        "slippage_cost": round(total_slippage_cost, 2),
        "trade_logs": trade_logs,
        "t1_captured": t1_filled,
        "t2_captured": t2_filled,
        "t3_captured": t3_filled,
        "pyramided": pyramided,
        "max_high": round(max_high_reached, 2),
        "min_low": round(min_low_reached, 2),
    }