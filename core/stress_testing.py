"""
Black Swan Crisis & Macro Stress-Testing Simulator
- Replays historical crisis stress scenarios on individual stocks and portfolios:
  1. COVID-19 Liquidity Shock (March 2020: Nifty -38%, Volatility +120%)
  2. Global Financial Crisis (2008: -55% Drawdown, High-Beta Collapse)
  3. Geopolitical Crude Oil Shock ($120+/bbl Spike, Margin Compression)
  4. US Fed Rate Hike & Rupee Depreciation Cycle (2022)
- Calculates simulated drawdown, Parametric VaR-99%, recovery duration, and hedging strategies.
"""
import logging
from typing import Dict, List, Optional
import numpy as np
import pandas as pd
from scipy.stats import norm

logger = logging.getLogger(__name__)

HISTORICAL_CRISIS_SCENARIOS = {
    "🦠 March 2020 COVID-19 Shock": {
        "market_drawdown_pct": -38.4,
        "volatility_multiplier": 2.2,
        "sector_sensitivity": {
            "Technology": 0.85,
            "Banking & Finance": 1.25,
            "Pharma & Healthcare": 0.45,
            "Auto & Mobility": 1.30,
            "Consumer & FMCG": 0.70,
            "Metals & Mining": 1.40,
            "Energy & Oil": 1.20,
            "Real Estate": 1.50,
        },
        "description": "Global liquidity crisis and pandemic lockdown causing indiscriminate across-the-board liquidation.",
    },
    "💥 2008 Global Financial Crisis (GFC)": {
        "market_drawdown_pct": -54.8,
        "volatility_multiplier": 2.5,
        "sector_sensitivity": {
            "Technology": 0.90,
            "Banking & Finance": 1.60,
            "Pharma & Healthcare": 0.50,
            "Auto & Mobility": 1.45,
            "Consumer & FMCG": 0.60,
            "Metals & Mining": 1.75,
            "Energy & Oil": 1.30,
            "Real Estate": 1.80,
        },
        "description": "Lehman Brothers collapse triggering global banking freeze, high-leverage collapse, and credit crunch.",
    },
    "🛢️ Geopolitical Crude Oil Shock ($120+/bbl)": {
        "market_drawdown_pct": -18.5,
        "volatility_multiplier": 1.6,
        "sector_sensitivity": {
            "Technology": 0.70,
            "Banking & Finance": 1.10,
            "Pharma & Healthcare": 0.60,
            "Auto & Mobility": 1.40,
            "Consumer & FMCG": 1.20,
            "Metals & Mining": 0.80,
            "Energy & Oil": -0.40, # Energy benefits / hedges
            "Real Estate": 1.15,
        },
        "description": "Supply dislocation causing crude oil spike, trade deficit expansion, and domestic inflation headwinds.",
    },
    "📉 US Fed Rate Hike & Foreign Outflow (2022)": {
        "market_drawdown_pct": -15.2,
        "volatility_multiplier": 1.4,
        "sector_sensitivity": {
            "Technology": 1.65, # Growth tech suffers multiple compression
            "Banking & Finance": 0.90,
            "Pharma & Healthcare": 0.75,
            "Auto & Mobility": 1.05,
            "Consumer & FMCG": 0.80,
            "Metals & Mining": 1.10,
            "Energy & Oil": 0.70,
            "Real Estate": 1.20,
        },
        "description": "Aggressive monetary tightening prompting global bond yield spikes and FII capital repatriation.",
    },
}


