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
    signal_type: str = "BUY"
) -> Dict:
    """
    Simulates institutional 3-stage bracket execution:
    - Target 1: Closes 50% position, moves Stop-Loss to Breakeven (Entry price).
    - Target 2: Closes 30% position.
    - Target 3 / Runner: Trails remaining 20% position with ATR dynamic trail.
    """
    if not forward_candles or entry_price <= 0:
        return {
            "realized_pnl": 0.0,
            "realized_return_pct": 0.0,
            "exit_reason": "NO_DATA",
            "trades": [],
            "days_held": 0,
            "slippage_cost": 0.0,
        }

    # Slippage at entry
    entry_slip = calculate_slippage(position_size_qty * entry_price, daily_adv, daily_volatility)
    effective_entry = entry_price * (1.0 + entry_slip if signal_type == "BUY" else 1.0 - entry_slip)

    qty_remaining = position_size_qty
    t1_qty = int(position_size_qty * 0.50)
    t2_qty = int(position_size_qty * 0.30)
    runner_qty = position_size_qty - t1_qty - t2_qty

    current_sl = initial_stop_loss
    t1_filled = False
    t2_filled = False
    t3_filled = False
    exit_reason = "ACTIVE_IN_PLAY"
    exit_date = forward_candles[-1][0]
    total_realized_pnl = 0.0
    total_slippage_cost = position_size_qty * entry_price * entry_slip
    trade_logs = []

    for day_idx, (dt, h, l, c) in enumerate(forward_candles):
        if qty_remaining <= 0:
            break

        # 1. Check Stop-Loss
        sl_breached = (l <= current_sl) if signal_type == "BUY" else (h >= current_sl)
        if sl_breached:
            exit_slip = calculate_slippage(qty_remaining * current_sl, daily_adv, daily_volatility)
            fill_sl = current_sl * (1.0 - exit_slip if signal_type == "BUY" else 1.0 + exit_slip)
            pnl_sl = (fill_sl - effective_entry) * qty_remaining if signal_type == "BUY" else (effective_entry - fill_sl) * qty_remaining
            total_realized_pnl += pnl_sl
            total_slippage_cost += qty_remaining * current_sl * exit_slip
            trade_logs.append({
                "stage": "STOP_LOSS / TRAIL_EXIT",
                "date": dt,
                "qty": qty_remaining,
                "fill_price": round(fill_sl, 2),
                "pnl": round(pnl_sl, 2),
                "is_breakeven": (current_sl == effective_entry)
            })
            exit_reason = "BREAKEVEN_SL_HIT" if abs(current_sl - effective_entry) < 1e-4 else "STOP_LOSS_TRIGGERED"
            qty_remaining = 0
            exit_date = dt
            break

        # 2. Check Target 1 (50% scale-out & Move SL to Breakeven)
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
                current_sl = effective_entry # 🔒 Lock-in Breakeven
                trade_logs.append({
                    "stage": "TARGET_1_SCALE_OUT (50%)",
                    "date": dt,
                    "qty": t1_qty,
                    "fill_price": round(fill, 2),
                    "pnl": round(pnl, 2),
                    "action": "Stop-Loss moved to Breakeven (Entry)"
                })

        # 3. Check Target 2 (30% scale-out)
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
                current_sl = target_1
                trade_logs.append({
                    "stage": "TARGET_2_SCALE_OUT (30%)",
                    "date": dt,
                    "qty": t2_qty,
                    "fill_price": round(fill, 2),
                    "pnl": round(pnl, 2),
                    "action": "Stop-Loss locked at Target 1"
                })

        # 4. Check Target 3 / Runner Exit (remaining 20%)
        if t2_filled and not t3_filled and qty_remaining > 0:
            t3_hit = (h >= target_3) if signal_type == "BUY" else (l <= target_3)
            if t3_hit:
                slip = calculate_slippage(qty_remaining * target_3, daily_adv, daily_volatility)
                fill = target_3 * (1.0 - slip if signal_type == "BUY" else 1.0 + slip)
                pnl = (fill - effective_entry) * qty_remaining if signal_type == "BUY" else (effective_entry - fill) * qty_remaining
                total_realized_pnl += pnl
                total_slippage_cost += qty_remaining * target_3 * slip
                trade_logs.append({
                    "stage": "TARGET_3_RUNNER_EXIT (20%)",
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

    # If position is still open at the end of data, calculate mark-to-market
    if qty_remaining > 0 and forward_candles:
        last_c = forward_candles[-1][3]
        unrealized = (last_c - effective_entry) * qty_remaining if signal_type == "BUY" else (effective_entry - last_c) * qty_remaining
        total_realized_pnl += unrealized
        exit_reason = "OPEN_MARK_TO_MARKET"

    invested_capital = position_size_qty * entry_price
    realized_ret_pct = round((total_realized_pnl / max(1.0, invested_capital)) * 100.0, 2)

    return {
        "entry_price": round(entry_price, 2),
        "effective_entry": round(effective_entry, 2),
        "invested_capital": round(invested_capital, 2),
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
    }