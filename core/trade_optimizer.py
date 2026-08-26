"""
Trade Execution & Profit Maximization Optimizer
- Position Sizing & Kelly Criterion Calculator
- Multi-Tranche Profit Scaling Strategy (40% T1 / 35% T2 / 25% T3 Trailing)
- Execution Mode Decision Engine (Single Trade vs Pyramiding vs Scale-In)
- Risk Management & Capital Allocation Rules
"""
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


def calculate_position_size(
    capital: float,
    current_price: float,
    stop_loss: float,
    risk_per_trade_pct: float = 1.5,
    win_rate: float = 0.58,
    risk_reward: float = 2.2,
    champion_info: dict = None,
) -> Dict:
    """
    Calculate optimal position size using Fixed Fractional and Half-Kelly Criterion.
    If champion_info is provided, uses empirical backtested win rate & profit factor.
    """
    if champion_info:
        win_rate = (champion_info.get("win_rate_pct", 58.0)) / 100.0
        risk_reward = max(1.5, champion_info.get("profit_factor", 2.2))

    if current_price <= 0 or stop_loss <= 0 or stop_loss >= current_price:
        risk_per_share = current_price * 0.05
    else:
        risk_per_share = current_price - stop_loss

    risk_per_share_pct = (risk_per_share / current_price) * 100

    # 1. Fixed Fractional Sizing (Max ₹ Risk / Trade)
    max_risk_amount = capital * (risk_per_trade_pct / 100.0)
    fixed_shares = int(max_risk_amount / risk_per_share) if risk_per_share > 0 else 0
    fixed_allocated_capital = fixed_shares * current_price
    fixed_allocation_pct = (fixed_allocated_capital / capital) * 100 if capital > 0 else 0

    # Cap single stock exposure to 20% of portfolio
    if fixed_allocation_pct > 20.0:
        fixed_shares = int((capital * 0.20) / current_price)
        fixed_allocated_capital = fixed_shares * current_price
        fixed_allocation_pct = 20.0

    # 2. Half-Kelly Criterion (f* = (b*p - q)/b) / 2
    b = max(1.0, risk_reward)
    p = max(0.1, min(0.95, win_rate))
    q = 1.0 - p
    full_kelly_pct = max(0.0, (b * p - q) / b) * 100
    half_kelly_pct = min(20.0, full_kelly_pct / 2.0)  # Conservative half-kelly
    kelly_shares = int((capital * (half_kelly_pct / 100.0)) / current_price) if current_price > 0 else 0

    return {
        "capital": capital,
        "current_price": current_price,
        "stop_loss": stop_loss,
        "risk_per_share": round(risk_per_share, 2),
        "risk_per_share_pct": round(risk_per_share_pct, 2),
        "max_risk_amount": round(max_risk_amount, 2),
        "recommended_shares": max(1, fixed_shares),
        "allocated_capital": round(fixed_allocated_capital, 2),
        "portfolio_allocation_pct": round(fixed_allocation_pct, 1),
        "half_kelly_pct": round(half_kelly_pct, 1),
        "kelly_shares": max(1, kelly_shares),
        "empirical_win_rate_used": round(p * 100, 1),
    }


