"""
Global Macro Transmission Matrix & Yield Curve Monitor
- India 10Y G-Sec vs US 10Y Treasury Yield Spread & FII Inflow/Outflow Pressure
- 10Y vs 2Y Yield Curve Slope & Economic Cycle Regime Indicator
- Sector Inter-Market Elasticity & Sensitivity Matrix (USD/INR, Brent Crude, Gold, Yields)
"""
import logging
from typing import Dict, List, Optional
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

SECTOR_MACRO_ELASTICITIES = {
    "Information Technology": {
        "USD_INR_Sensitivity": +0.65,
        "Crude_Oil_Sensitivity": -0.10,
        "Interest_Rate_Sensitivity": -0.45,
        "Gold_Sensitivity": -0.05,
        "Key_Catalyst": "US Tech Enterprise Spending & INR Depreciation"
    },
    "Banking & Finance": {
        "USD_INR_Sensitivity": -0.35,
        "Crude_Oil_Sensitivity": -0.30,
        "Interest_Rate_Sensitivity": +0.40,
        "Gold_Sensitivity": +0.15,
        "Key_Catalyst": "Credit Growth, Net Interest Margins (NIM), and RBI Liquidity"
    },
    "Automobile & Auto Ancillaries": {
        "USD_INR_Sensitivity": -0.25,
        "Crude_Oil_Sensitivity": -0.55,
        "Interest_Rate_Sensitivity": -0.60,
        "Gold_Sensitivity": -0.10,
        "Key_Catalyst": "Retail Auto Loan Rates, Fuel Prices, and Commodity Input Costs"
    },
    "Pharmaceuticals & Healthcare": {
        "USD_INR_Sensitivity": +0.50,
        "Crude_Oil_Sensitivity": -0.15,
        "Interest_Rate_Sensitivity": -0.10,
        "Gold_Sensitivity": +0.05,
        "Key_Catalyst": "US Generic Pricing, FDA Clearances, and INR Tailwinds"
    },
    "Energy & Power": {
        "USD_INR_Sensitivity": -0.40,
        "Crude_Oil_Sensitivity": +0.80,
        "Interest_Rate_Sensitivity": -0.20,
        "Gold_Sensitivity": +0.10,
        "Key_Catalyst": "Global Refining Margins (GRM) and Crude Realizations"
    },
    "Metals & Mining": {
        "USD_INR_Sensitivity": +0.20,
        "Crude_Oil_Sensitivity": -0.35,
        "Interest_Rate_Sensitivity": -0.30,
        "Gold_Sensitivity": +0.45,
        "Key_Catalyst": "China Real Estate Demand, LME Copper/Aluminium Prices"
    },
    "Fast Moving Consumer Goods (FMCG)": {
        "USD_INR_Sensitivity": -0.15,
        "Crude_Oil_Sensitivity": -0.45,
        "Interest_Rate_Sensitivity": -0.15,
        "Gold_Sensitivity": -0.05,
        "Key_Catalyst": "Rural Monsoon Demand, Palm Oil / Crude Packaging Costs"
    },
    "Real Estate & Construction": {
        "USD_INR_Sensitivity": -0.20,
        "Crude_Oil_Sensitivity": -0.40,
        "Interest_Rate_Sensitivity": -0.80,
        "Gold_Sensitivity": -0.10,
        "Key_Catalyst": "Home Loan Mortgage Rates, Cement / Steel Raw Material Input Costs"
    }
}


def compute_macro_transmission_dashboard(
    india_10y_yield: float = 6.85,
    us_10y_yield: float = 4.25,
    usd_inr: float = 87.20,
    brent_crude_usd: float = 78.50,
    gold_usd_oz: float = 2650.0
) -> Dict:
    """Computes global macro transmission matrix and yield curve spread analytics."""
    yield_spread = round(india_10y_yield - us_10y_yield, 2)
    
    # FII Inflow Incentive
    if yield_spread >= 3.20:
        fii_regime = "STRONG FII INFLOW INCENTIVE (WIDE SPREAD)"
        fii_badge = "🟢 FII INFLOW TAILWIND"
    elif yield_spread <= 2.20:
        fii_regime = "FII OUTFLOW PRESSURE (NARROW SPREAD)"
        fii_badge = "🔴 FII OUTFLOW HEADWIND"
    else:
        fii_regime = "MODERATE / BALANCED CAPITAL FLOWS"
        fii_badge = "🟡 BALANCED CAPITAL FLOWS"

    # Yield curve slope estimate (10Y - 2Y)
    yc_slope = round(india_10y_yield - 6.45, 2) # ~40 bps positive slope
    if yc_slope > 0.60:
        yc_regime = "STEEPENING (ECONOMIC EXPANSION / GROWTH)"
    elif yc_slope < 0.05:
        yc_regime = "FLATTENING / INVERTED (MONETARY TIGHTENING)"
    else:
        yc_regime = "NORMAL HEALTHY EXPANSION"

    # Compute Net Macro Impact on Each Sector
    # Normalize macro moves: USD/INR, Crude, Gold, Yields
    sector_impacts = []
    for sec, sens in SECTOR_MACRO_ELASTICITIES.items():
        # Net macro tailwind score (-100 to +100)
        net_score = (
            sens["USD_INR_Sensitivity"] * 25.0 +
            sens["Crude_Oil_Sensitivity"] * (-(brent_crude_usd - 75.0) / 75.0 * 50.0) +
            sens["Interest_Rate_Sensitivity"] * (-(india_10y_yield - 6.5) / 6.5 * 40.0)
        )
        net_score = float(np.clip(net_score, -85.0, 85.0))
        
        impact_label = "🟢 TAILWIND (BULLISH)" if net_score > 15 else ("🔴 HEADWIND (BEARISH)" if net_score < -15 else "🟡 NEUTRAL IMPACT")
        
        sector_impacts.append({
            "sector": sec,
            "net_macro_score": round(net_score, 1),
            "macro_status": impact_label,
            "usd_inr_beta": sens["USD_INR_Sensitivity"],
            "crude_beta": sens["Crude_Oil_Sensitivity"],
            "rate_beta": sens["Interest_Rate_Sensitivity"],
            "catalyst": sens["Key_Catalyst"]
        })

    sector_impacts.sort(key=lambda x: x["net_macro_score"], reverse=True)

    return {
        "india_10y_yield": india_10y_yield,
        "us_10y_yield": us_10y_yield,
        "yield_spread": yield_spread,
        "fii_regime": fii_regime,
        "fii_badge": fii_badge,
        "yc_slope": yc_slope,
        "yc_regime": yc_regime,
        "usd_inr": usd_inr,
        "brent_crude": brent_crude_usd,
        "gold_price": gold_usd_oz,
        "sector_matrix": sector_impacts
    }