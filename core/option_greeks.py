"""
Black-Scholes-Merton Option Greeks & Gamma Exposure (GEX) Engine
- Delta, Gamma, Theta, Vega, Rho analytical derivatives
- Gamma Exposure (GEX) Profile & Zero-Gamma Volatility Flip Point
- Implied Volatility (IV) Smile & Skew Analysis
"""
import logging
import math
from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np
from scipy.stats import norm

logger = logging.getLogger(__name__)


def calculate_black_scholes_greeks(
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    volatility: float,
    risk_free_rate: float = 0.065, # 6.5% benchmark
) -> Dict:
    """
    Computes analytical Black-Scholes-Merton Option Greeks for Call and Put options.
    """
    if spot <= 0 or strike <= 0 or time_to_expiry_years <= 0 or volatility <= 0:
        return {
            "call_delta": 0.5, "put_delta": -0.5,
            "gamma": 0.0, "theta_call": 0.0, "theta_put": 0.0,
            "vega": 0.0, "rho_call": 0.0, "rho_put": 0.0,
        }

    S = spot
    K = strike
    T = time_to_expiry_years
    r = risk_free_rate
    sigma = max(0.05, volatility)

    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T

    # Standard Normal CDF & PDF
    N_d1 = norm.cdf(d1)
    N_d2 = norm.cdf(d2)
    N_neg_d1 = norm.cdf(-d1)
    N_neg_d2 = norm.cdf(-d2)
    n_d1 = norm.pdf(d1)

    # 1. Delta (Price sensitivity per ₹1 move)
    call_delta = float(N_d1)
    put_delta = float(N_d1 - 1.0)

    # 2. Gamma (Rate of change of Delta per ₹1 move)
    gamma = float(n_d1 / (S * sigma * sqrt_T))

    # 3. Vega (Sensitivity to 1% change in volatility)
    vega = float(S * n_d1 * sqrt_T / 100.0)

    # 4. Theta (Daily time decay cost in ₹/day)
    theta_term1 = -(S * n_d1 * sigma) / (2.0 * sqrt_T)
    theta_call_annual = theta_term1 - r * K * math.exp(-r * T) * N_d2
    theta_put_annual = theta_term1 + r * K * math.exp(-r * T) * N_neg_d2
    theta_call_daily = float(theta_call_annual / 365.0)
    theta_put_daily = float(theta_put_annual / 365.0)

    # 5. Rho (Sensitivity to 1% interest rate change)
    rho_call = float(K * T * math.exp(-r * T) * N_d2 / 100.0)
    rho_put = float(-K * T * math.exp(-r * T) * N_neg_d2 / 100.0)

    return {
        "call_delta": round(call_delta, 3),
        "put_delta": round(put_delta, 3),
        "gamma": round(gamma, 6),
        "theta_call_daily": round(theta_call_daily, 2),
        "theta_put_daily": round(theta_put_daily, 2),
        "vega": round(vega, 2),
        "rho_call": round(rho_call, 2),
        "rho_put": round(rho_put, 2),
    }


def compute_gamma_exposure_profile(
    spot: float,
    options_chain: List[Dict],
    days_to_expiry: int = 15,
    annual_volatility: float = 0.22,
) -> Dict:
    """
    Computes strike-by-strike Gamma Exposure (GEX in ₹ Crores):
    Call GEX = + Gamma * S^2 * Call_OI * Contract_Size
    Put GEX  = - Gamma * S^2 * Put_OI * Contract_Size
    Net GEX  = Call GEX + Put GEX
    """
    T = max(1, days_to_expiry) / 365.0
    gex_table = []
    total_call_gex = 0.0
    total_put_gex = 0.0

    for opt in options_chain:
        strike = float(opt.get("strike") or opt.get("Strike Price (₹)") or 0.0)
        call_oi = float(opt.get("call_oi") or opt.get("Call OI (Contracts)") or 1000.0)
        put_oi = float(opt.get("put_oi") or opt.get("Put OI (Contracts)") or 1000.0)

        # Calculate Greek for this strike
        greeks = calculate_black_scholes_greeks(spot, strike, T, annual_volatility)
        gamma = greeks["gamma"]

        # Gamma Exposure in ₹ Lakhs / Crores
        # Contract multiplier approx 100 shares
        call_gex_cr = (gamma * (spot ** 2) * call_oi * 100) / 1e7
        put_gex_cr = -(gamma * (spot ** 2) * put_oi * 100) / 1e7
        net_gex_cr = call_gex_cr + put_gex_cr

        total_call_gex += call_gex_cr
        total_put_gex += put_gex_cr

        # Synthetic IV Smile with Put Skew
        moneyness = math.log(strike / spot)
        iv_skew = annual_volatility * (1.0 - 0.25 * moneyness + 0.15 * (moneyness ** 2))

        gex_table.append({
            "strike": strike,
            "call_delta": greeks["call_delta"],
            "put_delta": greeks["put_delta"],
            "gamma": greeks["gamma"],
            "theta_call": greeks["theta_call_daily"],
            "vega": greeks["vega"],
            "call_gex_cr": round(call_gex_cr, 2),
            "put_gex_cr": round(put_gex_cr, 2),
            "net_gex_cr": round(net_gex_cr, 2),
            "implied_volatility_pct": round(iv_skew * 100, 1),
            "call_oi": int(call_oi),
            "put_oi": int(put_oi),
        })

    # Find Zero Gamma Flip Level (where net GEX transitions from positive to negative)
    df_gex = pd.DataFrame(gex_table).sort_values("strike")
    zero_gamma_strike = spot
    for i in range(len(df_gex) - 1):
        if (df_gex["net_gex_cr"].iloc[i] <= 0 and df_gex["net_gex_cr"].iloc[i+1] > 0) or \
           (df_gex["net_gex_cr"].iloc[i] >= 0 and df_gex["net_gex_cr"].iloc[i+1] < 0):
            zero_gamma_strike = float(df_gex["strike"].iloc[i])
            break

    net_regime = "🟢 POSITIVE GAMMA (Volatility Dampening / Mean Reversion)" if (total_call_gex + total_put_gex) >= 0 else "🔴 NEGATIVE GAMMA (Volatility Expansion / Explosive Trend Acceleration)"

    return {
        "spot_price": spot,
        "total_call_gex_cr": round(total_call_gex, 2),
        "total_put_gex_cr": round(total_put_gex, 2),
        "total_net_gex_cr": round(total_call_gex + total_put_gex, 2),
        "zero_gamma_flip_strike": round(zero_gamma_strike, 2),
        "gamma_regime": net_regime,
        "gex_table": gex_table,
    }