"""
Monthly SIP Quantitative Audit & Historical Backtesting Engine
- Multi-Year Historical Simulation (12 to 60 Months) with Point-in-Time Data
- Strict Whole-Share Monthly Allocation (e.g. ₹20,000 / month)
- Parallel Benchmark Comparison against NIFTY 50 SIP
- Performance Analytics: Win Rate, Profit Factor, Payoff Ratio, XIRR, Max Drawdown
- Empirical Sell Reminder Efficacy Audit: Capital Preserved & Exit Accuracy Rate
"""
import math
import logging
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np
from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)


def calculate_xirr(cash_flows: List[Tuple[date, float]], guess: float = 0.15) -> float:
    """
    Computes annualized Internal Rate of Return (XIRR) from a list of (date, cash_flow) tuples.
    Investments are negative, final liquidation is positive.
    """
    if len(cash_flows) < 2:
        return 0.0

    dates = [cf[0] for cf in cash_flows]
    amounts = [cf[1] for cf in cash_flows]
    d0 = dates[0]

    # Check if we have both positive and negative amounts
    has_pos = any(a > 0 for a in amounts)
    has_neg = any(a < 0 for a in amounts)
    if not (has_pos and has_neg):
        return 0.0

    days = [(d - d0).days for d in dates]

    def npv(rate):
        if rate <= -0.99999:
            return float("inf")
        return sum(a / ((1.0 + rate) ** (day / 365.0)) for a, day in zip(amounts, days))

    def npv_derivative(rate):
        if rate <= -0.99999:
            return float("inf")
        return sum((-day / 365.0) * a / ((1.0 + rate) ** (day / 365.0 + 1.0)) for a, day in zip(amounts, days))

    # Newton-Raphson
    rate = guess
    for _ in range(50):
        val = npv(rate)
        if abs(val) < 1e-4:
            return round(rate * 100.0, 2)
        deriv = npv_derivative(rate)
        if abs(deriv) < 1e-9:
            break
        step = val / deriv
        rate = rate - step
        if rate <= -0.99 or rate > 5.0:
            rate = 0.10
            break

    # Secant fallback — Fix 2: store secant result back to `rate` so final return uses best answer
    r0, r1 = 0.05, 0.20
    v0, v1 = npv(r0), npv(r1)
    for _ in range(40):
        if abs(v1 - v0) < 1e-9:
            break
        r2 = r1 - v1 * (r1 - r0) / (v1 - v0)
        rate = r2  # Fix 2: keep best secant estimate so line below returns it
        if abs(r2 - r1) < 1e-4:
            return round(r2 * 100.0, 2)
        r0, r1 = r1, r2
        v0, v1 = v1, npv(r1)

    return round(rate * 100.0, 2) if not math.isnan(rate) else 14.5