def generate_trade_execution_plan(
    current_price: float,
    buy_price: float,
    t1: float,
    t2: float,
    t3: float,
    stop_loss: float,
    confluence_score: float = 65.0,
    pop_pct: float = 60.0,
    shares: int = 100,
    champion_info: dict = None,
) -> Dict:
    """
    Generate optimal trade execution and profit-maximization scaling plan.
    Dynamically adapts tranche distribution based on backtested strategy characteristics.
    """
    entry = buy_price if buy_price and buy_price > 0 else current_price
    t1 = t1 if t1 and t1 > entry else entry * 1.05
    t2 = t2 if t2 and t2 > entry else entry * 1.10
    t3 = t3 if t3 and t3 > entry else entry * 1.18
    sl = stop_loss if stop_loss and stop_loss < entry else entry * 0.95

    # Strategy-Aware Dynamic Tranche Allocation
    if champion_info:
        strat_name = champion_info.get("strategy_name", "")
        win_rate = champion_info.get("win_rate_pct", 50.0)
        pf = champion_info.get("profit_factor", 1.5)

        if "Momentum" in strat_name or "Breakout" in strat_name or "Trend" in strat_name:
            mode = f"Champion-Calibrated Aggressive Runner ({strat_name})"
            mode_desc = (
                f"Calibrated to {strat_name} (Win Rate: {win_rate:.1f}%, Profit Factor: {pf:.2f}). "
                "Takes moderate profit early (30% at T1) and maximizes the runner tranche (40% at T3) to capture high-alpha expansion."
            )
            t1_pct, t2_pct, t3_pct = 0.30, 0.30, 0.40
        elif "Mean Reversion" in strat_name or "Oversold" in strat_name:
            mode = f"Champion-Calibrated Snapback Scaler ({strat_name})"
            mode_desc = (
                f"Calibrated to {strat_name} (Win Rate: {win_rate:.1f}%). "
                "Front-loads 50% profit taking at Target 1 on quick mean-reversion bounce, securing gains rapidly."
            )
            t1_pct, t2_pct, t3_pct = 0.50, 0.35, 0.15
        else:
            mode = f"Champion-Calibrated Multi-Tranche ({strat_name})"
            mode_desc = f"Balanced 40/35/25 execution plan calibrated to {strat_name}."
            t1_pct, t2_pct, t3_pct = 0.40, 0.35, 0.25
    elif confluence_score >= 75 and pop_pct >= 65:
        mode = "Aggressive High-Conviction Swing"
        mode_desc = (
            "5-Engine Ultra Confluence & high Monte Carlo PoP (>65%). "
            "Enter full position at current level with confidence. Pyramiding add-on allowed on T1 breakout."
        )
        t1_pct, t2_pct, t3_pct = 0.35, 0.35, 0.30
    elif confluence_score >= 55:
        mode = "Multi-Tranche Scale-Out (Standard)"
        mode_desc = (
            "Solid multi-factor setup. Scale out 40% at T1 to lock gains and move Stop Loss to Breakeven. "
            "Sell 35% at T2 and let remaining 25% ride to T3 with trailing stop."
        )
        t1_pct, t2_pct, t3_pct = 0.40, 0.35, 0.25
    else:
        mode = "Conservative Dip Accumulation"
        mode_desc = (
            "Mixed signal environment. Split entry into 3 tranches (1/3 at entry, 1/3 on pullbacks, 1/3 on confirmed breakout). "
            "Take quick profits at T1 and T2."
        )
        t1_pct, t2_pct, t3_pct = 0.50, 0.30, 0.20

    t1_qty = int(shares * t1_pct)
    t2_qty = int(shares * t2_pct)
    t3_qty = shares - t1_qty - t2_qty

    # Profit Calculations
    t1_profit = t1_qty * (t1 - entry)
    t2_profit = t2_qty * (t2 - entry)
    t3_profit = t3_qty * (t3 - entry)
    total_projected_profit = t1_profit + t2_profit + t3_profit
    total_cost = shares * entry
    blended_gain_pct = (total_projected_profit / total_cost * 100) if total_cost > 0 else 0
    max_loss = shares * (entry - sl)

    # Expected Duration Modeling based on Volatility & Empirical Velocity
    atr = abs(entry - sl) / 1.5 if (entry - sl) > 0 else (entry * 0.02)
    t1_dist = abs(t1 - entry)
    t2_dist = abs(t2 - entry)
    t3_dist = abs(t3 - entry)

    d1 = max(2, int(round((t1_dist / (atr * 0.85)) * 1.4)))
    d2 = max(d1 + 4, int(round((t2_dist / (atr * 0.70)) * 1.8)))
    d3 = max(d2 + 10, int(round((t3_dist / (atr * 0.55)) * 2.2)))

    t1_dur_str = f"{max(2, d1-2)}–{d1+3} Days"
    t2_dur_str = f"{max(d1+3, d2-4)}–{d2+6} Days"
    t3_dur_str = f"{max(d2+6, d3-8)}–{d3+12} Days"

    # Strategy Expected Value: E(R) = (p * avg_win) - ((1-p) * avg_loss)
    expected_value_str = ""
    if champion_info:
        p = champion_info.get("win_rate_pct", 50) / 100.0
        avg_w = champion_info.get("avg_win_pct", 8.0)
        avg_l = abs(champion_info.get("avg_loss_pct", 4.0))
        ev = (p * avg_w) - ((1.0 - p) * avg_l)
        expected_value_str = f"Mathematical Expected Value per Trade: E(R) = {ev:+.2f}%"

    return {
        "execution_mode": mode,
        "mode_description": mode_desc,
        "total_shares": shares,
        "total_capital_deployed": round(total_cost, 2),
        "max_monetary_risk": round(max_loss, 2),
        "total_projected_profit": round(total_projected_profit, 2),
        "blended_gain_pct": round(blended_gain_pct, 2),
        "overall_risk_reward": round(total_projected_profit / max_loss, 2) if max_loss > 0 else 2.5,
        "expected_value_info": expected_value_str,
        "tranche_1": {
            "shares": t1_qty,
            "pct_label": f"{int(t1_pct*100)}%",
            "target_price": round(t1, 2),
            "gain_pct": round((t1 - entry) / entry * 100, 2),
            "projected_profit": round(t1_profit, 2),
            "expected_duration": t1_dur_str,
            "action": "Sell {}% -> Shift Stop Loss to Breakeven (₹{:,.2f})".format(int(t1_pct*100), entry),
        },
        "tranche_2": {
            "shares": t2_qty,
            "pct_label": f"{int(t2_pct*100)}%",
            "target_price": round(t2, 2),
            "gain_pct": round((t2 - entry) / entry * 100, 2),
            "projected_profit": round(t2_profit, 2),
            "expected_duration": t2_dur_str,
            "action": "Sell {}% -> Lock in major risk/reward gains".format(int(t2_pct*100)),
        },
        "tranche_3": {
            "shares": t3_qty,
            "pct_label": f"{int(t3_pct*100)}%",
            "target_price": round(t3, 2),
            "gain_pct": round((t3 - entry) / entry * 100, 2),
            "projected_profit": round(t3_profit, 2),
            "expected_duration": t3_dur_str,
            "action": "Ride {}% with Trailing Stop Loss on EMA-21".format(int(t3_pct*100)),
        },
    }


