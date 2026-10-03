import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from scripts.verify_quantum_50pct_winrate_5year import load_5year_data, run_verification_simulation, DB_PATH

def main():
    mkt_map, trading_dates, stock_dfs = load_5year_data(DB_PATH)
    print("=" * 90)
    print(f"{'T1 ATR Multiplier':<20} | {'Trades':<8} | {'WinRate':<9} | {'PF':<7} | {'CAGR':<8} | {'MaxDD':<8} | {'Calmar':<8}")
    print("-" * 90)
    for mult in [0.70, 0.80, 0.85, 0.90, 1.00, 1.10]:
        res = run_verification_simulation(
            trading_dates=trading_dates,
            stock_dfs=stock_dfs,
            mkt_map=mkt_map,
            variant_name=f"T1 @ {mult}x ATR",
            tier1_mult=mult,
            tier1_ratio=0.25,
            use_clenow_gate=False,
            instant_be_at_t1=True,
            use_jev_downsizing=False
        )
        print(f"{mult:<20.2f} | {res['trades']:<8} | {res['win_rate']:<8.1f}% | {res['profit_factor']:<6.2f}x | {res['cagr']:<7.1f}% | {res['max_dd']:<7.1f}% | {res['calmar']:<7.2f}")
    print("=" * 90)

if __name__ == '__main__':
    main()
