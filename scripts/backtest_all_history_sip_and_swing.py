"""
scripts/backtest_all_history_sip_and_swing.py

Comprehensive 12-Year Multi-Regime Historical Backtest (2015 - 2026):
Evaluates the Current Best Strategies for:
  1. SIP:
     - Pure Centurion Wealth Engine (Default Champion)
     - SIP_088024 (Fortress Clenow Alpha)
     - Apex Concentrated Compounder (SIP_00769)
     - Switch 5: Dynamic Core Blend (75/25 Bull -> 25/75 Bear)
     - Market Equal-Weight Index SIP (Benchmark)

  2. SWING:
     - Recommended Champion: SW_005479 (Alpha) + SW_000640 (Fortress Shield)
     - SW_005479 (Pure Alpha Champion - 3 Slots, Multi-Lookback, Pyramiding, No Bear Sweep)
     - SW_000640 (Pure Fortress Shield - 5 Slots, Defensive Regimes)
     - Classic 8-Slot Diversified Swing (12.5% Slots, 2x ATR SL, Standard 1:2 RR)
     - Market Buy & Hold Benchmark

Evaluated Across All Historical Market Classes:
  - Phase 1: Full 11.75-Year All-History Cycle (2015 - 2026)
  - Phase 2: Structural Bull Supercycle (2017)
  - Phase 3: Severe Small/Midcap Crash (2018)
  - Phase 4: Extreme Covid Crash (Feb - Mar 2020)
  - Phase 5: Post-Covid Liquidity Super-Bull (2020 - 2021)
  - Phase 6: High-Inflation / Ukraine War Chop (2022)
  - Phase 7: Broad-Market Momentum Expansion (2023)
  - Phase 8: Recent Multi-Regime Cycle (2024 - 2026)
"""
import sys
import math
import time
import logging
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional

import pandas as pd
import numpy as np
from sqlalchemy import text

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from db.database import get_session, get_global_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s")
logger = logging.getLogger("historical_backtest")


def calculate_xirr(cash_flows: List[Tuple[date, float]]) -> float:
    """Calculates annualized internal rate of return using Newton-Raphson."""
    if not cash_flows or len(cash_flows) < 2:
        return 0.0

    dates, amounts = zip(*cash_flows)
    d0 = dates[0]
    days = [(d - d0).days for d in dates]

    def npv(rate):
        if rate <= -0.9999:
            return float('inf')
        return sum(a / ((1.0 + rate) ** (day / 365.0)) for a, day in zip(amounts, days))

    def d_npv(rate):
        if rate <= -0.9999:
            return float('-inf')
        return sum(- (day / 365.0) * a / ((1.0 + rate) ** (day / 365.0 + 1.0)) for a, day in zip(amounts, days))

    # Fast Newton's method
    rate = 0.15
    for _ in range(60):
        val = npv(rate)
        dval = d_npv(rate)
        if abs(dval) < 1e-12:
            break
        new_rate = rate - val / dval
        if abs(new_rate - rate) < 1e-6:
            return round(new_rate * 100.0, 2)
        rate = new_rate
        if rate < -0.95:
            rate = -0.95
        elif rate > 10.0:
            rate = 10.0

    # Fallback to simple CAGR if xirr fails to converge
    total_invested = sum(-a for a in amounts if a < 0)
    final_val = amounts[-1]
    total_days = max(1, days[-1])
    if total_invested > 0 and final_val > 0:
        cagr = ((final_val / total_invested) ** (365.0 / total_days) - 1.0) * 100.0
        return round(cagr, 2)
    return 0.0


def calculate_max_drawdown(equity_series: List[float]) -> float:
    """Calculates peak-to-trough max drawdown percentage."""
    filtered = [v for v in equity_series if v is not None and not np.isnan(v) and v > 100.0]
    if not filtered or len(filtered) < 2:
        return 0.0
    peak = filtered[0]
    max_dd = 0.0
    for val in filtered:
        if val > peak:
            peak = val
        if peak > 0:
            dd = (peak - val) / peak * 100.0
            if dd > max_dd:
                max_dd = dd
    return round(max_dd, 2)



def load_universe_data(start_date: str = "2014-01-01"):
    """Loads historical prices and metadata for all liquid stocks."""
    logger.info("Loading historical price matrix from SQLite database...")
    t0 = time.time()
    session = get_session(get_global_engine())
    try:
        q = f"""
            SELECT p.symbol, p.date, p.open, p.high, p.low, p.close, p.volume,
                   s.name, s.sector, s.market_cap_tier
            FROM daily_prices p
            JOIN stocks s ON p.symbol = s.symbol
            WHERE p.date >= '{start_date}'
              AND p.symbol NOT IN ('^NSEI', 'NIFTY 50', 'NIFTY')
            ORDER BY p.date ASC, p.symbol ASC
        """
        rows = session.execute(text(q)).fetchall()
        df = pd.DataFrame([dict(r._mapping) for r in rows])
        df['date'] = pd.to_datetime(df['date']).dt.date

        # Load sector clusters
        from core.sector_clusters import get_sector_cluster
        df['cluster'] = df['sector'].apply(lambda x: get_sector_cluster(x) if x else "General")

        logger.info(f"Loaded {len(df):,} price records across {df['symbol'].nunique()} symbols in {time.time()-t0:.2f}s")
        return df
    finally:
        session.close()


