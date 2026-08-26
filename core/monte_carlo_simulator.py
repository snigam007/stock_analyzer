"""
10,000-Path Monte Carlo Jump-Diffusion Forward Price Simulator
- Stochastic Merton Jump-Diffusion Model:
  dS = (mu - lambda*k)*S*dt + sigma*S*dW + S*(J - 1)*dN
- Calculates Empirical Probability Cones (5th, 25th, 50th, 75th, 95th percentiles)
- Calculates Probability of Hitting Target 1, Target 2, Target 3, and Stop Loss
"""
import logging
from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def simulate_monte_carlo_jump_diffusion(
    current_price: float,
    daily_volatility: float = 0.02,
    annual_drift: float = 0.12,
    target_1: Optional[float] = None,
    target_2: Optional[float] = None,
    target_3: Optional[float] = None,
    stop_loss: Optional[float] = None,
    n_paths: int = 10000,
    horizon_days: int = 45,
    jump_intensity_lambda: float = 0.05, # ~12 jumps per year
    jump_mean_mu: float = -0.015,       # average -1.5% jump shock
    jump_vol_sigma: float = 0.045       # jump dispersion
) -> Dict:
    """Simulates 10,000 forward paths using Merton Jump-Diffusion."""
    if current_price <= 0:
        return {}

    dt = 1.0 / 252.0
    mu_daily = annual_drift * dt
    sigma_daily = max(0.005, daily_volatility)

    # Jump compensation factor k = E[J - 1] = exp(mu_J + 0.5*sigma_J^2) - 1
    k = np.exp(jump_mean_mu + 0.5 * (jump_vol_sigma ** 2)) - 1.0
    drift_adjusted = mu_daily - jump_intensity_lambda * k

    np.random.seed(int(abs(current_price * 100)) % 10000)

    # Vectorized Simulation Matrix: (n_paths, horizon_days)
    z_brownian = np.random.normal(0, 1, (n_paths, horizon_days))
    
    # Poisson jumps
    n_jumps = np.random.poisson(jump_intensity_lambda, (n_paths, horizon_days))
    jump_sizes = np.random.normal(jump_mean_mu, jump_vol_sigma, (n_paths, horizon_days)) * n_jumps

    # Log returns per step
    log_returns = (drift_adjusted - 0.5 * (sigma_daily ** 2)) + sigma_daily * z_brownian + jump_sizes
    cum_log_returns = np.cumsum(log_returns, axis=1)

    # Price paths: shape (n_paths, horizon_days + 1)
    paths = np.zeros((n_paths, horizon_days + 1))
    paths[:, 0] = current_price
    paths[:, 1:] = current_price * np.exp(cum_log_returns)

    # Empirical Percentiles over time
    days = list(range(horizon_days + 1))
    p5 = np.percentile(paths, 5, axis=0)
    p25 = np.percentile(paths, 25, axis=0)
    p50 = np.percentile(paths, 50, axis=0) # Median
    p75 = np.percentile(paths, 75, axis=0)
    p95 = np.percentile(paths, 95, axis=0)

    # Default targets if None
    t1 = target_1 or (current_price * 1.04)
    t2 = target_2 or (current_price * 1.08)
    t3 = target_3 or (current_price * 1.15)
    sl = stop_loss or (current_price * 0.95)

    # Probabilities across entire horizon (any day breach/touch)
    max_path_prices = np.max(paths, axis=1)
    min_path_prices = np.min(paths, axis=1)

    prob_t1 = round(float(np.mean(max_path_prices >= t1) * 100.0), 1)
    prob_t2 = round(float(np.mean(max_path_prices >= t2) * 100.0), 1)
    prob_t3 = round(float(np.mean(max_path_prices >= t3) * 100.0), 1)
    prob_sl = round(float(np.mean(min_path_prices <= sl) * 100.0), 1)

    # Expected value at horizon end
    terminal_prices = paths[:, -1]
    expected_terminal_price = round(float(np.mean(terminal_prices)), 2)
    expected_return_pct = round(((expected_terminal_price - current_price) / current_price) * 100.0, 2)

    return {
        "current_price": round(current_price, 2),
        "horizon_days": horizon_days,
        "n_paths": n_paths,
        "expected_terminal_price": expected_terminal_price,
        "expected_return_pct": expected_return_pct,
        "prob_target_1": prob_t1,
        "prob_target_2": prob_t2,
        "prob_target_3": prob_t3,
        "prob_stop_loss": prob_sl,
        "target_1": round(t1, 2),
        "target_2": round(t2, 2),
        "target_3": round(t3, 2),
        "stop_loss": round(sl, 2),
        "days": days,
        "p5": [round(x, 2) for x in p5],
        "p25": [round(x, 2) for x in p25],
        "p50": [round(x, 2) for x in p50],
        "p75": [round(x, 2) for x in p75],
        "p95": [round(x, 2) for x in p95],
        "sample_paths": [paths[i, :].tolist() for i in range(min(15, n_paths))]
    }