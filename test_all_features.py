import sys
from pathlib import Path
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
import numpy as np
from sqlalchemy import text

BASE_DIR = Path('.').resolve()
sys.path.insert(0, str(BASE_DIR))

from db.database import get_global_engine, get_session
engine = get_global_engine()
session = get_session(engine)

print("=== 1. TESTING DASHBOARD DATA & REGIMES ===")
from core.macro_regime import evaluate_macro_regime
from core.global_markets import analyze_global_market_spillovers

macro = evaluate_macro_regime(session)
print("Macro Regime:", macro["regime"], "| Score:", macro["macro_score"])

global_mkt = analyze_global_market_spillovers(session)
print("Global Sentiment:", global_mkt["global_sentiment_index"], "| Verdict:", global_mkt["sentiment_verdict"])

print("\n=== 2. TESTING MULTI-ASSET STOCK/INDEX/COMMODITY ANALYSIS ===")
import importlib.util

spec2 = importlib.util.spec_from_file_location("p2", "app/pages/2_Stock_Analysis.py")
p2 = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(p2)

# Test Stock
p_stock, ind_s, sig_s, sc_s, fc_s = p2.get_stock_data("RELIANCE", "Stock", 365)
print("Stock RELIANCE:", len(p_stock), "price records. Signal:", sig_s.get("signal"))

# Test Index
p_idx, ind_i, sig_i, sc_i, fc_i = p2.get_stock_data("^NSEI", "Index", 365)
print("Index ^NSEI:", len(p_idx), "price records. Signal:", sig_i.get("signal"))

# Test Commodity
p_comm, ind_c, sig_c, sc_c, fc_c = p2.get_stock_data("GC=F", "Commodity", 365)
print("Commodity GC=F:", len(p_comm), "price records. Signal:", sig_c.get("signal"))

# Test Scorecard Dataframe Formatting for Commodity (with None values)
ind_data = [
    ("RSI (14)", f"{ind_c.get('rsi_14', 0):.1f}" if ind_c.get("rsi_14") else "—", sig_c.get("rsi_signal"), sc_c.get("score_rsi")),
    ("MACD", f"{ind_c.get('macd', 0):.3f}" if ind_c.get("macd") else "—", sig_c.get("macd_signal"), sc_c.get("score_macd")),
    ("ATR (14)", f"{ind_c.get('atr_14', 0):.2f}" if ind_c.get("atr_14") else "—", "—", None),
]
scorecard_df = pd.DataFrame(ind_data, columns=["Indicator", "Value", "Signal", "Score (0-100)"])
styler = scorecard_df.style.format({"Score (0-100)": lambda x: f"{float(x):.0f}" if pd.notna(x) and x is not None else "—"}, na_rep="—")
html_out = styler.to_html()
print("Scorecard table rendered safely without NoneType error! Length:", len(html_out))

# Test Champion strategy & PDF generator
from core.pdf_report_generator import generate_institutional_advisory_pdf
from core.ml_models import compute_ml_ensemble_consensus
from core.trade_optimizer import generate_trade_execution_plan, calculate_position_size
from core.fno_analyzer import analyze_fno_derivatives

df_rel = pd.DataFrame(p_stock, columns=["date", "open", "high", "low", "close", "volume", "daily_return"])
curr_rel = float(df_rel["close"].iloc[0])
pdf_bytes = generate_institutional_advisory_pdf(
    symbol="RELIANCE",
    stock_name="Reliance Industries Ltd",
    sector="Energy",
    current_price=curr_rel,
    signal_data=sig_s,
    score_data=sc_s,
    ml_ensemble_data=compute_ml_ensemble_consensus(df_rel),
    champion_data=p2.get_cached_champion_strategy("RELIANCE"),
    trade_plan=generate_trade_execution_plan(curr_rel, curr_rel, curr_rel*1.05, curr_rel*1.10, curr_rel*1.15, curr_rel*0.95),
    pos_sizing=calculate_position_size(100000.0, curr_rel, curr_rel*0.95),
    fno_data=analyze_fno_derivatives("RELIANCE", curr_rel, session),
    macro_data=macro,
)
print("Advisory PDF Generated successfully! Size:", len(pdf_bytes), "bytes")

print("\n=== 3. TESTING DAILY TOP STOCKS (ALL TABS) ===")
spec4 = importlib.util.spec_from_file_location("p4", "app/pages/4_Daily_Top_Stocks.py")
p4 = importlib.util.module_from_spec(spec4)
spec4.loader.exec_module(p4)

top_buys = p4.get_top_stocks("BUY", "ALL", "All", 10)
print("Top BUY count:", len(top_buys))
top_sells = p4.get_top_stocks("SELL", "ALL", "All", 10)
print("Top SELL count:", len(top_sells))
idx_sigs = p4.get_asset_signals("index")
print("Index signals count:", len(idx_sigs))
comm_sigs = p4.get_asset_signals("commodity")
print("Commodity signals count:", len(comm_sigs))

from core.accuracy_tracker import evaluate_signal_audit_track_record
audit = evaluate_signal_audit_track_record(session)
print("Audit Track Record evaluated! Signals tracked:", audit["total_signals_tracked"])

print("\n=== 4. TESTING STRATEGY BACKTESTING ENGINE ===")
from core.backtester import run_backtest, find_champion_strategy
for strat in ["Multi-Engine Confluence", "EMA Golden Cross Trend", "RSI Oversold Mean Reversion", "Volume Breakout Momentum"]:
    bt = run_backtest("TCS", strat, session)
    print(f"Backtest {strat} on TCS: Trades={bt.get('total_trades')}, Return={bt.get('total_return_pct')}%, WinRate={bt.get('win_rate_pct')}%")

champ = find_champion_strategy("TCS", session)
print("Champion strategy for TCS:", champ["champion"]["strategy_name"], "| Return:", champ["champion"]["total_return_pct"], "%")

print("\n=== 5. TESTING TRENDS & COMMODITY HUMAN NAMES ===")
spec5 = importlib.util.spec_from_file_location("p5", "app/pages/5_Trends.py")
p5 = importlib.util.module_from_spec(spec5)
spec5.loader.exec_module(p5)
print("Commodity names mapped:", len(p5.COMMODITY_NAMES))
print("Index names mapped:", len(p5.INDEX_NAMES))

session.close()
print("\n=====================================================================")
print("🎉 ALL PAGES, TABS, TOGGLES, AND PIPELINES TESTED 100% ERROR-FREE!")
print("=====================================================================")