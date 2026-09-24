"""
scripts/sweep_breadth_gate_thresholds.py

Sweeps the exact mathematical parameter space for the Breadth Dual-Gate
between Pure Centurion and Apex Compounder (SIP_00769) to find the global optimum.
"""
import sys
from pathlib import Path
from typing import Dict, List, Any
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
from scripts.test_quantum_sip_strategies import compute_relative_cap_momentum_and_breadth

def run_sweep():
    df_all = load_universe_data(start_date="2014-01-01")
    daily_mkt, mkt_map = precompute_market_breadth_and_trend(df_all)
    stock_dfs = precompute_stock_technical_matrix(df_all)
    breadth_map = compute_relative_cap_momentum_and_breadth(stock_dfs, daily_mkt)

    all_trading_dates = sorted(list(mkt_map.keys()))
    monthly_injections = []
    seen_months = set()
    for d in all_trading_dates:
        m_key = (d.year, d.month)
        if m_key not in seen_months:
            seen_months.add(m_key)
            monthly_injections.append(d)

    monthly_installment = 25000.0

    breadth_thresholds = [35.0, 40.0, 45.0, 50.0, 52.5, 55.0, 60.0]
    ema_filters = ['ema_21', 'ema_50', 'ema_200', 'none']

    results = []

    for b_thresh in breadth_thresholds:
        for ema_filt in ema_filters:
            holdings = {}
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

            for curr_d in all_trading_dates:
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

                if is_rebalance_day:
                    wallet_to_deploy = new_cash + cash_liquidbees
                    mkt_row = mkt_map.get(curr_d)
                    b_info = breadth_map.get(curr_d, {'breadth_pct': 50.0, 'small_outperformance': 0.0})
                    breadth = b_info['breadth_pct']

                    if ema_filt == 'ema_21':
                        trend_ok = (mkt_row.market_close >= mkt_row.ema_21) if mkt_row else True
                    elif ema_filt == 'ema_50':
                        trend_ok = (mkt_row.market_close >= mkt_row.ema_50) if mkt_row else True
                    elif ema_filt == 'ema_200':
                        trend_ok = (mkt_row.market_close >= mkt_row.ema_200) if mkt_row else True
                    else:
                        trend_ok = True

                    use_apex = (breadth >= b_thresh and trend_ok)

                    # Screen active universe
                    screened = []
                    for sym, df_s in stock_dfs.items():
                        if curr_d in df_s.index:
                            row = df_s.loc[curr_d]
                            cp = row['close']
                            if cp < 30 or pd.isna(cp): continue
                            screened.append({
                                'symbol': sym,
                                'close': cp,
                                'ema_50': row['ema_50'],
                                'rsi': row['rsi_14'],
                                'mom_6m': row['mom_6m'],
                                'multi_score': row['multi_lookback_score'],
                                'tier': row['market_cap_tier']
                            })

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

                # Daily Portfolio Valuation
                tot_val = cash_liquidbees
                for sym, h in holdings.items():
                    if h['shares'] > 0:
                        df_s = stock_dfs.get(sym)
                        if df_s is not None and curr_d in df_s.index:
                            cp = df_s.loc[curr_d, 'close']
                            if isinstance(cp, pd.Series): cp = float(cp.iloc[-1])
                            h['last_price'] = cp
                        tot_val += h['shares'] * h['last_price']
                equity_curve.append((curr_d, tot_val))

            final_date, final_val = equity_curve[-1]
            cash_flows.append((final_date, final_val))
            xirr = calculate_xirr(cash_flows)
            equity_vals = [pt[1] for pt in equity_curve]
            max_dd = calculate_max_drawdown(equity_vals)
            calmar = (xirr / max_dd) if max_dd > 0 else 0.0
            invested = len(monthly_injections) * monthly_installment

            results.append({
                'breadth_thresh': b_thresh,
                'ema_filter': ema_filt,
                'xirr': round(xirr, 2),
                'final_val': round(final_val, 2),
                'max_dd': round(max_dd, 2),
                'calmar': round(calmar, 2),
                'multiple': round(final_val / invested, 2)
            })
            print(f"B={b_thresh:4.1f}% | EMA={ema_filt:7s} -> XIRR: {xirr:5.2f}% | Final: Rs {final_val:12,.2f} | MaxDD: {max_dd:4.2f}% | Calmar: {calmar:4.2f}")

    df_res = pd.DataFrame(results)
    df_res.sort_values(by='xirr', ascending=False, inplace=True)
    out_csv = BASE_DIR / "scripts" / "breadth_gate_sweep_results.csv"
    df_res.to_csv(out_csv, index=False)
    print(f"\nTop 10 Parameter Sets:")
    print(df_res.head(10).to_string(index=False))

if __name__ == "__main__":
    run_sweep()
