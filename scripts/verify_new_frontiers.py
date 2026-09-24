"""
scripts/verify_new_frontiers.py
Comprehensive End-to-End Verification Suite for the 5 Quantitative Frontiers:
1. Guardrail 7: Anti-Gap Exhaustion / "Gap & Trap" Pullback Gate (core/signals.py)
2. Volume Profile Point of Control (POC) Support Anchoring (core/signals.py)
3. Cross-Asset Correlation Clustering (r < 0.65 Orthogonal Shield) (core/correlation_clustering.py & monthly_sip_advisor.py)
4. Real-World Friction & Government Tax Reality Drag Simulator (core/sip_audit_backtester.py)
5. UI Dashboard Parity & Compile Integrity (pages/ & app/pages/)
"""

import sys
from pathlib import Path

import sys
from pathlib import Path

# Fix Windows stdout cp1252 encoding
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# Setup Path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import py_compile
import pandas as pd
import numpy as np
from datetime import date
from db.database import get_global_engine, get_session
from core.signals import calculate_targets, generate_signal_for_stock
from core.correlation_clustering import (
    compute_pairwise_correlation_matrix,
    filter_orthogonal_candidates,
    get_pairwise_correlations_summary
)
from core.monthly_sip_advisor import generate_monthly_sip_basket
from core.sip_audit_backtester import run_monthly_sip_backtest

def log(title: str, passed: bool, detail: str = ""):
    icon = "[PASS]" if passed else "[FAIL]"
    print(f"{icon} [{title}] {detail}")
    if not passed:
        raise AssertionError(f"Test failed: {title} - {detail}")


def test_frontier_1_and_2_signals():
    print("\n" + "="*70)
    print("TEST 1 & 2: Guardrail 7 Anti-Gap Exhaustion & Volume POC Anchoring")
    print("="*70)

    # 1. Test POC stop-loss anchoring
    targets_no_poc = calculate_targets(
        current_price=1000.0, atr=30.0, signal="BUY", trend_strength=60.0,
        poc_price=None, swing_low=950.0
    )
    targets_with_poc = calculate_targets(
        current_price=1000.0, atr=30.0, signal="BUY", trend_strength=60.0,
        poc_price=940.0, swing_low=950.0
    )
    # With raw_sl at 940 and POC at 940, floor is 940 * 0.992 = 932.48
    expected_poc_floor = round(940.0 * 0.992, 2)
    log("Volume POC SL Anchoring", targets_with_poc["stop_loss"] == expected_poc_floor,
        f"SL with POC ({targets_with_poc['stop_loss']}) safely anchored below POC floor ({expected_poc_floor})")

    # 2. Test gap_limit_price in calculate_targets
    targets_gap = calculate_targets(
        current_price=1050.0, atr=25.0, signal="BUY", trend_strength=70.0,
        gap_limit_price=1025.0
    )
    log("Tactical Gap Limit Price Override", targets_gap["buy_price"] == 1025.0,
        f"buy_price correctly overridden to gap_limit_price (1025.0 == {targets_gap['buy_price']})")

    # 3. Test Guardrail 7 live via database stock
    engine = get_global_engine()
    session = get_session(engine)
    try:
        from db.database import Stock
        stock = session.query(Stock).first()
        assert stock is not None, "At least 1 stock must exist in DB"

        # Mock price_df with +3.5% opening gap on latest bar
        dates = pd.date_range("2024-01-01", periods=60)
        df_gap = pd.DataFrame({
            "date": dates,
            "open": [100.0]*59 + [103.5],   # 3.5% gap up from prev close
            "high": [101.0]*59 + [104.0],
            "low":  [99.0]*59  + [101.5],
            "close": [100.0]*59 + [103.0],  # prev close was 100.0
            "volume": [100000]*60
        })

        mock_ind = {
            "rsi_14": 58.0, "macd_hist": 1.2, "ema_9": 101.5, "ema_21": 100.5,
            "ema_50": 98.0, "ema_200": 92.0, "close": 103.0, "atr_14": 2.5,
            "trend_strength": 65.0, "adx": 26.0, "stoch_k": 60.0, "stoch_d": 55.0,
            "cci_20": 40.0, "obv": 50000.0, "obv_sma": 45000.0, "volume_ratio": 1.4,
            "volume_spike": False
        }
        sig = generate_signal_for_stock(
            stock=stock,
            ind=mock_ind,
            composite_score=68.0,
            price_df=df_gap
        )
        log("Guardrail 7 Triggered", sig["gap_exhaustion_alert"] is True,
            f"Gap exhaustion alert triggered: {sig.get('gap_exhaustion_alert')}")
        log("Guardrail 7 Retest Limit Set", sig["gap_retest_limit_price"] is not None,
            f"Retest limit price computed: {sig.get('gap_retest_limit_price')}")
        
        # Expected retest limit is 0.50 * (open + prev_close) = 0.50 * (103.5 + 100.0) = 101.75
        expected_retest = round(0.50 * (103.5 + 100.0), 2)
        log("Guardrail 7 50% Gap Calculation", abs(sig["gap_retest_limit_price"] - expected_retest) < 0.05,
            f"Retest limit price ({sig['gap_retest_limit_price']}) matches 50% gap level ({expected_retest})")
        log("POC Price Returned", "poc_price" in sig, f"POC price present in signal dict: {sig.get('poc_price')}")

    finally:
        session.close()


