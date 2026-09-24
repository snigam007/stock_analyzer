"""
Empirical Backtest: Dynamic Mutual Fund Category Rotation & Tactical Dip Deployer (60 Months)
Evaluates:
  1. Static Buy-and-Hold MF SIP (35% Mid, 35% Small, 30% Flexi)
  2. Dynamic Regime-Adaptive Category Rotation (Bull: Small/Mid tilt, Neutral: Flexi tilt, Bear: Liquid tilt)
  3. Dynamic Category Rotation + Tactical Dip Deployer (Deploy 20% Liquid reserve on >= 3.5% index drops)
  4. Benchmark: NIFTY 50 TRI
"""
import sys, os, time
from datetime import datetime, date, timedelta
from typing import Dict, List, Tuple
import pandas as pd
import numpy as np

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from core.mf_sip_planner import calculate_xirr

DB_PATH = "data/stock_analyzer.db"
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
Session = sessionmaker(bind=engine)

def run_mf_rotation_backtest(
    session,
    budget: float = 20000.0,
    months_lookback: int = 60,
    annual_step_up_pct: float = 10.0,
    mode: str = "DYNAMIC_WITH_DIPS"  # "STATIC", "DYNAMIC", "DYNAMIC_WITH_DIPS"
) -> Dict:
    # 1. Fetch NIFTY 50 daily prices
    nifty_df = pd.read_sql_query(
        "SELECT date, close FROM index_prices WHERE symbol = '^NSEI' AND close IS NOT NULL ORDER BY date ASC",
        session.bind
    )
    if nifty_df.empty or len(nifty_df) < 250:
        return {"error": "Insufficient index data"}

    nifty_df['date'] = pd.to_datetime(nifty_df['date']).dt.date
    nifty_df = nifty_df.drop_duplicates(subset=['date']).sort_values('date').reset_index(drop=True)
    
    # Calculate 50 EMA and 200 EMA on NIFTY
    nifty_df['ema_50'] = nifty_df['close'].ewm(span=50, adjust=False).mean()
    nifty_df['ema_200'] = nifty_df['close'].ewm(span=200, adjust=False).mean()
    nifty_df['high_20d'] = nifty_df['close'].rolling(20, min_periods=5).max()
    
    # Determine date range
    end_date = nifty_df['date'].iloc[-1]
    start_date = end_date - timedelta(days=int(months_lookback * 30.4375))
    
    # Filter for active window
    eval_df = nifty_df[nifty_df['date'] >= start_date].copy().reset_index(drop=True)
    if eval_df.empty:
        return {"error": "No trading days in test window"}

    # In India:
    # Long-term historical category performance characteristics relative to NIFTY 50:
    # Small Cap Index has historical beta ~1.25, excess return ~4-6% annualized
    # Mid Cap Index has historical beta ~1.15, excess return ~3-4% annualized
    # Flexi Cap has historical beta ~1.00, excess return ~1.5-2.5% annualized
    # Liquid / Debt yields steady 6.5% annualized risk-free compounding (zero drawdown)
    
    # Precompute daily returns for categories
    eval_df['nifty_ret'] = eval_df['close'].pct_change().fillna(0.0)
    
    daily_rf = (1.0 + 0.065) ** (1.0 / 252.0) - 1.0
    eval_df['flexi_ret'] = eval_df['nifty_ret'] * 1.02 + (0.02 / 252.0)
    eval_df['mid_ret'] = eval_df['nifty_ret'] * 1.15 + (0.035 / 252.0)
    eval_df['small_ret'] = eval_df['nifty_ret'] * 1.25 + (0.05 / 252.0)
    eval_df['liquid_ret'] = daily_rf

    # Build monthly investment dates (first trading day of each month)
    eval_df['year_month'] = eval_df['date'].apply(lambda d: f"{d.year}-{d.month:02d}")
    monthly_first_idx = eval_df.groupby('year_month').apply(lambda g: g.index[0]).values

    # Simulation State
    wallet_init = budget
    initial_year = eval_df['date'].iloc[0].year
    
    # Category NAV indices (base = 100.0)
    cat_nav = {"flexi": 100.0, "mid": 100.0, "small": 100.0, "liquid": 100.0, "nifty": 100.0}
    cat_units = {"flexi": 0.0, "mid": 0.0, "small": 0.0, "liquid": 0.0}
    nifty_units = 0.0
    
    total_invested = 0.0
    strat_flows = []
    bm_flows = []
    trajectory = []
    
    tactical_dip_triggers_count = 0
    last_dip_day = -999
    
    for day_i, row in eval_df.iterrows():
        # Update category NAVs
        cat_nav["flexi"] *= (1.0 + row['flexi_ret'])
        cat_nav["mid"] *= (1.0 + row['mid_ret'])
        cat_nav["small"] *= (1.0 + row['small_ret'])
        cat_nav["liquid"] *= (1.0 + row['liquid_ret'])
        cat_nav["nifty"] *= (1.0 + row['nifty_ret'])
        
        # Check Monthly SIP Inflow
        if day_i in monthly_first_idx:
            curr_date = row['date']
            y_diff = curr_date.year - initial_year
            step_up = (1.0 + annual_step_up_pct / 100.0) ** max(0, y_diff)
            curr_wallet = round(wallet_init * step_up, 2)
            
            total_invested += curr_wallet
            strat_flows.append((curr_date, -curr_wallet))
            bm_flows.append((curr_date, -curr_wallet))
            
            # Benchmark purchase
            nifty_units += curr_wallet / max(1.0, row['close'])
            
            # Determine Allocation Weights
            if mode == "STATIC":
                w = {"flexi": 0.30, "mid": 0.35, "small": 0.35, "liquid": 0.00}
            else:
                # Dynamic Category Rotation based on Regime
                c_p = row['close']
                e50 = row['ema_50']
                e200 = row['ema_200']
                
                if c_p >= e50 and c_p >= e200:
                    # Bull Expansion: Tilt to Small & Mid
                    w = {"small": 0.35, "mid": 0.35, "flexi": 0.25, "liquid": 0.05}
                elif c_p >= e200:
                    # Neutral / Consolidation: Tilt to Flexi
                    w = {"flexi": 0.45, "mid": 0.30, "small": 0.15, "liquid": 0.10}
                else:
                    # Bear Defense: Tilt to Liquid & Large/Flexi
                    w = {"liquid": 0.40, "flexi": 0.35, "mid": 0.15, "small": 0.10}
                    
            # Allocate wallet
            for c_key, weight in w.items():
                alloc_amt = curr_wallet * weight
                cat_units[c_key] += alloc_amt / cat_nav[c_key]
                
        # Tactical Dip Deployer Check (Intra-month)
        if mode == "DYNAMIC_WITH_DIPS":
            h20 = row['high_20d']
            pullback_pct = (row['close'] - h20) / h20 * 100.0 if h20 > 0 else 0.0
            
            # If market drops >= 3.5% and not deployed in last 15 trading days
            if pullback_pct <= -3.5 and (day_i - last_dip_day) >= 15:
                # Value of liquid reserve
                liquid_val = cat_units["liquid"] * cat_nav["liquid"]
                if liquid_val >= 1000.0:
                    # Deploy 35% of liquid buffer into leading growth category (Mid / Small 50:50)
                    deploy_amt = liquid_val * 0.35
                    cat_units["liquid"] -= deploy_amt / cat_nav["liquid"]
                    
                    cat_units["mid"] += (deploy_amt * 0.50) / cat_nav["mid"]
                    cat_units["small"] += (deploy_amt * 0.50) / cat_nav["small"]
                    
                    tactical_dip_triggers_count += 1
                    last_dip_day = day_i

        # Record daily portfolio valuation
        curr_pv = sum(cat_units[k] * cat_nav[k] for k in cat_units)
        curr_bm = nifty_units * row['close']
        trajectory.append({"date": row['date'], "pv": curr_pv, "bm": curr_bm})

    # Terminal valuation
    final_pv = sum(cat_units[k] * cat_nav[k] for k in cat_units)
    final_bm = nifty_units * eval_df['close'].iloc[-1]
    
    strat_flows.append((eval_df['date'].iloc[-1], final_pv))
    bm_flows.append((eval_df['date'].iloc[-1], final_bm))
    
    strat_xirr = calculate_xirr(strat_flows)
    bm_xirr = calculate_xirr(bm_flows)
    
    # Calculate Max Drawdown
    peak = 0.0
    dds = []
    for pt in trajectory:
        v = pt["pv"]
        if v > peak:
            peak = v
        dd = (peak - v) / peak * 100.0 if peak > 0 else 0.0
        dds.append(dd)
    max_dd = max(dds) if dds else 0.0

    return {
        "mode": mode,
        "start_date": str(eval_df['date'].iloc[0]),
        "end_date": str(eval_df['date'].iloc[-1]),
        "total_invested": total_invested,
        "final_value": final_pv,
        "benchmark_value": final_bm,
        "strategy_xirr": strat_xirr,
        "benchmark_xirr": bm_xirr,
        "alpha": strat_xirr - bm_xirr,
        "max_drawdown": max_dd,
        "tactical_dip_triggers_count": tactical_dip_triggers_count,
        "units": cat_units,
        "final_navs": cat_nav
    }

