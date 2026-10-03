"""
scripts/run_15y_and_20y_backtest.py
===================================
Runs 15-Year (180 months) and 20-Year (240 months) historical simulations
spanning 2006-2026 (including 2008 Global Financial Crisis) to determine
true multi-decade realistic CAGR.
"""
import sys
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from db.database import get_global_engine, get_session
from core.sip_audit_backtester import run_monthly_sip_backtest

def run_multi_decade_tests():
    session = get_session(get_global_engine())
    cfg = {
        'monthly_wallet': 20000.0,
        'strategy': 'PURE_STOCKS',
        'exit_protocol': 'ADAPTIVE_STRUCTURAL',
        'risk_profile': 'RISKY',
        'annual_step_up_pct': 10.0,
        'pyramid_winners': True,
        'target_stock_count': 4,
        'dip_threshold_pct': 3.0,
        'dip_deploy_pct': 90.0,
        'skim_milestone_pct': 120.0,
        'skim_ratio_pct': 10.0,
        'enable_liquid_sweep': True,
        'liquid_yield_pct': 6.5
    }

    for months in [180, 240]:
        yr = months // 12
        cfg['months_lookback'] = months
        print(f"\nRunning {yr}-Year ({months} Months) Historical Backtest...")
        res = run_monthly_sip_backtest(session, **cfg)
        inv = res.get('total_invested', 0.0)
        val = res.get('final_strategy_value', 0.0)
        sxirr = res.get('strategy_xirr', 0.0)
        bxirr = res.get('benchmark_xirr', 0.0)
        mdd = res.get('max_drawdown_pct', 0.0)
        pf = res.get('profit_factor', 0.0)
        trades = res.get('total_trades', 0)
        
        print(f"  [{yr}-YEAR RESULT]")
        print(f"  Invested: Rs. {inv:,.0f} | Final Corpus: Rs. {val:,.0f} ({val/max(1,inv):.2f}x multiple)")
        print(f"  Net XIRR: {sxirr:.2f}% (Benchmark: {bxirr:.2f}% | Alpha: {sxirr-bxirr:+.2f}%)")
        print(f"  Max Drawdown: {mdd:.2f}% | Profit Factor: {pf:.2f}x | Total Trades: {trades}")

    session.close()

if __name__ == "__main__":
    run_multi_decade_tests()