def test_frontier_3_correlation_clustering():
    print("\n" + "="*70)
    print("TEST 3: Cross-Asset Correlation Clustering (r < 0.65 Orthogonal Shield)")
    print("="*70)

    engine = get_global_engine()
    session = get_session(engine)
    try:
        # 1. Test correlation matrix computation on known equities
        syms = ["TCS.NS", "INFY.NS", "HDFCBANK.NS", "RELIANCE.NS"]
        corr = compute_pairwise_correlation_matrix(syms, session, lookback_days=120)
        log("Correlation Matrix Generated", not corr.empty and len(corr) >= 2,
            f"Computed matrix with shape {corr.shape}")

        # 2. Test orthogonal filtering
        # TCS and INFY have high positive correlation (typically ~0.75 - 0.85)
        candidates = [
            {"symbol": "TCS.NS", "composite_score": 90.0, "sector": "Technology"},
            {"symbol": "INFY.NS", "composite_score": 85.0, "sector": "Technology"},
            {"symbol": "HDFCBANK.NS", "composite_score": 80.0, "sector": "Financial Services"},
        ]
        filtered, rejected = filter_orthogonal_candidates(
            candidates=candidates, corr_matrix=corr, max_corr=0.65, max_picks=5,
            get_symbol_fn=lambda c: c["symbol"]
        )
        filtered_syms = [c["symbol"] for c in filtered]
        log("Orthogonal Filtering Executed", len(filtered) >= 1,
            f"Filtered candidates: {filtered_syms}, Rejected: {[r['symbol'] for r in rejected]}")
        if "TCS.NS" in corr.index and "INFY.NS" in corr.index:
            tcs_infy_corr = corr.loc["TCS.NS", "INFY.NS"]
            if tcs_infy_corr >= 0.65:
                # One of them must have been excluded
                has_both = ("TCS.NS" in filtered_syms) and ("INFY.NS" in filtered_syms)
                log("High-Correlation Pair Blocked", not has_both,
                    f"TCS vs INFY corr = {tcs_infy_corr:.3f} >= 0.65 -> prevented co-selection!")

        # 3. Test pairwise correlation summary
        summary = get_pairwise_correlations_summary(filtered_syms, corr)
        log("Correlation Summary Dict", "avg_pairwise_corr" in summary and "is_well_diversified" in summary,
            f"Avg Corr: {summary.get('avg_pairwise_corr')}, Max Corr: {summary.get('max_pairwise_corr')}, Well-Diversified: {summary.get('is_well_diversified')}")

        # 4. Test integration into generate_monthly_sip_basket
        basket = generate_monthly_sip_basket(
            session=session,
            monthly_wallet=20000,
            strategy="PURE_STOCKS",
            enable_correlation_clustering=True,
            max_pairwise_correlation=0.65
        )
        log("Monthly SIP Basket Correlation Summary", "correlation_summary" in basket,
            f"Basket summary: {basket.get('correlation_summary')}")
        if basket.get("correlation_summary"):
            log("Basket Well Diversified", basket["correlation_summary"].get("is_well_diversified") is True,
                f"Basket Avg Pairwise Corr: {basket['correlation_summary'].get('avg_pairwise_corr')}")

    finally:
        session.close()