def simulate_stock_crisis_stress_test(
    symbol: str,
    stock_name: str,
    sector: str,
    current_price: float,
    beta: float = 1.0,
    annual_volatility: float = 0.22,
) -> Dict:
    """
    Simulates the impact of all 4 major historical crises on an individual stock.
    """
    beta = max(0.4, float(beta or 1.0))
    vol = max(0.10, float(annual_volatility or 0.22))
    
    # 99% 1-Month Parametric Value at Risk (VaR)
    # VaR_99 = S * Z_0.99 * (vol / sqrt(12))
    z_99 = 2.326
    monthly_vol = vol / np.sqrt(12)
    var_99_pct = float(z_99 * monthly_vol * 100.0)
    var_99_amount = float(current_price * (var_99_pct / 100.0))

    scenario_results = []

    for name, params in HISTORICAL_CRISIS_SCENARIOS.items():
        sec_sens = params["sector_sensitivity"].get(sector, 1.0)
        # Estimated stock shock = Market Shock * Beta * Sector Sensitivity
        sim_drawdown_pct = params["market_drawdown_pct"] * beta * sec_sens
        sim_drawdown_pct = max(-90.0, min(15.0, sim_drawdown_pct))
        sim_price = max(1.0, current_price * (1.0 + sim_drawdown_pct / 100.0))
        
        # Projected recovery duration based on drawdown depth
        recovery_days = int(abs(sim_drawdown_pct) * 6.5)

        # Hedging Recommendation
        if sim_drawdown_pct < -30.0:
            hedge_advice = "🚨 High Vulnerability: Allocate 15-20% to Gold or OTM Put Options"
            risk_tag = "CRITICAL RISK"
            tag_color = "#ff4b4b"
        elif sim_drawdown_pct < -15.0:
            hedge_advice = "⚠️ Moderate Impact: Tighten Trailing Stop-Loss to 20-EMA"
            risk_tag = "MODERATE RISK"
            tag_color = "#f0a500"
        else:
            hedge_advice = "🛡️ Defensive Resiliency: Minimal downside impact projected"
            risk_tag = "DEFENSIVE BUFFER"
            tag_color = "#00c875"

        scenario_results.append({
            "scenario": name,
            "description": params["description"],
            "simulated_drawdown_pct": round(sim_drawdown_pct, 1),
            "simulated_price": round(sim_price, 2),
            "recovery_days": recovery_days,
            "hedge_advice": hedge_advice,
            "risk_tag": risk_tag,
            "tag_color": tag_color,
        })

    return {
        "symbol": symbol,
        "stock_name": stock_name,
        "current_price": current_price,
        "beta": round(beta, 2),
        "annual_volatility_pct": round(vol * 100, 1),
        "var_99_pct": round(var_99_pct, 1),
        "var_99_amount": round(var_99_amount, 2),
        "scenarios": scenario_results,
    }


def simulate_portfolio_crisis_stress_test(
    positions: List[Dict],
    cash_balance: float = 0.0,
) -> Dict:
    """
    Simulates historical crisis shocks across a multi-asset portfolio.
    """
    total_equity = sum([pos["current_value"] for pos in positions])
    total_portfolio = total_equity + cash_balance

    if total_portfolio <= 0:
        return {"error": "Empty portfolio."}

    results = []
    for sc_name, params in HISTORICAL_CRISIS_SCENARIOS.items():
        sc_sim_equity = 0.0
        for pos in positions:
            # Approximate sector sensitivity
            sec_sens = 1.0
            pos_drop = params["market_drawdown_pct"] * sec_sens
            pos_val_after = max(0.0, pos["current_value"] * (1.0 + pos_drop / 100.0))
            sc_sim_equity += pos_val_after

        sc_total_val_after = sc_sim_equity + cash_balance
        p_drop_pct = ((sc_total_val_after - total_portfolio) / total_portfolio) * 100.0

        results.append({
            "scenario": sc_name,
            "description": params["description"],
            "simulated_portfolio_drawdown_pct": round(p_drop_pct, 1),
            "simulated_portfolio_value": round(sc_total_val_after, 2),
            "capital_loss": round(total_portfolio - sc_total_val_after, 2),
        })

    return {
        "initial_portfolio_value": total_portfolio,
        "cash_buffer_pct": round((cash_balance / total_portfolio) * 100, 1),
        "scenarios": results,
    }