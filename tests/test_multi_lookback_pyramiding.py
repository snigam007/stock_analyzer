"""
tests/test_multi_lookback_pyramiding.py

Unit and Integration Tests for:
1. Multi-Lookback Persistence Champion Evaluation (core/signals.py)
2. Jesse Livermore Winner Pyramiding & 3-Tier Scaling Execution (core/trade_execution.py)
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.signals import evaluate_multi_lookback_persistence
from core.trade_execution import simulate_bracket_trade_execution


def test_multi_lookback_persistence_hyper_qualified():
    """Verify that an explosive momentum stock qualifies for HYPER champion status (SW_0155)."""
    np.random.seed(42)
    dates = pd.date_range("2025-09-01", periods=260, freq="B")
    # Exponential hyper-trend (+7% 1M, +23% 3M, +55% 6M, +140% 12M)
    trend = 100.0 * (1.0035 ** np.arange(260))
    closes = trend

    df = pd.DataFrame({
        "close": closes,
        "high": closes * 1.01,
        "low": closes * 0.99,
        "open": closes * 0.995,
    }, index=dates)

    res = evaluate_multi_lookback_persistence(
        price_df=df,
        current_price=closes[-1],
        ema_50=float(closes[-30]),
        ema_200=float(closes[-120])
    )

    assert res["qualifies"] is True, f"Expected qualifies=True, got {res['qualifies']}"
    assert res["tier"] == "HYPER", f"Expected tier=HYPER, got {res['tier']}"
    assert res["score_boost"] == 5.0, f"Expected boost=5.0, got {res['score_boost']}"
    assert "Hyper-Lookback Momentum Champion" in res["badge"]
    assert res["mom_12m"] >= 50.0, f"Expected 12M mom >= 50%, got {res['mom_12m']}%"
    print("PASS: test_multi_lookback_persistence_hyper_qualified")


def test_multi_lookback_persistence_standard_qualified():
    """Verify that a steady momentum stock qualifies for STANDARD champion status."""
    dates = pd.date_range("2025-09-01", periods=260, freq="B")
    # Steady trend (+2.5% 1M, +11.4% 3M, +25.5% 6M, +45% 12M) -> satisfies standard (3M>=10, 6M>=25, 12M>=35) but not hyper (3M < 15%)
    trend = 100.0 * (1.0018 ** np.arange(260))
    closes = trend

    df = pd.DataFrame({"close": closes}, index=dates)

    res = evaluate_multi_lookback_persistence(
        price_df=df,
        current_price=closes[-1],
        ema_50=float(closes[-25]),
        ema_200=float(closes[-100])
    )

    assert res["qualifies"] is True
    assert res["tier"] == "STANDARD"
    assert res["score_boost"] == 3.5
    assert "Multi-Lookback Persistence Champion" in res["badge"]
    print("PASS: test_multi_lookback_persistence_standard_qualified")


def test_multi_lookback_persistence_rejected_on_lagging():
    """Verify that lagging or counter-trend stocks are rejected from champion status."""
    dates = pd.date_range("2025-09-01", periods=260, freq="B")
    # Downtrending / choppy
    closes = np.linspace(200.0, 140.0, 260)
    df = pd.DataFrame({"close": closes}, index=dates)

    res = evaluate_multi_lookback_persistence(
        price_df=df,
        current_price=closes[-1],
        ema_50=150.0,
        ema_200=170.0
    )

    assert res["qualifies"] is False
    assert res["score_boost"] == 0.0
    assert res["badge"] == ""
    print("PASS: test_multi_lookback_persistence_rejected_on_lagging")


def test_winner_pyramiding_and_3tier_scaling():
    """Verify that 3-tier bracket scaling and Jesse Livermore pyramiding function correctly."""
    # Trade starts at 100, rises to 105 (T1 hit + pyramiding triggered), 110 (T2 hit), and 118 (T3 hit)
    candles = [
        ("2026-07-01", 102.0, 99.0, 101.0),
        ("2026-07-02", 104.5, 100.5, 104.2), # Reaches +4.2% -> triggers pyramiding (+50% size)
        ("2026-07-03", 106.0, 103.0, 105.5), # Hits T1 (105.0) -> fills 33%
        ("2026-07-06", 111.0, 105.0, 110.5), # Hits T2 (110.0) -> fills 33%
        ("2026-07-07", 119.0, 110.0, 118.0), # Hits T3 (118.0) -> fills runner
    ]

    res = simulate_bracket_trade_execution(
        entry_price=100.0,
        target_1=105.0,
        target_2=110.0,
        target_3=118.0,
        initial_stop_loss=95.0,
        forward_candles=candles,
        position_size_qty=90,
        scaling_tiers=3,
        enable_pyramiding=True,
    )

    assert res["t1_captured"] is True
    assert res["t2_captured"] is True
    assert res["t3_captured"] is True
    assert res["pyramided"] is True
    assert res["exit_reason"] == "FULL_TARGET_3_CAPTURED"
    assert res["realized_return_pct"] > 0
    print("PASS: test_winner_pyramiding_and_3tier_scaling")


def test_inactivity_time_stop():
    """Verify that stagnant trades are cut after time_stop_days if gain < 1.5%."""
    # Flat candles around 100.0 for 8 days
    candles = [
        (f"2026-07-0{i}", 100.8, 99.5, 100.2) for i in range(1, 9)
    ]

    res = simulate_bracket_trade_execution(
        entry_price=100.0,
        target_1=106.0,
        target_2=112.0,
        target_3=120.0,
        initial_stop_loss=95.0,
        forward_candles=candles,
        position_size_qty=100,
        time_stop_days=6,
        enable_pyramiding=True
    )

    assert res["exit_reason"] == "TIME_STOP_INACTIVITY"
    assert any(log["stage"] == "TIME_STOP_INACTIVITY" for log in res["trade_logs"])
    print("PASS: test_inactivity_time_stop")


if __name__ == "__main__":
    print("=" * 60)
    print("🧪 RUNNING VALIDATION: MULTI-LOOKBACK & PYRAMIDING")
    print("=" * 60)
    test_multi_lookback_persistence_hyper_qualified()
    test_multi_lookback_persistence_standard_qualified()
    test_multi_lookback_persistence_rejected_on_lagging()
    test_winner_pyramiding_and_3tier_scaling()
    test_inactivity_time_stop()
    print("=" * 60)
    print("🎉 ALL TESTS PASSED SUCCESSFULLY!")
    print("=" * 60)