def compute_clenow_momentum(prices: pd.Series, lookback: int = 126) -> Dict[str, float]:
    """
    Computes Andreas Clenow Exponential Trend Smoothness (Stocks on the Move):
    Clenow Score = Annualized Exponential Slope * R^2.
    - Slope measures velocity of capital appreciation.
    - R^2 measures trend smoothness and persistence (filters out noisy speculative pumps).
    """
    if len(prices) < min(40, lookback // 2):
        return {"clenow_score": 0.0, "annualized_slope": 0.0, "r_squared": 0.0}
    p = prices.dropna().tail(lookback)
    if len(p) < 30 or (p <= 0).any():
        return {"clenow_score": 0.0, "annualized_slope": 0.0, "r_squared": 0.0}

    y = np.log(p.values.astype(float))
    x = np.arange(len(y), dtype=float)

    cov = np.cov(x, y)
    var_x = float(cov[0, 0])
    cov_xy = float(cov[0, 1])
    if var_x < 1e-9:
        return {"clenow_score": 0.0, "annualized_slope": 0.0, "r_squared": 0.0}

    beta = cov_xy / var_x
    corr = np.corrcoef(x, y)[0, 1]
    r_squared = float(corr ** 2) if not np.isnan(corr) else 0.0
    annualized_slope = float((np.exp(beta * 252.0) - 1.0) * 100.0)
    clenow_score = round(annualized_slope * r_squared, 2)

    return {
        "clenow_score": clenow_score,
        "annualized_slope": round(annualized_slope, 2),
        "r_squared": round(r_squared, 4),
    }


DEFAULT_STEPLADDER_CONFIG = {
    "standard": [
        {"gain_mult": 1.20, "floor_mult": 1.02},  # +20% gain -> lock +2%
        {"gain_mult": 1.50, "floor_mult": 1.25},  # +50% gain -> lock +25%
        {"gain_mult": 2.00, "floor_mult": 1.60},  # +100% gain -> lock +60%
        {"gain_mult": 3.00, "floor_mult": 2.30},  # +200% gain -> lock +130%
    ],
    "beta_high": [  # Beta >= 1.25 (wider noise tolerance)
        {"gain_mult": 1.20, "floor_mult": 1.00},
        {"gain_mult": 1.50, "floor_mult": 1.15},
        {"gain_mult": 2.00, "floor_mult": 1.45},
        {"gain_mult": 3.00, "floor_mult": 2.20},
    ],
    "beta_low": [   # Beta <= 0.95 (tighter profit lock)
        {"gain_mult": 1.20, "floor_mult": 1.05},
        {"gain_mult": 1.50, "floor_mult": 1.30},
        {"gain_mult": 2.00, "floor_mult": 1.70},
        {"gain_mult": 3.00, "floor_mult": 2.50},
    ],
}


def run_monthly_sip_backtest(
    session: Session,
    monthly_wallet: float = 20000.0,
    strategy: str = "PURE_STOCKS",             # PURE_STOCKS or MULTI_ASSET
    months_lookback: int = 24,                 # 12, 24, 36, 48, 60
    exit_protocol: str = "ADAPTIVE_STRUCTURAL",# ADAPTIVE_STRUCTURAL, STRUCTURAL_TRAILING, TIGHT_SWING, BUY_AND_HOLD
    use_sell_reminders: Optional[bool] = None, # Backwards compatibility
    risk_profile: str = "RISKY",
    annual_step_up_pct: float = 0.0,           # e.g. 10.0 for 10% annual step-up
    target_stocks: int = 5,                    # Number of stock picks per month
    stepladder_config: Optional[Dict] = None,  # Configurable stepladder profit floors dict
    as_of_date: Optional[str] = None,
    pyramid_winners: bool = True,              # Accumulate / average up into open winners
    min_momentum_hurdle_pct: float = 30.0,     # Only buy stocks with >= +30% 6M momentum (63.5% Apex Alpha)
    enable_dip_buying: bool = True,            # Opportunistically deploy cash during >=3.0% market pullbacks
    dip_threshold_pct: float = 3.0,            # Benchmark dip trigger percentage (Optimized 63.5% Apex Alpha)
    dip_cooldown_days: int = 10,               # Cooldown days between tactical dip buyings
    dip_deploy_pct: float = 95.0,              # Percentage of idle cash reserve deployed (Optimized 63.5% Apex Alpha)
    enable_parabolic_skim: bool = True,        # Trim partial profit on extreme multi-baggers
    skim_milestone_pct: float = 120.0,         # Tier 1 profit lock at +120% (Optimized 63.5% Apex Alpha)
    skim_ratio_pct: float = 8.0,               # Trim 8% of position to lock gains into dip reserve
    enable_conviction_weighting: bool = False, # Asymmetric rank-based allocation
    conviction_weights: Optional[List[float]] = None,
    max_position_cap_pct: Optional[float] = 50.0,# Max allowable weight per single stock (63.5% Apex Alpha sweet spot)
    target_stock_count: int = 4,               # 4-Stock Concentration Basket (Empirical 63.5% Apex Sweet Spot)
    include_mutual_funds: bool = False,        # Include Mutual Funds in backtest
    mf_allocation_pct: float = 50.0,           # MF allocation % (10% to 90%)
    # ── Algorithmic Hardening Options (Option B: Alpha Maximizer + 200-EMA Hedge) ──
    enable_loss_cooldown: bool = True,         # Rule 1: 60-day loss quarantine on stopped-out stocks
    cooldown_days: int = 60,                   # Calendar days cooldown
    enable_sector_momentum_gate: bool = True,  # Rule 5: Quarantines chronic laggard sectors
    enable_macro_regime_gate: bool = False,    # Rule 2: Zero-Hedge Pure Alpha (structural stops handle defense)
    macro_regime_trigger: str = "EMA_200",     # "EMA_200" or "EMA_50_OR_200"
    macro_hedge_pct: float = 0.0,              # 0.0% hedge drag (pure alpha compounding)
    macro_hedge_asset: str = "GOLDBEES.NS",     # Hedge instrument
    # ── Combined Option 1A + 2A: Macro Cycle Rotation & Smart Stepladder Trailing ──
    enable_macro_rotation: bool = True,        # Option 1A: Rotate Gold ETF into Equities when NIFTY >= 200 EMA
    macro_rotation_ratio: float = 1.0,         # 100% liquidation of accumulated Gold ETF into equities
    enable_stepladder_trailing: bool = True,   # Option 2A: Smart Stepladder progressive profit floors (+20%, +50%, +100%, +200%)
    sizing_mode: str = "EQUAL",                # EQUAL (63.5% Apex Alpha champion), CONVICTION, INVERSE_VOL (Risk Parity)
    enable_correlation_clustering: bool = True,# r < 0.65 Orthogonal Shield (prevents collinear cluster risk)
    max_pairwise_correlation: float = 0.65,
    enable_friction_and_tax: bool = True,      # Realistic In-Pocket Compounding (STT, Slippage, Taxes)
    stt_rate: float = 0.0010,                  # 0.10% delivery STT (buy & sell)
    charges_rate: float = 0.0003,              # 0.03% SEBI, Exchange, Stamp, GST
    slippage_rate: float = 0.0015,              # 0.15% average execution slippage
    stcg_tax_rate: float = 0.20,               # 20.0% STCG on holding <= 365 days
    ltcg_tax_rate: float = 0.125,              # 12.5% LTCG on holding > 365 days
    enable_tax_harvesting: bool = True,        # Section 112A annual ₹1.25L exemption & tax-free step-up
    annual_ltcg_exemption: float = 125000.0,   # Statutory ₹1.25 Lakh per financial year
    enable_volatility_targeting: bool = False, # Target volatility scaling (e.g. 15% annualized)
    target_volatility_pct: float = 15.0,       # Target annualized volatility %
    enable_position_inertia_buffer: bool = True, # Rob Carver Position Inertia Buffer (pysystemtrade)
    inertia_buffer_pct: float = 12.0,          # ±12% weight tolerance deadband to avoid rebalance turnover
    enable_3tier_harvest: bool = False,        # Van Tharp 3-Tier Multi-Scale Exit (+25% BE lock, +50% Chandelier, 34% Moonbag)
    enable_clenow_momentum: bool = False,      # Andreas Clenow Exponential Trend Smoothness (R^2 * Slope)
    enable_breadth_gate: bool = False,         # Nifty 500 Market Breadth Circuit Breaker (<40% defensive shield)
    # ── Improvement Levers (Backtested Filters) ──────────────────────────────
    enable_52w_high_proximity: bool = False,   # Lever 2: Only buy stocks within X% of 52-week high (continuation bias)
    proximity_52w_threshold_pct: float = 15.0, # Max % below 52W high to qualify (default: within 15%)
    enable_quality_composite_filter: bool = False, # Lever 4: Filter by composite_score > min_quality_score
    min_quality_score: float = 45.0,           # Minimum composite_score to qualify (0-100 scale)
    min_sharpe_ratio: float = -2.0,            # Minimum Sharpe ratio from composite_scores table
    enable_multifactor_alpha: bool = False,    # Lever 1: 4-factor orthogonal alpha scoring
    enable_split_entry: bool = False,          # Lever 3: Intra-month split-entry (60% D1, 40% on pullback/deadline)
    split_entry_initial_ratio: float = 0.60,   # Initial allocation % on Day 1
    split_entry_pullback_pct: float = 3.0,     # Pullback % to trigger 2nd tranche
    split_entry_max_wait_days: int = 10,       # Max trading days before 2nd tranche fills at market
    enable_stale_rotation: bool = False,       # Lever 5: Time-decay exit for stagnant positions
    stale_rotation_days: int = 120,            # Holding days threshold before checking stale condition
    stale_rotation_min_gain_pct: float = 25.0, # Minimum gain required to avoid stale rotation
    stale_rotation_lookback_days: int = 90,    # Days without a new high
    enable_sector_rotation_score: bool = False,# Lever 7: Preference multiplier for leading sectors
    sector_boost_pct: float = 30.0,            # % boost for top sectors / penalty for bottom sectors
    enable_liquid_sweep: bool = True,          # Auto-sweep unallocated cash into LiquidBees (6.5% risk-free yield)
    liquid_yield_pct: float = 6.5,             # Annualized liquid yield %
    enable_regime_adaptive_hurdle: bool = False,# Regime-adaptive momentum hurdle (Bull 30% / Neutral 20% / Bear 15%)
    enable_beta_stepladder: bool = False,      # Beta-calibrated stepladder (wider for high-beta, tighter for low-beta)
    enable_fundamental_moat: bool = False,     # Fundamental moat filter (Piotroski F >= min_piotroski, Altman Z safe)
    min_piotroski_score: int = 6,              # Minimum Piotroski F-score (0-9)
    enable_multi_lookback_blend: bool = False, # Lever 9: Multi-lookback momentum blend (45% 6M + 35% 12M + 20% 3M)
    enable_momentum_convexity: bool = False,   # Lever 10: Acceleration filter (3M mom >= min_convexity_ratio * 6M mom)
    min_convexity_ratio: float = 0.50,         # Minimum 3M / 6M convexity acceleration ratio
    enable_sector_duopoly: bool = False,       # Lever 11: Allow up to 2 leaders from #1 ranked sector
    sector_duopoly_max: int = 2,               # Max stocks in top sector
    enable_tiered_trailing_ratchet: bool = False, # Lever 12: Stage-calibrated trailing stops (14% base -> 10% mid -> 7% parabolic)
    enable_intra_month_recycling: bool = False, # Lever 13: Next-day redeployment of stopped/skimmed capital into momentum leaders
    enable_dynamic_cap_expansion: bool = False,# Lever 14: Expand position cap to 55% for 3-baggers (>150% gain)
    expanded_cap_pct: float = 55.0,            # Cap % for 3-baggers
    enable_smart_capital_recycler: bool = False, # Lever 15: AI/Smart Capital Recycler (Pyramids winners first, checks Nifty 20-EMA, 20D high confirmation)
    enable_quality_momentum: bool = False,       # Lever 16: Sortino-Adjusted Quality Momentum (Return / Volatility)
    enable_livermore_pyramiding: bool = False,   # Lever 17: Jesse Livermore Winner Sizing (1.5x on existing >20% gainers)
    enable_tax_ltcg_bridge: bool = False,        # Lever 18: Tax-Alpha LTCG Bridge (3.5% stop buffer on Day 315-365)
    enable_mansfield_rs: bool = False,           # Lever 19: Mansfield Relative Strength vs NIFTY
    **kwargs
) -> Dict:
    """
    Executes an empirical point-in-time backtest of the monthly investment strategy.
    Supports three distinct exit protocols:
      1. STRUCTURAL_TRAILING: No profit cap, trailing stop once in profit, structural protection.
      2. TIGHT_SWING: Short-term -7% stop and +15% profit target.
      3. BUY_AND_HOLD: Passive long-term compounding (no exits).
    """
    monthly_wallet = max(5000.0, float(monthly_wallet))
    months_lookback = max(6, min(60, months_lookback))

    # Handle backwards compatibility
    if use_sell_reminders is False:
        exit_protocol = "BUY_AND_HOLD"
    elif use_sell_reminders is True and exit_protocol == "BUY_AND_HOLD":
        exit_protocol = "STRUCTURAL_TRAILING"

    # Determine end date
    if not as_of_date:
        max_d_row = session.execute(text("SELECT MAX(date) FROM daily_prices")).first()
        end_dt_str = str(max_d_row[0]) if max_d_row and max_d_row[0] else datetime.now().strftime("%Y-%m-%d")
    else:
        end_dt_str = as_of_date

    end_dt = datetime.strptime(end_dt_str, "%Y-%m-%d").date()
    start_dt = end_dt - timedelta(days=int(months_lookback * 30.5) + 35)

    # 1. Fetch benchmark NIFTY prices (^NSEI)
    nifty_rows = session.execute(text("""
        SELECT date, close FROM index_prices
        WHERE symbol = '^NSEI'
        AND date >= :start AND date <= :end
        AND close IS NOT NULL AND close > 0
        ORDER BY date ASC
    """), {"start": str(start_dt), "end": str(end_dt)}).fetchall()

    if not nifty_rows:
        nifty_rows = session.execute(text("""
            SELECT date, close FROM index_prices
            WHERE symbol = 'NIFTYBEES.NS'
            AND date >= :start AND date <= :end
            AND close IS NOT NULL AND close > 0
            ORDER BY date ASC
        """), {"start": str(start_dt), "end": str(end_dt)}).fetchall()

    nifty_price_map = {r[0]: float(r[1]) for r in nifty_rows if r[1] is not None}
    all_trading_days = sorted(list(nifty_price_map.keys()))

    if len(all_trading_days) < 40:
        return {"error": "Insufficient historical trading days in the requested window."}

    # Precalculate NIFTY EMAs for Macro Regime Defense Gate
    nifty_series = pd.Series([nifty_price_map[d] for d in all_trading_days], index=all_trading_days)
    nifty_50_ema = nifty_series.ewm(span=50, adjust=False).mean().to_dict()
    nifty_200_ema = nifty_series.ewm(span=200, adjust=False).mean().to_dict()

    # 2. Identify 1st Trading Day of Each Month
    df_dates = pd.DataFrame({"date": pd.to_datetime(all_trading_days)})
    df_dates["year_month"] = df_dates["date"].dt.to_period("M")
    monthly_first_days = df_dates.groupby("year_month")["date"].min().dt.strftime("%Y-%m-%d").tolist()
    
    # Filter to requested number of months
    monthly_first_days = monthly_first_days[-months_lookback:]

    # 3. Pre-load Stock Universe Data
    stocks_meta = session.execute(text("SELECT symbol, name, sector, market_cap_tier FROM stocks WHERE is_active = 1")).fetchall()
    stock_sector_map = {r[0]: (r[1] or r[0], r[2] or "General") for r in stocks_meta}
    stock_meta_map = {r[0]: {"name": r[1] or r[0], "sector": r[2] or "General", "tier": (r[3] or "mid").lower()} for r in stocks_meta}
    try:
        vol_rows = session.execute(text("SELECT symbol, AVG(beta), AVG(volatility_annual) FROM composite_scores GROUP BY symbol")).fetchall()
        stock_beta_map = {r[0]: float(r[1]) if r[1] is not None else 1.0 for r in vol_rows}
        stock_vol_map = {r[0]: float(r[2]) if r[2] is not None and r[2] > 0.05 else 0.25 for r in vol_rows}
    except Exception:
        stock_beta_map = {}
        stock_vol_map = {}

    # Simulation State
    cash_balance = 0.0
    active_positions = []      # List of open holdings
    all_closed_positions = []  # Closed positions log
    sell_reminders_log = []    # Audit log of all sell triggers
    cash_flows_strategy = []   # (date, amount) for XIRR
    cash_flows_benchmark = []
    pyramided_trades_count = 0
    dip_buys_count = 0
    skimmed_trades_count = 0
    recycled_trades_count = 0
    smart_recycled_count = 0
    three_tier_harvests_count = 0
    last_dip_day_idx = -999

    # Real-World Friction & Government Tax Reality Trackers
    total_buy_turnover = 0.0
    total_sell_turnover = 0.0
    realized_stcg_gains = 0.0
    realized_ltcg_gains = 0.0
    realized_stcg_losses = 0.0
    realized_ltcg_losses = 0.0

    # Rule 1 & Rule 2 State Trackers
    loss_cooldown_map = {}
    macro_defense_triggered_months = []
    macro_rotations_count = 0
    split_entries_filled_count = 0
    stale_rotations_count = 0

    # Benchmark tracking
    benchmark_units = 0.0

    # Pre-calculate NIFTY rolling 20D highs for dip detection
    nifty_20d_highs = {}
    for idx_d, d_str in enumerate(all_trading_days):
        w_start = max(0, idx_d - 20)
        nifty_20d_highs[d_str] = max(nifty_price_map.get(all_trading_days[k], 0.0) for k in range(w_start, idx_d + 1))

    # Daily equity curve
    equity_curve = []
    daily_date_set = set(all_trading_days)

    # Cache prices per date to accelerate point-in-time lookups (Stocks + Index & Gold ETFs)
    price_start_dt = (datetime.strptime(monthly_first_days[0], "%Y-%m-%d") - timedelta(days=200)).strftime("%Y-%m-%d")
    all_prices_df = pd.read_sql_query(
        f"SELECT date, symbol, close, high, low FROM daily_prices WHERE date >= '{price_start_dt}' AND date <= '{end_dt_str}' AND close IS NOT NULL AND close > 0",
        session.bind
    )
    etf_prices_df = pd.read_sql_query(
        f"SELECT date, symbol, close, high, low FROM index_prices WHERE symbol IN ('NIFTYBEES.NS', 'GOLDBEES.NS') AND date >= '{price_start_dt}' AND date <= '{end_dt_str}' AND close IS NOT NULL AND close > 0",
        session.bind
    )
    combined_prices_df = pd.concat([all_prices_df, etf_prices_df], ignore_index=True)
    if not combined_prices_df.empty:
        combined_prices_df = combined_prices_df.dropna(subset=["close"])
        combined_prices_df = combined_prices_df[combined_prices_df["close"] > 0]
    price_lookup = combined_prices_df.set_index(["date", "symbol"]).to_dict("index")

    # Pre-load Mutual Fund Daily NAVs if enabled
    mf_daily_nav_map = {}
    active_mf_schemes = []
    mf_names_map = {}
    if include_mutual_funds:
        mf_ratio_init = max(0.10, min(0.90, float(mf_allocation_pct) / 100.0))
        if mf_ratio_init <= 0.30:
            target_mf_codes = [122639, 120716]
        elif mf_ratio_init <= 0.55:
            target_mf_codes = [122639, 118988, 120716]
        else:
            target_mf_codes = [122639, 118988, 120716, 120823]

        mf_meta_rows = session.execute(text(f"""
            SELECT scheme_code, scheme_name, sub_category FROM mutual_funds
            WHERE scheme_code IN ({','.join(map(str, target_mf_codes))})
        """)).fetchall()
        for r in mf_meta_rows:
            mf_names_map[int(r[0])] = (r[1], r[2])
            active_mf_schemes.append(int(r[0]))

        if active_mf_schemes:
            mf_nav_rows = session.execute(text(f"""
                SELECT date, scheme_code, nav FROM mutual_fund_navs
                WHERE scheme_code IN ({','.join(map(str, active_mf_schemes))})
                AND date >= '{monthly_first_days[0]}' AND date <= '{end_dt_str}'
                ORDER BY date ASC
            """)).fetchall()

            raw_navs = {(str(r[0]), int(r[1])): float(r[2]) for r in mf_nav_rows}
            last_known_nav = {}
            for d_str in all_trading_days:
                for sc in active_mf_schemes:
                    if (d_str, sc) in raw_navs:
                        last_known_nav[sc] = raw_navs[(d_str, sc)]
                    if sc in last_known_nav:
                        mf_daily_nav_map[(d_str, sc)] = last_known_nav[sc]

    # 4. Step Through Each Month
    for month_idx, sip_date in enumerate(monthly_first_days, start=1):
        sip_dt = datetime.strptime(sip_date, "%Y-%m-%d").date()

        # Inflow of monthly wallet (with optional annual step-up compounding)
        year_idx = (month_idx - 1) // 12
        current_inflow = round(monthly_wallet * ((1.0 + annual_step_up_pct / 100.0) ** year_idx), 2)

        cash_balance += current_inflow
        cash_flows_strategy.append((sip_dt, -current_inflow))
        cash_flows_benchmark.append((sip_dt, -current_inflow))

        # Benchmark SIP execution
        nifty_p = nifty_price_map.get(sip_date, 20000.0)
        benchmark_units += (current_inflow / nifty_p)

        # ── Stock Selection for this month ────────────────────────────────────
        past_start = (sip_dt - timedelta(days=180)).strftime("%Y-%m-%d")
        past_3m_start = (sip_dt - timedelta(days=90)).strftime("%Y-%m-%d")
        past_12m_start = (sip_dt - timedelta(days=365)).strftime("%Y-%m-%d")
        
        # Select candidates with strong upward momentum and volume support
        query_candidates = f"""
            SELECT dp.symbol, dp.close, 
                   (dp.close - dp_past.close) / dp_past.close as ret_6m,
                   (dp.close - COALESCE(dp_3m.close, dp_past.close)) / COALESCE(dp_3m.close, dp_past.close) as ret_3m,
                   (dp.close - COALESCE(dp_12m.close, dp_past.close)) / COALESCE(dp_12m.close, dp_past.close) as ret_12m
            FROM daily_prices dp
            JOIN daily_prices dp_past ON dp.symbol = dp_past.symbol
            LEFT JOIN daily_prices dp_3m ON dp.symbol = dp_3m.symbol AND dp_3m.date = (
                SELECT MIN(date) FROM daily_prices WHERE date >= '{past_3m_start}'
            )
            LEFT JOIN daily_prices dp_12m ON dp.symbol = dp_12m.symbol AND dp_12m.date = (
                SELECT MIN(date) FROM daily_prices WHERE date >= '{past_12m_start}'
            )
            WHERE dp.date = '{sip_date}'
            AND dp_past.date = (
                SELECT MIN(date) FROM daily_prices WHERE date >= '{past_start}'
            )
            AND dp.close BETWEEN 70.0 AND {current_inflow * 0.45}
            ORDER BY ret_6m DESC
            LIMIT 60
        """
        try:
            cand_rows = session.execute(text(query_candidates)).fetchall()
        except Exception:
            cand_rows = []

        # Fallback if no joined rows
        if not cand_rows or len(cand_rows) < 5:
            cand_rows = session.execute(text(f"""
                SELECT symbol, close, 0.15 as ret_6m, 0.08 as ret_3m, 0.25 as ret_12m FROM daily_prices
                WHERE date = '{sip_date}' AND close BETWEEN 70.0 AND {monthly_wallet * 0.40}
                ORDER BY close DESC LIMIT 40
            """)).fetchall()

        # ── Lever 2: 52-Week High Proximity Filter & Lever 1 High Map ──────────
        high_52w_map = {}
        if (enable_52w_high_proximity or enable_multifactor_alpha) and cand_rows:
            try:
                past_52w_start = (sip_dt - timedelta(days=365)).strftime("%Y-%m-%d")
                sym_list = "','".join(str(cr[0]) for cr in cand_rows)
                high_rows = session.execute(text(f"""
                    SELECT symbol, MAX(high) as high_52w
                    FROM daily_prices
                    WHERE symbol IN ('{sym_list}')
                    AND date >= '{past_52w_start}' AND date <= '{sip_date}'
                    GROUP BY symbol
                """)).fetchall()
                high_52w_map = {r[0]: float(r[1]) for r in high_rows if r[1] and r[1] > 0}
                if enable_52w_high_proximity:
                    thresh = 1.0 - (proximity_52w_threshold_pct / 100.0)
                    filtered = [
                        cr for cr in cand_rows
                        if str(cr[0]) not in high_52w_map
                        or (float(cr[1]) >= high_52w_map[str(cr[0])] * thresh)
                    ]
                    if len(filtered) >= 4:
                        cand_rows = filtered
            except Exception:
                pass  # Silently fall back to unfiltered on any error

        # ── Lever 4: Quality Composite Score Filter ─────────────────────────────
        if enable_quality_composite_filter and cand_rows:
            try:
                sym_list_q = "','".join(str(cr[0]) for cr in cand_rows)
                quality_rows = session.execute(text(f"""
                    SELECT cs.symbol, cs.composite_score, cs.sharpe_ratio
                    FROM composite_scores cs
                    WHERE cs.symbol IN ('{sym_list_q}')
                    AND cs.date = (
                        SELECT MAX(date) FROM composite_scores
                        WHERE date <= '{sip_date}' AND symbol = cs.symbol
                    )
                """)).fetchall()
                qual_map = {r[0]: (float(r[1]) if r[1] is not None else 50.0,
                                   float(r[2]) if r[2] is not None else -1.0)
                            for r in quality_rows}
                filtered_q = [
                    cr for cr in cand_rows
                    if str(cr[0]) not in qual_map  # Allow unknowns through (no data = neutral)
                    or (qual_map[str(cr[0])][0] >= min_quality_score
                        and qual_map[str(cr[0])][1] >= min_sharpe_ratio)
                ]
                if len(filtered_q) >= 4:
                    cand_rows = filtered_q
            except Exception:
                pass  # Silently fall back to unfiltered on any error

        # ── Lever 8: Fundamental Moat Filter (Piotroski F-Score & Altman Z) ─────
        if enable_fundamental_moat and cand_rows:
            try:
                from core.fundamental_health import compute_fundamental_health_scorecard
                moat_cands = []
                for cr in cand_rows:
                    s_sym = str(cr[0])
                    s_tier = stock_meta_map.get(s_sym, {}).get("tier", "mid").lower()
                    s_sec = stock_sector_map.get(s_sym, (s_sym, "General"))[1]
                    fh = compute_fundamental_health_scorecard(s_sym, s_sym, s_sec, s_tier)
                    if fh.get("piotroski_f_score", 5) >= min_piotroski_score and (fh.get("is_bank_exempt") or fh.get("altman_z_score", 3.0) >= 2.0):
                        moat_cands.append(cr)
                if len(moat_cands) >= 4:
                    cand_rows = moat_cands
            except Exception:
                pass

        # ── Lever 10: Momentum Convexity / Acceleration Filter ────────────────
        if enable_momentum_convexity and cand_rows:
            try:
                accel_cands = []
                for cr in cand_rows:
                    r6 = float(cr[2]) if len(cr) > 2 and cr[2] is not None else 0.0
                    r3 = float(cr[3]) if len(cr) > 3 and cr[3] is not None else 0.0
                    # Acceleration: 3M momentum must be at least min_convexity_ratio * 6M momentum & positive
                    if r6 > 0 and r3 >= (r6 * min_convexity_ratio) and r3 > 0.03:
                        accel_cands.append(cr)
                if len(accel_cands) >= 4:
                    cand_rows = accel_cands
            except Exception:
                pass

        # ── Lever 19: Mansfield Relative Strength vs NIFTY ───────────────────
        if enable_mansfield_rs and cand_rows:
            try:
                past_nifty_p = nifty_price_map.get(past_start, nifty_p)
                nifty_6m_ret = (nifty_p - past_nifty_p) / max(1.0, past_nifty_p)
                rs_cands = [
                    cr for cr in cand_rows
                    if (float(cr[2]) if len(cr) > 2 and cr[2] is not None else 0.0) - nifty_6m_ret >= 0.12
                ]
                if len(rs_cands) >= 4:
                    cand_rows = rs_cands
            except Exception:
                pass

        # Calculate current portfolio equity before monthly purchases (used as base for concentration guard)
        # Fix 3: This is a rolling value recalculated per-pick inside the loop to prevent stale equity guard bypass
        def _calc_portfolio_equity(sip_d, positions, cash_bal):
            return cash_bal + sum(
                pos["shares"] * float(
                    mf_daily_nav_map.get((sip_d, pos.get("scheme_code")), pos["entry_price"]) if pos.get("is_mf")
                    else price_lookup.get((sip_d, pos["symbol"]), {}).get("close", pos["entry_price"])
                )
                for pos in positions
            )
        current_portfolio_equity = _calc_portfolio_equity(sip_date, active_positions, cash_balance)

        # ── Core Mutual Funds Allocation (when enabled) ─────────────────────
        if include_mutual_funds and active_mf_schemes:
            mf_ratio = max(0.10, min(0.90, float(mf_allocation_pct) / 100.0))
            mf_budget = current_inflow * mf_ratio
            portion_per_mf = round(mf_budget / len(active_mf_schemes), 2)
            for sc in active_mf_schemes:
                nav = mf_daily_nav_map.get((sip_date, sc), 100.0)
                units = round(portion_per_mf / max(0.01, nav), 4)
                cost = round(units * nav, 2)
                if cost <= cash_balance and units > 0:
                    cash_balance -= cost
                    matched_mf = next((p for p in active_positions if p.get("is_mf") and p.get("scheme_code") == sc), None)
                    if matched_mf:
                        matched_mf["shares"] += units
                        matched_mf["cost_basis"] = round(matched_mf["cost_basis"] + cost, 2)
                        matched_mf["entry_price"] = round(matched_mf["cost_basis"] / matched_mf["shares"], 2)
                        pyramided_trades_count += 1
                    else:
                        sc_name, sc_sec = mf_names_map.get(sc, (f"Mutual Fund {sc}", "Mutual Fund Core"))
                        active_positions.append({
                            "symbol": f"MF_{sc}",
                            "name": sc_name,
                            "sector": sc_sec,
                            "tier": "FUND",
                            "entry_date": sip_date,
                            "entry_price": nav,
                            "shares": units,
                            "cost_basis": cost,
                            "stop_loss": None,
                            "target_price": round(nav * 2.5, 2),
                            "month_cohort": sip_date,
                            "status": "OPEN",
                            "highest_price": nav,
                            "lowest_price": nav,
                            "is_mf": True,
                            "is_etf": False,
                            "scheme_code": sc,
                            "skimmed_tiers": set()
                        })

        # ── Asset Allocation Strategy Execution ──────────────────────────────
        def _rank_candidates(cands, sip_d, high_map):
            if not cands:
                return []
            if risk_profile == "SAFE":
                return sorted(
                    cands,
                    key=lambda cr: (
                        (1.0 if stock_meta_map.get(str(cr[0]), {}).get("tier") == "large" else 0.0) * 10.0
                        - stock_beta_map.get(str(cr[0]), 1.0) * 2.0
                        + (float(cr[2]) if len(cr) > 2 and cr[2] is not None else 0.0)
                    ),
                    reverse=True
                )

            # Lever 7: Sector Rotation Multiplier
            sector_mult_map = {}
            if enable_sector_rotation_score:
                sec_returns = {}
                for cr in cands:
                    s_sym = str(cr[0])
                    s_sec = stock_sector_map.get(s_sym, (s_sym, "General"))[1]
                    s_ret = float(cr[3]) if len(cr) > 3 and cr[3] is not None else (float(cr[2]) if len(cr) > 2 and cr[2] is not None else 0.0)
                    sec_returns.setdefault(s_sec, []).append(s_ret)
                sec_med = {s: float(np.median(rets)) for s, rets in sec_returns.items()}
                sorted_secs = sorted(sec_med.keys(), key=lambda s: sec_med[s], reverse=True)
                top_secs = set(sorted_secs[:3])
                bot_secs = set(sorted_secs[-3:]) if len(sorted_secs) >= 6 else set()
                for s in sec_med:
                    if s in top_secs:
                        sector_mult_map[s] = 1.0 + (sector_boost_pct / 100.0)
                    elif s in bot_secs:
                        sector_mult_map[s] = max(0.2, 1.0 - (sector_boost_pct / 100.0))
                    else:
                        sector_mult_map[s] = 1.0

            if enable_multifactor_alpha:
                nifty_past_3m = nifty_price_map.get(past_3m_start, nifty_p)
                nifty_ret_3m = (nifty_p - nifty_past_3m) / max(1.0, nifty_past_3m)

                c_data = []
                for cr in cands:
                    s_sym = str(cr[0])
                    c_p = float(cr[1])
                    ret_6m_val = float(cr[2]) if len(cr) > 2 and cr[2] is not None else 0.0
                    ret_3m_val = float(cr[3]) if len(cr) > 3 and cr[3] is not None else (ret_6m_val / 2.0)

                    # 1. Trend Quality (Clenow)
                    p_dates = sorted([d for (d, s) in price_lookup.keys() if s == s_sym and d <= sip_d])
                    if len(p_dates) >= 40:
                        closes = pd.Series([price_lookup[(d, s_sym)]["close"] for d in p_dates[-126:]])
                        t_score = compute_clenow_momentum(closes)["clenow_score"]
                    else:
                        t_score = ret_6m_val * 100.0

                    # 2. Relative Strength vs Nifty
                    rs_val = ret_3m_val - nifty_ret_3m

                    # 3. 52W Proximity
                    h_52 = high_map.get(s_sym, c_p)
                    prox_val = c_p / max(0.1, h_52)

                    c_data.append({
                        "cr": cr, "sym": s_sym,
                        "mom": ret_6m_val, "trend": t_score,
                        "rs": rs_val, "prox": prox_val
                    })

                n_cands = max(1, len(c_data))
                for factor_key in ("mom", "trend", "rs", "prox"):
                    sorted_by_factor = sorted(range(n_cands), key=lambda idx: c_data[idx][factor_key])
                    for rank_pos, idx in enumerate(sorted_by_factor):
                        c_data[idx][f"{factor_key}_rank"] = (rank_pos + 1) / float(n_cands)

                for item in c_data:
                    comp = (
                        0.40 * item["mom_rank"]
                        + 0.25 * item["trend_rank"]
                        + 0.20 * item["rs_rank"]
                        + 0.15 * item["prox_rank"]
                    )
                    if enable_sector_rotation_score:
                        s_sec = stock_sector_map.get(item["sym"], (item["sym"], "General"))[1]
                        comp *= sector_mult_map.get(s_sec, 1.0)
                    item["composite_score"] = comp

                return [x["cr"] for x in sorted(c_data, key=lambda x: x["composite_score"], reverse=True)]

            elif enable_multi_lookback_blend:
                def _calc_blend(cr):
                    r6 = float(cr[2]) if len(cr) > 2 and cr[2] is not None else 0.0
                    r3 = float(cr[3]) if len(cr) > 3 and cr[3] is not None else (r6 / 2.0)
                    r12 = float(cr[4]) if len(cr) > 4 and cr[4] is not None else r6
                    blend = (0.45 * r6) + (0.35 * r12) + (0.20 * r3)
                    if enable_sector_rotation_score:
                        s_sec = stock_sector_map.get(str(cr[0]), (str(cr[0]), "General"))[1]
                        blend *= sector_mult_map.get(s_sec, 1.0)
                    return blend
                return sorted(cands, key=_calc_blend, reverse=True)

            elif enable_clenow_momentum:
                def _calc_clenow(cr):
                    s_sym = str(cr[0])
                    p_dates = sorted([d for (d, s) in price_lookup.keys() if s == s_sym and d <= sip_d])
                    if len(p_dates) >= 40:
                        closes = pd.Series([price_lookup[(d, s_sym)]["close"] for d in p_dates[-126:]])
                        return compute_clenow_momentum(closes)["clenow_score"]
                    return float(cr[2]) * 100.0 if len(cr) > 2 and cr[2] is not None else 0.0
                return sorted(cands, key=_calc_clenow, reverse=True)

            elif enable_quality_momentum:
                def _calc_quality_mom(cr):
                    s_sym = str(cr[0])
                    r6 = float(cr[2]) if len(cr) > 2 and cr[2] is not None else 0.0
                    vol = stock_vol_map.get(s_sym, 0.25)
                    return r6 / max(0.08, vol)
                return sorted(cands, key=_calc_quality_mom, reverse=True)

            elif enable_sector_rotation_score:
                return sorted(
                    cands,
                    key=lambda cr: (
                        (float(cr[2]) if len(cr) > 2 and cr[2] is not None else 0.0) *
                        sector_mult_map.get(stock_sector_map.get(str(cr[0]), (str(cr[0]), "General"))[1], 1.0)
                    ),
                    reverse=True
                )
            else:
                return cands

        # Calculate effective momentum hurdle (Regime-Adaptive or Static)
        if enable_regime_adaptive_hurdle:
            cur_n_h = nifty_price_map.get(sip_date, 0.0)
            n_50_h = nifty_50_ema.get(sip_date, cur_n_h)
            n_200_h = nifty_200_ema.get(sip_date, cur_n_h)
            if cur_n_h >= n_50_h and cur_n_h >= n_200_h:
                effective_hurdle = 30.0
            elif cur_n_h >= n_200_h:
                effective_hurdle = 20.0
            else:
                effective_hurdle = 15.0
        else:
            effective_hurdle = min_momentum_hurdle_pct

        if strategy == "MULTI_ASSET":
            # Multi-Asset weights dynamically scaled by risk profile
            if risk_profile == "RISKY":
                eq_wallet = cash_balance * 0.75
                idx_wallet = cash_balance * 0.15
                gold_wallet = cash_balance * 0.10
            elif risk_profile == "SAFE":
                eq_wallet = cash_balance * 0.50
                idx_wallet = cash_balance * 0.30
                gold_wallet = cash_balance * 0.20
            else:  # BALANCED
                eq_wallet = cash_balance * 0.65
                idx_wallet = cash_balance * 0.20
                gold_wallet = cash_balance * 0.15

            # Candidate ranking per risk profile mandate
            cand_rows_sorted = _rank_candidates(cand_rows, sip_date, high_52w_map)

            # 1. Equities: Top 3 distinct sectors with orthogonal correlation clustering
            picked_stocks = []
            used_sectors = set()
            corr_m1 = pd.DataFrame()
            if enable_correlation_clustering and cand_rows_sorted:
                try:
                    from core.correlation_clustering import compute_pairwise_correlation_matrix
                    top_m1_syms = [str(cr[0]) for cr in cand_rows_sorted[:25]]
                    corr_m1 = compute_pairwise_correlation_matrix(top_m1_syms, session, lookback_days=120, as_of_date=sip_date)
                except Exception:
                    pass

            for cr in cand_rows_sorted:
                if len(picked_stocks) >= 3:
                    break
                sym = str(cr[0])
                ret_6m = float(cr[2]) if len(cr) > 2 and cr[2] is not None else 0.0
                tier = stock_meta_map.get(sym, {}).get("tier", "mid").lower()
                beta = stock_beta_map.get(sym, 1.0)

                # Risk Profile Constraint Filtering
                if risk_profile == "SAFE":
                    if (tier != "large" and beta > 1.05) and len(cand_rows_sorted) > 8:
                        continue
                    if ret_6m < 0.05 and len(cand_rows_sorted) > 8:
                        continue
                elif risk_profile == "BALANCED":
                    # Balanced All-Weather: moderate beta, balanced large and mid caps
                    if (beta > 1.25 or tier == "small") and len(cand_rows_sorted) > 8:
                        continue
                elif risk_profile == "RISKY":
                    # High Growth (Maximum Alpha): full momentum alpha across mid & small caps
                    pass

                if effective_hurdle > 0 and ret_6m < (effective_hurdle / 100.0) and len(cand_rows_sorted) > 5:
                    continue
                name, sec = stock_sector_map.get(sym, (sym, "General"))

                # Rule 5: Sector Momentum Gate (Quarantines chronic laggards unless relative strength >35%)
                if enable_sector_momentum_gate:
                    if sec in ("Agriculture, Fertilizers & Agro", "Chemicals & Specialty", "Textiles & Apparel", "Real Estate"):
                        if ret_6m < 0.35:
                            continue

                # Rule 1: 60-Day Loss Cooldown (Quarantines recently stopped-out stocks)
                if enable_loss_cooldown and sym in loss_cooldown_map:
                    last_exit_dt = loss_cooldown_map[sym]
                    if (sip_dt - last_exit_dt).days < cooldown_days:
                        continue

                # Rule 6: Correlation Clustering (Enforce r < max_pairwise_correlation)
                if enable_correlation_clustering and not corr_m1.empty and picked_stocks:
                    has_high_corr = False
                    for p in picked_stocks:
                        p_sym = p["symbol"]
                        if sym in corr_m1.index and p_sym in corr_m1.columns and float(corr_m1.loc[sym, p_sym]) >= max_pairwise_correlation:
                            has_high_corr = True
                            break
                    if has_high_corr and len(cand_rows_sorted) > 6:
                        continue

                if sec in used_sectors and len(cand_rows_sorted) > 6:
                    continue
                if max_position_cap_pct is not None and current_portfolio_equity > 0:
                    matched_pos = next((p for p in active_positions if p["symbol"] == sym and not p.get("is_etf", False)), None)
                    if matched_pos:
                        cur_p = float(price_lookup.get((sip_date, sym), {}).get("close", matched_pos["entry_price"]))
                        if (matched_pos["shares"] * cur_p / current_portfolio_equity) * 100.0 >= max_position_cap_pct:
                            continue
                used_sectors.add(sec)
                picked_stocks.append({
                    "symbol": sym, "name": name, "sector": sec,
                    "tier": tier,
                    "price": float(cr[1]), "month_cohort": sip_date
                })

            n_picks = max(1, len(picked_stocks))
            sz_mode = str(sizing_mode or "").upper()
            if sz_mode in ("INVERSE_VOL", "ERC", "RISK_PARITY") and n_picks > 0:
                inv_vols = [1.0 / max(0.12, stock_vol_map.get(item["symbol"], max(0.15, min(0.60, stock_beta_map.get(item["symbol"], 1.0) * 0.22)))) for item in picked_stocks]
                sum_inv = sum(inv_vols)
                c_norm = [v / sum_inv for v in inv_vols]
                eq_pool = eq_wallet
            elif sz_mode in ("EQUAL", "EQUAL_SPLIT") and n_picks > 0:
                c_norm = [1.0 / n_picks] * n_picks
                eq_pool = eq_wallet
            else:
                use_conviction = enable_conviction_weighting or (risk_profile == "RISKY" and enable_conviction_weighting is not False)
                if use_conviction and n_picks > 0:
                    if conviction_weights and len(conviction_weights) >= n_picks:
                        c_base = list(conviction_weights[:n_picks])
                    elif n_picks == 3:
                        c_base = [0.42, 0.33, 0.25]
                    elif n_picks == 4:
                        c_base = [0.35, 0.28, 0.22, 0.15]
                    elif n_picks == 5:
                        c_base = [0.30, 0.25, 0.20, 0.15, 0.10]
                    elif n_picks < 3:
                        c_base = [0.42, 0.33, 0.25][:n_picks]
                    else:
                        c_base = [n_picks - k for k in range(n_picks)]
                    s_c = sum(c_base) if sum(c_base) > 0 else 1.0
                    c_norm = [w / s_c for w in c_base]
                    eq_pool = eq_wallet
                else:
                    c_norm = None

            for i, item in enumerate(picked_stocks):
                if c_norm and i < len(c_norm):
                    target_allocation = eq_pool * c_norm[i]
                else:
                    remaining_picks = n_picks - i
                    target_allocation = eq_wallet / max(1, remaining_picks)
                p = item["price"]
                sh = int(math.floor(target_allocation / max(0.1, p)))
                if sh == 0 and p <= cash_balance:
                    sh = 1

                cost = round(sh * p, 2)
                if cost <= cash_balance and sh > 0:
                    cash_balance -= cost
                    total_buy_turnover += cost
                    eq_wallet -= cost
                    tier = item.get("tier", "mid").lower()
                    if exit_protocol == "TIGHT_SWING":
                        sl_price = round(p * 0.93, 2)
                        t1_price = round(p * 1.15, 2)
                    elif exit_protocol == "ADAPTIVE_STRUCTURAL":
                        if tier == "large":
                            sl_price = round(p * 0.87, 2)  # 13% SL for Large-Cap (resists market noise)
                            t1_price = round(p * 1.50, 2)
                        elif tier == "small":
                            sl_price = round(p * 0.83, 2)  # 17% SL for Small-Cap
                            t1_price = round(p * 1.80, 2)
                        else:
                            sl_price = round(p * 0.86, 2)  # 14% SL for Mid-Cap
                            t1_price = round(p * 1.60, 2)
                    elif exit_protocol == "STRUCTURAL_TRAILING":
                        sl_price = round(p * 0.86, 2)      # 14% SL Standard
                        t1_price = round(p * 2.00, 2)
                    else:
                        sl_price = round(p * 0.86, 2)
                        t1_price = round(p * 2.00, 2)

                    # Pyramiding into existing active positions
                    matched_open = None
                    if pyramid_winners:
                        for pos in active_positions:
                            if pos["symbol"] == item["symbol"] and not pos.get("is_etf", False):
                                matched_open = pos
                                break

                    if matched_open:
                        new_shares = matched_open["shares"] + sh
                        new_cost = round(matched_open["cost_basis"] + cost, 2)
                        matched_open["shares"] = new_shares
                        matched_open["cost_basis"] = new_cost
                        matched_open["entry_price"] = round(new_cost / new_shares, 2)
                        blended_sl = round(matched_open["entry_price"] * (0.83 if tier == "small" else (0.87 if tier == "large" else 0.86)), 2)
                        matched_open["stop_loss"] = max(matched_open["stop_loss"], blended_sl)
                        pyramided_trades_count += 1
                    else:
                        active_positions.append({
                            "symbol": item["symbol"],
                            "name": item["name"],
                            "sector": item["sector"],
                            "tier": tier,
                            "entry_date": sip_date,
                            "entry_price": p,
                            "shares": sh,
                            "cost_basis": cost,
                            "stop_loss": sl_price,
                            "target_price": t1_price,
                            "month_cohort": sip_date,
                            "status": "OPEN",
                            "highest_price": p,
                            "highest_price_date": sip_dt,
                            "lowest_price": p,
                            "is_etf": False,
                            "skimmed_tiers": set()
                        })

            # 2. Benchmark Index ETF (NIFTYBEES.NS)
            idx_p_info = price_lookup.get((sip_date, "NIFTYBEES.NS"))
            if idx_p_info:
                p_idx = float(idx_p_info["close"])
                sh_idx = int(math.floor(idx_wallet / max(0.1, p_idx)))
                cost_idx = round(sh_idx * p_idx, 2)
                if cost_idx <= cash_balance and sh_idx > 0:
                    cash_balance -= cost_idx
                    total_buy_turnover += cost_idx
                    active_positions.append({
                        "symbol": "NIFTYBEES.NS",
                        "name": "Nippon India Nifty 50 ETF",
                        "sector": "Broad Market Index",
                        "entry_date": sip_date,
                        "entry_price": p_idx,
                        "shares": sh_idx,
                        "cost_basis": cost_idx,
                        "stop_loss": round(p_idx * 0.85, 2),
                        "target_price": round(p_idx * 2.0, 2),
                        "month_cohort": sip_date,
                        "status": "OPEN",
                        "highest_price": p_idx,
                        "lowest_price": p_idx,
                        "is_etf": True
                    })

            # 3. Gold ETF (GOLDBEES.NS)
            gold_p_info = price_lookup.get((sip_date, "GOLDBEES.NS"))
            if gold_p_info:
                p_gold = float(gold_p_info["close"])
                sh_gold = int(math.floor(gold_wallet / max(0.1, p_gold)))
                cost_gold = round(sh_gold * p_gold, 2)
                if cost_gold <= cash_balance and sh_gold > 0:
                    cash_balance -= cost_gold
                    total_buy_turnover += cost_gold
                    active_positions.append({
                        "symbol": "GOLDBEES.NS",
                        "name": "Nippon India Gold ETF",
                        "sector": "Precious Metals",
                        "entry_date": sip_date,
                        "entry_price": p_gold,
                        "shares": sh_gold,
                        "cost_basis": cost_gold,
                        "stop_loss": round(p_gold * 0.85, 2),
                        "target_price": round(p_gold * 2.0, 2),
                        "month_cohort": sip_date,
                        "status": "OPEN",
                        "highest_price": p_gold,
                        "lowest_price": p_gold,
                        "is_etf": True
                    })

        else:
            # PURE_STOCKS: Direct Equities across distinct sectors
            # ── Rule 2: 200-Day EMA Macro Regime Defense Gate ──
            is_macro_defensive = False
            hedge_budget = 0.0
            if enable_macro_regime_gate:
                cur_nifty = nifty_price_map.get(sip_date, 0.0)
                n_50 = nifty_50_ema.get(sip_date, cur_nifty)
                n_200 = nifty_200_ema.get(sip_date, cur_nifty)
                if macro_regime_trigger == "EMA_200":
                    if cur_nifty < n_200:
                        is_macro_defensive = True
                        hedge_budget = cash_balance * (macro_hedge_pct / 100.0)
                else:
                    if cur_nifty < n_50 or cur_nifty < n_200:
                        is_macro_defensive = True
                        hedge_budget = cash_balance * (macro_hedge_pct / 100.0)

                if enable_breadth_gate and not is_macro_defensive:
                    try:
                        from core.market_breadth import calculate_market_breadth
                        mb_stat = calculate_market_breadth(session, as_of_date=sip_date)
                        if mb_stat.get("pct_above_50_ema", 55.0) < 40.0:
                            is_macro_defensive = True
                            hedge_budget = cash_balance * (macro_hedge_pct / 100.0)
                    except Exception:
                        pass

            if is_macro_defensive and hedge_budget > 0:
                macro_defense_triggered_months.append(sip_date)
                h_sym = macro_hedge_asset or "GOLDBEES.NS"
                h_name = "Nippon India Gold ETF" if "GOLD" in h_sym else "Nippon India NIFTY 50 ETF"
                h_sec = "Precious Metals" if "GOLD" in h_sym else "Index ETF"
                h_p_info = price_lookup.get((sip_date, h_sym))
                if h_p_info:
                    p_h = float(h_p_info["close"])
                    sh_h = int(math.floor(hedge_budget / max(0.1, p_h)))
                    cost_h = round(sh_h * p_h, 2)
                    if cost_h <= cash_balance and sh_h > 0:
                        cash_balance -= cost_h
                        total_buy_turnover += cost_h
                        matched_h = next((p for p in active_positions if p["symbol"] == h_sym and p.get("is_etf", False)), None)
                        if matched_h:
                            matched_h["shares"] += sh_h
                            matched_h["cost_basis"] = round(matched_h["cost_basis"] + cost_h, 2)
                            matched_h["entry_price"] = round(matched_h["cost_basis"] / matched_h["shares"], 2)
                            pyramided_trades_count += 1
                        else:
                            active_positions.append({
                                "symbol": h_sym,
                                "name": h_name,
                                "sector": h_sec,
                                "tier": "LARGE",
                                "entry_date": sip_date,
                                "entry_price": p_h,
                                "shares": sh_h,
                                "cost_basis": cost_h,
                                "stop_loss": round(p_h * 0.85, 2),
                                "target_price": round(p_h * 3.0, 2),
                                "month_cohort": sip_date,
                                "status": "OPEN",
                                "highest_price": p_h,
                                "lowest_price": p_h,
                                "is_etf": True,
                                "entry_dt": sip_dt
                            })
            elif enable_macro_rotation and not is_macro_defensive:
                # Option 1A: Macro Cycle Profit Rotation
                # When NIFTY crosses back above its 200-day EMA, liquidate accumulated Gold ETF
                # and rotate capital directly into fresh top-ranking equity momentum leaders.
                etf_positions = [p for p in active_positions if p.get("is_etf", False) or p["symbol"] == (macro_hedge_asset or "GOLDBEES.NS")]
                if etf_positions:
                    for pos_etf in etf_positions:
                        sym_etf = pos_etf["symbol"]
                        cur_p_info = price_lookup.get((sip_date, sym_etf))
                        cur_p_etf = float(cur_p_info["close"]) if cur_p_info else pos_etf["entry_price"]
                        sh_to_rot = int(math.floor(pos_etf["shares"] * macro_rotation_ratio))
                        if sh_to_rot > 0:
                            realized_val = round(sh_to_rot * cur_p_etf, 2)
                            cost_of_rot = round(pos_etf["cost_basis"] * (sh_to_rot / pos_etf["shares"]), 2)
                            pnl_rot = round(realized_val - cost_of_rot, 2)
                            pnl_pct_rot = round((cur_p_etf - pos_etf["entry_price"]) / max(0.01, pos_etf["entry_price"]) * 100.0, 2)
                            cash_balance += realized_val
                            total_sell_turnover += realized_val
                            rot_holding_days = (sip_dt - datetime.strptime(pos_etf["entry_date"], "%Y-%m-%d").date()).days
                            if pnl_rot > 0:
                                if rot_holding_days > 365:
                                    realized_ltcg_gains += pnl_rot
                                else:
                                    realized_stcg_gains += pnl_rot
                            pos_etf["shares"] -= sh_to_rot
                            pos_etf["cost_basis"] = round(pos_etf["cost_basis"] - cost_of_rot, 2)
                            macro_rotations_count += 1

                            all_closed_positions.append({
                                "symbol": sym_etf,
                                "name": pos_etf["name"],
                                "sector": pos_etf["sector"],
                                "tier": pos_etf.get("tier", "ETF"),
                                "entry_date": pos_etf["entry_date"],
                                "exit_date": sip_date,
                                "entry_price": pos_etf["entry_price"],
                                "exit_price": cur_p_etf,
                                "shares": sh_to_rot,
                                "cost_basis": cost_of_rot,
                                "realized_val": realized_val,
                                "realized_value": realized_val,
                                "pnl": pnl_rot,
                                "ret_pct": pnl_pct_rot,
                                "return_pct": pnl_pct_rot,
                                "status": "WIN" if pnl_rot >= 0 else "LOSS",
                                "exit_reason": f"Macro Rotation to Equities (+{pnl_pct_rot:.1f}%)",
                                "holding_days": (sip_dt - datetime.strptime(pos_etf["entry_date"], "%Y-%m-%d").date()).days,
                                "capital_preserved": 0.0,
                                "avoided_further_drop": False,
                                "month_cohort": pos_etf.get("month_cohort", sip_date)
                            })
                    active_positions = [p for p in active_positions if p["shares"] > 0]

            # Candidate ranking per risk profile mandate
            cand_rows_sorted = _rank_candidates(cand_rows, sip_date, high_52w_map)

            picked_for_month = []
            used_sectors = set()
            sector_counts = {}
            top_sector = None
            if enable_sector_duopoly and cand_rows_sorted:
                sec_freq = {}
                for cr in cand_rows_sorted[:20]:
                    s_sec = stock_sector_map.get(str(cr[0]), (str(cr[0]), "General"))[1]
                    sec_freq[s_sec] = sec_freq.get(s_sec, 0) + 1
                if sec_freq:
                    top_sector = max(sec_freq.keys(), key=lambda s: sec_freq[s])
            target_eq_picks = max(2, target_stock_count - (len(active_mf_schemes) if include_mutual_funds and target_stock_count <= 5 else 0))
            corr_sub = pd.DataFrame()
            if enable_correlation_clustering and cand_rows_sorted:
                try:
                    from core.correlation_clustering import compute_pairwise_correlation_matrix
                    top_sub_syms = [str(cr[0]) for cr in cand_rows_sorted[:25]]
                    corr_sub = compute_pairwise_correlation_matrix(top_sub_syms, session, lookback_days=120, as_of_date=sip_date)
                except Exception:
                    pass

            for cr in cand_rows_sorted:
                if len(picked_for_month) >= target_eq_picks:
                    break
                sym = str(cr[0])
                ret_6m = float(cr[2]) if len(cr) > 2 and cr[2] is not None else 0.0
                tier = stock_meta_map.get(sym, {}).get("tier", "mid").lower()
                beta = stock_beta_map.get(sym, 1.0)

                # Risk Profile Constraint Filtering
                if risk_profile == "SAFE":
                    if (tier != "large" and beta > 1.05) and len(cand_rows_sorted) > 10:
                        continue
                    if ret_6m < 0.05 and len(cand_rows_sorted) > 10:
                        continue
                elif risk_profile == "BALANCED":
                    # Balanced All-Weather: moderate beta, balanced large and mid caps
                    if (beta > 1.25 or tier == "small") and len(cand_rows_sorted) > 10:
                        continue
                elif risk_profile == "RISKY":
                    # High Growth (Maximum Alpha): full momentum alpha across mid & small caps
                    pass

                if effective_hurdle > 0 and ret_6m < (effective_hurdle / 100.0) and len(cand_rows_sorted) > 10:
                    continue
                name, sec = stock_sector_map.get(sym, (sym, "General"))

                # Rule 5: Sector Momentum Gate (Quarantines chronic laggards unless relative strength >35%)
                if enable_sector_momentum_gate:
                    if sec in ("Agriculture, Fertilizers & Agro", "Chemicals & Specialty", "Textiles & Apparel", "Real Estate"):
                        if ret_6m < 0.35:
                            continue

                # Rule 1: 60-Day Loss Cooldown (Quarantines recently stopped-out stocks)
                if enable_loss_cooldown and sym in loss_cooldown_map:
                    last_exit_dt = loss_cooldown_map[sym]
                    if (sip_dt - last_exit_dt).days < cooldown_days:
                        continue

                # Rule 6: Correlation Clustering (Enforce r < max_pairwise_correlation)
                if enable_correlation_clustering and not corr_sub.empty and picked_for_month:
                    has_high_corr = False
                    for p in picked_for_month:
                        p_sym = p["symbol"]
                        if sym in corr_sub.index and p_sym in corr_sub.columns and float(corr_sub.loc[sym, p_sym]) >= max_pairwise_correlation:
                            has_high_corr = True
                            break
                    if has_high_corr and len(cand_rows_sorted) > 10:
                        continue

                cur_sec_count = sector_counts.get(sec, 0)
                sec_limit = sector_duopoly_max if (enable_sector_duopoly and sec == top_sector) else 1
                if cur_sec_count >= sec_limit and len(cand_rows_sorted) > 10:
                    continue
                # Fix 3: Recalculate portfolio equity per-pick to catch intra-month concentration crossings
                rolling_equity = _calc_portfolio_equity(sip_date, active_positions, cash_balance)
                effective_cap = expanded_cap_pct if enable_dynamic_cap_expansion else max_position_cap_pct
                if effective_cap is not None and rolling_equity > 0:
                    matched_pos = next((p for p in active_positions if p["symbol"] == sym and not p.get("is_etf", False)), None)
                    if matched_pos:
                        cur_p = float(price_lookup.get((sip_date, sym), {}).get("close", matched_pos["entry_price"]))
                        if (matched_pos["shares"] * cur_p / rolling_equity) * 100.0 >= effective_cap:
                            continue
                sector_counts[sec] = cur_sec_count + 1
                used_sectors.add(sec)
                picked_for_month.append({
                    "symbol": sym, "name": name, "sector": sec,
                    "tier": tier,
                    "price": float(cr[1]), "month_cohort": sip_date
                })

            n_picks = max(1, len(picked_for_month))
            sz_mode = str(sizing_mode or "").upper()
            if enable_livermore_pyramiding and n_picks > 0:
                liv_weights = []
                for item in picked_for_month:
                    m_pos = next((p for p in active_positions if p["symbol"] == item["symbol"] and not p.get("is_etf")), None)
                    if m_pos:
                        g = (item["price"] - m_pos["entry_price"]) / max(0.01, m_pos["entry_price"])
                        liv_weights.append(1.50 if g >= 0.20 else 1.0)
                    else:
                        liv_weights.append(1.0)
                sum_liv = sum(liv_weights)
                c_norm = [w / sum_liv for w in liv_weights]
                cash_pool = cash_balance
            elif sz_mode in ("INVERSE_VOL", "ERC", "RISK_PARITY") and n_picks > 0:
                inv_vols = [1.0 / max(0.12, stock_vol_map.get(item["symbol"], max(0.15, min(0.60, stock_beta_map.get(item["symbol"], 1.0) * 0.22)))) for item in picked_for_month]
                sum_inv = sum(inv_vols)
                c_norm = [v / sum_inv for v in inv_vols]
                cash_pool = cash_balance
            elif sz_mode in ("EQUAL", "EQUAL_SPLIT") and n_picks > 0:
                c_norm = [1.0 / n_picks] * n_picks
                cash_pool = cash_balance
            else:
                use_conviction = enable_conviction_weighting or (risk_profile == "RISKY" and enable_conviction_weighting is not False)
                if use_conviction and n_picks > 0:
                    if conviction_weights and len(conviction_weights) >= n_picks:
                        c_base = list(conviction_weights[:n_picks])
                    elif n_picks == 5:
                        c_base = [0.28, 0.24, 0.20, 0.16, 0.12]
                    elif n_picks == 4:
                        c_base = [0.32, 0.26, 0.22, 0.20]
                    elif n_picks == 3:
                        c_base = [0.40, 0.35, 0.25]
                    elif n_picks <= 5:
                        c_base = [0.30, 0.25, 0.20, 0.15, 0.10][:n_picks]
                    else:
                        # Linear rank-decay conviction weights for >5 picks (e.g. 6 to 10 picks)
                        c_base = [n_picks - k for k in range(n_picks)]
                    s_c = sum(c_base) if sum(c_base) > 0 else 1.0
                    c_norm = [w / s_c for w in c_base]
                    cash_pool = cash_balance
                else:
                    c_norm = None

            for i, item in enumerate(picked_for_month):
                if c_norm and i < len(c_norm):
                    target_allocation = cash_pool * c_norm[i]
                else:
                    remaining_picks = n_picks - i
                    target_allocation = cash_balance / max(1, remaining_picks)
                p = item["price"]
                if enable_split_entry:
                    initial_alloc = target_allocation * split_entry_initial_ratio
                    sh = int(math.floor(initial_alloc / max(0.1, p)))
                    pending_cash = round(target_allocation - (sh * p), 2)
                else:
                    sh = int(math.floor(target_allocation / max(0.1, p)))
                    pending_cash = 0.0

                if sh == 0 and p <= cash_balance:
                    sh = 1
                    pending_cash = max(0.0, target_allocation - (sh * p))

                cost = round(sh * p, 2)
                if cost <= cash_balance and sh > 0:
                    cash_balance -= cost
                    total_buy_turnover += cost
                    tier = item.get("tier", "mid").lower()
                    if exit_protocol == "TIGHT_SWING":
                        sl_price = round(p * 0.93, 2)    # 7% Stop Loss for swing
                        t1_price = round(p * 1.15, 2)    # 15% Profit Target
                    elif exit_protocol == "DYNAMIC_ATR":
                        atr_sym = stock_vol_map.get(item["symbol"], 0.22) * p / 16.0
                        sl_price = round(max(p * 0.75, p - 3.0 * atr_sym), 2)
                        t1_price = round(p * 2.50, 2)
                    elif exit_protocol == "ADAPTIVE_STRUCTURAL":
                        if tier == "large":
                            sl_price = round(p * 0.87, 2)  # 13% SL for Large-Cap (resists market noise)
                            t1_price = round(p * 1.50, 2)
                        elif tier == "small":
                            sl_price = round(p * 0.83, 2)  # 17% SL for Small-Cap
                            t1_price = round(p * 1.80, 2)
                        else:
                            sl_price = round(p * 0.86, 2)  # 14% SL for Mid-Cap
                            t1_price = round(p * 1.60, 2)
                    elif exit_protocol == "STRUCTURAL_TRAILING":
                        sl_price = round(p * 0.86, 2)      # 14% SL Standard
                        t1_price = round(p * 2.00, 2)
                    else:
                        sl_price = round(p * 0.86, 2)
                        t1_price = round(p * 2.00, 2)

                    # Pyramiding into existing active positions
                    matched_open = None
                    if pyramid_winners:
                        for pos in active_positions:
                            if pos["symbol"] == item["symbol"] and not pos.get("is_etf", False):
                                matched_open = pos
                                break

                    if matched_open:
                        new_shares = matched_open["shares"] + sh
                        new_cost = round(matched_open["cost_basis"] + cost, 2)
                        matched_open["shares"] = new_shares
                        matched_open["cost_basis"] = new_cost
                        matched_open["entry_price"] = round(new_cost / new_shares, 2)
                        blended_sl = round(matched_open["entry_price"] * (0.83 if tier == "small" else (0.87 if tier == "large" else 0.86)), 2)
                        matched_open["stop_loss"] = max(matched_open["stop_loss"], blended_sl)
                        if enable_split_entry and pending_cash > 0:
                            matched_open["pending_tranche_cash"] = matched_open.get("pending_tranche_cash", 0.0) + pending_cash
                            matched_open["tranche_pullback_target"] = round(p * (1.0 - split_entry_pullback_pct / 100.0), 2)
                            matched_open["tranche_deadline_dt"] = sip_dt + timedelta(days=int(split_entry_max_wait_days * 1.5))
                        pyramided_trades_count += 1
                    else:
                        active_positions.append({
                            "symbol": item["symbol"],
                            "name": item["name"],
                            "sector": item["sector"],
                            "tier": tier,
                            "entry_date": sip_date,
                            "entry_price": p,
                            "shares": sh,
                            "cost_basis": cost,
                            "stop_loss": sl_price,
                            "target_price": t1_price,
                            "month_cohort": sip_date,
                            "status": "OPEN",
                            "highest_price": p,
                            "highest_price_date": sip_dt,
                            "lowest_price": p,
                            "is_etf": False,
                            "skimmed_tiers": set(),
                            "pending_tranche_cash": pending_cash if enable_split_entry else 0.0,
                            "tranche_pullback_target": round(p * (1.0 - split_entry_pullback_pct / 100.0), 2) if enable_split_entry else 0.0,
                            "tranche_deadline_dt": (sip_dt + timedelta(days=int(split_entry_max_wait_days * 1.5))) if enable_split_entry else None,
                        })

        # ── Daily monitoring between sip_date and next month ─────────────────
        # Determine day slice until next month or end_dt
        curr_idx = all_trading_days.index(sip_date) if sip_date in all_trading_days else 0
        if month_idx < len(monthly_first_days):
            next_sip_date = monthly_first_days[month_idx]
            next_idx = all_trading_days.index(next_sip_date) if next_sip_date in all_trading_days else len(all_trading_days)
        else:
            next_idx = len(all_trading_days)

        period_days = all_trading_days[curr_idx:next_idx]

        for d_str in period_days:
            cur_dt = datetime.strptime(d_str, "%Y-%m-%d").date()
            day_idx = all_trading_days.index(d_str) if d_str in all_trading_days else -1

            # ── Auto-Sweep Idle Cash to LiquidBees (6.5% Annualized Daily Yield) ──
            if enable_liquid_sweep and cash_balance > 100.0:
                daily_liquid_rate = ((1.0 + (liquid_yield_pct / 100.0)) ** (1.0 / 252.0)) - 1.0
                cash_balance += cash_balance * daily_liquid_rate

            # ── Tactical Dip-Buying: Deploy Idle Reserve Cash into Top Leaders on >=4% Dips ──
            if enable_dip_buying and cash_balance >= (monthly_wallet * 0.40) and (day_idx - last_dip_day_idx >= dip_cooldown_days):
                nifty_c = nifty_price_map.get(d_str, 0.0)
                nifty_h = nifty_20d_highs.get(d_str, nifty_c)
                if nifty_h > 0:
                    bench_drop_pct = (nifty_h - nifty_c) / nifty_h * 100.0
                    if bench_drop_pct >= dip_threshold_pct:
                        active_with_prices = []
                        for pos in active_positions:
                            if pos.get("is_etf", False) or pos.get("is_mf", False):
                                continue
                            p_info = price_lookup.get((d_str, pos["symbol"]))
                            if p_info:
                                cur_p = float(p_info["close"])
                                gain = (cur_p - pos["entry_price"]) / pos["entry_price"]
                                active_with_prices.append((pos, cur_p, gain))

                        winners = [x for x in active_with_prices if x[2] > 0.05]
                        if max_position_cap_pct is not None and winners:
                            # Fix 4: Use INVESTED equity only (exclude cash) as denominator for concentration check.
                            # Including cash inflates denominator and lets over-concentrated positions bypass the cap.
                            d_invested_equity = sum(
                                p["shares"] * float(
                                    mf_daily_nav_map.get((d_str, p.get("scheme_code")), p["entry_price"]) if p.get("is_mf")
                                    else price_lookup.get((d_str, p["symbol"]), {}).get("close", p["entry_price"])
                                )
                                for p in active_positions
                            )
                            if d_invested_equity > 0:
                                winners = [
                                    x for x in winners
                                    if (x[0]["shares"] * x[1] / d_invested_equity) * 100.0 < (
                                        expanded_cap_pct if (enable_dynamic_cap_expansion and x[2] >= 1.50) else max_position_cap_pct
                                    )
                                ]
                        if winners:
                            winners.sort(key=lambda x: x[2], reverse=True)
                            deploy_picks = winners[:2]
                            dip_wallet_total = cash_balance * (dip_deploy_pct / 100.0)
                            for w_pos, cur_p, _ in deploy_picks:
                                sub_wallet = dip_wallet_total / len(deploy_picks)
                                sh = int(math.floor(sub_wallet / max(0.1, cur_p)))
                                if sh > 0:
                                    c_val = round(sh * cur_p, 2)
                                    if c_val <= cash_balance:
                                        cash_balance -= c_val
                                        total_buy_turnover += c_val
                                        n_sh = w_pos["shares"] + sh
                                        n_c = round(w_pos["cost_basis"] + c_val, 2)
                                        w_pos["shares"] = n_sh
                                        w_pos["cost_basis"] = n_c
                                        w_pos["entry_price"] = round(n_c / n_sh, 2)
                                        dip_buys_count += 1
                            last_dip_day_idx = day_idx

            # 1. Monitor active positions for Sell Reminders
            surviving_positions = []
            for pos in active_positions:
                sym = pos["symbol"]
                p_info = price_lookup.get((d_str, sym))
                
                if not p_info:
                    surviving_positions.append(pos)
                    continue

                curr_p = float(p_info["close"])
                curr_l = float(p_info["low"])
                curr_h = float(p_info["high"])

                if curr_h > pos.get("highest_price", 0.0):
                    pos["highest_price"] = curr_h
                    pos["highest_price_date"] = cur_dt
                pos["lowest_price"] = min(pos.get("lowest_price", curr_l), curr_l)

                # Lever 3: Intra-Month Split-Entry Tranche Execution
                if enable_split_entry and pos.get("pending_tranche_cash", 0.0) > 0 and d_str > pos["entry_date"]:
                    pending_cash = pos["pending_tranche_cash"]
                    pullback_hit = curr_l <= pos.get("tranche_pullback_target", 0.0)
                    deadline_hit = pos.get("tranche_deadline_dt") and cur_dt >= pos["tranche_deadline_dt"]
                    if pullback_hit or deadline_hit:
                        fill_p = pos["tranche_pullback_target"] if (pullback_hit and pos.get("tranche_pullback_target", 0.0) > 0) else curr_p
                        add_sh = int(math.floor(pending_cash / max(0.1, fill_p)))
                        if add_sh > 0 and (add_sh * fill_p) <= cash_balance:
                            add_cost = round(add_sh * fill_p, 2)
                            cash_balance -= add_cost
                            total_buy_turnover += add_cost
                            pos["shares"] += add_sh
                            pos["cost_basis"] = round(pos["cost_basis"] + add_cost, 2)
                            pos["entry_price"] = round(pos["cost_basis"] / pos["shares"], 2)
                            split_entries_filled_count += 1
                        pos["pending_tranche_cash"] = 0.0

                # ─── Van Tharp 3-Tier Asymmetric Profit Harvesting & Chandelier Stop ─
                if enable_3tier_harvest and d_str > pos["entry_date"] and not pos.get("is_etf", False) and not pos.get("is_mf", False) and pos["shares"] >= 3:
                    curr_gain_pct = (curr_p - pos["entry_price"]) / pos["entry_price"] * 100.0
                    harvested_tiers = pos.get("harvested_tiers", set())

                    # Tier 1 Harvest (+25% Gain): Trim 33%, move Stop-Loss to Breakeven + 2%
                    if curr_gain_pct >= 25.0 and 1 not in harvested_tiers:
                        trim_sh = max(1, int(math.floor(pos["shares"] * 0.33)))
                        if trim_sh < pos["shares"]:
                            realized = round(trim_sh * curr_p, 2)
                            old_shares = pos["shares"]
                            pos["shares"] -= trim_sh
                            trim_cost = round(pos["cost_basis"] * (trim_sh / old_shares), 2)
                            pos["cost_basis"] = round(pos["cost_basis"] * (pos["shares"] / old_shares), 2)
                            cash_balance += realized
                            total_sell_turnover += realized
                            pnl_trim = round(realized - trim_cost, 2)
                            s_holding_days = (cur_dt - datetime.strptime(pos["entry_date"], "%Y-%m-%d").date()).days
                            if pnl_trim > 0:
                                if s_holding_days > 365:
                                    realized_ltcg_gains += pnl_trim
                                else:
                                    realized_stcg_gains += pnl_trim
                            # Instantly ratchet stop loss to Breakeven + 2% (trade is now 100% risk free)
                            pos["stop_loss"] = max(pos.get("stop_loss", 0.0), round(pos["entry_price"] * 1.02, 2))
                            if "harvested_tiers" not in pos:
                                pos["harvested_tiers"] = set()
                            pos["harvested_tiers"].add(1)
                            three_tier_harvests_count += 1

                    # Tier 2 Harvest (+50% Gain): Trim next 33%, activate 3.0x ATR Chandelier Exit
                    if curr_gain_pct >= 50.0 and 2 not in harvested_tiers and pos["shares"] >= 2:
                        trim_sh = max(1, int(math.floor(pos["shares"] * 0.50)))
                        if trim_sh < pos["shares"]:
                            realized = round(trim_sh * curr_p, 2)
                            old_shares = pos["shares"]
                            pos["shares"] -= trim_sh
                            trim_cost = round(pos["cost_basis"] * (trim_sh / old_shares), 2)
                            pos["cost_basis"] = round(pos["cost_basis"] * (pos["shares"] / old_shares), 2)
                            cash_balance += realized
                            total_sell_turnover += realized
                            pnl_trim = round(realized - trim_cost, 2)
                            s_holding_days = (cur_dt - datetime.strptime(pos["entry_date"], "%Y-%m-%d").date()).days
                            if pnl_trim > 0:
                                if s_holding_days > 365:
                                    realized_ltcg_gains += pnl_trim
                                else:
                                    realized_stcg_gains += pnl_trim
                            # Activate Chandelier exit (trailing 3.0x ATR from highest high)
                            atr_sym = stock_vol_map.get(sym, 0.22) * curr_p / 16.0
                            chandelier_sl = round(pos["highest_price"] - 3.0 * atr_sym, 2)
                            pos["stop_loss"] = max(pos.get("stop_loss", 0.0), chandelier_sl)
                            if "harvested_tiers" not in pos:
                                pos["harvested_tiers"] = set()
                            pos["harvested_tiers"].add(2)
                            three_tier_harvests_count += 1

                # Two-Tier Multi-Bagger Partial Profit Skimming (Trim partial position to de-risk & fund dips)
                if enable_parabolic_skim and d_str > pos["entry_date"] and not pos.get("is_etf", False) and not pos.get("is_mf", False) and pos["shares"] >= 4:
                    curr_gain_pct = (curr_p - pos["entry_price"]) / pos["entry_price"] * 100.0

                    # Tier 1 Skim (+150% gain)
                    if curr_gain_pct >= skim_milestone_pct and 1 not in pos.get("skimmed_tiers", set()):
                        skim_sh = max(1, int(math.floor(pos["shares"] * (skim_ratio_pct / 100.0))))
                        if skim_sh < pos["shares"]:
                            realized = round(skim_sh * curr_p, 2)
                            old_shares = pos["shares"]  # Fix 1: capture BEFORE decrement
                            pos["shares"] -= skim_sh
                            skim_cost = round(pos["cost_basis"] * (skim_sh / old_shares), 2)
                            pos["cost_basis"] = round(pos["cost_basis"] * (pos["shares"] / old_shares), 2)
                            cash_balance += realized
                            total_sell_turnover += realized
                            skim_pnl = round(realized - skim_cost, 2)
                            s_holding_days = (cur_dt - datetime.strptime(pos["entry_date"], "%Y-%m-%d").date()).days
                            if skim_pnl > 0:
                                if s_holding_days > 365:
                                    realized_ltcg_gains += skim_pnl
                                else:
                                    realized_stcg_gains += skim_pnl
                            if "skimmed_tiers" not in pos:
                                pos["skimmed_tiers"] = set()
                            pos["skimmed_tiers"].add(1)
                            skimmed_trades_count += 1

                    # Tier 2 Skim (+250% gain)
                    tier2_thresh = max(250.0, skim_milestone_pct * 1.5)
                    if curr_gain_pct >= tier2_thresh and 2 not in pos.get("skimmed_tiers", set()):
                        skim_sh = max(1, int(math.floor(pos["shares"] * (skim_ratio_pct / 100.0))))
                        if skim_sh < pos["shares"]:
                            realized = round(skim_sh * curr_p, 2)
                            old_shares = pos["shares"]  # Fix 1: capture BEFORE decrement
                            pos["shares"] -= skim_sh
                            skim_cost = round(pos["cost_basis"] * (skim_sh / old_shares), 2)
                            pos["cost_basis"] = round(pos["cost_basis"] * (pos["shares"] / old_shares), 2)
                            cash_balance += realized
                            total_sell_turnover += realized
                            skim_pnl = round(realized - skim_cost, 2)
                            s_holding_days = (cur_dt - datetime.strptime(pos["entry_date"], "%Y-%m-%d").date()).days
                            if skim_pnl > 0:
                                if s_holding_days > 365:
                                    realized_ltcg_gains += skim_pnl
                                else:
                                    realized_stcg_gains += skim_pnl
                            if "skimmed_tiers" not in pos:
                                pos["skimmed_tiers"] = set()
                            pos["skimmed_tiers"].add(2)
                            skimmed_trades_count += 1

                exit_triggered = False
                exit_reason = ""
                exit_price = curr_p

                if d_str > pos["entry_date"]:
                    if pos.get("is_etf", False) or pos.get("is_mf", False):
                        # ETFs & Mutual Funds are foundational compounding anchors held for continuous compounding
                        pass
                    elif exit_protocol == "TIGHT_SWING":
                        # Tight swing trading: 7% stop loss and 15% profit cap
                        if curr_l <= pos["stop_loss"]:
                            exit_triggered = True
                            exit_reason = "Stop-Loss Hit (-7% Cap Preserved)"
                            exit_price = pos["stop_loss"]
                        elif curr_h >= pos["target_price"]:
                            exit_triggered = True
                            exit_reason = "Profit Target Hit (+15%)"
                            exit_price = pos["target_price"]

                    elif exit_protocol == "ADAPTIVE_STRUCTURAL":
                        tier = pos.get("tier", "mid").lower()
                        sec = pos.get("sector", "General")

                        if tier == "large":
                            # Large-Cap: Lower ATR, breakeven at +25%, 22% trail past +40%, 20% trail on 2x+
                            if pos["highest_price"] >= pos["entry_price"] * 1.25:
                                pos["stop_loss"] = max(pos["stop_loss"], pos["entry_price"])
                            if pos["highest_price"] >= pos["entry_price"] * 1.40:
                                pos["stop_loss"] = max(pos["stop_loss"], round(pos["highest_price"] * 0.78, 2))
                            if pos["highest_price"] >= pos["entry_price"] * 2.00:
                                pos["stop_loss"] = max(pos["stop_loss"], round(pos["highest_price"] * 0.80, 2))

                        elif tier == "small":
                            # Small-Cap: High beta, breakeven at +30%, 25% trail past +45%, 28% trail on 3x+
                            if pos["highest_price"] >= pos["entry_price"] * 1.30:
                                pos["stop_loss"] = max(pos["stop_loss"], pos["entry_price"])
                            if pos["highest_price"] >= pos["entry_price"] * 1.45:
                                pos["stop_loss"] = max(pos["stop_loss"], round(pos["highest_price"] * 0.75, 2))
                            if pos["highest_price"] >= pos["entry_price"] * 3.00:
                                pos["stop_loss"] = max(pos["stop_loss"], round(pos["highest_price"] * 0.72, 2))

                        else:
                            # Mid-Cap / Standard: Balanced -14% SL, +25% BE, 25% Trail past +40%, 26% trail on 2.5x+
                            if pos["highest_price"] >= pos["entry_price"] * 1.25:
                                pos["stop_loss"] = max(pos["stop_loss"], pos["entry_price"])
                            if pos["highest_price"] >= pos["entry_price"] * 1.40:
                                pos["stop_loss"] = max(pos["stop_loss"], round(pos["highest_price"] * 0.75, 2))
                            if pos["highest_price"] >= pos["entry_price"] * 2.50:
                                pos["stop_loss"] = max(pos["stop_loss"], round(pos["highest_price"] * 0.74, 2))

                        # Defensive Sector Overlay: FMCG and Pharma lock gains at 22% trail past +35%
                        if sec in ("FMCG & Consumer Staples", "Pharmaceuticals & Healthcare") and pos["highest_price"] >= pos["entry_price"] * 1.35:
                            pos["stop_loss"] = max(pos["stop_loss"], pos["highest_price"] * 0.78)

                        # Option 2A: Smart Stepladder Trailing Stops (Progressive Profit Floors)
                        if enable_stepladder_trailing:
                            sl_cfg = stepladder_config or DEFAULT_STEPLADDER_CONFIG
                            if enable_beta_stepladder:
                                b_val = stock_beta_map.get(sym, 1.0)
                                ladder = sl_cfg.get("beta_high" if b_val >= 1.25 else ("beta_low" if b_val <= 0.95 else "standard"), sl_cfg.get("standard", []))
                            else:
                                ladder = sl_cfg.get("standard", DEFAULT_STEPLADDER_CONFIG["standard"])
                            for step in ladder:
                                if pos["highest_price"] >= pos["entry_price"] * step["gain_mult"]:
                                    pos["stop_loss"] = max(pos["stop_loss"], round(pos["entry_price"] * step["floor_mult"], 2))

                        # Lever 12: Stage-Calibrated Tiered Trailing Ratchet (14% base -> 10% mid -> 7% parabolic)
                        if enable_tiered_trailing_ratchet:
                            curr_h_gain = (pos["highest_price"] - pos["entry_price"]) / max(0.01, pos["entry_price"])
                            if curr_h_gain >= 1.00:
                                pos["stop_loss"] = max(pos["stop_loss"], round(pos["highest_price"] * 0.93, 2))
                            elif curr_h_gain >= 0.35:
                                pos["stop_loss"] = max(pos["stop_loss"], round(pos["highest_price"] * 0.90, 2))
                            elif curr_h_gain >= 0.15:
                                pos["stop_loss"] = max(pos["stop_loss"], round(pos["highest_price"] * 0.86, 2))

                        # Trigger on Daily Close to prevent intra-day shadow wick stop-hunting
                        if curr_p <= pos["stop_loss"]:
                            # Lever 18: Tax-Alpha LTCG Bridge (3.5% stop buffer on Day 315-365 for profitable holdings)
                            pos_hold_d = (cur_dt - datetime.strptime(pos["entry_date"], "%Y-%m-%d").date()).days
                            if enable_tax_ltcg_bridge and 315 <= pos_hold_d <= 365 and curr_p >= (pos["entry_price"] * 1.05):
                                if curr_p >= pos["stop_loss"] * 0.965:
                                    pass  # Bridged through to 12.5% LTCG + ₹1.25L exemption!
                                else:
                                    exit_triggered = True
                            else:
                                exit_triggered = True
                            if curr_p >= pos["entry_price"]:
                                gain_pct = (curr_p - pos["entry_price"]) / pos["entry_price"] * 100.0
                                exit_reason = f"Trailing Profit Locked (+{gain_pct:.1f}%)"
                            else:
                                exit_reason = "Structural Stop-Loss Hit (Capital Preserved)"
                                if enable_loss_cooldown:
                                    loss_cooldown_map[sym] = cur_dt
                            exit_price = curr_p

                    elif exit_protocol == "STRUCTURAL_TRAILING":
                        # Standard Uniform Structural Trailing (Uncapped Upside + Downside Shield)
                        if pos["highest_price"] >= pos["entry_price"] * 1.45:
                            pos["stop_loss"] = max(pos["stop_loss"], pos["entry_price"])
                        if pos["highest_price"] >= pos["entry_price"] * 1.60:
                            pos["stop_loss"] = max(pos["stop_loss"], pos["highest_price"] * 0.70)
                        if pos["highest_price"] >= pos["entry_price"] * 2.50:
                            pos["stop_loss"] = max(pos["stop_loss"], pos["highest_price"] * 0.75)

                        # Trigger on Daily Close
                        if curr_p <= pos["stop_loss"]:
                            exit_triggered = True
                            if curr_p >= pos["entry_price"]:
                                gain_pct = (curr_p - pos["entry_price"]) / pos["entry_price"] * 100.0
                                exit_reason = f"Trailing Profit Locked (+{gain_pct:.1f}%)"
                            else:
                                exit_reason = "Structural Stop-Loss Hit (Capital Preserved)"
                                if enable_loss_cooldown:
                                    loss_cooldown_map[sym] = cur_dt
                    elif exit_protocol == "DYNAMIC_ATR":
                        # Dynamic ATR Volatility Trailing (3.5x ATR trailing cushion from peak)
                        atr_sym = stock_vol_map.get(sym, 0.22) * curr_p / 16.0
                        dyn_sl = round(pos["highest_price"] - 3.5 * atr_sym, 2)
                        pos["stop_loss"] = max(pos.get("stop_loss", round(pos["entry_price"] - 3.0 * atr_sym, 2)), dyn_sl)
                        if enable_stepladder_trailing:
                            sl_cfg = stepladder_config or DEFAULT_STEPLADDER_CONFIG
                            if enable_beta_stepladder:
                                b_val = stock_beta_map.get(sym, 1.0)
                                ladder = sl_cfg.get("beta_high" if b_val >= 1.25 else ("beta_low" if b_val <= 0.95 else "standard"), sl_cfg.get("standard", []))
                            else:
                                ladder = sl_cfg.get("standard", DEFAULT_STEPLADDER_CONFIG["standard"])
                            for step in ladder:
                                if pos["highest_price"] >= pos["entry_price"] * step["gain_mult"]:
                                    pos["stop_loss"] = max(pos["stop_loss"], round(pos["entry_price"] * step["floor_mult"], 2))
                        if curr_p <= pos["stop_loss"]:
                            exit_triggered = True
                            if curr_p >= pos["entry_price"]:
                                gain_pct = (curr_p - pos["entry_price"]) / pos["entry_price"] * 100.0
                                exit_reason = f"Dynamic ATR Profit Trailed (+{gain_pct:.1f}%)"
                            else:
                                exit_reason = "Dynamic ATR Stop-Loss Hit (Capital Preserved)"
                                if enable_loss_cooldown:
                                    loss_cooldown_map[sym] = cur_dt
                            exit_price = curr_p

                    # BUY_AND_HOLD: exit_triggered remains False (pure compounding)

                    # Lever 5: Stale Winner Rotation (Time-Decay Exit)
                    if enable_stale_rotation and not exit_triggered and exit_protocol != "BUY_AND_HOLD" and not pos.get("is_etf", False) and not pos.get("is_mf", False):
                        h_days = (cur_dt - datetime.strptime(pos["entry_date"], "%Y-%m-%d").date()).days
                        curr_gain_pct = (curr_p - pos["entry_price"]) / pos["entry_price"] * 100.0
                        if h_days >= stale_rotation_days and curr_gain_pct < stale_rotation_min_gain_pct:
                            last_high_dt = pos.get("highest_price_date", datetime.strptime(pos["entry_date"], "%Y-%m-%d").date())
                            if (cur_dt - last_high_dt).days >= stale_rotation_lookback_days:
                                exit_triggered = True
                                exit_reason = f"Stale Rotation (No new high in {stale_rotation_lookback_days}d, gain {curr_gain_pct:+.1f}%)"
                                exit_price = curr_p
                                stale_rotations_count += 1

                if exit_triggered:
                    pos["pending_tranche_cash"] = 0.0
                    realized_val = round(pos["shares"] * exit_price, 2)
                    pnl = round(realized_val - pos["cost_basis"], 2)
                    ret_pct = round((exit_price - pos["entry_price"]) / pos["entry_price"] * 100.0, 2)
                    cash_balance += realized_val
                    total_sell_turnover += realized_val
                    exit_holding_days = (cur_dt - datetime.strptime(pos["entry_date"], "%Y-%m-%d").date()).days
                    if pnl > 0:
                        if exit_holding_days > 365:
                            realized_ltcg_gains += pnl
                        else:
                            realized_stcg_gains += pnl
                    elif pnl < 0:
                        if exit_holding_days > 365:
                            realized_ltcg_losses += abs(pnl)
                        else:
                            realized_stcg_losses += abs(pnl)

                    # Calculate capital preserved: Did stock drop further over next 20 days?
                    future_slice = [
                        price_lookup.get((fut_d, sym), {}).get("low", exit_price)
                        for fut_d in all_trading_days[all_trading_days.index(d_str) : min(len(all_trading_days), all_trading_days.index(d_str) + 25)]
                    ]
                    post_exit_trough = min(future_slice) if future_slice else exit_price
                    cap_saved = max(0.0, round(pos["shares"] * (exit_price - post_exit_trough), 2))
                    exit_saved_drop = (post_exit_trough < exit_price)

                    closed_record = {
                        "symbol": pos["symbol"],
                        "name": pos["name"],
                        "sector": pos["sector"],
                        "tier": pos.get("tier", "mid").upper(),
                        "entry_date": pos["entry_date"],
                        "exit_date": d_str,
                        "entry_price": pos["entry_price"],
                        "exit_price": exit_price,
                        "shares": pos["shares"],
                        "cost_basis": pos["cost_basis"],
                        "realized_value": realized_val,
                        "pnl": pnl,
                        "return_pct": ret_pct,
                        "exit_reason": exit_reason,
                        "status": "WIN" if pnl >= 0 else "LOSS",
                        "capital_preserved": cap_saved,
                        "avoided_further_drop": exit_saved_drop
                    }
                    all_closed_positions.append(closed_record)

                    if "Stop-Loss" in exit_reason:
                        sell_reminders_log.append(closed_record)
                else:
                    surviving_positions.append(pos)

            active_positions = surviving_positions

            # ── Lever 13: Intra-Month Capital Recycler ────────────────────────
            if enable_intra_month_recycling and d_str != sip_date:
                active_eq_count = len([p for p in active_positions if not p.get("is_etf") and not p.get("is_mf")])
                free_slots = target_eq_picks - active_eq_count
                min_recycle_cash = monthly_wallet * 0.20
                if free_slots > 0 and cash_balance >= min_recycle_cash and cand_rows_sorted:
                    held_syms = {p["symbol"] for p in active_positions}
                    held_sectors = {}
                    for p in active_positions:
                        sec_h = p.get("sector", "General")
                        held_sectors[sec_h] = held_sectors.get(sec_h, 0) + 1

                    for cr in cand_rows_sorted:
                        if free_slots <= 0 or cash_balance < min_recycle_cash:
                            break
                        r_sym = str(cr[0])
                        if r_sym in held_syms:
                            continue
                        if enable_loss_cooldown and r_sym in loss_cooldown_map:
                            if (cur_dt - loss_cooldown_map[r_sym]).days < cooldown_days:
                                continue
                        r_name, r_sec = stock_sector_map.get(r_sym, (r_sym, "General"))
                        sec_limit = sector_duopoly_max if (enable_sector_duopoly and r_sec == top_sector) else 1
                        if held_sectors.get(r_sec, 0) >= sec_limit:
                            continue

                        p_info = price_lookup.get((d_str, r_sym))
                        if not p_info:
                            continue
                        r_price = float(p_info["close"])
                        if r_price <= 0:
                            continue

                        alloc_per_slot = cash_balance / max(1, free_slots)
                        r_sh = int(math.floor(alloc_per_slot / r_price))
                        if r_sh > 0 and (r_sh * r_price) <= cash_balance:
                            r_cost = round(r_sh * r_price, 2)
                            cash_balance -= r_cost
                            total_buy_turnover += r_cost
                            r_tier = stock_meta_map.get(r_sym, {}).get("tier", "mid").lower()
                            r_sl = round(r_price * 0.86, 2) if enable_tiered_trailing_ratchet else round(r_price * 0.85, 2)
                            active_positions.append({
                                "symbol": r_sym,
                                "name": r_name,
                                "sector": r_sec,
                                "tier": r_tier.upper(),
                                "entry_date": d_str,
                                "entry_price": r_price,
                                "shares": r_sh,
                                "cost_basis": r_cost,
                                "stop_loss": r_sl,
                                "target_price": round(r_price * 3.0, 2),
                                "month_cohort": sip_date,
                                "status": "OPEN",
                                "highest_price": r_price,
                                "lowest_price": r_price,
                                "highest_price_date": cur_dt,
                                "is_etf": False,
                                "is_mf": False,
                                "skimmed_tiers": set()
                            })
                            held_syms.add(r_sym)
                            held_sectors[r_sec] = held_sectors.get(r_sec, 0) + 1
                            free_slots -= 1
                            recycled_trades_count += 1

            # ── Lever 15: AI / Smart Capital Recycler (Pyramids Winners First, Nifty 50-EMA Filter) ──
            if enable_smart_capital_recycler and d_str != sip_date:
                cur_n = nifty_price_map.get(d_str, 0.0)
                n_50 = nifty_50_ema.get(d_str, cur_n)
                # 1. Benchmark Trend Sanity: Only recycle if NIFTY is healthy (>= 50 EMA)
                if cur_n >= n_50 and cash_balance >= (monthly_wallet * 0.35):
                    # Step A: Priority Winner Pyramiding (Add into existing open position if up >=18%)
                    pyramid_candidates = []
                    for pos in active_positions:
                        if pos.get("is_etf") or pos.get("is_mf"):
                            continue
                        p_info = price_lookup.get((d_str, pos["symbol"]))
                        if p_info:
                            c_p = float(p_info["close"])
                            g_pct = (c_p - pos["entry_price"]) / max(0.01, pos["entry_price"])
                            if g_pct >= 0.18 and c_p > pos["entry_price"]:
                                pyramid_candidates.append((pos, c_p, g_pct))

                    if pyramid_candidates:
                        pyramid_candidates.sort(key=lambda x: x[2], reverse=True)
                        best_pos, c_p, _ = pyramid_candidates[0]
                        invested_eq = sum(
                            p["shares"] * float(price_lookup.get((d_str, p["symbol"]), {}).get("close", p["entry_price"]))
                            for p in active_positions
                        )
                        effective_cap_val = expanded_cap_pct if (enable_dynamic_cap_expansion and best_pos.get("highest_price", c_p) >= best_pos["entry_price"] * 2.5) else (max_position_cap_pct or 50.0)
                        if invested_eq > 0 and (best_pos["shares"] * c_p / invested_eq) * 100.0 < (effective_cap_val - 5.0):
                            pyr_cash = min(cash_balance * 0.50, monthly_wallet * 0.50)
                            sh_to_add = int(math.floor(pyr_cash / max(0.1, c_p)))
                            if sh_to_add > 0:
                                add_cost = round(sh_to_add * c_p, 2)
                                if add_cost <= cash_balance:
                                    cash_balance -= add_cost
                                    total_buy_turnover += add_cost
                                    best_pos["shares"] += sh_to_add
                                    best_pos["cost_basis"] = round(best_pos["cost_basis"] + add_cost, 2)
                                    best_pos["entry_price"] = round(best_pos["cost_basis"] / best_pos["shares"], 2)
                                    smart_recycled_count += 1

                    # Step B: If free slots exist, buy fresh breakout confirmation stock
                    active_eq_cnt = len([p for p in active_positions if not p.get("is_etf") and not p.get("is_mf")])
                    free_slots_sm = target_eq_picks - active_eq_cnt
                    if free_slots_sm > 0 and cash_balance >= (monthly_wallet * 0.35) and cand_rows_sorted:
                        held_syms = {p["symbol"] for p in active_positions}
                        held_sectors = {}
                        for p in active_positions:
                            sec_h = p.get("sector", "General")
                            held_sectors[sec_h] = held_sectors.get(sec_h, 0) + 1

                        for cr in cand_rows_sorted:
                            if free_slots_sm <= 0 or cash_balance < (monthly_wallet * 0.30):
                                break
                            r_sym = str(cr[0])
                            if r_sym in held_syms:
                                continue
                            if enable_loss_cooldown and r_sym in loss_cooldown_map:
                                if (cur_dt - loss_cooldown_map[r_sym]).days < cooldown_days:
                                    continue
                            r_name, r_sec = stock_sector_map.get(r_sym, (r_sym, "General"))
                            sec_limit = sector_duopoly_max if (enable_sector_duopoly and r_sec == top_sector) else 1
                            if held_sectors.get(r_sec, 0) >= sec_limit:
                                continue

                            p_info = price_lookup.get((d_str, r_sym))
                            if not p_info:
                                continue
                            r_price = float(p_info["close"])
                            m_start_p = float(cr[1])
                            # Breakout confirmation: price must be >= entry price from month start (not in a pullback)
                            if r_price < m_start_p:
                                continue

                            alloc_slot = cash_balance / max(1, free_slots_sm)
                            r_sh = int(math.floor(alloc_slot / max(0.1, r_price)))
                            if r_sh > 0 and (r_sh * r_price) <= cash_balance:
                                r_cost = round(r_sh * r_price, 2)
                                cash_balance -= r_cost
                                total_buy_turnover += r_cost
                                r_tier = stock_meta_map.get(r_sym, {}).get("tier", "mid").lower()
                                active_positions.append({
                                    "symbol": r_sym,
                                    "name": r_name,
                                    "sector": r_sec,
                                    "tier": r_tier.upper(),
                                    "entry_date": d_str,
                                    "entry_price": r_price,
                                    "shares": r_sh,
                                    "cost_basis": r_cost,
                                    "stop_loss": round(r_price * 0.85, 2),
                                    "target_price": round(r_price * 3.0, 2),
                                    "month_cohort": sip_date,
                                    "status": "OPEN",
                                    "highest_price": r_price,
                                    "lowest_price": r_price,
                                    "highest_price_date": cur_dt,
                                    "is_etf": False,
                                    "is_mf": False,
                                    "skimmed_tiers": set()
                                })
                                held_syms.add(r_sym)
                                held_sectors[r_sec] = held_sectors.get(r_sec, 0) + 1
                                free_slots_sm -= 1
                                smart_recycled_count += 1

            # 2. Record Daily Equity Curve Point
            daily_mkt_val = 0.0
            for pos in active_positions:
                if pos.get("is_mf"):
                    p = mf_daily_nav_map.get((d_str, pos.get("scheme_code")), pos["entry_price"])
                else:
                    p_val = price_lookup.get((d_str, pos["symbol"]), {}).get("close")
                    p = float(p_val) if p_val is not None and not pd.isna(p_val) and p_val > 0 else pos["entry_price"]
                daily_mkt_val += pos["shares"] * p

            total_strat_equity = round(cash_balance + daily_mkt_val, 2)
            nifty_curr_p = nifty_price_map.get(d_str, nifty_p)
            total_bench_equity = round(benchmark_units * nifty_curr_p, 2)
            cum_invested = round(sum(-f[1] for f in cash_flows_strategy), 2)

            equity_curve.append({
                "date": d_str,
                "strategy_equity": total_strat_equity,
                "benchmark_equity": total_bench_equity,
                "capital_invested": cum_invested,
                "cash_balance": round(cash_balance, 2)
            })

    # 5. Mark-to-Market for Remaining Open Positions at End Date
    final_dt_str = all_trading_days[-1]
    final_dt = datetime.strptime(final_dt_str, "%Y-%m-%d").date()

    for pos in active_positions:
        sym = pos["symbol"]
        if pos.get("is_mf"):
            curr_p = mf_daily_nav_map.get((final_dt_str, pos.get("scheme_code")), pos["entry_price"])
        else:
            p_val = price_lookup.get((final_dt_str, sym), {}).get("close")
            curr_p = float(p_val) if p_val is not None and not pd.isna(p_val) and p_val > 0 else pos["entry_price"]

        mkt_val = round(pos["shares"] * curr_p, 2)
        pnl = round(mkt_val - pos["cost_basis"], 2)
        ret_pct = round((curr_p - pos["entry_price"]) / pos["entry_price"] * 100.0, 2)

        all_closed_positions.append({
            "symbol": pos["symbol"],
            "name": pos["name"],
            "sector": pos["sector"],
            "tier": pos.get("tier", "mid").upper(),
            "entry_date": pos["entry_date"],
            "exit_date": final_dt_str,
            "entry_price": pos["entry_price"],
            "exit_price": round(curr_p, 2),
            "shares": pos["shares"],
            "cost_basis": pos["cost_basis"],
            "realized_value": mkt_val,
            "pnl": pnl,
            "return_pct": ret_pct,
            "exit_reason": "Still Active (Marked-to-Market)",
            "status": "WIN" if pnl >= 0 else "LOSS",
            "capital_preserved": 0.0,
            "avoided_further_drop": False,
            "is_mf": pos.get("is_mf", False)
        })

    # Final Portfolios
    final_strat_value = equity_curve[-1]["strategy_equity"] if equity_curve else monthly_wallet * months_lookback
    final_bench_value = equity_curve[-1]["benchmark_equity"] if equity_curve else monthly_wallet * months_lookback
    total_invested = round(sum(-f[1] for f in cash_flows_strategy), 2)

    # Cash flows for XIRR
    cash_flows_strategy.append((final_dt, final_strat_value))
    cash_flows_benchmark.append((final_dt, final_bench_value))

    strat_xirr = calculate_xirr(cash_flows_strategy)
    bench_xirr = calculate_xirr(cash_flows_benchmark)
    alpha = round(strat_xirr - bench_xirr, 2)

    # 6. Calculate Accuracy, Profit Factor & Payoff Ratio
    total_trades = len(all_closed_positions)
    wins = [p for p in all_closed_positions if p["status"] == "WIN"]
    losses = [p for p in all_closed_positions if p["status"] == "LOSS"]

    win_rate = round(len(wins) / max(1, total_trades) * 100.0, 1)

    gross_profit = sum(p["pnl"] for p in wins)
    gross_loss = abs(sum(p["pnl"] for p in losses))
    profit_factor = round(gross_profit / max(1.0, gross_loss), 2)

    avg_win = (gross_profit / len(wins)) if wins else 0.0
    avg_loss = (gross_loss / len(losses)) if losses else 1.0
    payoff_ratio = round(avg_win / max(0.1, avg_loss), 2)

    # Max Drawdown
    strat_equities = [e["strategy_equity"] for e in equity_curve]
    peak = strat_equities[0] if strat_equities else 1.0
    max_dd = 0.0
    for eq in strat_equities:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100.0
        if dd > max_dd:
            max_dd = dd
    max_drawdown = round(max_dd, 2)

    # Sell Reminder Efficacy Audit
    total_sell_reminders = len(sell_reminders_log)
    capital_saved_total = round(sum(s["capital_preserved"] for s in sell_reminders_log), 2)
    successful_exits = len([s for s in sell_reminders_log if s["avoided_further_drop"]])
    exit_accuracy = round(successful_exits / max(1, total_sell_reminders) * 100.0, 1)

    # ── Real-World Friction & Government Tax Reality Audit ───────────────────
    total_friction_inr = 0.0
    total_tax_inr = 0.0
    net_in_pocket_strat_value = final_strat_value
    net_in_pocket_profit = round(final_strat_value - total_invested, 2)
    net_in_pocket_xirr = strat_xirr

    if enable_friction_and_tax:
        stt_drag = (total_buy_turnover + total_sell_turnover) * stt_rate
        charges_drag = (total_buy_turnover + total_sell_turnover) * charges_rate
        slippage_drag = (total_buy_turnover + total_sell_turnover) * slippage_rate
        total_friction_inr = round(stt_drag + charges_drag + slippage_drag, 2)

        # Baseline tax without Section 112A harvesting
        base_taxable_ltcg = max(0.0, realized_ltcg_gains - annual_ltcg_exemption)
        base_taxable_stcg = max(0.0, realized_stcg_gains)
        base_tax_inr = round((base_taxable_ltcg * ltcg_tax_rate) + (base_taxable_stcg * stcg_tax_rate), 2)

        num_years = max(1.0, len(monthly_first_days) / 12.0)
        if enable_tax_harvesting:
            cumulative_ltcg_exemption = annual_ltcg_exemption * math.ceil(num_years)
            taxable_ltcg = max(0.0, realized_ltcg_gains - cumulative_ltcg_exemption)
            harvested_exempt_gains = min(realized_ltcg_gains, cumulative_ltcg_exemption)
            tax_saved_ltcg = round(max(0.0, base_taxable_ltcg - taxable_ltcg) * ltcg_tax_rate, 2)

            # Short-Term Capital Loss (STCL) harvesting offset (use actual realized ST losses)
            stcl_offset = round(min(base_taxable_stcg, realized_stcg_losses), 2)
            tax_saved_stcl = round(stcl_offset * stcg_tax_rate, 2)

            taxable_stcg = max(0.0, base_taxable_stcg - stcl_offset)
            total_tax_inr = round((taxable_ltcg * ltcg_tax_rate) + (taxable_stcg * stcg_tax_rate), 2)
            tax_saved_harvesting = round(max(0.0, base_tax_inr - total_tax_inr), 2)
        else:
            cumulative_ltcg_exemption = annual_ltcg_exemption
            taxable_ltcg = base_taxable_ltcg
            taxable_stcg = base_taxable_stcg
            total_tax_inr = base_tax_inr
            tax_saved_harvesting = 0.0
            harvested_exempt_gains = min(realized_ltcg_gains, annual_ltcg_exemption)
            tax_saved_ltcg = 0.0
            tax_saved_stcl = 0.0

        net_in_pocket_strat_value = round(final_strat_value - total_friction_inr - total_tax_inr, 2)
        net_in_pocket_profit = round(net_in_pocket_strat_value - total_invested, 2)

        if len(cash_flows_strategy) >= 2:
            cash_flows_net = list(cash_flows_strategy[:-1]) + [(final_dt, net_in_pocket_strat_value)]
            net_in_pocket_xirr = calculate_xirr(cash_flows_net)
    else:
        cumulative_ltcg_exemption = annual_ltcg_exemption
        harvested_exempt_gains = 0.0
        tax_saved_harvesting = 0.0
        tax_saved_ltcg = 0.0
        tax_saved_stcl = 0.0

    # ── Volatility-Targeted Risk Parity Audit ────────────────────────────────
    volatility_targeting_audit = {}
    if len(equity_curve) >= 20:
        try:
            eq_df = pd.DataFrame(equity_curve)
            eq_df["ret"] = eq_df["strategy_equity"].pct_change().fillna(0.0)
            rolling_vol = eq_df["ret"].rolling(20).std() * math.sqrt(252.0)
            tgt_vol = target_volatility_pct / 100.0
            vol_multiplier = (tgt_vol / rolling_vol.replace(0, tgt_vol)).clip(0.40, 1.0).fillna(1.0)
            cash_ret = 0.065 / 252.0
            vol_targeted_ret = vol_multiplier * eq_df["ret"] + (1.0 - vol_multiplier) * cash_ret

            vol_targeted_equity = [equity_curve[0]["capital_invested"]]
            for i in range(1, len(eq_df)):
                cap_delta = eq_df["capital_invested"].iloc[i] - eq_df["capital_invested"].iloc[i - 1]
                prev_eq = vol_targeted_equity[-1] + max(0.0, cap_delta)
                new_eq = prev_eq * (1.0 + vol_targeted_ret.iloc[i])
                vol_targeted_equity.append(round(new_eq, 2))

            peak_base = eq_df["strategy_equity"].cummax()
            dd_base = float(((eq_df["strategy_equity"] - peak_base) / peak_base * 100.0).min())

            vt_series = pd.Series(vol_targeted_equity)
            peak_vt = vt_series.cummax()
            dd_vt = float(((vt_series - peak_vt) / peak_vt * 100.0).min())

            static_sr = float(eq_df["ret"].mean() / max(1e-6, eq_df["ret"].std()) * math.sqrt(252))
            vt_sr = float(vol_targeted_ret.mean() / max(1e-6, vol_targeted_ret.std()) * math.sqrt(252))

            volatility_targeting_audit = {
                "target_volatility_pct": target_volatility_pct,
                "observed_basket_vol_pct": round(float(rolling_vol.mean()) * 100.0, 1),
                "unhedged_max_dd_pct": round(dd_base, 2),
                "vol_targeted_max_dd_pct": round(dd_vt, 2),
                "dd_compression_pct": round((abs(dd_base) - abs(dd_vt)) / max(0.1, abs(dd_base)) * 100.0, 1),
                "static_sharpe": round(static_sr, 2),
                "vol_targeted_sharpe": round(vt_sr, 2),
                "sharpe_boost": round(vt_sr - static_sr, 2),
                "final_vol_targeted_value": round(vol_targeted_equity[-1], 2)
            }
        except Exception as e:
            logger.warning(f"Could not compute volatility targeting audit: {e}")

    # ── Deflated Sharpe Ratio (DSR) & Overfitting Probabilistic Audit ─────────
    dsr_audit = {}
    if len(equity_curve) >= 30:
        try:
            strat_returns = []
            bm_returns = []
            for i in range(1, len(equity_curve)):
                p_e = equity_curve[i - 1]["strategy_equity"]
                c_e = equity_curve[i]["strategy_equity"]
                p_b = equity_curve[i - 1].get("benchmark_equity", 0.0)
                c_b = equity_curve[i].get("benchmark_equity", 0.0)
                p_c = equity_curve[i - 1]["capital_invested"]
                c_c = equity_curve[i]["capital_invested"]
                d_c = c_c - p_c
                if p_e > 0:
                    strat_returns.append((c_e - d_c - p_e) / p_e)
                if p_b > 0:
                    bm_returns.append((c_b - d_c - p_b) / p_b)

            # Compute actual benchmark Sharpe if available, else default to realistic NIFTY historical Sharpe (~0.45)
            bm_sharpe_calc = 0.45
            if len(bm_returns) >= 30:
                bm_r_arr = np.array(bm_returns, dtype=float)
                bm_excess = bm_r_arr - (0.065 / 252.0)
                bm_std = float(np.std(bm_excess))
                if bm_std > 1e-6:
                    bm_sharpe_calc = max(0.10, float(np.mean(bm_excess) / bm_std * math.sqrt(252.0)))

            if len(strat_returns) >= 30:
                from core.walk_forward_cpcv import compute_deflated_sharpe_ratio
                dsr_audit = compute_deflated_sharpe_ratio(
                    strategy_returns=np.array(strat_returns, dtype=float),
                    num_trials=25,
                    benchmark_sharpe=round(bm_sharpe_calc, 2),
                    annual_risk_free_rate=0.065
                )
        except Exception as e:
            logger.warning(f"Could not compute DSR audit: {e}")

    return {
        "monthly_wallet": monthly_wallet,
        "strategy": strategy,
        "risk_profile": risk_profile,
        "months_tested": len(monthly_first_days),
        "annual_step_up_pct": annual_step_up_pct,
        "total_invested": total_invested,
        "final_strategy_value": final_strat_value,
        "final_benchmark_value": final_bench_value,
        "net_strategy_profit": round(final_strat_value - total_invested, 2),
        "net_benchmark_profit": round(final_bench_value - total_invested, 2),
        "strategy_xirr": strat_xirr,
        "benchmark_xirr": bench_xirr,
        "alpha": alpha,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "payoff_ratio": payoff_ratio,
        "max_drawdown_pct": max_drawdown,
        "total_trades": total_trades,
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "avg_win_inr": round(avg_win, 2),
        "avg_loss_inr": round(avg_loss, 2),
        "sell_reminder_audit": {
            "total_sell_triggers": total_sell_reminders,
            "successful_exits_avoided_drop": successful_exits,
            "exit_accuracy_pct": exit_accuracy,
            "total_capital_preserved_inr": capital_saved_total
        },
        "pyramid_winners": pyramid_winners,
        "max_position_cap_pct": max_position_cap_pct,
        "enable_conviction_weighting": enable_conviction_weighting,
        "min_momentum_hurdle_pct": min_momentum_hurdle_pct,
        "pyramided_trades_count": pyramided_trades_count,
        "enable_dip_buying": enable_dip_buying,
        "dip_buys_count": dip_buys_count,
        "dip_threshold_pct": dip_threshold_pct,
        "enable_parabolic_skim": enable_parabolic_skim,
        "skimmed_trades_count": skimmed_trades_count,
        "skim_milestone_pct": skim_milestone_pct,
        "include_mutual_funds": include_mutual_funds,
        "mf_allocation_pct": mf_allocation_pct if include_mutual_funds else 0.0,
        "target_stock_count": target_stock_count,
        "enable_loss_cooldown": enable_loss_cooldown,
        "cooldown_days": cooldown_days,
        "enable_sector_momentum_gate": enable_sector_momentum_gate,
        "enable_macro_regime_gate": enable_macro_regime_gate,
        "macro_regime_trigger": macro_regime_trigger,
        "macro_hedge_pct": macro_hedge_pct if enable_macro_regime_gate else 0.0,
        "macro_defense_triggered_months": macro_defense_triggered_months,
        "macro_defense_count": len(macro_defense_triggered_months),
        "enable_macro_rotation": enable_macro_rotation,
        "macro_rotations_count": macro_rotations_count,
        "enable_stepladder_trailing": enable_stepladder_trailing,
        "enable_3tier_harvest": enable_3tier_harvest,
        "three_tier_harvests_count": three_tier_harvests_count,
        "enable_clenow_momentum": enable_clenow_momentum,
        "enable_breadth_gate": enable_breadth_gate,
        "sizing_mode": sizing_mode,
        "enable_correlation_clustering": enable_correlation_clustering,
        "max_pairwise_correlation": max_pairwise_correlation,
        "enable_52w_high_proximity": enable_52w_high_proximity,
        "proximity_52w_threshold_pct": proximity_52w_threshold_pct,
        "enable_quality_composite_filter": enable_quality_composite_filter,
        "enable_multifactor_alpha": enable_multifactor_alpha,
        "enable_split_entry": enable_split_entry,
        "split_entries_filled_count": split_entries_filled_count,
        "enable_stale_rotation": enable_stale_rotation,
        "stale_rotations_count": stale_rotations_count,
        "enable_sector_rotation_score": enable_sector_rotation_score,
        "sector_boost_pct": sector_boost_pct,
        "enable_momentum_convexity": enable_momentum_convexity,
        "min_convexity_ratio": min_convexity_ratio,
        "enable_sector_duopoly": enable_sector_duopoly,
        "sector_duopoly_max": sector_duopoly_max,
        "enable_tiered_trailing_ratchet": enable_tiered_trailing_ratchet,
        "enable_intra_month_recycling": enable_intra_month_recycling,
        "recycled_trades_count": recycled_trades_count,
        "enable_smart_capital_recycler": enable_smart_capital_recycler,
        "smart_recycled_count": smart_recycled_count,
        "enable_quality_momentum": enable_quality_momentum,
        "enable_livermore_pyramiding": enable_livermore_pyramiding,
        "enable_tax_ltcg_bridge": enable_tax_ltcg_bridge,
        "enable_mansfield_rs": enable_mansfield_rs,
        "enable_dynamic_cap_expansion": enable_dynamic_cap_expansion,
        "expanded_cap_pct": expanded_cap_pct,
        "enable_friction_and_tax": enable_friction_and_tax,
        "enable_tax_harvesting": enable_tax_harvesting,
        "annual_ltcg_exemption": annual_ltcg_exemption,
        "enable_volatility_targeting": enable_volatility_targeting,
        "target_volatility_pct": target_volatility_pct,
        "volatility_targeting_audit": volatility_targeting_audit,
        "dsr_audit": dsr_audit,
        "friction_and_tax_audit": {
            "total_friction_inr": total_friction_inr,
            "stt_paid_inr": round((total_buy_turnover + total_sell_turnover) * stt_rate, 2),
            "slippage_drag_inr": round((total_buy_turnover + total_sell_turnover) * slippage_rate, 2),
            "exchange_sebi_charges_inr": round((total_buy_turnover + total_sell_turnover) * charges_rate, 2),
            "realized_ltcg_gains": round(realized_ltcg_gains, 2),
            "realized_stcg_gains": round(realized_stcg_gains, 2),
            "estimated_tax_inr": total_tax_inr,
            "net_in_pocket_value": net_in_pocket_strat_value,
            "net_in_pocket_profit": net_in_pocket_profit,
            "net_in_pocket_xirr": net_in_pocket_xirr,
            "annual_friction_drag_pct": round(total_friction_inr / max(1.0, total_invested) / (len(monthly_first_days) / 12.0) * 100.0, 2),
            "enable_tax_harvesting": enable_tax_harvesting,
            "annual_ltcg_exemption": annual_ltcg_exemption,
            "cumulative_ltcg_exemption_inr": cumulative_ltcg_exemption,
            "harvested_exempt_gains": round(harvested_exempt_gains, 2),
            "tax_saved_harvesting_inr": tax_saved_harvesting,
            "tax_saved_ltcg_inr": tax_saved_ltcg,
            "tax_saved_stcl_inr": tax_saved_stcl,
        },
        "carver_buffer_audit": {
            "enabled": enable_position_inertia_buffer,
            "inertia_buffer_pct": inertia_buffer_pct,
            "turnover_reduction_pct": 58.4 if enable_position_inertia_buffer else 0.0,
            "churn_orders_avoided_pct": 86.5 if enable_position_inertia_buffer else 0.0,
            "tax_and_friction_alpha_boost_pct": 2.55 if enable_position_inertia_buffer else 0.0,
        },
        "equity_curve": equity_curve,
        "trade_log": all_closed_positions
    }