def test_frontier_4_friction_and_tax():
    print("\n" + "="*70)
    print("TEST 4: Real-World Friction & Government Tax Reality Drag Simulator")
    print("="*70)

    engine = get_global_engine()
    session = get_session(engine)
    try:
        # Run 12-month SIP backtest with friction & tax enabled
        res = run_monthly_sip_backtest(
            session=session,
            monthly_wallet=25000,
            strategy="PURE_STOCKS",
            months_lookback=12,
            exit_protocol="ADAPTIVE_STRUCTURAL",
            enable_correlation_clustering=True,
            enable_friction_and_tax=True,
            stt_rate=0.0010,
            charges_rate=0.0003,
            slippage_rate=0.0015,
            stcg_tax_rate=0.20,
            ltcg_tax_rate=0.125
        )

        log("Backtest Executed Successfully", "error" not in res,
            f"Months Tested: {res.get('months_tested')}, Final Value: ₹{res.get('final_strategy_value', 0):,.2f}")

        # Verify friction and tax audit structure
        audit = res.get("friction_and_tax_audit")
        log("Friction & Tax Audit Returned", audit is not None, f"Audit keys: {list(audit.keys()) if audit else 'None'}")

        if audit:
            log("Transaction Friction Tracked", audit["total_friction_inr"] > 0,
                f"Total Friction: ₹{audit['total_friction_inr']:,.2f} (STT: ₹{audit['stt_paid_inr']:,.2f}, Slippage: ₹{audit['slippage_drag_inr']:,.2f}, SEBI/Charges: ₹{audit['exchange_sebi_charges_inr']:,.2f})")
            log("Net In-Pocket Value <= Gross Final Value", audit["net_in_pocket_value"] <= res["final_strategy_value"],
                f"Gross: ₹{res['final_strategy_value']:,.2f} -> Net In-Pocket: ₹{audit['net_in_pocket_value']:,.2f}")
            log("Net In-Pocket XIRR Calculated", audit["net_in_pocket_xirr"] is not None,
                f"Gross XIRR: {res['strategy_xirr']:+.1f}% -> Net In-Pocket XIRR: {audit['net_in_pocket_xirr']:+.1f}%")
            log("Annual Friction Drag % Tracked", audit["annual_friction_drag_pct"] >= 0,
                f"Friction Drag: {audit['annual_friction_drag_pct']:.2f}% / year")

    finally:
        session.close()


def test_frontier_5_ui_parity_and_compilation():
    print("\n" + "="*70)
    print("TEST 5: UI Parity & Compilation Verification")
    print("="*70)

    pages = [
        ("pages/4_Daily_Top_Stocks.py", "app/pages/4_Daily_Top_Stocks.py"),
        ("pages/16_Monthly_SIP_and_Sell_Radar.py", "app/pages/16_Monthly_SIP_and_Sell_Radar.py")
    ]

    for p1, p2 in pages:
        # Check existence
        path1 = BASE_DIR / p1
        path2 = BASE_DIR / p2
        log(f"File Exists: {p1}", path1.exists(), str(path1))
        log(f"File Exists: {p2}", path2.exists(), str(path2))

        # Check Byte-for-byte parity
        with open(path1, "rb") as f1, open(path2, "rb") as f2:
            identical = (f1.read() == f2.read())
        log(f"Byte Parity: {p1} == {p2}", identical, "100% byte-for-byte identical")

        # Compile check
        py_compile.compile(str(path1), doraise=True)
        py_compile.compile(str(path2), doraise=True)
        log(f"PyCompile: {p1}", True, "Syntax valid, byte-compiled with zero errors")


def main():
    print("\n" + "#"*70)
    print("  LAUNCHING 5 QUANTITATIVE FRONTIERS END-TO-END VERIFICATION SUITE")
    print("#"*70)

    test_frontier_1_and_2_signals()
    test_frontier_3_correlation_clustering()
    test_frontier_4_friction_and_tax()
    test_frontier_5_ui_parity_and_compilation()

    print("\n" + "#"*70)
    print("  🎉 ALL 5 QUANTITATIVE FRONTIERS VERIFIED WITH ZERO ERRORS!")
    print("#"*70 + "\n")


if __name__ == "__main__":
    main()
