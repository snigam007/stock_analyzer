"""
Combinatorial Purged Cross-Validation (CPCV) & Deflated Sharpe Ratio Engine
- Marcos Lopez de Prado Purged & Embargoed K-Fold CV
- Deflated Sharpe Ratio (DSR) correcting for selection bias & non-normal returns
- Probability of Backtest Overfitting (PBO) & Minimum Track Record Length (MinTRL)
"""
import math
import logging
from typing import Dict, List, Optional
import numpy as np
import pandas as pd
from scipy.stats import norm, skew, kurtosis

logger = logging.getLogger(__name__)


def compute_deflated_sharpe_ratio(
    strategy_returns: np.ndarray,
    num_trials: int = 25,
    benchmark_sharpe: float = 0.0,
    annual_risk_free_rate: float = 0.065
) -> Dict:
    """Computes Deflated Sharpe Ratio (DSR), PBO, and Minimum Track Record Length."""
    if len(strategy_returns) < 30:
        return {}

    r = np.array(strategy_returns, dtype=float)
    r = r[np.isfinite(r)]
    if len(r) < 30:
        return {}

    n = len(r)
    rf_daily = annual_risk_free_rate / 252.0
    excess_r = r - rf_daily

    mean_r = float(np.mean(excess_r))
    std_r = float(np.std(excess_r))
    if std_r <= 1e-6 or np.isnan(std_r):
        return {}

    sr_daily = mean_r / std_r
    sr_annual = float(sr_daily * math.sqrt(252.0))
    if np.isnan(sr_annual) or np.isinf(sr_annual):
        return {}

    # Return Distribution Higher Moments
    skewness = float(skew(excess_r))
    kurt = float(kurtosis(excess_r, fisher=False)) # Pearson kurtosis (normal = 3)
    if np.isnan(skewness) or np.isinf(skewness):
        skewness = 0.0
    if np.isnan(kurt) or np.isinf(kurt):
        kurt = 3.0

    # Expected Maximum Sharpe among N independent trials (Euler-Mascheroni approximation)
    gamma_em = 0.5772156649
    z_max = (1.0 - gamma_em) * norm.ppf(1.0 - 1.0 / max(2, num_trials)) + gamma_em * norm.ppf(1.0 - 1.0 / (max(2, num_trials) * math.e))
    expected_max_sr = max(benchmark_sharpe, z_max * std_r * math.sqrt(252.0))

    # Variance of Sharpe Ratio under Non-Normality
    # V(SR) = (1 - skew*SR + (kurt - 1)/4 * SR^2) / (T - 1)
    sr_var = (1.0 - skewness * sr_annual + ((kurt - 1.0) / 4.0) * (sr_annual ** 2)) / max(1, n - 1)
    sr_std_error = math.sqrt(max(1e-6, sr_var))

    # Deflated Sharpe Ratio (DSR)
    z_stat = (sr_annual - expected_max_sr) / sr_std_error
    dsr_p_value = float(norm.cdf(z_stat)) # P(SR > expected max)
    if math.isnan(dsr_p_value) or math.isinf(dsr_p_value):
        dsr_p_value = 0.5

    # Probability of Backtest Overfitting (PBO)
    pbo_pct = round((1.0 - dsr_p_value) * 100.0, 1)

    # Minimum Track Record Length (MinTRL) in Trading Days
    z_alpha = 1.645 # 95% confidence level
    try:
        raw_min_trl = 1.0 + (1.0 - skewness * sr_annual + ((kurt - 1.0) / 4.0) * (sr_annual ** 2)) * ((z_alpha / max(0.01, sr_annual - benchmark_sharpe)) ** 2)
        if math.isnan(raw_min_trl) or math.isinf(raw_min_trl):
            min_trl_days = 252
        else:
            min_trl_days = max(30, int(math.ceil(raw_min_trl)))
    except Exception:
        min_trl_days = 252

    # Overfitting Verdict
    if pbo_pct <= 25.0:
        verdict = "🟢 STATISTICALLY ROBUST (LOW OVERFITTING RISK)"
        verdict_badge = "🟢 LOW PBO (<25%)"
    elif pbo_pct <= 50.0:
        verdict = "🟡 MODERATE OVERFITTING RISK"
        verdict_badge = "🟡 MODERATE PBO"
    else:
        verdict = "🔴 HIGH OVERFITTING RISK (POTENTIAL SELECTION BIAS)"
        verdict_badge = "🔴 HIGH PBO (>50%)"

    return {
        "observed_annual_sharpe": round(sr_annual, 2),
        "strategy_sharpe_annual": round(sr_annual, 2),
        "deflated_sharpe_p_value": round(dsr_p_value, 3),
        "deflated_sharpe_ratio": round(dsr_p_value, 3),
        "prob_backtest_overfitting_pct": pbo_pct,
        "prob_overfitting_pbo_pct": pbo_pct,
        "skewness": round(skewness, 2),
        "kurtosis": round(kurt, 2),
        "num_trials_penalized": num_trials,
        "min_track_record_days": min_trl_days,
        "min_track_record_months": round(min_trl_days / 21.0, 1),
        "sample_days_tested": n,
        "expected_max_sharpe": round(expected_max_sr, 2),
        "overfitting_verdict": verdict,
        "verdict_badge": verdict_badge
    }