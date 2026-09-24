"""
scripts/test_quantum_sip_strategies.py

Research and Backtesting Script to Crack the Optimal Automatic Switching
between Centurion Wealth Engine and Apex Concentrated Compounder,
AND create the Quantum-Level Strategy that dominates both.

Candidate Strategies Tested:
  1. Benchmark A: Pure Centurion Wealth Engine (Defensive Anchor)
  2. Benchmark B: Pure Apex Compounder SIP_00769 (Alpha Rocket)
  3. Quantum Model 1: Market Breadth Dual-Gate Switcher (Breadth >= 50% Apex, else Centurion)
  4. Quantum Model 2: Small/Large Cap Relative Momentum Gate (Cap-Ratio Switcher)
  5. Quantum Model 3: 4-State Dynamic Macro Tensor Engine:
       - State 1 (Super Bull: Nifty > 21 EMA & Breadth > 60%): 85% Apex + 15% Centurion
       - State 2 (Moderate Bull: Nifty > 50 EMA & Breadth > 40%): 50% Apex + 50% Centurion
       - State 3 (Distribution / Chop: Breadth < 40% or Nifty < 50 EMA): 20% Apex + 80% Centurion
       - State 4 (Severe Bear: Nifty < 50 & 200 EMA): 10% Centurion Large + 90% LiquidBees
  6. Quantum Model 4: Quantum Horizon Synergy (Stock-Level Alpha-Fortress Fusion):
       - 2 Large Cap Anchors (Quality + Low Vol) + 2 High-Momentum Rockets + 1 Tactical Dip / LiquidBees Hedge
       - Active Winner Skimming (+100% gain -> skim 10% to LiquidBees)
  7. Quantum Model 5: Quantum Asymmetric Ratchet Engine:
       - Volatility-scaled dynamic deployment with tactical crash double-down
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

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from scripts.backtest_all_history_sip_and_swing import (
    load_universe_data,
    precompute_market_breadth_and_trend,
    precompute_stock_technical_matrix,
    calculate_xirr,
    calculate_max_drawdown
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s")
logger = logging.getLogger("quantum_research")


def compute_relative_cap_momentum_and_breadth(stock_dfs: Dict[str, pd.DataFrame], daily_mkt: pd.DataFrame):
    """
    Computes daily:
      1. Market Breadth: % of stocks with close >= 50 EMA
      2. Small vs Large Cap Ratio: Relative performance of Small/Mid vs Large caps over 60 days
    """
    logger.info("Computing macro breadth and SmallCap/LargeCap relative momentum...")
    breadth_map = {}
    
    # Pre-index dates
    all_dates = daily_mkt['date'].tolist()
    
    for d in all_dates:
        n_total = 0
        n_above_50 = 0
        small_returns = []
        large_returns = []
        
        for sym, df_s in stock_dfs.items():
            if d in df_s.index:
                row = df_s.loc[d]
                cp = row['close']
                e50 = row['ema_50']
                tier = row['market_cap_tier']
                m3 = row['mom_3m']
                
                if cp > 30 and not pd.isna(cp):
                    n_total += 1
                    if cp >= e50:
                        n_above_50 += 1
                    if tier == 'Small' or tier == 'Mid':
                        small_returns.append(m3)
                    elif tier == 'Large':
                        large_returns.append(m3)
        
        breadth_pct = (n_above_50 / n_total * 100.0) if n_total > 0 else 50.0
        avg_small_m3 = np.mean(small_returns) if small_returns else 0.0
        avg_large_m3 = np.mean(large_returns) if large_returns else 0.0
        small_outperformance = avg_small_m3 - avg_large_m3
        
        breadth_map[d] = {
            'breadth_pct': round(breadth_pct, 1),
            'small_outperformance': round(small_outperformance, 1)
        }
        
    logger.info("Macro breadth and cap-ratio vectors computed.")
    return breadth_map


def simulate_quantum_sip(
    strategy_key: str,
    trading_dates: List[date],
    stock_dfs: Dict[str, pd.DataFrame],
    mkt_map: Dict[date, Any],
    breadth_map: Dict[date, Any],
    monthly_installment: float = 25000.0,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None
) -> Dict[str, Any]:
    """
    Executes monthly SIP simulation under quantum switching and hybrid rules.
    """
    filtered_dates = [d for d in trading_dates if (start_date is None or d >= start_date) and (end_date is None or d <= end_date)]
    if not filtered_dates:
        return {"xirr": 0.0, "final_val": 0.0, "max_dd": 0.0, "calmar": 0.0, "invested": 0.0, "multiple": 0.0}

    monthly_injections = []
    seen_months = set()
    for d in filtered_dates:
        m_key = (d.year, d.month)
        if m_key not in seen_months:
            seen_months.add(m_key)
            monthly_injections.append(d)

    holdings = {} # sym -> {shares, cost_basis, last_price, peak_price}
    cash_liquidbees = 0.0
    cash_flows = []
    equity_curve = []

    def update_holding(sym_code, num_sh, close_px, tot_cost):
        h_obj = holdings.get(sym_code, {'shares': 0, 'cost_basis': close_px, 'last_price': close_px, 'peak_price': close_px})
        new_shares = h_obj['shares'] + num_sh
        h_obj['cost_basis'] = (h_obj['cost_basis'] * h_obj['shares'] + tot_cost) / new_shares
        h_obj['shares'] = new_shares
        h_obj['last_price'] = close_px
        h_obj['peak_price'] = max(h_obj.get('peak_price', close_px), close_px)
        holdings[sym_code] = h_obj

    last_inj_idx = 0
    next_inj_date = monthly_injections[0] if monthly_injections else None

    for curr_d in filtered_dates:
        is_rebalance_day = False
        if next_inj_date and curr_d == next_inj_date:
            is_rebalance_day = True
            cash_flows.append((curr_d, -monthly_installment))
            new_cash = monthly_installment
            last_inj_idx += 1
            next_inj_date = monthly_injections[last_inj_idx] if last_inj_idx < len(monthly_injections) else None
        else:
            new_cash = 0.0

        if cash_liquidbees > 0:
            cash_liquidbees += cash_liquidbees * (0.065 / 365.0)

        # Winner Skimming for Model 4 & 5 (+100% gain -> skim 10% to LiquidBees)
        if "SKIM" in strategy_key or "QUANTUM" in strategy_key:
            for sym, h in list(holdings.items()):
                if h['shares'] > 0:
                    df_s = stock_dfs.get(sym)
                    if df_s is not None and curr_d in df_s.index:
                        cp = df_s.loc[curr_d, 'close']
                        if isinstance(cp, pd.Series): cp = float(cp.iloc[-1])
                        if cp >= h['cost_basis'] * 2.0:
                            # Skim 10% of position
                            skim_sh = max(1, int(h['shares'] * 0.10))
                            if h['shares'] > skim_sh:
                                cash_liquidbees += skim_sh * cp
                                h['shares'] -= skim_sh
                                h['cost_basis'] = cp # reset cost basis reference for next skim tier

        if is_rebalance_day:
            wallet_to_deploy = new_cash + cash_liquidbees
            mkt_row = mkt_map.get(curr_d)
            b_info = breadth_map.get(curr_d, {'breadth_pct': 50.0, 'small_outperformance': 0.0})
            
            is_bull = mkt_row.is_bull if mkt_row else True
            breadth = b_info['breadth_pct']
            small_alpha = b_info['small_outperformance']
            mkt_close = mkt_row.market_close if mkt_row else 2000.0
            mkt_e50 = mkt_row.ema_50 if mkt_row else 2000.0
            mkt_e200 = mkt_row.ema_200 if mkt_row else 2000.0

            # Screen active universe
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

            # --- STRATEGY 1: Pure Centurion ---
            if strategy_key == "PURE_CENTURION":
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

                cash_liquidbees = 0.0
                for cand, w in selected:
                    alloc = wallet_to_deploy * w
                    sh = int(alloc / cand['close'])
                    if sh > 0:
                        cost = sh * cand['close']
                        wallet_to_deploy -= cost
                        update_holding(cand['symbol'], sh, cand['close'], cost)
                cash_liquidbees += wallet_to_deploy

            # --- STRATEGY 2: Pure Apex Compounder (SIP_00769) ---
            elif strategy_key == "APEX_00769":
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
                            update_holding(cand['symbol'], sh, cand['close'], cost)
                cash_liquidbees += wallet_to_deploy

            # --- QUANTUM MODEL 1: Market Breadth Dual-Gate Switcher ---
            elif strategy_key == "QM1_BREADTH_SWITCHER":
                # If Market Breadth >= 50% and NIFTY >= 50 EMA -> 100% Apex Compounder
                # Else -> 100% Centurion Wealth Engine
                use_apex = (breadth >= 50.0 and is_bull)
                cash_liquidbees = 0.0
                if use_apex:
                    cands = sorted([s for s in screened if s['mom_6m'] >= 25.0 and s['close'] >= s['ema_50']], key=lambda x: x['multi_score'], reverse=True)[:4]
                    if cands:
                        per_slot = wallet_to_deploy / len(cands)
                        for cand in cands:
                            sh = int(per_slot / cand['close'])
                            if sh > 0:
                                cost = sh * cand['close']
                                wallet_to_deploy -= cost
                                update_holding(cand['symbol'], sh, cand['close'], cost)
                else:
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
                    for cand, w in selected:
                        alloc = wallet_to_deploy * w
                        sh = int(alloc / cand['close'])
                        if sh > 0:
                            cost = sh * cand['close']
                            wallet_to_deploy -= cost
                            update_holding(cand['symbol'], sh, cand['close'], cost)
                cash_liquidbees += wallet_to_deploy

            # --- QUANTUM MODEL 2: Small/Large Cap Relative Alpha Switcher ---
            elif strategy_key == "QM2_CAP_RATIO_SWITCHER":
                # If Small-Caps outperforming Large-Caps by >= +2% over 3M -> Apex Compounder
                # Else -> Centurion Wealth Engine
                use_apex = (small_alpha >= 2.0 and is_bull)
                cash_liquidbees = 0.0
                if use_apex:
                    cands = sorted([s for s in screened if s['mom_6m'] >= 25.0 and s['close'] >= s['ema_50']], key=lambda x: x['multi_score'], reverse=True)[:4]
                    if cands:
                        per_slot = wallet_to_deploy / len(cands)
                        for cand in cands:
                            sh = int(per_slot / cand['close'])
                            if sh > 0:
                                cost = sh * cand['close']
                                wallet_to_deploy -= cost
                                update_holding(cand['symbol'], sh, cand['close'], cost)
                else:
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
                    for cand, w in selected:
                        alloc = wallet_to_deploy * w
                        sh = int(alloc / cand['close'])
                        if sh > 0:
                            cost = sh * cand['close']
                            wallet_to_deploy -= cost
                            update_holding(cand['symbol'], sh, cand['close'], cost)
                cash_liquidbees += wallet_to_deploy

            # --- QUANTUM MODEL 3: 4-State Dynamic Macro Tensor Engine ---
            elif strategy_key == "QM3_4STATE_TENSOR":
                # Determine state:
                if is_bull and breadth >= 55.0 and small_alpha >= 0.0:
                    # State 1: Super Bull -> 85% Apex, 15% Centurion
                    w_apex, w_cent, w_hedge = 0.85, 0.15, 0.0
                elif is_bull and breadth >= 40.0:
                    # State 2: Steady Bull -> 50% Apex, 50% Centurion
                    w_apex, w_cent, w_hedge = 0.50, 0.50, 0.0
                elif mkt_close >= mkt_e200:
                    # State 3: Distribution / Chop -> 20% Apex, 80% Centurion
                    w_apex, w_cent, w_hedge = 0.20, 0.80, 0.0
                else:
                    # State 4: Deep Bear (Below 200 EMA) -> 30% Centurion Large Cap, 70% LiquidBees
                    w_apex, w_cent, w_hedge = 0.0, 0.30, 0.70

                cash_liquidbees = 0.0
                cash_for_apex = wallet_to_deploy * w_apex
                cash_for_cent = wallet_to_deploy * w_cent
                cash_for_hedge = wallet_to_deploy * w_hedge
                cash_liquidbees += cash_for_hedge

                # Deploy Apex portion
                if cash_for_apex > 0:
                    apex_cands = sorted([s for s in screened if s['mom_6m'] >= 20.0 and s['close'] >= s['ema_50']], key=lambda x: x['multi_score'], reverse=True)[:4]
                    if apex_cands:
                        per_a = cash_for_apex / len(apex_cands)
                        for cand in apex_cands:
                            sh = int(per_a / cand['close'])
                            if sh > 0:
                                cost = sh * cand['close']
                                update_holding(cand['symbol'], sh, cand['close'], cost)
                    else:
                        cash_liquidbees += cash_for_apex

                # Deploy Centurion portion
                if cash_for_cent > 0:
                    cands = [s for s in screened if s['close'] >= s['ema_50'] and 40.0 <= s['rsi'] <= 75.0]
                    large = sorted([s for s in cands if s['tier'] == 'Large'], key=lambda x: x['multi_score'], reverse=True)
                    mid = sorted([s for s in cands if s['tier'] == 'Mid'], key=lambda x: x['multi_score'], reverse=True)
                    small = sorted([s for s in cands if s['tier'] == 'Small'], key=lambda x: x['multi_score'], reverse=True)
                    selected = []
                    if large: selected.append((large[0], 0.40))
                    if mid:
                        for m in mid[:2]: selected.append((m, 0.35 / min(2, len(mid))))
                    if small and w_apex == 0.0: # only buy small cap in centurion if not super-bear
                        for sm in small[:2]: selected.append((sm, 0.25 / min(2, len(small))))
                    for cand, w in selected:
                        alloc = cash_for_cent * w
                        sh = int(alloc / cand['close'])
                        if sh > 0:
                            cost = sh * cand['close']
                            update_holding(cand['symbol'], sh, cand['close'], cost)

            # --- QUANTUM MODEL 4: Quantum Horizon Synergy (Stock-Level Fusion) ---
            elif strategy_key == "QM4_HORIZON_SYNERGY":
                # Always holds:
                # 1. Slot 1 & 2 (40%): Top 2 Large-Cap Quality Compounders (Close >= 50 EMA, RSI 40-70)
                # 2. Slot 3 & 4 (40%): Top 2 Alpha Clenow/Multi-lookback Rockets (Small/Mid, 6M mom >= 30%)
                # 3. Slot 5 (20%): Tactical Dip / Hedging Slot:
                #    If NIFTY >= 50 EMA -> 3rd Momentum Rocket
                #    If NIFTY < 50 EMA -> 100% LiquidBees (~6.5% Yield)
                cash_liquidbees = 0.0
                cands_50 = [s for s in screened if s['close'] >= s['ema_50']]
                large_anchors = sorted([s for s in cands_50 if s['tier'] == 'Large'], key=lambda x: x['multi_score'], reverse=True)[:2]
                alpha_rockets = sorted([s for s in cands_50 if s['mom_6m'] >= 25.0], key=lambda x: x['clenow'], reverse=True)[:3]

                # Deploy Anchors (40% total = 20% each)
                anchor_cash = wallet_to_deploy * 0.40
                if large_anchors:
                    per_anc = anchor_cash / len(large_anchors)
                    for cand in large_anchors:
                        sh = int(per_anc / cand['close'])
                        if sh > 0:
                            cost = sh * cand['close']
                            wallet_to_deploy -= cost
                            update_holding(cand['symbol'], sh, cand['close'], cost)
                else:
                    cash_liquidbees += anchor_cash

                # Deploy Rockets (40% total = 20% each)
                rocket_cash = wallet_to_deploy * 0.40
                if alpha_rockets:
                    for cand in alpha_rockets[:2]:
                        alloc = rocket_cash / 2.0
                        sh = int(alloc / cand['close'])
                        if sh > 0:
                            cost = sh * cand['close']
                            wallet_to_deploy -= cost
                            update_holding(cand['symbol'], sh, cand['close'], cost)
                else:
                    cash_liquidbees += rocket_cash

                # Deploy Tactical Slot (20%)
                tactical_cash = wallet_to_deploy * 0.20
                if is_bull and len(alpha_rockets) >= 3:
                    cand = alpha_rockets[2]
                    sh = int(tactical_cash / cand['close'])
                    if sh > 0:
                        cost = sh * cand['close']
                        wallet_to_deploy -= cost
                        update_holding(cand['symbol'], sh, cand['close'], cost)
                else:
                    # In correction or bear regime: sweep tactical slot into LiquidBees!
                    cash_liquidbees += tactical_cash

            # --- QUANTUM MODEL 5: Quantum Asymmetric Ratchet Engine ---
            elif strategy_key == "QM5_ASYMMETRIC_RATCHET":
                # Employs an asymmetric ratchet:
                # When market dips (-5% to -15% correction), it DOUBLES down on top alpha momentum picks (tactical dip deployment).
                # When market is overextended (RSI > 75 or Breadth > 80%), it skims 20% cash into LiquidBees.
                # In secular bear (Below 200 EMA), it switches 100% to Centurion + LiquidBees.
                cash_liquidbees = 0.0
                
                # Check for tactical dip:
                is_dip_opportunity = (mkt_close < mkt_e50 and mkt_close >= mkt_e200)
                is_overheated = (breadth >= 78.0)
                is_deep_bear = (mkt_close < mkt_e200)

                if is_deep_bear:
                    # 40% Large Cap Centurion, 60% LiquidBees
                    w_apex, w_cent, w_hedge = 0.0, 0.40, 0.60
                elif is_dip_opportunity:
                    # Tactical deployment: 90% Apex Alpha leaders at discount, 10% Centurion
                    w_apex, w_cent, w_hedge = 0.90, 0.10, 0.0
                elif is_overheated:
                    # Overheated rally: 40% Apex, 40% Centurion, 20% skimmed to LiquidBees
                    w_apex, w_cent, w_hedge = 0.40, 0.40, 0.20
                else:
                    # Normal trending bull: 70% Apex, 30% Centurion
                    w_apex, w_cent, w_hedge = 0.70, 0.30, 0.0

                cash_liquidbees += wallet_to_deploy * w_hedge
                cash_a = wallet_to_deploy * w_apex
                cash_c = wallet_to_deploy * w_cent

                if cash_a > 0:
                    cands = sorted([s for s in screened if s['mom_6m'] >= 20.0], key=lambda x: x['multi_score'], reverse=True)[:4]
                    if cands:
                        per_c = cash_a / len(cands)
                        for cand in cands:
                            sh = int(per_c / cand['close'])
                            if sh > 0:
                                cost = sh * cand['close']
                                update_holding(cand['symbol'], sh, cand['close'], cost)
                    else:
                        cash_liquidbees += cash_a

                if cash_c > 0:
                    cands = [s for s in screened if s['close'] >= s['ema_50'] and 40.0 <= s['rsi'] <= 75.0]
                    large = sorted([s for s in cands if s['tier'] == 'Large'], key=lambda x: x['multi_score'], reverse=True)
                    mid = sorted([s for s in cands if s['tier'] == 'Mid'], key=lambda x: x['multi_score'], reverse=True)
                    selected = []
                    if large: selected.append((large[0], 0.50))
                    if mid: selected.append((mid[0], 0.50))
                    for cand, w in selected:
                        alloc = cash_c * w
                        sh = int(alloc / cand['close'])
                        if sh > 0:
                            cost = sh * cand['close']
                            update_holding(cand['symbol'], sh, cand['close'], cost)

        # End of day valuation
        total_equity = cash_liquidbees
        for sym, h in list(holdings.items()):
            if h['shares'] > 0:
                df_s = stock_dfs.get(sym)
                if df_s is not None and curr_d in df_s.index:
                    cp = df_s.loc[curr_d, 'close']
                    if isinstance(cp, pd.Series): cp = float(cp.iloc[-1])
                    if pd.isna(cp) or cp <= 0:
                        cp = h.get('last_price', h['cost_basis'])
                    else:
                        h['last_price'] = float(cp)
                    total_equity += h['shares'] * float(cp)
                else:
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


def run_quantum_strategy_matrix():
    logger.info("=" * 75)
    logger.info("  STARTING QUANTUM SIP STRATEGY MATRIX (2015 - 2026)")
    logger.info("=" * 75)

    df_all = load_universe_data(start_date="2014-01-01")
    daily_mkt, mkt_map = precompute_market_breadth_and_trend(df_all)
    stock_dfs = precompute_stock_technical_matrix(df_all)
    breadth_map = compute_relative_cap_momentum_and_breadth(stock_dfs, daily_mkt)

    all_trading_dates = sorted([d for d in daily_mkt['date'] if d >= date(2015, 1, 1)])

    regimes = [
        {"key": "ALL_HISTORY_12YR", "name": "Class 0: Full 11.75-Year Supercycle", "start": date(2015, 1, 1), "end": date(2026, 9, 22)},
        {"key": "BULL_2017", "name": "Class 1: 2017 Secular Bull Market", "start": date(2017, 1, 1), "end": date(2017, 12, 31)},
        {"key": "CRASH_2018", "name": "Class 2: 2018 Small/Mid-Cap Carnage", "start": date(2018, 1, 1), "end": date(2018, 12, 31)},
        {"key": "COVID_CRASH_2020", "name": "Class 3: 2020 Covid Crash & Recovery", "start": date(2020, 1, 1), "end": date(2020, 12, 31)},
        {"key": "SUPERBULL_2021", "name": "Class 4: 2021 Super-Bull", "start": date(2021, 1, 1), "end": date(2021, 12, 31)},
        {"key": "INFLATION_CHOP_2022", "name": "Class 5: 2022 Inflation Chop", "start": date(2022, 1, 1), "end": date(2022, 12, 31)},
        {"key": "BREAKOUT_2023", "name": "Class 6: 2023 Midcap Breakout", "start": date(2023, 1, 1), "end": date(2023, 12, 31)},
        {"key": "RECENT_2024_2026", "name": "Class 7: Recent 2024-2026 Cycle", "start": date(2024, 1, 1), "end": date(2026, 9, 22)}
    ]

    candidate_strategies = [
        ("PURE_CENTURION", "Benchmark A: Pure Centurion Wealth Engine"),
        ("APEX_00769", "Benchmark B: Pure Apex Compounder (SIP_00769)"),
        ("QM1_BREADTH_SWITCHER", "Quantum 1: Market Breadth Dual-Gate Switcher"),
        ("QM2_CAP_RATIO_SWITCHER", "Quantum 2: Small/Large Cap Relative Alpha Switcher"),
        ("QM3_4STATE_TENSOR", "Quantum 3: 4-State Dynamic Macro Tensor Engine"),
        ("QM4_HORIZON_SYNERGY", "Quantum 4: Quantum Horizon Synergy (Stock-Level Fusion + Skim)"),
        ("QM5_ASYMMETRIC_RATCHET", "Quantum 5: Quantum Asymmetric Ratchet Engine (Dip Buy + Skim)")
    ]

    results = []

    for reg in regimes:
        logger.info(f"\n========================================================")
        logger.info(f"  EVALUATING IN: {reg['name']} ({reg['start']} to {reg['end']})")
        logger.info(f"========================================================")
        for skey, sname in candidate_strategies:
            res = simulate_quantum_sip(
                strategy_key=skey,
                trading_dates=all_trading_dates,
                stock_dfs=stock_dfs,
                mkt_map=mkt_map,
                breadth_map=breadth_map,
                monthly_installment=25000.0,
                start_date=reg['start'],
                end_date=reg['end']
            )
            results.append({
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
            logger.info(f"  [{skey:24}] XIRR: {res['xirr']:+6.2f}% | Max DD: {res['max_dd']:5.2f}% | Final: ₹{res['final_val']:12,.2f} | Mult: {res['multiple']:.2f}x | Calmar: {res['calmar']:4.2f}")

    df_res = pd.DataFrame(results)
    out_csv = BASE_DIR / "scripts" / "quantum_sip_backtest_results.csv"
    df_res.to_csv(out_csv, index=False)
    logger.info(f"\nSaved Quantum SIP Backtest Results to: {out_csv}")


if __name__ == "__main__":
    run_quantum_strategy_matrix()
