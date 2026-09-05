"""
Test script for Monthly SIP Quantitative Audit & Backtesting Engine.
"""
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from db.database import get_global_engine, get_session
from core.sip_audit_backtester import run_monthly_sip_backtest


def test_backtest_engine():
    engine = get_global_engine()
    session = get_session(engine)

    print("=" * 65)
    print("TEST 1: Structural Trailing Protocol (12-Month SIP)")
    print("=" * 65)

    res = run_monthly_sip_backtest(
        session=session,
        monthly_wallet=20000.0,
        strategy="PURE_STOCKS",
        months_lookback=12,
        exit_protocol="STRUCTURAL_TRAILING"
    )

    print(f"Final Strategy Value: Rs. {res['final_strategy_value']:,.2f}")
    print(f"Strategy XIRR: {res['strategy_xirr']}% | NIFTY XIRR: {res['benchmark_xirr']}% | Alpha: {res['alpha']:+0.2f}%")
    print(f"Profit Factor: {res['profit_factor']} | Max Drawdown: {res['max_drawdown_pct']}%")
    print(f"Capital Preserved: Rs. {res['sell_reminder_audit']['total_capital_preserved_inr']:,.2f}")

    print("\n" + "=" * 65)
    print("TEST 2: Buy & Hold Protocol (12-Month SIP)")
    print("=" * 65)
    res_bh = run_monthly_sip_backtest(
        session=session,
        monthly_wallet=20000.0,
        strategy="PURE_STOCKS",
        months_lookback=12,
        exit_protocol="BUY_AND_HOLD"
    )
    print(f"Final Value: Rs. {res_bh['final_strategy_value']:,.2f} | XIRR: {res_bh['strategy_xirr']}% | PF: {res_bh['profit_factor']}")

    print("\n" + "=" * 65)
    print("TEST 3: Tight Swing Protocol (-7% / +15%) (12-Month SIP)")
    print("=" * 65)
    res_sw = run_monthly_sip_backtest(
        session=session,
        monthly_wallet=20000.0,
        strategy="PURE_STOCKS",
        months_lookback=12,
        exit_protocol="TIGHT_SWING"
    )
    print("\n" + "=" * 65)
    print("TEST 4: 10% Annual Step-Up SIP (24-Month SIP)")
    print("=" * 65)
    res_step = run_monthly_sip_backtest(
        session=session,
        monthly_wallet=20000.0,
        strategy="PURE_STOCKS",
        months_lookback=24,
        exit_protocol="STRUCTURAL_TRAILING",
        annual_step_up_pct=10.0
    )
    print(f"Total Invested: Rs. {res_step['total_invested']:,.2f} (with +10% step-up in Yr 2)")
    print(f"Final Strategy Value: Rs. {res_step['final_strategy_value']:,.2f} | XIRR: {res_step['strategy_xirr']}% | Alpha: {res_step['alpha']:+0.2f}%")
    assert res_step["total_invested"] == (20000.0 * 12) + (22000.0 * 12), "Step-up total invested mismatch!"
    assert res_step["annual_step_up_pct"] == 10.0, "annual_step_up_pct mismatch!"

    print("\n" + "=" * 65)
    print("TEST 5: Multi-Asset Strategy (65% Stocks + 20% Index ETF + 15% Gold ETF)")
    print("=" * 65)
    res_multi = run_monthly_sip_backtest(
        session=session,
        monthly_wallet=20000.0,
        strategy="MULTI_ASSET",
        months_lookback=24,
        exit_protocol="STRUCTURAL_TRAILING"
    )
    print(f"Total Invested: Rs. {res_multi['total_invested']:,.2f}")
    print(f"Final Strategy Value: Rs. {res_multi['final_strategy_value']:,.2f} | XIRR: {res_multi['strategy_xirr']}% | Alpha: {res_multi['alpha']:+0.2f}%")
    print(f"Strategy: {res_multi['strategy']}")

    assert res_multi["months_tested"] == 24, "Multi-asset months tested mismatch"
    assert res_multi["final_strategy_value"] > 0, "Multi-asset final value should be positive"
    assert res_multi["strategy"] == "MULTI_ASSET", "Strategy name mismatch"

    print("\n" + "=" * 65)
    print("TEST 6: Adaptive Structural Trailing Protocol (Tier-Tuned)")
    print("=" * 65)
    res_adapt = run_monthly_sip_backtest(
        session=session,
        monthly_wallet=20000.0,
        strategy="PURE_STOCKS",
        months_lookback=24,
        exit_protocol="ADAPTIVE_STRUCTURAL"
    )
    print(f"Final Strategy Value: Rs. {res_adapt['final_strategy_value']:,.2f} | XIRR: {res_adapt['strategy_xirr']}% | Alpha: {res_adapt['alpha']:+0.2f}%")
    print(f"Profit Factor: {res_adapt['profit_factor']} | Max Drawdown: {res_adapt['max_drawdown_pct']}%")
    assert res_adapt["final_strategy_value"] > 0, "Adaptive final value should be positive"

    print("\n" + "=" * 65)
    print("TEST 7: Tactical Boosters (Pyramiding + Dip-Buying + Parabolic Skimming)")
    print("=" * 65)
    res_boost = run_monthly_sip_backtest(
        session=session,
        monthly_wallet=20000.0,
        strategy="PURE_STOCKS",
        months_lookback=24,
        exit_protocol="ADAPTIVE_STRUCTURAL",
        pyramid_winners=True,
        min_momentum_hurdle_pct=15.0,
        enable_dip_buying=True,
        dip_threshold_pct=4.0,
        enable_parabolic_skim=True,
        skim_milestone_pct=250.0
    )
    print(f"Final Strategy Value: Rs. {res_boost['final_strategy_value']:,.2f} | XIRR: {res_boost['strategy_xirr']}% | Alpha: {res_boost['alpha']:+0.2f}%")
    print(f"Dip Buys: {res_boost.get('dip_buys_count', 0)} | Skims: {res_boost.get('skimmed_trades_count', 0)} | Pyramided: {res_boost.get('pyramided_trades_count', 0)}")
    assert res_boost["enable_dip_buying"] is True, "Dip buying flag should be True"
    assert res_boost["enable_parabolic_skim"] is True, "Parabolic skim flag should be True"
    assert "dip_buys_count" in res_boost, "dip_buys_count missing in result"

    assert res["months_tested"] > 0, "Months tested should be > 0"
    assert res["total_invested"] > 0, "Total invested should be positive"
    assert res["final_strategy_value"] > 0, "Final value should be positive"
    assert res["win_rate"] >= 0 and res["win_rate"] <= 100, "Win rate out of bounds"
    assert res["profit_factor"] >= 0, "Profit factor should be non-negative"
    assert len(res["equity_curve"]) > 0, "Equity curve should not be empty"

    session.close()
    print("\n" + "=" * 65)
    print("ALL 7 BACKTEST TESTS PASSED SUCCESSFULLY!")
    print("=" * 65)


if __name__ == "__main__":
    test_backtest_engine()
