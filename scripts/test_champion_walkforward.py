import time
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.sip_audit_backtester import run_monthly_sip_backtest
from scripts.backtest_60_plus_alpha_frontiers import BASE_CHAMP
from scripts.backtest_all_history_sip_and_swing import (
    load_market_regime_map, load_and_enrich_all_stocks, simulate_swing_engine
)

DB_PATH = Path("data/stock_analyzer.db")
engine = create_engine(f"sqlite:///{DB_PATH}")
Session = sessionmaker(bind=engine)
session = Session()

print("=" * 80)
print("  EXECUTING QUANTUM CHAMPION 5-YEAR AUDIT")
print("=" * 80)

# 1. CHAMPION SIP
t0 = time.time()
sip_res = run_monthly_sip_backtest(session, **BASE_CHAMP)
print(f"1. QUANTUM SIP CHAMPION (60 Months / 5.0 Years):")
print(f"   Net XIRR        : {sip_res['strategy_xirr']:.2f}% (Benchmark: {sip_res['benchmark_xirr']:.2f}%)")
print(f"   Alpha vs NIFTY  : {sip_res['alpha']:+.2f}%")
print(f"   Total Invested  : Rs. {sip_res['total_invested']:,.2f}")
print(f"   Final Corpus    : Rs. {sip_res['final_strategy_value']:,.2f}")
print(f"   Net Profit      : Rs. {sip_res['net_strategy_profit']:,.2f}")
print(f"   Profit Factor   : {sip_res['profit_factor']:.2f}x | Payoff: {sip_res['payoff_ratio']:.2f}x")
print(f"   Max Drawdown    : {sip_res['max_drawdown_pct']:.2f}%")
print(f"   Trades          : {sip_res['total_trades']} (Win Rate: {sip_res['win_rate']:.1f}%)")
print(f"   [Execution Time : {time.time()-t0:.2f}s]")

# 2. CHAMPION SWING
t1 = time.time()
mkt_map, all_dates = load_market_regime_map(DB_PATH)
stock_dfs = load_and_enrich_all_stocks(DB_PATH, all_dates)

start_d = pd.to_datetime("2021-09-27").date()
end_d = pd.to_datetime("2026-09-25").date()

swing_champ = simulate_swing_engine(
    "CHAMPION_SW_005479_000640",
    all_dates, stock_dfs, mkt_map,
    initial_capital=500000.0,
    start_date=start_d, end_date=end_d
)

print(f"\n2. QUANTUM SWING CHAMPION (SW_005479 + SW_000640 Fusion, 5.0 Years):")
print(f"   Starting Capital: Rs. 500,000.00")
print(f"   Final Equity    : Rs. {swing_champ['final_val']:,.2f} ({swing_champ['multiple']:.2f}x Capital)")
print(f"   Annualized CAGR : {swing_champ['cagr']:.2f}%")
print(f"   Max Drawdown    : {swing_champ['max_dd']:.2f}%")
print(f"   Profit Factor   : {swing_champ['profit_factor']:.2f}x")
print(f"   Win Rate        : {swing_champ['win_rate']:.1f}% ({swing_champ['trades']} Trades)")
print(f"   Calmar Ratio    : {swing_champ['calmar']:.2f}")

pure_champ = simulate_swing_engine(
    "PURE_SW_005479",
    all_dates, stock_dfs, mkt_map,
    initial_capital=500000.0,
    start_date=start_d, end_date=end_d
)
print(f"\n3. PURE SW_005479 (ALPHA CHAMPION, 5.0 Years):")
print(f"   Final Equity    : Rs. {pure_champ['final_val']:,.2f} ({pure_champ['multiple']:.2f}x Capital)")
print(f"   Annualized CAGR : {pure_champ['cagr']:.2f}%")
print(f"   Max Drawdown    : {pure_champ['max_dd']:.2f}%")
print(f"   Profit Factor   : {pure_champ['profit_factor']:.2f}x")
print(f"   Win Rate        : {pure_champ['win_rate']:.1f}% ({pure_champ['trades']} Trades)")
print("=" * 80)
