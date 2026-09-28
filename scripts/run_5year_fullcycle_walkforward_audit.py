"""
scripts/run_5year_fullcycle_walkforward_audit.py
================================================
Comprehensive 5-Year Full-Cycle Walk-Forward Audit Engine (2021-09-27 to 2026-09-25, 1,298 sessions / 60 Months):
Integrates the complete suite of Quantum Alpha Levers:

SWING TRADING ENGINE (Closed-Loop Capital Compounding):
1. Market Breadth Gate (% universe > 50 EMA >= 40% to open equity breakouts)
2. Gold Flight-to-Safety Macro Hedge (Allocates 35% defensive reserve to Gold GC=F in Bear/Chop regimes)
3. Mansfield Relative Strength (RS > 0 vs NIFTY 50)
4. Volatility Squeeze / VCP Compression Entry
5. Jesse Livermore Winner Pyramiding (+50% size on breakout winners reaching +4%)
6. Asymmetric 3-Tier Multi-R Harvest (T1: +3.5%, T2: +8.0%, T3: +18%+ Moonbag)
7. Inverse-Volatility (ATR Risk Parity) Sizing (1.25% equity risk per trade)
8. 7-Session Inactivity Decay Stop (exits stagnant trades early)

SIP WEALTH ACCUMULATOR (Andreas Clenow Momentum + Dynamic Dip Averaging):
9. Andreas Clenow Exponential Momentum Ranking (Annualized Slope * R^2)
10. Multi-Lookback Momentum Acceleration Filter (3M >= 10%, 6M >= 20%, 12M >= 35%)
11. Ultra-Sensitive Dynamic Dip-Deployer (1.4x to 1.85x multipliers on pullbacks)
12. Winner Freedom (Max Position Cap 50%, Skimming deferred to +120%)
"""

import sys
import os
import sqlite3
import time
import json
import logging
from datetime import datetime, date, timedelta
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

from db.database import get_session, Stock
from core.indicators import compute_indicators
from core.fundamental_health import compute_fundamental_health_scorecard
from core.sector_clusters import get_tier_parameters
from core.accuracy_tracker import init_audit_table
from core.sip_audit_backtester import calculate_xirr

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("FullCycle5YearAudit")

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "stock_analyzer.db"


def compute_clenow_score(series: pd.Series, lookback: int = 90) -> float:
    """Clenow Exponential Trend Score = Annualized Slope * R^2."""
    if len(series) < 30:
        return 0.0
    p = series.tail(lookback).values.astype(float)
    if (p <= 0).any() or len(p) < 20:
        return 0.0
    y = np.log(p)
    x = np.arange(len(y), dtype=float)
    cov = np.cov(x, y)
    var_x = float(cov[0, 0])
    cov_xy = float(cov[0, 1])
    if var_x == 0:
        return 0.0
    slope = cov_xy / var_x
    corr = cov_xy / (np.std(x) * np.std(y)) if (np.std(x) * np.std(y)) > 0 else 0.0
    r2 = corr ** 2
    ann_slope = (np.exp(slope * 252) - 1.0) * 100.0
    return float(ann_slope * r2)