def precompute_market_breadth_and_trend(df_all: pd.DataFrame):
    """Precomputes market-level daily index, breadth, and EMAs."""
    logger.info("Precomputing daily market proxy index and trend indicators...")
    daily_mkt = df_all.groupby('date').agg(
        market_close=('close', 'mean'),
        num_stocks=('symbol', 'count')
    ).reset_index()

    daily_mkt['ema_21'] = daily_mkt['market_close'].ewm(span=21, adjust=False).mean()
    daily_mkt['ema_50'] = daily_mkt['market_close'].ewm(span=50, adjust=False).mean()
    daily_mkt['ema_200'] = daily_mkt['market_close'].ewm(span=200, adjust=False).mean()
    daily_mkt['is_bull'] = (daily_mkt['market_close'] >= daily_mkt['ema_50']) & (daily_mkt['market_close'] >= daily_mkt['ema_21'])

    mkt_map = {row.date: row for row in daily_mkt.itertuples()}
    return daily_mkt, mkt_map


def precompute_stock_technical_matrix(df_all: pd.DataFrame):
    """
    Computes all lookbacks, momentum metrics, ATR, RSI, EMAs in bulk for speed.
    """
    logger.info("Vectorizing technical indicators and momentum lookbacks per stock...")
    t0 = time.time()
    stock_dfs = {}

    for sym, group in df_all.groupby('symbol'):
        if len(group) < 60:
            continue
        g = group.sort_values('date').copy()
        c = g['close']
        h = g['high']
        l = g['low']

        g['ema_20'] = c.ewm(span=20, adjust=False).mean()
        g['ema_50'] = c.ewm(span=50, adjust=False).mean()
        g['ema_200'] = c.ewm(span=200, adjust=False).mean()

        hl = h - l
        hc = (h - c.shift(1)).abs()
        lc = (l - c.shift(1)).abs()
        tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
        g['atr_14'] = tr.rolling(14, min_periods=14).mean().fillna(c * 0.02)

        g['mom_1m'] = ((c - c.shift(20)) / c.shift(20) * 100.0).fillna(0.0)
        g['mom_3m'] = ((c - c.shift(60)) / c.shift(60) * 100.0).fillna(0.0)
        g['mom_6m'] = ((c - c.shift(126)) / c.shift(126) * 100.0).fillna(0.0)
        g['mom_12m'] = ((c - c.shift(250)) / c.shift(250) * 100.0).fillna(0.0)

        delta = c.diff()
        gain = (delta.where(delta > 0, 0)).rolling(14, min_periods=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14, min_periods=14).mean()
        rs = gain / loss.replace(0, 0.0001)
        g['rsi_14'] = 100.0 - (100.0 / (1.0 + rs)).fillna(50.0)

        # Clenow momentum score: slope * r2 over 90 days
        log_c = np.log(c.replace(0, np.nan))
        x = np.arange(90)
        x_mean = 44.5
        x_dev = x - x_mean
        ss_x = np.sum(x_dev ** 2)

        def rolling_clenow(window):
            if len(window) < 90:
                return 0.0
            y = window.values
            y_mean = np.mean(y)
            slope = np.sum(x_dev * (y - y_mean)) / ss_x
            annualized_slope = (math.exp(slope * 250.0) - 1.0) * 100.0
            ss_tot = np.sum((y - y_mean) ** 2)
            if ss_tot <= 0:
                return 0.0
            ss_res = np.sum((y - (y_mean + slope * x_dev)) ** 2)
            r2 = max(0.0, 1.0 - (ss_res / ss_tot))
            return annualized_slope * r2

        g['clenow_score'] = log_c.rolling(90).apply(rolling_clenow, raw=False).fillna(0.0)

        # Multi-lookback momentum score
        g['multi_lookback_score'] = (
            0.15 * g['mom_1m'] +
            0.25 * g['mom_3m'] +
            0.40 * g['mom_6m'] +
            0.20 * g['mom_12m']
        )

        stock_dfs[sym] = g.set_index('date')

    logger.info(f"Vectorized technical matrix for {len(stock_dfs)} stocks in {time.time()-t0:.2f}s")
    return stock_dfs


# ==============================================================================
# SIMULATION ENGINES: SIP
# ==============================================================================

