"""
scripts/backtest_mean_reversion_all_tf.py
Evaluates Mean-Reversion (RSI Oversold Bounces) across all 4 timeframes:
1-Hour vs Daily vs Weekly vs Monthly
"""
import sys
import numpy as np
import pandas as pd
import yfinance as yf

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SYMBOLS = [
    "RELIANCE.NS", "TCS.NS", "INFY.NS", "ICICIBANK.NS",
    "SBIN.NS", "BHARTIARTL.NS", "SUNPHARMA.NS", "ITC.NS"
]

FRICTION_MAP = {
    "1-Hour": 0.0020,
    "Daily": 0.0015,
    "Weekly": 0.0012,
    "Monthly": 0.0010
}

def resample_bars(df_daily, freq):
    agg = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    return df_daily.resample(freq).agg(agg).dropna(subset=["Close"])

def test_mr(df, tf_name, rsi_period=14, oversold=35, exit_rsi=55):
    if len(df) < rsi_period * 2:
        return None
    c = df["Close"]
    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/rsi_period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/rsi_period, adjust=False).mean()
    rsi = (100 - (100 / (1 + gain / loss.replace(0, np.nan)))).fillna(50)
    
    atr = (df["High"] - df["Low"]).rolling(14).mean().bfill()
    fric = FRICTION_MAP.get(tf_name, 0.0015)
    
    trades = []
    in_pos = False
    ep, sl, tp, e_idx = 0, 0, 0, 0
    
    for i in range(rsi_period + 5, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i-1]
        
        if not in_pos:
            # RSI crosses up through oversold threshold
            if prev.name in rsi.index and row.name in rsi.index:
                if rsi.iloc[i-1] <= oversold and rsi.iloc[i] > oversold:
                    in_pos = True
                    ep = row["Close"] * (1 + fric/2)
                    sl = ep - 1.8 * atr.iloc[i]
                    tp = ep + 3.0 * atr.iloc[i]
                    e_idx = i
        else:
            hit_sl = row["Low"] <= sl
            hit_tp = row["High"] >= tp
            rsi_exit = rsi.iloc[i] >= exit_rsi
            
            if hit_sl or hit_tp or rsi_exit:
                xp = sl if hit_sl else (tp if hit_tp else row["Close"])
                xp = xp * (1 - fric/2)
                ret = (xp - ep) / ep * 100.0 - (fric * 100)
                trades.append({
                    "pnl": ret,
                    "bars": i - e_idx,
                    "win": ret > 0
                })
                in_pos = False
                
    if not trades:
        return {"tf": tf_name, "trades": 0, "win_rate": 0, "profit_factor": 0, "total_return": 0, "max_dd": 0, "avg_bars": 0}
        
    df_t = pd.DataFrame(trades)
    wins = df_t[df_t["win"]]
    losses = df_t[~df_t["win"]]
    win_rate = len(wins) / len(df_t) * 100.0
    gw = wins["pnl"].sum() if len(wins) > 0 else 0
    gl = abs(losses["pnl"].sum()) if len(losses) > 0 else 0.001
    pf = gw / gl
    
    eq = (1 + df_t["pnl"] / 100.0).cumprod()
    peak = eq.cummax()
    dd = (eq - peak) / peak * 100.0
    max_dd = abs(dd.min()) if len(dd) > 0 else 0
    tot_ret = (eq.iloc[-1] - 1.0) * 100.0
    
    return {
        "tf": tf_name,
        "trades": len(df_t),
        "win_rate": round(win_rate, 1),
        "profit_factor": round(pf, 2),
        "total_return": round(tot_ret, 1),
        "max_dd": round(max_dd, 1),
        "avg_bars": round(df_t["bars"].mean(), 1)
    }

def run():
    print("=" * 90)
    print("  MEAN REVERSION STUDY (RSI OVERSOLD DIP-BUYING) ACROSS 4 TIMEFRAMES")
    print("=" * 90)
    
    results = {"1-Hour (2Y)": [], "Daily (5Y)": [], "Weekly (10Y)": [], "Monthly (10Y)": []}
    
    for sym in SYMBOLS:
        tk = yf.Ticker(sym)
        d1h = tk.history(period="2y", interval="1h")
        d5d = tk.history(period="5y", interval="1d")
        d10d = tk.history(period="10y", interval="1d")
        
        if d1h.empty or d10d.empty:
            continue
            
        w10 = resample_bars(d10d, "W-FRI")
        m10 = resample_bars(d10d, "ME")
        
        r_1h = test_mr(d1h, "1-Hour", rsi_period=14, oversold=32, exit_rsi=55)
        r_d = test_mr(d5d, "Daily", rsi_period=14, oversold=35, exit_rsi=55)
        r_w = test_mr(w10, "Weekly", rsi_period=14, oversold=40, exit_rsi=60)
        r_m = test_mr(m10, "Monthly", rsi_period=14, oversold=45, exit_rsi=65)
        
        if r_1h: results["1-Hour (2Y)"].append(r_1h)
        if r_d: results["Daily (5Y)"].append(r_d)
        if r_w: results["Weekly (10Y)"].append(r_w)
        if r_m: results["Monthly (10Y)"].append(r_m)
        
    rows = []
    for tf, arr in results.items():
        df_a = pd.DataFrame(arr)
        rows.append({
            "Timeframe": tf,
            "Total Trades": int(df_a["trades"].sum()),
            "Trades/Stock": round(df_a["trades"].mean(), 1),
            "Win Rate (%)": round(df_a["win_rate"].mean(), 1),
            "Profit Factor": round(df_a["profit_factor"].mean(), 2),
            "Avg Total Return (%)": round(df_a["total_return"].mean(), 1),
            "Avg Max Drawdown (%)": round(df_a["max_dd"].mean(), 1),
            "Avg Holding": f"{df_a['avg_bars'].mean():.1f} bars"
        })
        
    print(pd.DataFrame(rows).to_string(index=False))
    print("=" * 90)

if __name__ == "__main__":
    run()
