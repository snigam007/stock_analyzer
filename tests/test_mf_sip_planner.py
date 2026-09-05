"""
Unit Tests for Mutual Fund Dedicated SIP Planner & Backtester
"""
import sys
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from db.database import get_session, get_global_engine
from core.mf_sip_planner import (
    CURATED_MF_BASKETS,
    plan_mf_sip_allocation,
    run_mf_sip_backtest,
    calculate_mf_sip_accuracy
)


def test_curated_baskets_structure():
    assert len(CURATED_MF_BASKETS) >= 5
    for key, basket in CURATED_MF_BASKETS.items():
        assert "title" in basket
        assert "schemes" in basket
        assert len(basket["schemes"]) >= 3
        total_w = sum(s["weight"] for s in basket["schemes"])
        assert round(total_w, 1) == 100.0


def test_allocation_planning_frequencies():
    engine = get_global_engine()
    session = get_session(engine)

    # 1. Monthly test
    p_m = plan_mf_sip_allocation(budget=15000.0, frequency="MONTHLY", basket_key="BALANCED_ALL_WEATHER", session=session)
    assert p_m["frequency"] == "MONTHLY"
    assert p_m["installment_budget"] == 15000.0
    assert p_m["annual_commitment"] == 180000.0
    alloc_sum_m = sum(a["installment_amount"] for a in p_m["allocations"])
    assert round(alloc_sum_m, 2) == 15000.0

    # 2. Quarterly test
    p_q = plan_mf_sip_allocation(budget=30000.0, frequency="QUARTERLY", basket_key="AGGRESSIVE_ALPHA", session=session)
    assert p_q["frequency"] == "QUARTERLY"
    assert p_q["installment_budget"] == 30000.0
    assert p_q["annual_commitment"] == 120000.0
    alloc_sum_q = sum(a["installment_amount"] for a in p_q["allocations"])
    assert round(alloc_sum_q, 2) == 30000.0

    # 3. Yearly test
    p_y = plan_mf_sip_allocation(budget=120000.0, frequency="YEARLY", basket_key="PASSIVE_INDEX", session=session)
    assert p_y["frequency"] == "YEARLY"
    assert p_y["installment_budget"] == 120000.0
    assert p_y["annual_commitment"] == 120000.0
    alloc_sum_y = sum(a["installment_amount"] for a in p_y["allocations"])
    assert round(alloc_sum_y, 2) == 120000.0

    session.close()


def test_mf_sip_backtest_monthly_and_quarterly():
    engine = get_global_engine()
    session = get_session(engine)

    # Backtest 36 Months Monthly
    res = run_mf_sip_backtest(
        session=session,
        budget=10000.0,
        frequency="MONTHLY",
        basket_key="BALANCED_ALL_WEATHER",
        months_lookback=36,
        annual_step_up_pct=10.0
    )

    assert "error" not in res
    assert res["total_invested"] > 0
    assert res["final_portfolio_value"] > 0
    assert res["strategy_xirr"] != 0.0
    assert len(res["trajectory"]) > 0
    assert len(res["scheme_breakdown"]) >= 3

    # Backtest 36 Months Quarterly
    res_q = run_mf_sip_backtest(
        session=session,
        budget=30000.0,
        frequency="QUARTERLY",
        basket_key="AGGRESSIVE_ALPHA",
        months_lookback=36,
        annual_step_up_pct=0.0
    )
    assert "error" not in res_q
    assert res_q["total_invested"] > 0
    assert res_q["final_portfolio_value"] > 0

    session.close()


def test_mf_sip_accuracy():
    engine = get_global_engine()
    session = get_session(engine)

    acc = calculate_mf_sip_accuracy(session, basket_key="BALANCED_ALL_WEATHER")
    assert "error" not in acc
    assert acc["win_rate_pct"] >= 0.0
    assert "strategy_5y_xirr" in acc
    assert "confidence_grade" in acc

    session.close()


if __name__ == "__main__":
    test_curated_baskets_structure()
    test_allocation_planning_frequencies()
    test_mf_sip_backtest_monthly_and_quarterly()
    test_mf_sip_accuracy()
    print("All MF SIP Planner tests passed successfully!")
