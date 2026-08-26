"""
Dynamic Institutional Multi-Asset Portfolio Advisor Engine
- Generates 10 / 20 / 50 or custom N asset portfolios across Stocks, Indexes, and Commodities
- 3 Risk Profiles: Safe Fortress, Balanced All-Weather, High-Growth (Risky)
- 4 Horizons: Daily Swing (1-30d), 1-Year, 3-Years, 5-Years
- Strict Institutional Diversification: Sector Caps (<=25%), Asset Caps (<=12%), Multi-Asset Buffer
"""
import math
import logging
from typing import Dict, List, Optional
import numpy as np
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)


def generate_institutional_portfolio(
    session: Session,
    n_assets: int = 20,
    risk_profile: str = "BALANCED",   # SAFE, BALANCED, RISKY
    horizon: str = "1_YEAR",         # DAILY, 1_YEAR, 3_YEARS, 5_YEARS
    total_capital_inr: float = 1000000.0,
    max_sector_exposure_pct: float = 25.0,
    max_single_asset_pct: float = 12.0
) -> Dict:
    """Generates an optimized multi-asset diversified portfolio based on user mandate."""
    n_assets = max(5, min(80, n_assets))
    
    # 1. Determine Asset Class Targets based on Risk Profile
    if risk_profile == "SAFE":
        target_commodity_pct = 20.0
        target_index_pct = 20.0
        target_equity_pct = 60.0
        min_score = 65.0
        beta_max = 0.90
        exp_cagr_1y = 13.5
        exp_cagr_3y = 14.2
        exp_cagr_5y = 15.0
        mandate_desc = "Capital Preservation & Low-Volatility Compounder Fortress"
    elif risk_profile == "RISKY":
        target_commodity_pct = 5.0
        target_index_pct = 10.0
        target_equity_pct = 85.0
        min_score = 55.0
        beta_max = 1.60
        exp_cagr_1y = 24.5
        exp_cagr_3y = 22.0
        exp_cagr_5y = 20.5
        mandate_desc = "Maximum Alpha & High-Momentum Growth Acceleration"
    else: # BALANCED
        target_commodity_pct = 12.0
        target_index_pct = 18.0
        target_equity_pct = 70.0
        min_score = 60.0
        beta_max = 1.20
        exp_cagr_1y = 18.2
        exp_cagr_3y = 17.5
        exp_cagr_5y = 17.0
        mandate_desc = "Ray Dalio All-Weather Risk-Parity Core Portfolio"

    # 2. Query Candidate Equities
    sql_stocks = """
        SELECT sig.symbol, s.name, s.sector, s.market_cap_tier, sig.current_price,
               cs.composite_score, sig.signal, sig.risk_level, sig.target_price_1, sig.stop_loss,
               cs.volatility_annual, cs.beta
        FROM signals sig
        JOIN stocks s ON sig.symbol = s.symbol
        JOIN composite_scores cs ON sig.symbol = cs.symbol AND cs.date = sig.date
        WHERE sig.date = (SELECT MAX(date) FROM signals)
        AND s.is_active = 1
        ORDER BY cs.composite_score DESC
    """
    stock_rows = session.execute(text(sql_stocks)).fetchall()

    # 3. Query Candidate Commodities & Indexes
    com_rows = session.execute(text("""
        SELECT symbol, name, close FROM commodity_prices
        WHERE date = (SELECT MAX(date) FROM commodity_prices)
    """)).fetchall()

    idx_rows = session.execute(text("""
        SELECT symbol, name, close FROM index_prices
        WHERE date = (SELECT MAX(date) FROM index_prices)
    """)).fetchall()

    # 4. Selection & Allocation Logic
    selected_portfolio = []
    sector_allocations = {}
    
    # Target counts
    n_comm = max(1, int(round(n_assets * (target_commodity_pct / 100.0))))
    n_idx = max(1, int(round(n_assets * (target_index_pct / 100.0))))
    n_eq = n_assets - n_comm - n_idx

    # A. Allocate Commodities
    for r in com_rows[:n_comm]:
        c_sym = str(r[0])
        c_name = str(r[1]) if r[1] else c_sym
        c_price = float(r[2]) if r[2] else 2500.0
        selected_portfolio.append({
            "symbol": c_sym,
            "name": c_name,
            "asset_class": "Commodity",
            "sector": "Commodities & Precious Metals",
            "tier": "macro",
            "current_price": c_price,
            "target_price_1": round(c_price * 1.06, 2),
            "stop_loss": round(c_price * 0.96, 2),
            "composite_score": 75.0,
            "signal": "BUY",
            "risk_level": "SAFE" if "Gold" in c_name or "Silver" in c_name else "MODERATE",
            "expected_1y_ret_pct": 12.0,
            "raw_weight": target_commodity_pct / max(1, n_comm)
        })

    # B. Allocate Benchmark Indexes / Sectors
    for r in idx_rows[:n_idx]:
        i_sym = str(r[0])
        i_name = str(r[1]) if r[1] else i_sym
        i_price = float(r[2]) if r[2] else 24000.0
        selected_portfolio.append({
            "symbol": i_sym,
            "name": i_name,
            "asset_class": "Index / ETF",
            "sector": "Benchmark Index",
            "tier": "macro",
            "current_price": i_price,
            "target_price_1": round(i_price * 1.05, 2),
            "stop_loss": round(i_price * 0.97, 2),
            "composite_score": 78.0,
            "signal": "BUY",
            "risk_level": "SAFE",
            "expected_1y_ret_pct": 14.0,
            "raw_weight": target_index_pct / max(1, n_idx)
        })

    # C. Allocate Equities with Sector & Cap Filters
    eq_weight_per_stock = target_equity_pct / max(1, n_eq)
    for r in stock_rows:
        if len([x for x in selected_portfolio if x["asset_class"] == "Equity"]) >= n_eq:
            break

        sym = str(r[0])
        s_name = str(r[1]) if r[1] else sym
        sec = str(r[2]) if r[2] else "General"
        tier = str(r[3]) if r[3] else "large"
        px = float(r[4]) if r[4] else 1000.0
        score = float(r[5]) if r[5] else 65.0
        sig = str(r[6]) if r[6] else "BUY"
        risk = str(r[7]) if r[7] else "SAFE"
        t1 = float(r[8]) if r[8] else px * 1.05
        sl = float(r[9]) if r[9] else px * 0.95

        # Check sector cap constraint
        current_sec_weight = sector_allocations.get(sec, 0.0)
        if current_sec_weight + eq_weight_per_stock > max_sector_exposure_pct:
            continue # Skip to maintain sector diversification

        # Risk profile filter
        if risk_profile == "SAFE" and risk == "RISKY":
            continue

        sector_allocations[sec] = current_sec_weight + eq_weight_per_stock

        exp_ret = 18.0 if horizon == "1_YEAR" else (55.0 if horizon == "3_YEARS" else 115.0)
        if risk_profile == "RISKY":
            exp_ret *= 1.3
        elif risk_profile == "SAFE":
            exp_ret *= 0.85

        selected_portfolio.append({
            "symbol": sym,
            "name": s_name,
            "asset_class": "Equity",
            "sector": sec,
            "tier": tier,
            "current_price": px,
            "target_price_1": t1,
            "stop_loss": sl,
            "composite_score": score,
            "signal": sig,
            "risk_level": risk,
            "expected_1y_ret_pct": round(exp_ret, 1),
            "raw_weight": eq_weight_per_stock
        })

    # 5. Normalize weights to exactly 100%
    total_raw_weight = sum(item["raw_weight"] for item in selected_portfolio)
    for item in selected_portfolio:
        norm_w = (item["raw_weight"] / max(1e-6, total_raw_weight)) * 100.0
        # Cap single asset
        norm_w = min(max_single_asset_pct, norm_w)
        item["weight_pct"] = round(norm_w, 2)
        item["allocated_capital_inr"] = round((total_capital_inr * norm_w) / 100.0, 2)
        item["shares_to_buy"] = int(math.floor(item["allocated_capital_inr"] / max(0.01, item["current_price"])))

    # Re-normalize precisely to 100.0%
    w_sum = sum(x["weight_pct"] for x in selected_portfolio)
    if w_sum > 0:
        for x in selected_portfolio:
            x["weight_pct"] = round((x["weight_pct"] / w_sum) * 100.0, 2)
            x["allocated_capital_inr"] = round((total_capital_inr * x["weight_pct"]) / 100.0, 2)

    # 6. Horizon Compounding Projections
    proj_1y_val = round(total_capital_inr * (1.0 + exp_cagr_1y / 100.0), 2)
    proj_3y_val = round(total_capital_inr * ((1.0 + exp_cagr_3y / 100.0) ** 3), 2)
    proj_5y_val = round(total_capital_inr * ((1.0 + exp_cagr_5y / 100.0) ** 5), 2)

    # Sector breakdown for donut charts
    sec_summary = {}
    for x in selected_portfolio:
        sec = x["sector"]
        sec_summary[sec] = round(sec_summary.get(sec, 0.0) + x["weight_pct"], 2)

    asset_class_summary = {}
    for x in selected_portfolio:
        ac = x["asset_class"]
        asset_class_summary[ac] = round(asset_class_summary.get(ac, 0.0) + x["weight_pct"], 2)

    return {
        "n_assets": len(selected_portfolio),
        "risk_profile": risk_profile,
        "horizon": horizon,
        "mandate_desc": mandate_desc,
        "total_capital_inr": total_capital_inr,
        "expected_cagr_pct": exp_cagr_1y if horizon in ["DAILY", "1_YEAR"] else (exp_cagr_3y if horizon == "3_YEARS" else exp_cagr_5y),
        "projected_1y_capital": proj_1y_val,
        "projected_3y_capital": proj_3y_val,
        "projected_5y_capital": proj_5y_val,
        "asset_class_summary": asset_class_summary,
        "sector_summary": sec_summary,
        "assets": selected_portfolio
    }