def simulate_sip_engine(
    strategy_key: str,
    trading_dates: List[date],
    stock_dfs: Dict[str, pd.DataFrame],
    mkt_map: Dict[date, Any],
    monthly_installment: float = 25000.0,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None
) -> Dict[str, Any]:
    """
    Simulates monthly SIP execution across specified date window.
    """
    filtered_dates = [d for d in trading_dates if (start_date is None or d >= start_date) and (end_date is None or d <= end_date)]
    if not filtered_dates:
        return {"xirr": 0.0, "final_val": 0.0, "max_dd": 0.0, "calmar": 0.0, "invested": 0.0, "multiple": 0.0}

    # Identify monthly injection dates (first trading day of each calendar month)
    monthly_injections = []
    seen_months = set()
    for d in filtered_dates:
        m_key = (d.year, d.month)
        if m_key not in seen_months:
            seen_months.add(m_key)
            monthly_injections.append(d)

    holdings = {} # sym -> {shares, cost_basis}
    cash_liquidbees = 0.0
    cash_flows = []
    equity_curve = []

    def update_holding(h_dict, sym_code, num_sh, close_px, tot_cost):
        h_obj = h_dict.get(sym_code, {'shares': 0, 'cost_basis': close_px, 'last_price': close_px})
        new_shares = h_obj['shares'] + num_sh
        h_obj['cost_basis'] = (h_obj['cost_basis'] * h_obj['shares'] + tot_cost) / new_shares
        h_obj['shares'] = new_shares
        h_obj['last_price'] = close_px
        h_dict[sym_code] = h_obj

    last_inj_idx = 0
    next_inj_date = monthly_injections[0] if monthly_injections else None


    for curr_d in filtered_dates:
        # Check for monthly cash injection
        is_rebalance_day = False
        if next_inj_date and curr_d == next_inj_date:
            is_rebalance_day = True
            cash_flows.append((curr_d, -monthly_installment))
            new_cash = monthly_installment
            last_inj_idx += 1
            next_inj_date = monthly_injections[last_inj_idx] if last_inj_idx < len(monthly_injections) else None
        else:
            new_cash = 0.0

        # Accrue daily yield on LiquidBees cash (~6.5% p.a.)
        if cash_liquidbees > 0:
            cash_liquidbees += cash_liquidbees * (0.065 / 365.0)

        # Execute monthly rebalance / stock selection
        if is_rebalance_day:
            wallet_to_deploy = new_cash + cash_liquidbees
            mkt_row = mkt_map.get(curr_d)
            is_bull = mkt_row.is_bull if mkt_row else True

            # Candidate universe screening for curr_d
            screened = []
            for sym, df_s in stock_dfs.items():
                if curr_d in df_s.index:
                    row = df_s.loc[curr_d]
                    cp = row['close']
                    e50 = row['ema_50']
                    e200 = row['ema_200']
                    rsi = row['rsi_14']
                    m6 = row['mom_6m']
                    tier = row['market_cap_tier']
                    sector = row['sector']
                    cluster = row['cluster']

                    if cp < 30 or pd.isna(cp):
                        continue

                    screened.append({
                        'symbol': sym,
                        'close': cp,
                        'ema_50': e50,
                        'ema_200': e200,
                        'rsi': rsi,
                        'mom_6m': m6,
                        'clenow': row['clenow_score'],
                        'multi_score': row['multi_lookback_score'],
                        'tier': tier,
                        'sector': sector,
                        'cluster': cluster
                    })

            if strategy_key == "PURE_CENTURION":
                # 40% Large, 35% Mid, 25% Small. 5 stocks total. Close >= 50 EMA, RSI 42-74
                cands = [s for s in screened if s['close'] >= s['ema_50'] and 40.0 <= s['rsi'] <= 75.0]
                large = sorted([s for s in cands if s['tier'] == 'Large'], key=lambda x: x['multi_score'], reverse=True)
                mid = sorted([s for s in cands if s['tier'] == 'Mid'], key=lambda x: x['multi_score'], reverse=True)
                small = sorted([s for s in cands if s['tier'] == 'Small'], key=lambda x: x['multi_score'], reverse=True)

                selected = []
                if large: selected.append((large[0], 0.40))
                if mid:
                    for m in mid[:2]: selected.append((m, 0.35 / min(2, len(mid))))
                if small:
                    for sm in small[:2]: selected.append((sm, 0.25 / min(2, len(small))))

                if not selected and cands:
                    selected = [(cands[0], 1.0)]

                # Deploy wallet_to_deploy
                cash_liquidbees = 0.0
                for cand, w in selected:
                    alloc = wallet_to_deploy * w
                    sh = int(alloc / cand['close'])
                    if sh > 0:
                        cost = sh * cand['close']
                        wallet_to_deploy -= cost
                        update_holding(holdings, cand['symbol'], sh, cand['close'], cost)

                cash_liquidbees += wallet_to_deploy # remaining unallocated swept to LiquidBees

            elif strategy_key == "PURE_SIP_088024":
                # 4 stocks, Clenow momentum ranking, Close >= 50 EMA, LiquidBees sweep
                cands = sorted([s for s in screened if s['close'] >= s['ema_50'] and s['mom_6m'] > 0], key=lambda x: x['clenow'], reverse=True)
                selected = cands[:4]
                cash_liquidbees = 0.0
                if selected:
                    per_slot = wallet_to_deploy / 4.0
                    for cand in selected:
                        sh = int(per_slot / cand['close'])
                        if sh > 0:
                            cost = sh * cand['close']
                            wallet_to_deploy -= cost
                            update_holding(holdings, cand['symbol'], sh, cand['close'], cost)
                cash_liquidbees += wallet_to_deploy

            elif strategy_key == "APEX_00769":
                # Concentrated Alpha Compounder: 4 stocks, 6M mom >= +25%, Tactical Dip deployment
                cands = sorted([s for s in screened if s['mom_6m'] >= 25.0 and s['close'] >= s['ema_50']], key=lambda x: x['multi_score'], reverse=True)
                selected = cands[:4]
                cash_liquidbees = 0.0
                if selected:
                    per_slot = wallet_to_deploy / 4.0
                    for cand in selected:
                        sh = int(per_slot / cand['close'])
                        if sh > 0:
                            cost = sh * cand['close']
                            wallet_to_deploy -= cost
                            update_holding(holdings, cand['symbol'], sh, cand['close'], cost)
                cash_liquidbees += wallet_to_deploy

            elif strategy_key == "DYNAMIC_BLEND":
                # Switch 5: 75/25 Bull -> 25/75 Bear
                c_weight = 0.75 if is_bull else 0.25
                s_weight = 1.0 - c_weight

                c_cands = sorted([s for s in screened if s['close'] >= s['ema_50']], key=lambda x: x['multi_score'], reverse=True)[:5]
                s_cands = sorted([s for s in screened if s['close'] >= s['ema_50']], key=lambda x: x['clenow'], reverse=True)[:4]

                cash_liquidbees = 0.0
                c_cash = wallet_to_deploy * c_weight
                s_cash = wallet_to_deploy * s_weight

                if c_cands:
                    per_c = c_cash / len(c_cands)
                    for cand in c_cands:
                        sh = int(per_c / cand['close'])
                        if sh > 0:
                            cost = sh * cand['close']
                            wallet_to_deploy -= cost
                            update_holding(holdings, cand['symbol'], sh, cand['close'], cost)

                if s_cands:
                    per_s = s_cash / len(s_cands)
                    for cand in s_cands:
                        sh = int(per_s / cand['close'])
                        if sh > 0:
                            cost = sh * cand['close']
                            wallet_to_deploy -= cost
                            update_holding(holdings, cand['symbol'], sh, cand['close'], cost)

                cash_liquidbees += wallet_to_deploy

            elif strategy_key == "BENCHMARK_MARKET_SIP":
                # Buy & Hold Market Index / Broad Universe SIP
                cands = screened[:20]
                cash_liquidbees = 0.0
                if cands:
                    per_slot = wallet_to_deploy / len(cands)
                    for cand in cands:
                        sh = int(per_slot / cand['close'])
                        if sh > 0:
                            cost = sh * cand['close']
                            wallet_to_deploy -= cost
                            update_holding(holdings, cand['symbol'], sh, cand['close'], cost)
                cash_liquidbees += wallet_to_deploy

        # End-of-day equity valuation
        total_equity = cash_liquidbees
        for sym, h in list(holdings.items()):
            if h['shares'] > 0:
                df_s = stock_dfs.get(sym)
                if df_s is not None and curr_d in df_s.index:
                    cp = df_s.loc[curr_d, 'close']
                    if isinstance(cp, pd.Series):
                        cp = float(cp.iloc[-1])
                    if pd.isna(cp) or cp <= 0:
                        cp = h.get('last_price', h['cost_basis'])
                    else:
                        h['last_price'] = float(cp)
                    total_equity += h['shares'] * float(cp)
                else:
                    # use previous price if stock temporarily suspended
                    total_equity += h['shares'] * h.get('last_price', h['cost_basis'])

        if total_equity > 100.0:
            equity_curve.append(total_equity)

    final_val = equity_curve[-1] if equity_curve else 0.0
    cash_flows.append((filtered_dates[-1], final_val))
    total_invested = sum(-cf[1] for cf in cash_flows[:-1])
    xirr_val = calculate_xirr(cash_flows)
    max_dd = calculate_max_drawdown(equity_curve)
    calmar = round(xirr_val / max_dd, 2) if max_dd > 0 else 0.0
    multiple = round(final_val / total_invested, 2) if total_invested > 0 else 1.0

    return {
        "xirr": xirr_val,
        "final_val": round(final_val, 2),
        "total_invested": round(total_invested, 2),
        "max_dd": max_dd,
        "calmar": calmar,
        "multiple": multiple,
        "equity_curve": equity_curve
    }


