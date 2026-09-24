import pandas as pd
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

swing_csv = BASE_DIR / "scripts" / "swing_100_strategies_results.csv"
sip_csv = BASE_DIR / "scripts" / "sip_100_strategies_results.csv"

df_sw = pd.read_csv(swing_csv)
df_sip = pd.read_csv(sip_csv)

print("=" * 120)
print("TOP 5 DAILY SWING STRATEGIES")
print("=" * 120)
for r in df_sw.head(5).to_dict(orient="records"):
    print(f"[{r['id']}] {r['name']}")
    print(f"   Score: {r['composite_score']:+.1f} | 1Yr XIRR: {r['cycle_xirr']:+.1f}% | 1Yr Alpha: {r['cycle_alpha']:+.1f}% | Bull Ret: {r['bull_ret']:+.1f}% | Chop Ret: {r['chop_ret']:+.1f}% | Bear Ret: {r['worst_bear_ret']:+.1f}% | PR: {r['cycle_pr']:.2f}x | PF: {r['cycle_pf']:.2f} | DD: {r['cycle_dd']:.1f}%")

print("\n" + "=" * 120)
print("TOP 5 MONTHLY SIP STRATEGIES")
print("=" * 120)
for r in df_sip.head(5).to_dict(orient="records"):
    print(f"[{r['id']}] {r['name']}")
    print(f"   Score: {r['composite_score']:+.1f} | Full XIRR: {r['full_xirr']:+.1f}% | 1Yr XIRR: {r['one_yr_xirr']:+.1f}% | 1Yr Alpha: {r['one_yr_alpha']:+.1f}% | Bull Ret: {r['bull_ret']:+.1f}% | Bear Ret: {r['bear_ret']:+.1f}% | PR: {r['full_pr']:.2f}x | DD: {r['full_dd']:.1f}%")
