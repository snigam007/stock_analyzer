"""
Verify upgraded sip_audit_backtester defaults
"""
import sys
from pathlib import Path
_curr = Path(__file__).resolve()
while _curr != _curr.parent:
    if (_curr / "core").exists() and (_curr / "db").exists():
        break
    _curr = _curr.parent
BASE_DIR = _curr
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from db.database import get_global_engine, get_session
from core.sip_audit_backtester import run_monthly_sip_backtest

def main():
    s = get_session(get_global_engine())
    r = run_monthly_sip_backtest(s, months_lookback=60, annual_step_up_pct=10.0, risk_profile="RISKY")
    print("=======================================================")
    print("UPGRADED 5-YEAR AUDIT RESULT (PRODUCTION DEFAULTS)")
    print("=======================================================")
    print(f"  Corpus:       Rs. {r['final_strategy_value']:,.2f}")
    print(f"  XIRR:         {r['strategy_xirr']:.2f}%")
    print(f"  Benchmark:    {r['benchmark_xirr']:.2f}%")
    print(f"  Alpha:        +{r['alpha']:.2f}%")
    print(f"  Max Drawdown: {r['max_drawdown_pct']:.2f}%")
    print(f"  Profit Fact:  {r['profit_factor']:.2f}")
    print(f"  Win Rate:     {r['win_rate']:.1f}%")
    print(f"  Skims:        {r['skimmed_trades_count']}")
    print(f"  Dip Buys:     {r['dip_buys_count']}")
    print(f"  Pyramids:     {r['pyramided_trades_count']}")
    s.close()

if __name__ == "__main__":
    main()