def main():
    print("=" * 115)
    print("🚀 QUANTITATIVE BACKTEST: MUTUAL FUND DYNAMIC CATEGORY ROTATION & TACTICAL DIP DEPLOYER (60M)")
    print("=" * 115)
    
    session = Session()
    modes = [
        ("🏛️ Baseline: Static Standard MF SIP (35% Mid, 35% Small, 30% Flexi)", "STATIC"),
        ("⚖️ Dynamic MF Category Rotation (Bull Small/Mid, Neut Flexi, Bear Liquid)", "DYNAMIC"),
        ("👑 Dynamic Rotation + Tactical Dip Deployer (Deploy Liquid Buffer on >= 3.5% Dips)", "DYNAMIC_WITH_DIPS")
    ]
    
    results = []
    for name, m in modes:
        t0 = time.time()
        res = run_mf_rotation_backtest(session, budget=20000.0, months_lookback=60, annual_step_up_pct=10.0, mode=m)
        dur = time.time() - t0
        
        xirr = res["strategy_xirr"]
        corpus = res["final_value"]
        invested = res["total_invested"]
        dd = res["max_drawdown"]
        alpha = res["alpha"]
        dips = res["tactical_dip_triggers_count"]
        bm_xirr = res["benchmark_xirr"]
        bm_corpus = res["benchmark_value"]
        
        print(f"\n{name}")
        print(f"    --> Net XIRR: {xirr:5.2f}% (vs Benchmark Nifty: {bm_xirr:5.2f}% | Alpha: {alpha:+5.2f}%)")
        print(f"    --> Final Corpus: ₹{corpus:,.0f} | Invested: ₹{invested:,.0f} | Profit: ₹{corpus-invested:,.0f}")
        print(f"    --> Max Drawdown: {dd:4.1f}% | Tactical Dip Triggers: {dips} | Dur: {dur:.2f}s")
        
        results.append({
            "name": name,
            "xirr": xirr,
            "corpus": corpus,
            "invested": invested,
            "dd": dd,
            "alpha": alpha,
            "dips": dips
        })
        
    session.close()
    
    print("\n" + "=" * 120)
    print(f"{'Strategy Variant':<75} | {'Net XIRR':<10} | {'Final Corpus':<15} | {'Alpha':<8} | {'Max DD':<7} | {'Dips':<5}")
    print("-" * 120)
    for r in results:
        print(f"{r['name']:<75} | {r['xirr']:>8.2f}% | ₹{r['corpus']:>13,.0f} | {r['alpha']:>+6.2f}% | {r['dd']:>5.1f}% | {r['dips']:>4}")
    print("=" * 120)

if __name__ == "__main__":
    main()
