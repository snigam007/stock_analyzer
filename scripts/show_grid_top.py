import sys, csv
sys.stdout.reconfigure(encoding='utf-8')

with open('scripts/grid_results_60m.csv', encoding='utf-8') as f:
    rows = list(csv.DictReader(f))

rows.sort(key=lambda r: float(r['xirr']), reverse=True)

print("TOP 15 BY XIRR:")
print(f"{'XIRR':>6} {'PF':>5} {'Payoff':>7} {'WinR':>5} {'DD':>6}  {'Protocol':18} {'Sizing':18} {'Step':5} {'3Tier':5} {'Clenow':6} {'Hedge':5}")
print("-" * 110)
for r in rows[:15]:
    print(f"{float(r['xirr']):6.1f}% {float(r['profit_factor']):5.2f}  {float(r['payoff']):6.2f}x {float(r['win_rate']):5.1f}% {float(r['max_dd']):6.1f}%  {r['proto'][:18]:18} {r['sizing'][:18]:18} {r['step'][:5]:5} {r['3tier'][:5]:5} {r['clenow'][:5]:6} {r['hedge_pct']:>3}%")

print()
print("CORRELATION ANALYSIS: what matters most?")
print("-" * 60)
for col in ['proto', 'sizing', 'step', '3tier', 'clenow', 'hedge_pct']:
    vals = {}
    for r in rows:
        k = r[col]
        vals.setdefault(k, []).append(float(r['xirr']))
    print(f"\n  {col}:")
    for k, xirrs in sorted(vals.items(), key=lambda x: -sum(x[1])/len(x[1])):
        avg = sum(xirrs)/len(xirrs)
        mx = max(xirrs)
        print(f"    {k:30} avg={avg:5.1f}%  max={mx:5.1f}%  n={len(xirrs)}")