# ==============================================================================
# SIMULATION ENGINES: SWING
# ==============================================================================

def simulate_swing_engine(
    strategy_key: str,
    trading_dates: List[date],
    stock_dfs: Dict[str, pd.DataFrame],
    mkt_map: Dict[date, Any],
    initial_capital: float = 300000.0,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None
) -> Dict[str, Any]:
    """
    Simulates high-precision daily swing trading across specified date window.
    """
    filtered_dates = [d for d in trading_dates if (start_date is None or d >= start_date) and (end_date is None or d <= end_date)]
    if not filtered_dates:
        return {"cagr": 0.0, "final_val": initial_capital, "max_dd": 0.0, "calmar": 0.0, "win_rate": 0.0, "trades": 0}

    # Configuration per strategy
    if strategy_key == "CHAMPION_SW_005479_000640":
        max_slots = 3
        bear_fortress_active = True
        pyramiding_active = True
        tiers = [(1.5, 0.333), (3.0, 0.333), (8.5, 0.334)]
    elif strategy_key == "PURE_SW_005479":
        max_slots = 3
        bear_fortress_active = False
        pyramiding_active = True
        tiers = [(1.5, 0.333), (3.0, 0.333), (8.5, 0.334)]
    elif strategy_key == "PURE_SW_000640":
        max_slots = 5
        bear_fortress_active = True
        pyramiding_active = False
        tiers = [(1.5, 0.50), (3.0, 0.50)]
    elif strategy_key == "CLASSIC_8SLOT":
        max_slots = 8
        bear_fortress_active = False
        pyramiding_active = False
        tiers = [(2.0, 0.50), (4.0, 0.50)]
    elif strategy_key == "BENCHMARK_BUY_HOLD":
        # Simply hold market index
        start_mkt = mkt_map[filtered_dates[0]].market_close
        end_mkt = mkt_map[filtered_dates[-1]].market_close
        m_ret = (end_mkt / start_mkt - 1.0)
        days = (filtered_dates[-1] - filtered_dates[0]).days
        cagr = ((1.0 + m_ret) ** (365.0 / max(1, days)) - 1.0) * 100.0
        mkt_curve = [initial_capital * (mkt_map[d].market_close / start_mkt) for d in filtered_dates]
        dd = calculate_max_drawdown(mkt_curve)
        return {
            "cagr": round(cagr, 2),
            "final_val": round(initial_capital * (1.0 + m_ret), 2),
            "max_dd": dd,
            "calmar": round(cagr / dd, 2) if dd > 0 else 0.0,
            "win_rate": 50.0,
            "trades": 1,
            "profit_factor": 1.0,
            "multiple": round(1.0 + m_ret, 2)
        }

    cash = initial_capital
    cash_liquidbees = 0.0
    open_positions = {} # sym -> details
    closed_trades = []
    equity_curve = []

    for curr_d in filtered_dates:
        mkt_row = mkt_map.get(curr_d)
        is_bull = mkt_row.is_bull if mkt_row else True

        # Regulate allowed slots
        if bear_fortress_active and not is_bull:
            active_allowed_slots = 1
        else:
            active_allowed_slots = max_slots

        # Accrue daily yield on liquid cash
        if cash_liquidbees > 0:
            cash_liquidbees += cash_liquidbees * (0.065 / 365.0)

        # 1. Manage Open Positions (Exits, Pyramiding, Trailing Stops)
        for sym, pos in list(open_positions.items()):
            df_s = stock_dfs.get(sym)
            if df_s is None or curr_d not in df_s.index:
                continue

            row = df_s.loc[curr_d]
            h = row['high']
            l = row['low']
            c = row['close']
            atr = pos['atr']

            # Check Stop Loss Trigger
            if l <= pos['stop_loss']:
                exit_price = min(pos['stop_loss'], row['open'])
                pnl = (exit_price - pos['avg_price']) * pos['shares']
                pnl_pct = (exit_price - pos['avg_price']) / pos['avg_price'] * 100.0
                cash += pos['shares'] * exit_price
                closed_trades.append({'symbol': sym, 'pnl': pnl, 'pnl_pct': pnl_pct, 'hold_days': (curr_d - pos['entry_date']).days})
                del open_positions[sym]
                continue

            # Check Winner Pyramiding (+4.0% gain -> Add +50% size, move SL to breakeven)
            if pyramiding_active and not pos['pyramided'] and h >= pos['entry_price'] * 1.04:
                add_shares = int(pos['original_shares'] * 0.5)
                add_cost = add_shares * c
                if cash >= add_cost and add_shares > 0:
                    cash -= add_cost
                    pos['shares'] += add_shares
                    pos['avg_price'] = (pos['avg_price'] * (pos['shares'] - add_shares) + add_cost) / pos['shares']
                    pos['stop_loss'] = pos['entry_price'] * 1.002 # Ratchet to Breakeven
                    pos['pyramided'] = True

            # Dynamic Tier Exits
            cur_tier = pos['tier_idx']
            if cur_tier < len(tiers) - 1:
                tier_mult, trim_ratio = tiers[cur_tier]
                if h >= pos['entry_price'] + (tier_mult * atr):
                    trim_shares = int(pos['original_shares'] * trim_ratio)
                    if trim_shares > 0 and pos['shares'] > trim_shares:
                        t_price = pos['entry_price'] + (tier_mult * atr)
                        cash += trim_shares * t_price
                        pos['shares'] -= trim_shares
                        pos['tier_idx'] += 1
                        pos['stop_loss'] = max(pos['stop_loss'], pos['entry_price'] + (cur_tier * 0.5 * atr))
            else:
                # Final Runner Tier (Trail Chandelier Stop / Upper target)
                highest_since = pos.get('highest_close', c)
                if c > highest_since:
                    pos['highest_close'] = c
                chand_stop = pos['highest_close'] - (2.5 * atr)
                pos['stop_loss'] = max(pos['stop_loss'], chand_stop)

                upper_mult = tiers[-1][0]
                if h >= pos['entry_price'] + (upper_mult * atr):
                    # Reached maximum target
                    cash += pos['shares'] * c
                    pnl = (c - pos['avg_price']) * pos['shares']
                    pnl_pct = (c - pos['avg_price']) / pos['avg_price'] * 100.0
                    closed_trades.append({'symbol': sym, 'pnl': pnl, 'pnl_pct': pnl_pct, 'hold_days': (curr_d - pos['entry_date']).days})
                    del open_positions[sym]
                    continue


        # 2. Check for New Entries if Slots Available
        needed_slots = active_allowed_slots - len(open_positions)
        if needed_slots > 0 and cash > 20000:
            slot_capital = (cash + cash_liquidbees) / max_slots

            # Screener
            candidates = []
            for sym, df_s in stock_dfs.items():
                if sym in open_positions:
                    continue
                if curr_d in df_s.index:
                    row = df_s.loc[curr_d]
                    cp = row['close']
                    e50 = row['ema_50']
                    e200 = row['ema_200']
                    rsi = row['rsi_14']
                    atr = row['atr_14']
                    m1 = row['mom_1m']
                    m3 = row['mom_3m']
                    m6 = row['mom_6m']
                    score = row['multi_lookback_score']

                    if cp < 30 or atr <= 0:
                        continue

                    # Multi-lookback Entry Filter:
                    # Close >= 50 EMA >= 200 EMA * 0.98, 1M > 0, 3M > 0, 6M > 10, 45 <= RSI <= 72
                    if (cp >= e50 >= e200 * 0.98) and (m1 > 0 and m3 > 0 and m6 > 10.0) and (45.0 <= rsi <= 72.0):
                        candidates.append({
                            'symbol': sym,
                            'close': cp,
                            'atr': atr,
                            'score': score
                        })

            candidates.sort(key=lambda x: x['score'], reverse=True)

            for cand in candidates[:needed_slots]:
                alloc = min(cash, slot_capital)
                sh = int(alloc / cand['close'])
                if sh > 0:
                    cost = sh * cand['close']
                    cash -= cost
                    open_positions[cand['symbol']] = {
                        'entry_date': curr_d,
                        'entry_price': cand['close'],
                        'avg_price': cand['close'],
                        'shares': sh,
                        'original_shares': sh,
                        'atr': cand['atr'],
                        'stop_loss': cand['close'] - (2.0 * cand['atr']),
                        'tier_idx': 0,
                        'pyramided': False,
                        'highest_close': cand['close']
                    }

        # 3. Sweep unallocated cash to LiquidBees if Bear Fortress active
        if bear_fortress_active and not is_bull:
            if cash > 10000:
                cash_liquidbees += cash
                cash = 0.0
        else:
            if cash_liquidbees > 0:
                cash += cash_liquidbees
                cash_liquidbees = 0.0

        # 4. Daily Portfolio Equity Valuation
        day_equity = cash + cash_liquidbees
        for sym, pos in open_positions.items():
            df_s = stock_dfs.get(sym)
            if df_s is not None and curr_d in df_s.index:
                day_equity += pos['shares'] * df_s.loc[curr_d, 'close']
            else:
                day_equity += pos['shares'] * pos['avg_price']

        equity_curve.append(day_equity)

    final_val = equity_curve[-1] if equity_curve else initial_capital
    days = (filtered_dates[-1] - filtered_dates[0]).days
    cagr = ((final_val / initial_capital) ** (365.0 / max(1, days)) - 1.0) * 100.0
    max_dd = calculate_max_drawdown(equity_curve)
    calmar = round(cagr / max_dd, 2) if max_dd > 0 else 0.0
    multiple = round(final_val / initial_capital, 2)

    wins = [t for t in closed_trades if t['pnl'] > 0]
    losses = [t for t in closed_trades if t['pnl'] <= 0]
    win_rate = round(len(wins) / len(closed_trades) * 100.0, 1) if closed_trades else 0.0
    total_gains = sum(t['pnl'] for t in wins)
    total_losses = abs(sum(t['pnl'] for t in losses))
    profit_factor = round(total_gains / total_losses, 2) if total_losses > 0 else 3.0

    return {
        "cagr": round(cagr, 2),
        "final_val": round(final_val, 2),
        "max_dd": max_dd,
        "calmar": calmar,
        "multiple": multiple,
        "win_rate": win_rate,
        "trades": len(closed_trades),
        "profit_factor": profit_factor,
        "equity_curve": equity_curve
    }


