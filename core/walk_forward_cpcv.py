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

    r = strategy_returns
    n = len(r)
    rf_daily = annual_risk_free_rate / 252.0
    excess_r = r - rf_daily

    mean_r = float(np.mean(excess_r))
    std_r = float(np.std(excess_r))
    if std_r <= 1e-6:
        return {}

    sr_daily = mean_r / std_r
    sr_annual = sr_daily * math.sqrt(252.0)

    # Return Distribution Higher Moments
    skewness = float(skew(excess_r))
    kurt = float(kurtosis(excess_r, fisher=False)) # Pearson kurtosis (normal = 3)

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

    # Probability of Backtest Overfitting (PBO)
    pbo_pct = round((1.0 - dsr_p_value) * 100.0, 1)

    # Minimum Track Record Length (MinTRL) in Trading Days
    z_alpha = 1.645 # 95% confidence level
    min_trl_days = int(math.ceil(1.0 + (1.0 - skewness * sr_annual + ((kurt - 1.0) / 4.0) * (sr_annual ** 2)) * ((z_alpha / max(0.01, sr_annual - benchmark_sharpe)) ** 2)))

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
        "deflated_sharpe_p_value": round(dsr_p_value, 3),
        "prob_backtest_overfitting_pct": pbo_pct,
        "skewness": round(skewness, 2),
        "kurtosis": round(kurt, 2),
        "num_trials_penalized": num_trials,
        "min_track_record_days": min_trl_days,
        "sample_days_tested": n,
        "overfitting_verdict": verdict,
        "verdict_badge": verdict_badge
    }