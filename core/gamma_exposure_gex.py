"""
Market Maker Net Gamma Exposure (GEX) & Zero-Gamma Volatility Engine
- Strike-by-Strike Net Dealer Gamma Exposure (GEX in ₹ Crores)
- Zero-Gamma Level: Transition boundary between Volatility Dampening (+GEX) & Volatility Squeeze (-GEX)
- Gamma Squeeze Trigger Strikes & Major Dealer Pinning Zones
"""
import math
import logging
from typing import Dict, List, Optional
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def compute_net_gamma_exposure_profile(
    spot_price: float,
    strikes: List[float],
    call_oi: List[int],
    put_oi: List[int],
    iv: float = 0.18,
    dte_days: int = 15,
    r: float = 0.065
) -> Dict:
    """Computes strike-by-strike Dealer Net Gamma Exposure and Zero-Gamma threshold."""
    if not strikes or spot_price <= 0:
        return {}

    t = max(1, dte_days) / 365.0
    vol = max(0.01, iv)
    s = spot_price

    gex_records = []
    total_call_gex = 0.0
    total_put_gex = 0.0

    for k, c_oi, p_oi in zip(strikes, call_oi, put_oi):
        d1 = (math.log(s / max(0.01, k)) + (r + 0.5 * vol ** 2) * t) / (vol * math.sqrt(t))
        pdf_d1 = (1.0 / math.sqrt(2.0 * math.pi)) * math.exp(-0.5 * d1 * d1)
        gamma = pdf_d1 / (s * vol * math.sqrt(t))

        # Spot * Gamma * OI * 100 / 1e7 (in ₹ Crores per 1% move)
        call_gex = (s * gamma * c_oi * 100.0 * (s * 0.01)) / 1e7
        put_gex = - (s * gamma * p_oi * 100.0 * (s * 0.01)) / 1e7
        net_gex = call_gex + put_gex

        total_call_gex += call_gex
        total_put_gex += put_gex

        gex_records.append({
            "strike": k,
            "call_oi": c_oi,
            "put_oi": p_oi,
            "gamma": gamma,
            "call_gex_cr": round(call_gex, 2),
            "put_gex_cr": round(put_gex, 2),
            "net_gex_cr": round(net_gex, 2)
        })

    df_gex = pd.DataFrame(gex_records)
    total_net_gex = round(total_call_gex + total_put_gex, 2)

    # Calculate Zero-Gamma Level (Strike where cumulative net gamma transitions zero)
    zero_gamma_level = spot_price
    if not df_gex.empty:
        # Find strike closest to 0 Net GEX
        zero_gamma_idx = int(np.argmin(np.abs(df_gex["net_gex_cr"])))
        zero_gamma_level = float(df_gex["strike"].iloc[zero_gamma_idx])

    # Volatility Regime
    if total_net_gex > 50.0:
        vol_regime = "HIGH POSITIVE GAMMA (+GEX)"
        regime_desc = "Dealers are long gamma: Buying dips & selling rallies. Volatility is suppressed, price tends to pin near strikes."
        regime_badge = "🟢 VOLATILITY DAMPENING (+GEX)"
    elif total_net_gex < -50.0:
        vol_regime = "NEGATIVE GAMMA REGIME (-GEX)"
        regime_desc = "Dealers are short gamma: Forced to sell into selloffs & buy into breakouts. High probability of violent squeezes and flash moves."
        regime_badge = "🔴 VOLATILITY SQUEEZE (-GEX)"
    else:
        vol_regime = "NEUTRAL / BALANCED GAMMA"
        regime_desc = "Gamma exposure is balanced. Directional trend follows underlying order flow momentum."
        regime_badge = "🟡 BALANCED GAMMA"

    # Squeeze Trigger Strikes
    call_wall_idx = int(np.argmax(df_gex["call_gex_cr"])) if not df_gex.empty else 0
    put_wall_idx = int(np.argmin(df_gex["put_gex_cr"])) if not df_gex.empty else 0
    call_squeeze_level = float(df_gex["strike"].iloc[call_wall_idx]) if not df_gex.empty else spot_price
    put_liquidity_support = float(df_gex["strike"].iloc[put_wall_idx]) if not df_gex.empty else spot_price

    return {
        "spot_price": spot_price,
        "total_net_gex_cr": total_net_gex,
        "total_call_gex_cr": round(total_call_gex, 2),
        "total_put_gex_cr": round(total_put_gex, 2),
        "zero_gamma_level": zero_gamma_level,
        "vol_regime": vol_regime,
        "regime_desc": regime_desc,
        "regime_badge": regime_badge,
        "call_squeeze_level": call_squeeze_level,
        "put_liquidity_support": put_liquidity_support,
        "gex_table": df_gex
    }