# ==============================================================================
# MAIN MULTI-REGIME MASTER EXECUTION
# ==============================================================================

def run_master_all_history_backtest():
    logger.info("=" * 75)
    logger.info("  STARTING ALL-HISTORY MULTI-REGIME BACKTEST (2015 - 2026)")
    logger.info("=" * 75)

    df_all = load_universe_data(start_date="2014-01-01")
    daily_mkt, mkt_map = precompute_market_breadth_and_trend(df_all)
    stock_dfs = precompute_stock_technical_matrix(df_all)

    # Master list of all unique trading dates from 2015 onwards
    all_trading_dates = sorted([d for d in daily_mkt['date'] if d >= date(2015, 1, 1)])
    logger.info(f"Total valid trading days for backtesting: {len(all_trading_dates):,} (from {all_trading_dates[0]} to {all_trading_dates[-1]})")

    # Define Distinct Historical Market Regimes & Classes:
    regimes = [
        {
            "key": "ALL_HISTORY_12YR",
            "name": "Class 0: Full 11.75-Year All-History Supercycle",
            "start": date(2015, 1, 1),
            "end": date(2026, 9, 22),
            "desc": "Complete 11.75-year economic cycle (demonetization, 2017 bull, 2018 crash, Covid, 2021 super-bull, 2022 inflation, 2023-26 expansion)"
        },
        {
            "key": "BULL_2017",
            "name": "Class 1: 2017 Secular Bull Market",
            "start": date(2017, 1, 1),
            "end": date(2017, 12, 31),
            "desc": "Uninterrupted liquidity-driven bull run (+33% market gain)"
        },
        {
            "key": "CRASH_2018",
            "name": "Class 2: 2018 Small/Mid-Cap Carnage & NBFC Crisis",
            "start": date(2018, 1, 1),
            "end": date(2018, 12, 31),
            "desc": "Severe liquidity crisis, IL&FS default, small-caps down -35%"
        },
        {
            "key": "COVID_CRASH_2020",
            "name": "Class 3: 2020 Covid Crash & Rapid V-Shape Recovery",
            "start": date(2020, 1, 1),
            "end": date(2020, 12, 31),
            "desc": "Black-swan crash (-38% in 30 days) followed by massive global stimulus rebound"
        },
        {
            "key": "SUPERBULL_2021",
            "name": "Class 4: 2021 Post-Covid Momentum Supercycle",
            "start": date(2021, 1, 1),
            "end": date(2021, 12, 31),
            "desc": "Relentless retail & FII liquidity expansion (+26% market gain)"
        },
        {
            "key": "INFLATION_CHOP_2022",
            "name": "Class 5: 2022 Global Rate-Hike & Ukraine War Chop",
            "start": date(2022, 1, 1),
            "end": date(2022, 12, 31),
            "desc": "High inflation, Fed aggressive hikes, rangebound whipsaw (-1% market)"
        },
        {
            "key": "BREAKOUT_2023",
            "name": "Class 6: 2023 Broad-Market Midcap Frenzy",
            "start": date(2023, 1, 1),
            "end": date(2023, 12, 31),
            "desc": "Manufacturing & capex supercycle breakout (+31% market gain)"
        },
        {
            "key": "RECENT_CYCLE_2024_2026",
            "name": "Class 7: Recent Multi-Regime Cycle (2024 - 2026)",
            "start": date(2024, 1, 1),
            "end": date(2026, 9, 22),
            "desc": "Recent 2.75-year market environment with election rally, crash (-14.4%), and rebound"
        }
    ]

    sip_strats = [
        ("PURE_CENTURION", "Pure Centurion Wealth Engine (Default)"),
        ("PURE_SIP_088024", "Pure SIP_088024 Fortress Clenow"),
        ("APEX_00769", "Apex Concentrated Compounder (SIP_00769)"),
        ("DYNAMIC_BLEND", "Dynamic Core Blend (Switch 5: 75/25 -> 25/75)"),
        ("BENCHMARK_MARKET_SIP", "Benchmark: Broad Market Universe SIP")
    ]

    swing_strats = [
        ("CHAMPION_SW_005479_000640", "Champion Fusion: SW_005479 (Alpha) + SW_000640 (Fortress)"),
        ("PURE_SW_005479", "Pure SW_005479 (Alpha Champion - No Bear Sweep)"),
        ("PURE_SW_000640", "Pure SW_000640 (Fortress Shield - 5 Slots)"),
        ("CLASSIC_8SLOT", "Classic 8-Slot Diversified Swing (12.5% Slots)"),
        ("BENCHMARK_BUY_HOLD", "Benchmark: Buy & Hold Market Index")
    ]

    sip_results = []
    swing_results = []

    # 1. RUN SIP BACKTESTS
    logger.info("\n" + "=" * 60)
    logger.info("  EXECUTING SIP BACKTESTS ACROSS ALL MARKET CLASSES")
    logger.info("=" * 60)
    for reg in regimes:
        logger.info(f"\n--- Backtesting SIP in {reg['name']} ({reg['start']} to {reg['end']}) ---")
        for skey, sname in sip_strats:
            res = simulate_sip_engine(
                strategy_key=skey,
                trading_dates=all_trading_dates,
                stock_dfs=stock_dfs,
                mkt_map=mkt_map,
                monthly_installment=25000.0,
                start_date=reg['start'],
                end_date=reg['end']
            )
            sip_results.append({
                "regime_key": reg['key'],
                "regime_name": reg['name'],
                "strategy_key": skey,
                "strategy_name": sname,
                "xirr": res['xirr'],
                "final_val": res['final_val'],
                "invested": res['total_invested'],
                "multiple": res['multiple'],
                "max_dd": res['max_dd'],
                "calmar": res['calmar']
            })
            logger.info(f"  [{skey:20}] XIRR: {res['xirr']:+6.2f}% | Max DD: {res['max_dd']:5.2f}% | Final: ₹{res['final_val']:12,.2f} (Inv: ₹{res['total_invested']:10,.2f}) | Mult: {res['multiple']:.2f}x | Calmar: {res['calmar']:4.2f}")

    # 2. RUN SWING BACKTESTS
    logger.info("\n" + "=" * 60)
    logger.info("  EXECUTING SWING BACKTESTS ACROSS ALL MARKET CLASSES")
    logger.info("=" * 60)
    for reg in regimes:
        logger.info(f"\n--- Backtesting SWING in {reg['name']} ({reg['start']} to {reg['end']}) ---")
        for skey, sname in swing_strats:
            res = simulate_swing_engine(
                strategy_key=skey,
                trading_dates=all_trading_dates,
                stock_dfs=stock_dfs,
                mkt_map=mkt_map,
                initial_capital=300000.0,
                start_date=reg['start'],
                end_date=reg['end']
            )
            swing_results.append({
                "regime_key": reg['key'],
                "regime_name": reg['name'],
                "strategy_key": skey,
                "strategy_name": sname,
                "cagr": res['cagr'],
                "final_val": res['final_val'],
                "multiple": res['multiple'],
                "max_dd": res['max_dd'],
                "calmar": res['calmar'],
                "win_rate": res['win_rate'],
                "trades": res['trades'],
                "profit_factor": res['profit_factor']
            })
            logger.info(f"  [{skey:26}] CAGR: {res['cagr']:+6.2f}% | Max DD: {res['max_dd']:5.2f}% | Final: ₹{res['final_val']:12,.2f} | Mult: {res['multiple']:.2f}x | Win: {res['win_rate']:4.1f}% | PF: {res['profit_factor']:.2f}")

    # Export CSVs
    df_sip = pd.DataFrame(sip_results)
    df_swing = pd.DataFrame(swing_results)

    sip_csv = BASE_DIR / "scripts" / "historical_all_regimes_sip_backtest.csv"
    swing_csv = BASE_DIR / "scripts" / "historical_all_regimes_swing_backtest.csv"

    df_sip.to_csv(sip_csv, index=False)
    df_swing.to_csv(swing_csv, index=False)

    logger.info(f"\nSaved SIP results to: {sip_csv}")
    logger.info(f"Saved SWING results to: {swing_csv}")
    logger.info("All-History Multi-Regime Backtest Complete!")


if __name__ == "__main__":
    run_master_all_history_backtest()