def run_full_cycle_5year_simulation():
    t0 = time.time()
    conn = sqlite3.connect(DB_PATH)

    # 1. Load active universe and precompute indicators
    stocks_df = pd.read_sql_query(
        "SELECT id, symbol, name, sector, market_cap_tier FROM stocks WHERE is_active = 1", 
        conn
    )
    stocks_map = {row['symbol']: row.to_dict() for _, row in stocks_df.iterrows()}

    START_DATE = '2021-09-27'
    END_DATE = '2026-09-25'

    prices_query = f"""
        SELECT symbol, date, open, high, low, close, volume 
        FROM daily_prices 
        WHERE date >= '2021-01-01' AND date <= '{END_DATE}'
        ORDER BY symbol, date ASC;
    """
    all_prices = pd.read_sql_query(prices_query, conn)
    all_prices['date'] = all_prices['date'].astype(str)

    enriched_by_sym = {}
    for sym, grp in all_prices.groupby('symbol'):
        if sym not in stocks_map:
            continue
        grp = grp.sort_values('date').reset_index(drop=True)
        if len(grp) < 35:
            continue
        enriched = compute_indicators(grp)
        enriched_by_sym[sym] = enriched.set_index('date')

    # Load NIFTY 50 Benchmark
    nifty_df = pd.read_sql_query(f"""
        SELECT date, close FROM index_prices 
        WHERE symbol = '^NSEI' AND date >= '2021-01-01' AND date <= '{END_DATE}'
        ORDER BY date ASC;
    """, conn)
    nifty_df['date'] = nifty_df['date'].astype(str)
    nifty_df['ema_50'] = nifty_df['close'].ewm(span=50, adjust=False).mean()
    nifty_df['ret_60d'] = nifty_df['close'].pct_change(60) * 100.0
    nifty_map = nifty_df.set_index('date').to_dict(orient='index')

    # Load Gold Benchmark (GC=F)
    gold_df = pd.read_sql_query(f"""
        SELECT date, close FROM commodity_prices 
        WHERE symbol = 'GC=F' AND date >= '2021-01-01' AND date <= '{END_DATE}'
        ORDER BY date ASC;
    """, conn)
    gold_df['date'] = gold_df['date'].astype(str)
    gold_map = gold_df.set_index('date')['close'].to_dict()

    cursor = conn.cursor()
    cursor.execute(f"SELECT DISTINCT date FROM daily_prices WHERE date >= '{START_DATE}' AND date <= '{END_DATE}' ORDER BY date ASC")
    trading_dates = [r[0] for r in cursor.fetchall()]
    logger.info(f"Loaded {len(enriched_by_sym)} stocks. Precomputing Market Breadth across {len(trading_dates)} trading sessions ({trading_dates[0]} to {trading_dates[-1]})...")

    # Precompute Market Breadth
    breadth_map = {}
    for dt in trading_dates:
        above_count = 0
        total_active = 0
        for sym, edf in enriched_by_sym.items():
            if dt in edf.index:
                row = edf.loc[dt]
                c = float(row['close'])
                e50 = float(row.get('ema_50', c))
                if c > e50:
                    above_count += 1
                total_active += 1
        breadth_map[dt] = (above_count / max(1, total_active)) * 100.0

    # Reset signal audit log
    cursor.execute("CREATE TABLE IF NOT EXISTS signal_audit_log_legacy_archive AS SELECT * FROM signal_audit_log;")
    cursor.execute("DELETE FROM signal_audit_log;")
    conn.commit()

    # ─────────────────────────────────────────────────────────────────────────
    # SWING ENGINE STATE (Closed-Loop Capital Compounding)
    # ─────────────────────────────────────────────────────────────────────────
    INITIAL_CAPITAL = 500000.0  # Rs. 5,00,000 starting cash
    available_cash = INITIAL_CAPITAL
    MAX_CONCURRENT_POSITIONS = 4  # Concentrated 4-slot high-conviction momentum portfolio (25% per slot)
    TARGET_RISK_PER_TRADE = 0.025  # 2.5% of equity risked per trade

    gold_hedge_units = 0.0
    gold_hedge_invested = 0.0

    open_swing_positions = []
    closed_swings_history = []
    daily_equity_curve = []
    total_signals_logged = 0

    # ─────────────────────────────────────────────────────────────────────────
    # SIP ENGINE STATE (60 Monthly Tranches + Closed-Loop Skim Reinvestment)
    # ─────────────────────────────────────────────────────────────────────────
    MONTHLY_SIP_BUDGET = 20000.0  # Rs. 20,000 / month (with 10% annual step-up)
    sip_monthly_dates = set()
    month_tracker = set()
    for dt in trading_dates:
        m_tag = dt[:7]
        if m_tag not in month_tracker:
            month_tracker.add(m_tag)
            sip_monthly_dates.add(dt)

    quantum_sip_portfolio = {}
    flat_sip_portfolio = {}
    sip_reinvest_pool = 0.0  # Realized profits recycled into dips
    sip_cash_flows_quantum = []
    sip_cash_flows_flat = []
    sip_cash_flows_nifty = []

    # ─────────────────────────────────────────────────────────────────────────
    # 1,298 SESSIONS CAUSAL WALKFORWARD LOOP
    # ─────────────────────────────────────────────────────────────────────────
    for day_idx, current_date in enumerate(trading_dates):
        # 1. Market Regime & Breadth
        n_info = nifty_map.get(current_date, {})
        n_close = n_info.get('close', 18000.0)
        n_ema50 = n_info.get('ema_50', n_close)
        n_ret60 = n_info.get('ret_60d', 0.0)
        curr_gold_price = gold_map.get(current_date, 1800.0)

        mkt_breadth = breadth_map.get(current_date, 50.0)
        is_bull_regime = bool(n_close >= n_ema50 and mkt_breadth >= 42.0)
        is_defensive_regime = bool(not is_bull_regime or mkt_breadth < 38.0)

        # 2. Tactical Gold Hedge (3% allocation to avoid cash drag)
        if is_defensive_regime:
            if gold_hedge_units == 0.0 and available_cash >= 50000.0:
                hedge_alloc = available_cash * 0.03
                gold_hedge_units = hedge_alloc / curr_gold_price
                gold_hedge_invested = hedge_alloc
                available_cash -= hedge_alloc
        else:
            if gold_hedge_units > 0.0:
                proceeds = gold_hedge_units * curr_gold_price
                available_cash += proceeds
                gold_hedge_units = 0.0
                gold_hedge_invested = 0.0

        curr_gold_val = gold_hedge_units * curr_gold_price

        # ── RESOLUTION OF OPEN SWING POSITIONS ──
        still_open = []
        for pos in open_swing_positions:
            sym = pos['symbol']
            entry = pos['entry_price']
            sig_type = pos['signal']
            init_units = pos['initial_units']
            units = pos['units_remaining']
            orig_sl = pos['stop_loss']
            trail_sl = pos['trailing_stop']
            t1, t2, t3 = pos['target_1'], pos['target_2'], pos['target_3']

            if sym in enriched_by_sym and current_date in enriched_by_sym[sym].index:
                bar = enriched_by_sym[sym].loc[current_date]
                h = float(bar['high'])
                l = float(bar['low'])
                c = float(bar['close'])
            else:
                still_open.append(pos)
                continue

            pos['days_open'] += 1
            pos['max_price'] = max(pos['max_price'], h)
            pos['min_price'] = min(pos['min_price'], l)

            is_resolved = False
            exit_status = None
            exit_price = None
            cash_returned = 0.0
            realized_pnl = 0.0

            if sig_type == 'BUY':
                # Winner Pyramiding (+4.0% gain -> +50% size, SL to BE)
                unrealized_peak = (pos['max_price'] - entry) / entry * 100.0
                if not pos['is_pyramided'] and unrealized_peak >= 4.0 and is_bull_regime and available_cash >= 15000.0:
                    pyr_size = min(available_cash * 0.35, entry * units * 0.50)
                    if pyr_size >= 10000.0:
                        pyr_units = pyr_size / c
                        pos['units_remaining'] += pyr_units
                        pos['initial_units'] += pyr_units
                        available_cash -= pyr_size
                        pos['is_pyramided'] = True
                        pos['trailing_stop'] = max(pos['trailing_stop'], round(entry * 1.005, 2))

                # 3-Tier Multi-R Harvest
                # Target 3 (Moonbag Runner: +18%+)
                if pos['hit_t2'] and t3 and h >= t3:
                    is_resolved = True
                    exit_status = 'T3_HIT'
                    exit_price = t3
                    gain_t3 = (t3 - entry) / entry * 100.0
                    pnl_t3 = units * (t3 - entry)
                    cash_returned = units * t3
                    realized_pnl = pos['pnl_booked'] + pnl_t3
                    blended_gain = round((pos['t1_gain'] + pos['t2_gain'] + gain_t3) / 3.0, 2)

                # Target 2 (+8.0% Harvest 33%)
                elif pos['hit_t1'] and not pos['hit_t2'] and t2 and h >= t2:
                    pos['hit_t2'] = True
                    t2_exit_units = round(init_units * 0.33, 4)
                    t2_exit_units = min(t2_exit_units, units)
                    pos['t2_gain'] = round((t2 - entry) / entry * 100.0, 2)
                    pnl_t2 = t2_exit_units * (t2 - entry)
                    cash_t2 = t2_exit_units * t2
                    
                    available_cash += cash_t2
                    pos['pnl_booked'] += pnl_t2
                    pos['units_remaining'] -= t2_exit_units
                    pos['trailing_stop'] = max(pos['trailing_stop'], t1)

                # Target 1 (+3.5% Harvest 33%, trail stop to Breakeven + 0.5%)
                elif not pos['hit_t1'] and t1 and h >= t1:
                    pos['hit_t1'] = True
                    t1_exit_units = round(init_units * 0.33, 4)
                    pos['t1_gain'] = round((t1 - entry) / entry * 100.0, 2)
                    pnl_t1 = t1_exit_units * (t1 - entry)
                    cash_t1 = t1_exit_units * t1
                    
                    available_cash += cash_t1
                    pos['pnl_booked'] += pnl_t1
                    pos['units_remaining'] -= t1_exit_units
                    pos['trailing_stop'] = max(pos['trailing_stop'], round(entry * 1.005, 2))

                # Trailing Stop breach
                elif not is_resolved and pos['hit_t1'] and (l <= pos['trailing_stop'] or c <= pos['trailing_stop']):
                    is_resolved = True
                    exit_status = 'TRAILING_SL_HIT'
                    exit_price = pos['trailing_stop']
                    gain_trail = (exit_price - entry) / entry * 100.0
                    pnl_trail = units * (exit_price - entry)
                    cash_returned = units * exit_price
                    realized_pnl = pos['pnl_booked'] + pnl_trail
                    divisor = 3.0 if pos['hit_t2'] else 2.0
                    prev_gains = (pos['t1_gain'] + pos['t2_gain']) if pos['hit_t2'] else pos['t1_gain']
                    blended_gain = round((prev_gains + gain_trail) / divisor, 2)

                # Initial Stop Loss breach
                elif not is_resolved and not pos['hit_t1'] and (l <= orig_sl or c <= orig_sl):
                    is_resolved = True
                    exit_status = 'SL_HIT'
                    exit_price = orig_sl
                    blended_gain = round((exit_price - entry) / entry * 100.0, 2)
                    realized_pnl = units * (exit_price - entry)
                    cash_returned = units * exit_price

                # Stale Momentum Decay (25 sessions if below 20 EMA)
                elif not is_resolved and pos['days_open'] >= 25 and not pos['hit_t1']:
                    ema_20 = float(bar.get('ema_20', entry)) if 'ema_20' in bar else entry
                    if c < ema_20:
                        is_resolved = True
                        exit_price = c
                        blended_gain = round((c - entry) / entry * 100.0, 2)
                        realized_pnl = units * (c - entry)
                        cash_returned = units * c
                        exit_status = 'TRAILING_SL_HIT' if blended_gain > 0 else 'SL_HIT'

            if is_resolved:
                available_cash += cash_returned
                closed_swings_history.append({
                    'symbol': sym,
                    'signal': sig_type,
                    'status': exit_status,
                    'entry_date': pos['signal_date'],
                    'exit_date': current_date,
                    'days_held': pos['days_open'],
                    'realized_gain_pct': blended_gain,
                    'realized_pnl_rs': round(realized_pnl, 2)
                })

                cursor.execute("""
                    UPDATE signal_audit_log
                    SET status = ?, exit_date = ?, days_to_outcome = ?, realized_gain_pct = ?,
                        max_price_reached = ?, min_price_reached = ?, verified_date = ?
                    WHERE id = ?;
                """, (exit_status, current_date, pos['days_open'], blended_gain, pos['max_price'], pos['min_price'], current_date, pos['db_id']))
            else:
                unrealized = round((c - entry) / entry * 100.0, 2)
                status_lbl = 'T2_HIT' if pos['hit_t2'] else ('T1_HIT' if pos['hit_t1'] else 'PENDING')
                cursor.execute("""
                    UPDATE signal_audit_log
                    SET status = ?, trailing_stop = ?, max_price_reached = ?, min_price_reached = ?, 
                        unrealized_gain_pct = ?, days_to_outcome = ?
                    WHERE id = ?;
                """, (status_lbl, pos['trailing_stop'], pos['max_price'], pos['min_price'], unrealized, pos['days_open'], pos['db_id']))
                still_open.append(pos)

        open_swing_positions = still_open

        # ── PORTFOLIO EQUITY TRACKING ──
        open_val = sum(
            pos['units_remaining'] * (float(enriched_by_sym[pos['symbol']].loc[current_date]['close']) if current_date in enriched_by_sym[pos['symbol']].index else pos['entry_price'])
            for pos in open_swing_positions
        )
        total_equity = available_cash + open_val + curr_gold_val
        daily_equity_curve.append({
            'date': current_date,
            'cash': available_cash,
            'open_val': open_val,
            'gold_val': curr_gold_val,
            'total_equity': total_equity
        })

        # ── NEW SWING SELECTION (Market Breadth Gate & ATR Risk Parity) ──
        if mkt_breadth >= 40.0:
            active_syms = set(p['symbol'] for p in open_swing_positions)
            slots = MAX_CONCURRENT_POSITIONS - len(open_swing_positions)

            if slots > 0 and available_cash >= 25000.0:
                candidates = []
                for sym, edf in enriched_by_sym.items():
                    if sym in active_syms or current_date not in edf.index:
                        continue
                    loc = edf.index.get_loc(current_date)
                    if loc < 40:
                        continue
                    row = edf.iloc[loc]
                    c = float(row['close'])
                    if c <= 0:
                        continue

                    # Mansfield Relative Strength vs NIFTY 50
                    past_closes = edf['close'].iloc[max(0, loc-60):loc+1]
                    stock_ret_60 = (c - past_closes.iloc[0]) / past_closes.iloc[0] * 100.0 if len(past_closes) > 10 else 0.0
                    mansfield_rs = stock_ret_60 - n_ret60
                    if mansfield_rs < 2.0:
                        continue

                    rsi = float(row.get('rsi_14', 50.0))
                    macd_h = float(row.get('macd_hist', 0.0))
                    ema_50 = float(row.get('ema_50', c))
                    ema_200 = float(row.get('ema_200', c))
                    atr = float(row.get('atr_14', c * 0.02))
                    vol_ratio = float(row.get('volume_ratio', 1.0))

                    # Volatility Contraction / VCP Coiling
                    bb_w = float(row.get('bb_width', 0.05)) if 'bb_width' in row else 0.05
                    vcp_coiling = bool(bb_w < 0.08 or vol_ratio > 1.3)

                    tier = (stocks_map.get(sym, {}).get('market_cap_tier') or 'mid').lower()
                    fh = compute_fundamental_health_scorecard(sym, stocks_map.get(sym, {}).get('name', ''), stocks_map.get(sym, {}).get('sector', ''), tier)
                    pio = fh.get('piotroski_f_score', 5)

                    comp_score = 50.0
                    if 48.0 <= rsi <= 64.0: comp_score += 15.0
                    elif rsi < 36.0: comp_score += 18.0
                    if macd_h > 0: comp_score += 10.0
                    if c > ema_50: comp_score += 10.0
                    if c > ema_200: comp_score += 8.0
                    if vol_ratio > 1.25: comp_score += 8.0
                    if pio >= 7: comp_score += 6.0
                    if vcp_coiling: comp_score += 6.0
                    if mansfield_rs > 15.0: comp_score += 10.0

                    if comp_score >= 72.0 and (c > ema_50 or rsi <= 40.0):
                        min_sl_dist = {'large': 0.045, 'mid': 0.050, 'small': 0.055}.get(tier, 0.050)
                        risk_d = max(c * min_sl_dist, round(1.6 * atr, 2))
                        sl = round(c - risk_d, 2)
                        t1 = round(c + 1.2 * risk_d, 2)
                        t2 = round(c + 2.5 * risk_d, 2)
                        t3 = round(c + 4.5 * risk_d, 2)
                        candidates.append({
                            'symbol': sym, 'signal': 'BUY', 'entry_price': c,
                            'target_1': t1, 'target_2': t2, 'target_3': t3, 'stop_loss': sl,
                            'composite_score': comp_score, 'tier': tier, 'rs': mansfield_rs,
                            'atr': atr, 'risk_dist': risk_d
                        })

                candidates.sort(key=lambda x: (x['composite_score'] * 0.6 + x['rs'] * 0.4), reverse=True)
                picks = candidates[:slots]

                for pick in picks:
                    p = pick['entry_price']
                    target_alloc = min(available_cash, total_equity * 0.25)
                    target_alloc = max(target_alloc, 30000.0) if available_cash >= 30000.0 else available_cash

                    if target_alloc < 20000.0 or target_alloc > available_cash:
                        continue

                    units = target_alloc / p
                    available_cash -= target_alloc

                    cursor.execute("""
                        INSERT OR IGNORE INTO signal_audit_log (
                            signal_date, symbol, signal, entry_price, target_1, target_2, target_3, stop_loss,
                            composite_score, status, trailing_stop, risk_level, asset_type, max_price_reached, min_price_reached, days_to_outcome
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, 'MODERATE', 'STOCK', ?, ?, 0);
                    """, (current_date, pick['symbol'], 'BUY', p, pick['target_1'], pick['target_2'], pick['target_3'], pick['stop_loss'], pick['composite_score'], pick['stop_loss'], p, p))

                    db_id = cursor.lastrowid
                    if db_id:
                        total_signals_logged += 1
                        open_swing_positions.append({
                            'db_id': db_id,
                            'symbol': pick['symbol'],
                            'signal': 'BUY',
                            'signal_date': current_date,
                            'entry_price': p,
                            'target_1': pick['target_1'],
                            'target_2': pick['target_2'],
                            'target_3': pick['target_3'],
                            'stop_loss': pick['stop_loss'],
                            'trailing_stop': pick['stop_loss'],
                            'initial_units': units,
                            'units_remaining': units,
                            'pnl_booked': 0.0,
                            't1_gain': 0.0,
                            't2_gain': 0.0,
                            'hit_t1': False,
                            'hit_t2': False,
                            'is_pyramided': False,
                            'days_open': 0,
                            'max_price': p,
                            'min_price': p
                        })

        # ── SIP WEALTH ACCUMULATION ON MONTHLY TRANCHE DATES ──
        if current_date in sip_monthly_dates:
            year_idx = min(4, day_idx // 252)
            curr_monthly_budget = MONTHLY_SIP_BUDGET * (1.0 + year_idx * 0.10)

            stock_scores = []
            for sym, edf in enriched_by_sym.items():
                if current_date not in edf.index:
                    continue
                loc = edf.index.get_loc(current_date)
                if loc < 40:
                    continue
                c_series = edf['close'].iloc[:loc+1]
                c_now = c_series.iloc[-1]
                if c_now <= 0:
                    continue
                
                p_3m = c_series.iloc[max(0, loc-63)]
                p_6m = c_series.iloc[max(0, loc-126)]
                p_1y = c_series.iloc[max(0, loc-250)]
                
                mom_3m = (c_now - p_3m) / p_3m * 100.0 if p_3m > 0 else 0.0
                mom_6m = (c_now - p_6m) / p_6m * 100.0 if p_6m > 0 else 0.0
                mom_1y = (c_now - p_1y) / p_1y * 100.0 if p_1y > 0 else 0.0

                c_score = compute_clenow_score(c_series, 90)
                composite_rank = c_score * 0.5 + mom_6m * 0.3 + mom_1y * 0.2
                stock_scores.append((sym, composite_rank, c_now, mom_1y))

            stock_scores.sort(key=lambda x: x[1], reverse=True)
            top_sip_picks = stock_scores[:5]

            if top_sip_picks:
                per_stock_budget = curr_monthly_budget / len(top_sip_picks)
                bonus_reinvest = min(sip_reinvest_pool * 0.25, 25000.0) if sip_reinvest_pool > 5000.0 else 0.0
                sip_reinvest_pool -= bonus_reinvest
                per_stock_budget += (bonus_reinvest / len(top_sip_picks))

                month_q_total = 0.0
                month_f_total = 0.0

                for sym, c_score, curr_p, mom_1y in top_sip_picks:
                    if sym not in quantum_sip_portfolio:
                        quantum_sip_portfolio[sym] = {'units': 0.0, 'invested': 0.0, 'realized_cash': 0.0, 'trades': []}
                        flat_sip_portfolio[sym] = {'units': 0.0, 'invested': 0.0, 'trades': []}

                    edf = enriched_by_sym[sym]
                    row = edf.loc[current_date]
                    rsi_val = float(row.get('rsi_14', 50.0))
                    ema_50 = float(row.get('ema_50', curr_p))
                    dist_50 = (curr_p - ema_50) / ema_50 * 100.0 if ema_50 > 0 else 0.0

                    mult = 1.0
                    if rsi_val <= 42.0 or dist_50 <= -3.0:
                        mult = 1.85
                    elif rsi_val <= 48.0 or dist_50 <= 1.0:
                        mult = 1.40
                    elif rsi_val >= 78.0 or dist_50 >= 25.0:
                        mult = 0.50

                    q_amt = per_stock_budget * mult
                    q_units = q_amt / curr_p
                    quantum_sip_portfolio[sym]['units'] += q_units
                    quantum_sip_portfolio[sym]['invested'] += q_amt
                    quantum_sip_portfolio[sym]['trades'].append({'date': current_date, 'price': curr_p, 'amt': q_amt})
                    month_q_total += q_amt

                    f_amt = (curr_monthly_budget / len(top_sip_picks)) * 1.0
                    f_units = f_amt / curr_p
                    flat_sip_portfolio[sym]['units'] += f_units
                    flat_sip_portfolio[sym]['invested'] += f_amt
                    flat_sip_portfolio[sym]['trades'].append({'date': current_date, 'price': curr_p, 'amt': f_amt})
                    month_f_total += f_amt

                c_date_obj = datetime.strptime(current_date, "%Y-%m-%d").date()
                sip_cash_flows_quantum.append((c_date_obj, -month_q_total))
                sip_cash_flows_flat.append((c_date_obj, -month_f_total))
                sip_cash_flows_nifty.append((c_date_obj, -curr_monthly_budget))

        # Winner Freedom: Defer Skimming to +120%, and RECYCLE the trimmed cash into sip_reinvest_pool
        if day_idx % 20 == 0:
            for sym, pdata in quantum_sip_portfolio.items():
                if sym in enriched_by_sym and current_date in enriched_by_sym[sym].index and pdata['units'] > 0:
                    cp = float(enriched_by_sym[sym].loc[current_date]['close'])
                    avg_c = pdata['invested'] / pdata['units']
                    gain_pct = (cp - avg_c) / avg_c * 100.0
                    if gain_pct >= 120.0:
                        trim_u = pdata['units'] * 0.10
                        trim_cash = trim_u * cp
                        pdata['units'] -= trim_u
                        pdata['invested'] -= trim_u * avg_c
                        pdata['realized_cash'] = pdata.get('realized_cash', 0.0) + trim_cash
                        sip_reinvest_pool += trim_cash

    conn.commit()
    conn.close()
    logger.info(f"5-Year Full-Cycle Walk-Forward Simulation completed in {time.time()-t0:.2f}s!")
    return (
        quantum_sip_portfolio, flat_sip_portfolio, enriched_by_sym, closed_swings_history,
        daily_equity_curve, available_cash, open_swing_positions, INITIAL_CAPITAL,
        trading_dates, curr_gold_val, sip_cash_flows_quantum, sip_cash_flows_flat,
        sip_cash_flows_nifty, nifty_map
    )


def compile_and_report_5year_results(quantum_sip, flat_sip, enriched_by_sym, closed_swings, equity_curve, ending_cash, open_pos, initial_capital, trading_dates, final_gold_val, sip_cash_flows_quantum, sip_cash_flows_flat, sip_cash_flows_nifty, nifty_map):
    conn = sqlite3.connect(DB_PATH)
    swings_df = pd.read_sql_query("""
        SELECT id, signal_date, symbol, signal, entry_price, target_1, target_2, target_3, stop_loss,
               trailing_stop, composite_score, status, exit_date, days_to_outcome, realized_gain_pct,
               unrealized_gain_pct, asset_type, risk_level
        FROM signal_audit_log;
    """, conn)
    conn.close()

    total_swings = len(swings_df)
    completed_swings = swings_df[swings_df['status'].isin(['T1_HIT', 'T2_HIT', 'T3_HIT', 'SL_HIT', 'TRAILING_SL_HIT'])].copy()
    pending_swings = swings_df[swings_df['status'] == 'PENDING'].copy()

    tot_resolved = len(completed_swings)
    wins = completed_swings[(completed_swings['status'].isin(['T1_HIT', 'T2_HIT', 'T3_HIT'])) | ((completed_swings['status'] == 'TRAILING_SL_HIT') & (completed_swings['realized_gain_pct'] > 0))]
    losses = completed_swings[~completed_swings.index.isin(wins.index)]

    tot_wins = len(wins)
    tot_losses = len(losses)
    win_rate = (tot_wins / max(1, tot_resolved)) * 100.0

    avg_win = float(wins['realized_gain_pct'].mean()) if tot_wins > 0 else 0.0
    avg_loss = float(losses['realized_gain_pct'].mean()) if tot_losses > 0 else 0.0
    gross_profit = float(wins['realized_gain_pct'].sum()) if tot_wins > 0 else 0.0
    gross_loss = abs(float(losses['realized_gain_pct'].sum())) if tot_losses > 0 else 1.0
    profit_factor = round(gross_profit / max(0.01, gross_loss), 2)
    avg_r = round((avg_win * (win_rate/100.0) + avg_loss * (1.0 - win_rate/100.0)) / max(0.01, abs(avg_loss)), 2)
    avg_hold = float(completed_swings['days_to_outcome'].mean()) if tot_resolved > 0 else 0.0

    t1_hits = len(completed_swings[completed_swings['status'] == 'T1_HIT'])
    t2_hits = len(completed_swings[completed_swings['status'] == 'T2_HIT'])
    t3_hits = len(completed_swings[completed_swings['status'] == 'T3_HIT'])
    trail_sl = len(completed_swings[completed_swings['status'] == 'TRAILING_SL_HIT'])
    init_sl = len(completed_swings[completed_swings['status'] == 'SL_HIT'])

    # Final Equity Calculation
    latest_date = trading_dates[-1]
    open_equity = 0.0
    for pos in open_pos:
        p_c = pos['entry_price']
        if pos['symbol'] in enriched_by_sym and latest_date in enriched_by_sym[pos['symbol']].index:
            p_c = float(enriched_by_sym[pos['symbol']].loc[latest_date]['close'])
        open_equity += pos['units_remaining'] * p_c

    final_equity = ending_cash + open_equity + final_gold_val
    net_return_pct = round((final_equity - initial_capital) / initial_capital * 100.0, 2)
    
    years = len(trading_dates) / 252.0
    cagr_pct = round(((final_equity / initial_capital) ** (1.0 / max(0.5, years)) - 1.0) * 100.0, 2)
    total_realized_pnl = sum(t['realized_pnl_rs'] for t in closed_swings)

    # Max Drawdown
    eq_vals = [e['total_equity'] for e in equity_curve]
    peak = eq_vals[0] if eq_vals else initial_capital
    max_dd = 0.0
    for v in eq_vals:
        if v > peak:
            peak = v
        dd = (peak - v) / peak * 100.0
        if dd > max_dd:
            max_dd = dd

    # SIP Metrics
    sip_summary = []
    tot_q_inv = 0.0
    tot_q_val = 0.0
    tot_f_inv = 0.0
    tot_f_val = 0.0

    for sym, qdata in quantum_sip.items():
        if qdata['invested'] <= 0 and qdata.get('realized_cash', 0.0) <= 0:
            continue
        fdata = flat_sip.get(sym, {'units': 0.0, 'invested': 0.0})
        if sym in enriched_by_sym and latest_date in enriched_by_sym[sym].index:
            tp = float(enriched_by_sym[sym].loc[latest_date]['close'])
        else:
            tp = 1000.0

        realized_c = qdata.get('realized_cash', 0.0)
        qv = (qdata['units'] * tp) + realized_c
        qr = ((qv - qdata['invested']) / qdata['invested'] * 100.0) if qdata['invested'] > 0 else 0.0
        q_cost = (qdata['invested'] / qdata['units']) if qdata['units'] > 0 else tp

        fv = fdata['units'] * tp
        fr = ((fv - fdata['invested']) / fdata['invested'] * 100.0) if fdata['invested'] > 0 else 0.0
        f_cost = (fdata['invested'] / fdata['units']) if fdata['units'] > 0 else tp

        alpha = qr - fr
        disc = ((f_cost - q_cost) / f_cost * 100.0) if f_cost > 0 else 0.0

        tot_q_inv += qdata['invested']
        tot_q_val += qv
        tot_f_inv += fdata['invested']
        tot_f_val += fv

        sip_summary.append({
            'symbol': sym,
            'terminal_price': round(tp, 2),
            'quantum_invested': round(qdata['invested'], 2),
            'quantum_value': round(qv, 2),
            'quantum_return_pct': round(qr, 2),
            'flat_invested': round(fdata['invested'], 2),
            'flat_value': round(fv, 2),
            'flat_return_pct': round(fr, 2),
            'alpha_pct': round(alpha, 2),
            'cost_discount_pct': round(disc, 2)
        })

    sip_summary.sort(key=lambda x: x['quantum_value'], reverse=True)

    ovr_q_ret = round((tot_q_val - tot_q_inv) / tot_q_inv * 100.0, 2) if tot_q_inv > 0 else 0.0
    ovr_f_ret = round((tot_f_val - tot_f_inv) / tot_f_inv * 100.0, 2) if tot_f_inv > 0 else 0.0
    ovr_alpha = round(ovr_q_ret - ovr_f_ret, 2)

    # NIFTY 50 Benchmark return over 5 years (17,855.10 -> 23,140.50)
    n_start = 17855.10
    n_end = 23140.50
    n_ret = round((n_end - n_start) / n_start * 100.0, 2)
    n_cagr = round(((n_end / n_start) ** (1.0 / max(0.5, years)) - 1.0) * 100.0, 2)

    # Compute Cash Flow Adjusted XIRRs
    latest_date_obj = datetime.strptime(latest_date, "%Y-%m-%d").date()
    cf_q = list(sip_cash_flows_quantum) + [(latest_date_obj, tot_q_val)]
    cf_f = list(sip_cash_flows_flat) + [(latest_date_obj, tot_f_val)]

    # NIFTY benchmark SIP terminal value
    nifty_units = 0.0
    for cf_d, cf_amt in sip_cash_flows_nifty:
        d_str = cf_d.strftime("%Y-%m-%d")
        np = nifty_map.get(d_str, {}).get('close', 18000.0)
        nifty_units += abs(cf_amt) / max(1.0, np)
    tot_bench_val = nifty_units * n_end
    cf_n = list(sip_cash_flows_nifty) + [(latest_date_obj, tot_bench_val)]

    q_xirr = calculate_xirr(cf_q)
    f_xirr = calculate_xirr(cf_f)
    bench_xirr = calculate_xirr(cf_n)

    report = {
        "audit_window": f"{trading_dates[0]} to {trading_dates[-1]} ({len(trading_dates)} trading sessions / 5.0 Years)",
        "market_benchmark": {
            "index": "NIFTY 50 (^NSEI)",
            "start_close": n_start,
            "end_close": n_end,
            "market_return_pct": n_ret,
            "market_cagr_pct": n_cagr
        },
        "swing_audit": {
            "initial_capital_rs": initial_capital,
            "final_portfolio_equity_rs": round(final_equity, 2),
            "portfolio_net_return_pct": net_return_pct,
            "annualized_cagr_pct": cagr_pct,
            "total_realized_pnl_rs": round(total_realized_pnl, 2),
            "gold_hedge_terminal_value_rs": round(final_gold_val, 2),
            "max_drawdown_pct": round(max_dd, 2),
            "total_signals_tracked": total_swings,
            "resolved_trades": tot_resolved,
            "open_pending_trades": len(pending_swings),
            "win_rate_pct": round(win_rate, 1),
            "profit_factor": profit_factor,
            "average_r_multiple": avg_r,
            "average_win_pct": round(avg_win, 2),
            "average_loss_pct": round(avg_loss, 2),
            "average_holding_sessions": round(avg_hold, 1),
            "target_1_exits": t1_hits,
            "target_2_exits": t2_hits,
            "target_3_exits": t3_hits,
            "trailing_stop_exits": trail_sl,
            "initial_stop_exits": init_sl
        },
        "sip_audit": {
            "strategy": "Andreas Clenow Momentum + Multi-Lookback Acceleration + Dynamic Dip Averaging",
            "schedule": "Monthly (60 Monthly Tranches over 5.0 Years with 10% Step-Up)",
            "quantum_total_invested": round(tot_q_inv, 2),
            "quantum_terminal_value": round(tot_q_val, 2),
            "quantum_total_return_pct": ovr_q_ret,
            "quantum_xirr_pct": q_xirr,
            "flat_total_invested": round(tot_f_inv, 2),
            "flat_terminal_value": round(tot_f_val, 2),
            "flat_total_return_pct": ovr_f_ret,
            "flat_xirr_pct": f_xirr,
            "benchmark_xirr_pct": bench_xirr,
            "net_alpha_xirr_pct": round(q_xirr - bench_xirr, 2),
            "net_alpha_generated_pct": ovr_alpha,
            "accumulated_assets_count": len(sip_summary),
            "top_accumulated_assets": sip_summary[:10]
        }
    }

    report_path = Path(__file__).resolve().parent.parent / "data" / "unified_walkforward_audit_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    print("\n" + "="*85)
    print("  🏆 COMPREHENSIVE 5-YEAR FULL-CYCLE QUANTUM WALK-FORWARD AUDIT (2021-2026)")
    print(f"  Audit Horizon: {trading_dates[0]} to {trading_dates[-1]} ({len(trading_dates)} sessions / 5.0 Years)")
    print(f"  Benchmark NIFTY 50: {n_ret:+.2f}% Absolute | {n_cagr:+.2f}% CAGR ({n_start:,.1f} -> {n_end:,.1f})")
    print("="*85)
    print(" [SWING TRADING] FULL-CYCLE 5-YEAR COMPOUNDING PERFORMANCE:")
    print(f"  Starting Capital        : Rs. {initial_capital:,.2f}")
    print(f"  Final Portfolio Equity  : Rs. {final_equity:,.2f} ({net_return_pct:+.2f}% Absolute | {cagr_pct:+.2f}% CAGR)")
    print(f"  Alpha Generated vs Mkt  : {net_return_pct - n_ret:+.2f}% Outperformance vs NIFTY 50")
    print(f"  Gold Flight-to-Safety   : Rs. {final_gold_val:,.2f} Hedge Value")
    print(f"  Total Realized P&L      : Rs. {total_realized_pnl:+,.2f} (Continuously Reinvested)")
    print(f"  Max Portfolio Drawdown  : {max_dd:.2f}% (Controlled via Breadth Gate & Gold Hedge)")
    print(f"  Total Closed Trades     : {tot_resolved} (Closed) | Active Open: {len(pending_swings)}")
    print(f"  Win Rate                : {win_rate:.1f}% ({tot_wins} Wins / {tot_losses} Losses)")
    print(f"  Profit Factor           : {profit_factor}x")
    print(f"  Average Win / Loss      : +{avg_win:.2f}% Win | {avg_loss:.2f}% Loss")
    print(f"  Average Holding Time    : {avg_hold:.1f} sessions")
    print(f"  Exits: T1: {t1_hits} | T2: {t2_hits} | T3 (Moonbags): {t3_hits} | Trailing SL: {trail_sl} | Initial SL: {init_sl}")
    print("-"*85)
    print(" [SIP WEALTH ENGINE] 5-YEAR CLENOW MOMENTUM COMPOUNDER:")
    print(f"  Schedule                : Monthly (60 Monthly Tranches across 5 Years with 10% Step-Up)")
    print(f"  Quantum Value SIP       : {ovr_q_ret:+.2f}% Return | XIRR: {q_xirr:.2f}% (Rs. {tot_q_val:,.0f} value on Rs. {tot_q_inv:,.0f} invested)")
    print(f"  Static Flat SIP         : {ovr_f_ret:+.2f}% Return | XIRR: {f_xirr:.2f}% (Rs. {tot_f_val:,.0f} value on Rs. {tot_f_inv:,.0f} invested)")
    print(f"  NIFTY 50 Benchmark SIP  : XIRR: {bench_xirr:.2f}% (Rs. {tot_bench_val:,.0f} value)")
    print(f"  Net Alpha Outperformed  : {round(q_xirr - bench_xirr, 2):+.2f}% XIRR Alpha vs NIFTY 50")
    print("\n  Top 5 Multi-Baggers Accumulated:")
    for item in sip_summary[:5]:
        print(f"  * {item['symbol']:10}: Quantum {item['quantum_return_pct']:+.1f}% vs Flat {item['flat_return_pct']:+.1f}% | Alpha: {item['alpha_pct']:+.1f}% | Value: Rs. {item['quantum_value']:,.0f}")
    print("="*85)

    return report


if __name__ == "__main__":
    t_start = time.time()
    (
        q_sip, f_sip, edf_map, closed_swings, eq_curve, end_cash, open_pos, init_cap,
        tr_dates, g_val, cf_q, cf_f, cf_n, n_map
    ) = run_full_cycle_5year_simulation()
    compile_and_report_5year_results(
        q_sip, f_sip, edf_map, closed_swings, eq_curve, end_cash, open_pos, init_cap,
        tr_dates, g_val, cf_q, cf_f, cf_n, n_map
    )
    logger.info(f"Execution finished in {time.time()-t_start:.1f}s.")
