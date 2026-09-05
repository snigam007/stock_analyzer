"""
Unit & Stress Test Suite for Monte Carlo Simulation Engine.
"""
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from db.database import get_global_engine, get_session
from core.monte_carlo_engine import run_monte_carlo_simulation


def test_monte_carlo():
    engine = get_global_engine()
    session = get_session(engine)

    print("=" * 65)
    print("TEST 1: Standard 5-Year Monte Carlo (250 Simulated Paths)")
    print("=" * 65)

    res = run_monte_carlo_simulation(
        session=session,
        monthly_wallet=20000.0,
        horizon_months=60,
        strategy="PURE_STOCKS",
        exit_protocol="ADAPTIVE_STRUCTURAL",
        annual_step_up_pct=10.0,
        n_simulations=250,
        random_seed=42
    )

    print(f"Total Invested: Rs. {res['total_invested']:,.2f}")
    print(f"Median Corpus: Rs. {res['median_corpus']:,.2f} | Median XIRR: {res['median_strategy_xirr']}%")
    print(f"5th Percentile (VaR 95%): Rs. {res['worst_case_corpus_5th']:,.2f}")
    print(f"95th Percentile (Bull Outlier): Rs. {res['best_case_corpus_95th']:,.2f}")
    print(f"Benchmark Median: Rs. {res['benchmark_median_corpus']:,.2f} | Alpha: {res['alpha_median']:+0.2f}%")
    print(f"Probability of Beating NIFTY: {res['prob_beat_benchmark']}%")
    print(f"Median Max Drawdown: {res['median_max_drawdown']}% | Worst 5% DD: {res['worst_case_max_drawdown_95th']}%")

    # Assertions
    assert res["total_invested"] > 0, "Total invested should be > 0"
    assert res["worst_case_corpus_5th"] <= res["median_corpus"], "5th percentile must be <= median"
    assert res["median_corpus"] <= res["best_case_corpus_95th"], "Median must be <= 95th percentile"
    assert 0.0 <= res["prob_beat_benchmark"] <= 100.0, "Prob beat benchmark out of bounds"
    assert len(res["fan_chart_data"]["months"]) == 61, "Fan chart months axis count mismatch"
    assert len(res["fan_chart_data"]["p5"]) == 61, "Fan chart p5 count mismatch"
    assert len(res["drawdown_hist"]["counts"]) > 0, "Drawdown hist should not be empty"

    print("\n" + "=" * 65)
    print("TEST 2: Stress-Test with -25% Market Shock Injection")
    print("=" * 65)

    res_shock = run_monte_carlo_simulation(
        session=session,
        monthly_wallet=20000.0,
        horizon_months=60,
        strategy="MULTI_ASSET",
        exit_protocol="ADAPTIVE_STRUCTURAL",
        n_simulations=200,
        stress_shock_pct=25.0,
        random_seed=42
    )

    print(f"Shock Test Total Invested: Rs. {res_shock['total_invested']:,.2f}")
    print(f"Shock Test Median Corpus: Rs. {res_shock['median_corpus']:,.2f}")
    print(f"Shock Test 5th Percentile: Rs. {res_shock['worst_case_corpus_5th']:,.2f}")
    print(f"Shock Test Worst-Case Drawdown: {res_shock['worst_case_max_drawdown_95th']}%")

    assert res_shock["median_corpus"] > 0, "Shock test median corpus should be positive"
    assert res_shock["stress_shock_pct"] == 25.0, "Shock pct mismatch"

    session.close()
    print("\n" + "=" * 65)
    print("ALL MONTE CARLO ENGINE TESTS PASSED SUCCESSFULLY!")
    print("=" * 65)


if __name__ == "__main__":
    test_monte_carlo()
