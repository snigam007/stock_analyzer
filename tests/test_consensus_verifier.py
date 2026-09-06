"""
Unit Tests for External Consensus Verifier & Dual-Confirmation Engine
"""
import sys
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from db.database import get_session, get_global_engine
from core.consensus_verifier import (
    fetch_stock_consensus,
    evaluate_stock_alignment,
    fetch_mf_consensus,
    evaluate_mf_alignment,
    compute_portfolio_consensus_summary
)


def test_evaluate_stock_alignment_quadrants():
    # 1. Dual confirmed
    res_dual = evaluate_stock_alignment("STRONG_BUY", "strong_buy", target_upside_pct=22.5, number_of_analysts=35)
    assert res_dual["status"] == "DUAL_CONFIRMED"
    assert "Dual-Confirmed" in res_dual["badge"]
    assert res_dual["is_dual_confirmed"] is True

    # 2. Model leading
    res_lead = evaluate_stock_alignment("BUY", "hold", target_upside_pct=10.0, number_of_analysts=15)
    assert res_lead["status"] == "MODEL_LEAD"
    assert "Model Leading" in res_lead["badge"]

    # 3. Divergence warning
    res_div = evaluate_stock_alignment("SELL", "strong_buy", target_upside_pct=15.0, number_of_analysts=20)
    assert res_div["status"] == "DIVERGENCE_ALERT"
    assert "Divergence" in res_div["badge"]

    # 4. Consensus sell
    res_sell = evaluate_stock_alignment("SELL", "sell", target_upside_pct=-5.0, number_of_analysts=10)
    assert res_sell["status"] == "CONSENSUS_SELL"


def test_mf_consensus_alignment():
    engine = get_global_engine()
    session = get_session(engine)

    # Test scheme 122639 (Parag Parikh Flexi Cap)
    mf_eval = evaluate_mf_alignment("ACCUMULATE", 122639, session)
    assert "verification_status" in mf_eval
    assert "crisil_stars" in mf_eval
    assert mf_eval["crisil_stars"] >= 4
    assert "Dual Confirmed" in mf_eval["verification_badge"]

    session.close()


def test_fetch_stock_consensus_live_or_fallback():
    data = fetch_stock_consensus("HDFCBANK", current_price=1600.0)
    assert data["symbol"] == "HDFCBANK"
    assert "consensus_key" in data
    assert "consensus_label" in data
    assert "target_mean_price" in data


def test_portfolio_consensus_summary():
    mock_items = [
        {"is_dual_confirmed": True, "consensus_upside_pct": 20.0, "analyst_count": 30},
        {"is_dual_confirmed": True, "consensus_upside_pct": 15.0, "analyst_count": 25},
        {"is_dual_confirmed": False, "consensus_upside_pct": 10.0, "analyst_count": 12}
    ]
    summary = compute_portfolio_consensus_summary(mock_items)
    assert summary["total_items"] == 3
    assert summary["dual_confirmed_count"] == 2
    assert summary["dual_confirmed_pct"] == 66.7
    assert summary["total_analyst_opinions"] == 67


if __name__ == "__main__":
    test_evaluate_stock_alignment_quadrants()
    test_mf_consensus_alignment()
    test_fetch_stock_consensus_live_or_fallback()
    test_portfolio_consensus_summary()
    print("All Consensus Verifier unit tests passed successfully!")
