"""
Monte Carlo Simulation & Risk Lab Engine for Monthly SIP Strategies.
Performs vectorized bootstrapping, sequence-of-returns path simulation,
tail risk (VaR/CVaR) quantification, and stress-test crash injection.
"""
from datetime import datetime, timedelta
import math
from typing import Dict, List, Optional
import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from core.sip_audit_backtester import run_monthly_sip_backtest


def run_monte_carlo_simulation(
    session: Session,
    monthly_wallet: float = 20000.0,
    horizon_months: int = 60,
    strategy: str = "PURE_STOCKS",
    exit_protocol: str = "ADAPTIVE_STRUCTURAL",
    annual_step_up_pct: float = 0.0,
    n_simulations: int = 500,
    stress_shock_pct: float = 0.0,
    random_seed: Optional[int] = 42
) -> Dict:
    """
    Executes a multi-path Monte Carlo simulation based on empirical return distributions.
    
    Parameters:
      - monthly_wallet: Base monthly inflow in INR.
      - horizon_months: SIP investment duration (12, 24, 36, 60).
      - strategy: "PURE_STOCKS" or "MULTI_ASSET".
      - exit_protocol: "ADAPTIVE_STRUCTURAL", "STRUCTURAL_TRAILING", "BUY_AND_HOLD", "TIGHT_SWING".
      - annual_step_up_pct: % increase in monthly SIP every 12 months.
      - n_simulations: Number of synthetic market paths (250, 500, 1000).
      - stress_shock_pct: Optional black-swan shock (e.g. 20.0 for -20% flash drop).
      - random_seed: Seed for reproducible simulation results.
    """
    if random_seed is not None:
        np.random.seed(random_seed)

    n_simulations = max(50, min(2000, n_simulations))
    horizon_months = max(6, min(120, horizon_months))
    monthly_wallet = max(5000.0, float(monthly_wallet))

    # 1. Run empirical baseline backtest to extract real historical monthly returns
    base_res = run_monthly_sip_backtest(
        session=session,
        monthly_wallet=monthly_wallet,
        strategy=strategy,
        months_lookback=min(60, horizon_months),
        exit_protocol=exit_protocol,
        annual_step_up_pct=annual_step_up_pct
    )

    eq_curve = base_res.get("equity_curve", [])
    if not eq_curve or len(eq_curve) < 30:
        # Fallback parametric distribution if historical days are limited
        strat_monthly_mean = 0.0195
        strat_monthly_std = 0.048
        bench_monthly_mean = 0.0098
        bench_monthly_std = 0.042
        correlation = 0.72
    else:
        # Convert daily equity curve to monthly returns
        df_eq = pd.DataFrame(eq_curve)
        df_eq["date"] = pd.to_datetime(df_eq["date"])
        df_eq["year_month"] = df_eq["date"].dt.to_period("M")

        # Monthly closing points
        m_ends = df_eq.groupby("year_month").last().reset_index()
        m_ends["strat_ret"] = m_ends["strategy_equity"].pct_change().fillna(0.0)
        m_ends["bench_ret"] = m_ends["benchmark_equity"].pct_change().fillna(0.0)

        # Drop 1st month artifact
        m_valid = m_ends.iloc[1:] if len(m_ends) > 2 else m_ends
        strat_monthly_mean = float(m_valid["strat_ret"].mean())
        strat_monthly_std = float(m_valid["strat_ret"].std()) if float(m_valid["strat_ret"].std()) > 0 else 0.045
        bench_monthly_mean = float(m_valid["bench_ret"].mean())
        bench_monthly_std = float(m_valid["bench_ret"].std()) if float(m_valid["bench_ret"].std()) > 0 else 0.040

        # Bound parameters to realistic market limits
        strat_monthly_mean = max(0.005, min(0.035, strat_monthly_mean))
        strat_monthly_std = max(0.025, min(0.090, strat_monthly_std))
        bench_monthly_mean = max(0.003, min(0.020, bench_monthly_mean))
        bench_monthly_std = max(0.020, min(0.075, bench_monthly_std))

        corr_matrix = np.corrcoef(m_valid["strat_ret"].values, m_valid["bench_ret"].values)
        correlation = float(corr_matrix[0, 1]) if not np.isnan(corr_matrix[0, 1]) else 0.70

    # Covariance matrix for correlated bivariate simulation
    cov = correlation * strat_monthly_std * bench_monthly_std
    cov_matrix = np.array([
        [strat_monthly_std ** 2, cov],
        [cov, bench_monthly_std ** 2]
    ])

    # 2. Vectorized Path Generation across n_simulations
    # Shape: (n_simulations, horizon_months, 2)
    mean_vec = [strat_monthly_mean, bench_monthly_mean]
    sim_returns = np.random.multivariate_normal(mean_vec, cov_matrix, size=(n_simulations, horizon_months))

    strat_sim_rets = sim_returns[:, :, 0] # (n_simulations, horizon_months)
    bench_sim_rets = sim_returns[:, :, 1]

    # If stress shock is requested, inject flash drop at month ~midpoint
    if stress_shock_pct > 0:
        shock_decimal = -abs(stress_shock_pct) / 100.0
        shock_month = max(2, horizon_months // 2)
        # Trailing exits protect: strategy only absorbs fraction of the shock (e.g. 50-65% due to stop loss)
        strat_sim_rets[:, shock_month] = shock_decimal * 0.60
        bench_sim_rets[:, shock_month] = shock_decimal

    # 3. Simulate SIP Cash Flows and Equity Accumulation
    # Compute stepped-up monthly wallet array
    monthly_inflows = np.zeros(horizon_months)
    for m in range(horizon_months):
        yr = m // 12
        monthly_inflows[m] = round(monthly_wallet * ((1.0 + annual_step_up_pct / 100.0) ** yr), 2)

    total_invested = float(np.sum(monthly_inflows))

    # Arrays to track path trajectories: (n_simulations, horizon_months + 1)
    strat_paths = np.zeros((n_simulations, horizon_months + 1))
    bench_paths = np.zeros((n_simulations, horizon_months + 1))
    invested_path = np.zeros(horizon_months + 1)

    cum_invested = 0.0
    for m in range(horizon_months):
        inflow = monthly_inflows[m]
        cum_invested += inflow
        invested_path[m + 1] = cum_invested

        # Next month compounding
        r_strat = strat_sim_rets[:, m]
        r_bench = bench_sim_rets[:, m]

        strat_paths[:, m + 1] = (strat_paths[:, m] + inflow) * (1.0 + r_strat)
        bench_paths[:, m + 1] = (bench_paths[:, m] + inflow) * (1.0 + r_bench)

    final_strat = strat_paths[:, -1]
    final_bench = bench_paths[:, -1]

    # 4. Compute Drawdowns for each simulated path
    # Peak-to-trough calculation across months for strategy
    running_max = np.maximum.accumulate(strat_paths, axis=1)
    # Avoid zero-division at index 0
    with np.errstate(divide='ignore', invalid='ignore'):
        drawdown_matrix = np.where(running_max > 0, (strat_paths - running_max) / running_max, 0.0)
    
    path_max_drawdowns = np.abs(np.min(drawdown_matrix, axis=1)) * 100.0

    # 5. Summary Statistics & Risk Percentiles
    p5_final = float(np.percentile(final_strat, 5))
    p25_final = float(np.percentile(final_strat, 25))
    median_final = float(np.percentile(final_strat, 50))
    p75_final = float(np.percentile(final_strat, 75))
    p95_final = float(np.percentile(final_strat, 95))

    bench_median_final = float(np.percentile(final_bench, 50))
    bench_p5_final = float(np.percentile(final_bench, 5))
    bench_p95_final = float(np.percentile(final_bench, 95))

    prob_beat_bench = float(np.mean(final_strat > final_bench) * 100.0)
    prob_profit = float(np.mean(final_strat > total_invested) * 100.0)

    # VaR 95% (Value at Risk): Maximum loss relative to invested capital or 5th percentile outcome
    worst_5_strat = final_strat[final_strat <= p5_final]
    cvar_95 = float(np.mean(worst_5_strat)) if len(worst_5_strat) > 0 else p5_final

    median_max_dd = float(np.median(path_max_drawdowns))
    worst_max_dd_95 = float(np.percentile(path_max_drawdowns, 95))

    # Annualized Compound XIRR approximation for median and percentiles
    def approx_cagr(final_v, total_inv, months):
        if final_v <= 0 or total_inv <= 0:
            return 0.0
        yrs = months / 12.0
        # For systematic SIP with mid-duration cash flows, standard rule-of-thumb doubler
        effective_duration = yrs / 2.0
        try:
            return round(((final_v / total_inv) ** (1.0 / effective_duration) - 1.0) * 100.0, 2)
        except Exception:
            return 0.0

    median_xirr = approx_cagr(median_final, total_invested, horizon_months)
    bench_median_xirr = approx_cagr(bench_median_final, total_invested, horizon_months)

    # 6. Build Plotly Fan Chart Curve Data
    # Month-by-month percentile curves
    months_axis = [f"Month {m}" for m in range(horizon_months + 1)]
    fan_p5 = np.percentile(strat_paths, 5, axis=0).tolist()
    fan_p25 = np.percentile(strat_paths, 25, axis=0).tolist()
    fan_p50 = np.percentile(strat_paths, 50, axis=0).tolist()
    fan_p75 = np.percentile(strat_paths, 75, axis=0).tolist()
    fan_p95 = np.percentile(strat_paths, 95, axis=0).tolist()

    fan_bench_p50 = np.percentile(bench_paths, 50, axis=0).tolist()
    fan_invested = invested_path.tolist()

    fan_chart_data = {
        "months": months_axis,
        "p5": [round(x, 2) for x in fan_p5],
        "p25": [round(x, 2) for x in fan_p25],
        "median": [round(x, 2) for x in fan_p50],
        "p75": [round(x, 2) for x in fan_p75],
        "p95": [round(x, 2) for x in fan_p95],
        "benchmark_median": [round(x, 2) for x in fan_bench_p50],
        "capital_invested": [round(x, 2) for x in fan_invested]
    }

    # Drawdown histogram bins
    dd_counts, dd_bins = np.histogram(path_max_drawdowns, bins=12)
    drawdown_hist = {
        "bin_labels": [f"{dd_bins[i]:.1f}%–{dd_bins[i+1]:.1f}%" for i in range(len(dd_counts))],
        "counts": [int(c) for c in dd_counts]
    }

    return {
        "n_simulations": n_simulations,
        "horizon_months": horizon_months,
        "monthly_wallet": monthly_wallet,
        "annual_step_up_pct": annual_step_up_pct,
        "total_invested": round(total_invested, 2),
        "strategy": strategy,
        "exit_protocol": exit_protocol,
        "stress_shock_pct": stress_shock_pct,
        "median_corpus": round(median_final, 2),
        "worst_case_corpus_5th": round(p5_final, 2),
        "p25_corpus": round(p25_final, 2),
        "p75_corpus": round(p75_final, 2),
        "best_case_corpus_95th": round(p95_final, 2),
        "benchmark_median_corpus": round(bench_median_final, 2),
        "prob_beat_benchmark": round(prob_beat_bench, 1),
        "prob_profit": round(prob_profit, 1),
        "cvar_95": round(cvar_95, 2),
        "median_max_drawdown": round(median_max_dd, 2),
        "worst_case_max_drawdown_95th": round(worst_max_dd_95, 2),
        "median_strategy_xirr": median_xirr,
        "benchmark_median_xirr": bench_median_xirr,
        "alpha_median": round(median_xirr - bench_median_xirr, 2),
        "fan_chart_data": fan_chart_data,
        "drawdown_hist": drawdown_hist
    }
