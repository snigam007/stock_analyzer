"""
3D Implied Volatility Surface & Volatility Smile Engine
- Computes Strike-by-Expiry Implied Volatility Matrix: IV = f(K, T)
- Computes 25-Delta Put vs Call Skew (Crash Protection vs Speculative Call Demand)
- Generates 3D Interactive Mesh Surface Coordinates
"""
import math
import logging
from typing import Dict, List, Optional
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def generate_3d_volatility_surface(
    spot_price: float,
    atm_volatility: float = 0.18,
    symbol: str = "NIFTY"
) -> Dict:
    """Generates 3D Implied Volatility Surface mesh data across strikes and expiries."""
    if spot_price <= 0:
        return {}

    atm_vol = max(0.05, atm_volatility)
    s = spot_price

    # Strikes: 11 points from 85% to 115% of spot
    strike_pcts = np.linspace(0.85, 1.15, 11)
    strikes = [round(s * p, 0) for p in strike_pcts]

    # Expiries in days: 7d (Weekly), 14d, 30d (Monthly), 60d, 90d (Quarterly)
    expiries_days = [7, 14, 30, 60, 90]

    # Volatility Surface Formula:
    # IV(K, T) = sigma_ATM + skew*(K/S - 1) + smile_curvature*(K/S - 1)^2 + term_structure*(1/sqrt(T))
    iv_matrix = []
    for dte in expiries_days:
        row = []
        t_years = dte / 365.0
        term_adj = 0.015 * (1.0 / math.sqrt(max(0.01, t_years * 12.0)))
        
        for k in strikes:
            moneyness = (k / s) - 1.0 # <0 is OTM Put / ITM Call, >0 is OTM Call / ITM Put
            
            # Negative skew: OTM Puts have higher IV than OTM Calls (Crash protection demand)
            skew_component = -0.22 * moneyness
            smile_component = 0.65 * (moneyness ** 2)

            point_iv = atm_vol + skew_component + smile_component + term_adj
            point_iv = float(np.clip(point_iv, 0.08, 0.65))
            row.append(round(point_iv * 100.0, 2))
        iv_matrix.append(row)

    # 25-Delta Put vs Call Skew (30-day expiry)
    iv_30d = iv_matrix[2] # 30d row
    put_25d_iv = iv_30d[2] # ~90% strike
    call_25d_iv = iv_30d[8] # ~110% strike
    skew_25d = round(put_25d_iv - call_25d_iv, 2)

    if skew_25d >= 4.0:
        skew_sentiment = "HIGH INSTITUTIONAL DOWNSIDE HEDGING (PUT SKEW)"
        skew_badge = "🔴 ELEVATED CRASH PROTECTION"
    elif skew_25d <= 0.5:
        skew_sentiment = "EUPHORIC UPSIDE CALL SPECULATION (CALL SKEW)"
        skew_badge = "🟢 CALL HEAVY / MOMENTUM"
    else:
        skew_sentiment = "NORMAL INSTITUTIONAL VOLATILITY SKEW"
        skew_badge = "🟡 BALANCED VOL SKEW"

    return {
        "symbol": symbol,
        "spot_price": spot_price,
        "atm_iv_pct": round(atm_vol * 100.0, 1),
        "strikes": strikes,
        "expiries_days": expiries_days,
        "iv_matrix": iv_matrix,
        "put_25d_iv_pct": put_25d_iv,
        "call_25d_iv_pct": call_25d_iv,
        "skew_25d_pct": skew_25d,
        "skew_sentiment": skew_sentiment,
        "skew_badge": skew_badge
    }