def compute_empirical_strategy_projections(
    current_price: float,
    champion_info: dict,
    forecast_data: dict = None,
) -> Dict:
    """
    Project future price trend targets calibrated by empirical strategy win rates and velocity.
    """
    if not champion_info:
        return {}

    win_rate = champion_info.get("win_rate_pct", 50.0) / 100.0
    strat_return = champion_info.get("total_return_pct", 10.0)
    avg_win = champion_info.get("avg_win_pct", 7.5)
    pf = champion_info.get("profit_factor", 1.5)

    # Annualized Strategy Velocity
    annualized_strat_velocity = (strat_return / 3.0) / 100.0  # 3 year backtest annualized

    # Projections
    p_14d = current_price * (1 + (annualized_strat_velocity * (14/365)) * (win_rate / 0.5))
    p_1m = current_price * (1 + (annualized_strat_velocity * (30/365)) * (win_rate / 0.5))
    p_3m = current_price * (1 + (annualized_strat_velocity * (90/365)) * (win_rate / 0.5))
    p_6m = current_price * (1 + (annualized_strat_velocity * (180/365)) * (win_rate / 0.5))
    p_1y = current_price * (1 + annualized_strat_velocity * (win_rate / 0.5))

    return {
        "strategy_name": champion_info.get("strategy_name"),
        "empirical_win_rate": round(win_rate * 100, 1),
        "empirical_profit_factor": round(pf, 2),
        "proj_14d_price": round(p_14d, 2),
        "proj_14d_pct": round((p_14d - current_price) / current_price * 100, 2),
        "proj_1m_price": round(p_1m, 2),
        "proj_1m_pct": round((p_1m - current_price) / current_price * 100, 2),
        "proj_3m_price": round(p_3m, 2),
        "proj_3m_pct": round((p_3m - current_price) / current_price * 100, 2),
        "proj_6m_price": round(p_6m, 2),
        "proj_6m_pct": round((p_6m - current_price) / current_price * 100, 2),
        "proj_1y_price": round(p_1y, 2),
        "proj_1y_pct": round((p_1y - current_price) / current_price * 100, 2),
    }
