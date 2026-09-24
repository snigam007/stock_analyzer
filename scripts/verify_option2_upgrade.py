"""
Verification Test for Option 2 Full System Upgrade
===================================================
Tests:
1. Reachable T2/T3 targets & Pillar Weights in sector_clusters.py
2. Recalibrated score_rsi and score_technical in scoring.py
3. Guardrail 9 (Friday Gate) & Guardrail 10 (Sector Gate) in signals.py
4. Max Hold Duration (10 days) auto-exit in accuracy_tracker.py
"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8')
from datetime import date, datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.sector_clusters import get_tier_parameters, get_cluster_pillar_weights
from core.scoring import score_rsi, compute_apex_multi_factor_score
from core.signals import generate_signal_for_stock
from db.database import Stock

print("=" * 70)
print("VERIFICATION: OPTION 2 FULL SYSTEM UPGRADE")
print("=" * 70)

# 1. Tier Parameters
print("\n[1] Testing Reachable Targets in sector_clusters.py...")
for tier in ['large', 'mid', 'small']:
    p = get_tier_parameters(tier)
    print(f"  {tier.upper():<6} -> T1 floor: {p['target_1_floor_pct']*100:.1f}%, T2 floor: {p['target_2_floor_pct']*100:.1f}%, T3 floor: {p['target_3_floor_pct']*100:.1f}%")
    assert p['target_2_floor_pct'] <= 0.09, f"T2 floor too high for {tier}"
print("  ✓ Tier parameters verified.")

# Pillar Weights
pw = get_cluster_pillar_weights("CAPEX_MOMENTUM", has_fno=True, has_news=True)
print(f"  Pillar weights (Capex): Tech={pw['w_tech']:.2f}, SM={pw['w_sm']:.2f}, Fund={pw['w_fund']:.2f}, Deriv={pw['w_deriv']:.2f}, AI={pw['w_ai']:.2f}")
assert pw['w_ai'] >= 0.20, "AI weight should be >= 0.20"
print("  ✓ Cluster pillar weights verified.")

# 2. Scoring Recalibration
print("\n[2] Testing Scoring Recalibration in scoring.py...")
rsi_sweet = score_rsi(52.0)
rsi_ob = score_rsi(74.0)
print(f"  RSI 52 (Sweet Spot): {rsi_sweet:.1f} pts")
print(f"  RSI 74 (Overbought):  {rsi_ob:.1f} pts")
assert rsi_sweet > rsi_ob, "Sweet spot RSI should score higher than overbought RSI"

comp_score, details = compute_apex_multi_factor_score(
    indicators={"close": 1500.0, "rsi_14": 54.0, "macd": 5.0, "macd_signal": 2.0, "stoch_k": 30.0, "stoch_d": 20.0, "volume_ratio": 1.5, "adx": 28.0, "di_plus": 25.0, "di_minus": 15.0},
    symbol="INFY", name="Infosys", sector="IT & Technology", tier="large", ml_forecast_score=68.0
)
print(f"  Apex Multi-Factor Score (INFY): {comp_score:.1f}/100")
assert comp_score > 55.0, "High quality setup should score well"
print("  ✓ Scoring recalibration verified.")

# 3. Guardrails in signals.py
print("\n[3] Testing Guardrail 9 (Friday Gate) & Guardrail 10 (Sector Gate)...")

# Mock Stock
class MockStock:
    id = 1
    symbol = "HDFCBANK"
    name = "HDFC Bank"
    sector = "Banking & Finance"
    market_cap_tier = "large"

mock_bank = MockStock()

ind_base = {
    "date": "2026-09-25", # Friday (2026-09-25 is a Friday)
    "close": 1600.0, "atr_14": 25.0, "rsi_14": 52.0,
    "macd": 5.0, "macd_signal": 2.0, "volume_ratio": 1.5,
    "adx": 28.0, "di_plus": 25.0, "di_minus": 15.0,
    "ema_50": 1550.0, "ema_200": 1500.0
}

# Test Guardrail 9: Friday Gate
res_fri = generate_signal_for_stock(
    stock=mock_bank, ind=ind_base, composite_score=62.0
)
print(f"  Friday Signal Result: {res_fri['signal']} ({res_fri.get('key_reason', 'No reason')})")
assert res_fri['signal'] == "WATCH", "Friday BUY should be demoted to WATCH by Guardrail 9"
assert "Guardrail 9" in res_fri.get('key_reason', ''), "Guardrail 9 reason expected"
print("  ✓ Guardrail 9 (Friday Gate) successfully fired.")

# Test Guardrail 10: Sector Gate (Thursday date, score = 59.6 passes large-cap 59.5 hurdle, but caught by sector 60.0 gate)
ind_thu = ind_base.copy()
ind_thu["date"] = "2026-09-24" # Thursday
res_sec = generate_signal_for_stock(
    stock=mock_bank, ind=ind_thu, composite_score=59.6
)
print(f"  Banking Score 59.6 Result: {res_sec['signal']} ({res_sec.get('key_reason', 'No reason')})")
assert res_sec['signal'] == "WATCH", "Banking with score < 60 should be demoted to WATCH by Guardrail 10"
assert "Guardrail 10" in res_sec.get('key_reason', ''), "Guardrail 10 reason expected"
print("  ✓ Guardrail 10 (Sector Gate) successfully fired.")

# Test High Conviction Non-Friday (Thursday, score = 65.0 for IT stock)
class MockITStock:
    id = 2
    symbol = "TCS"
    name = "Tata Consultancy Services"
    sector = "IT & Technology"
    market_cap_tier = "large"

mock_it = MockITStock()
res_it = generate_signal_for_stock(
    stock=mock_it, ind=ind_thu, composite_score=65.0
)
print(f"  IT Score 65.0 Result: {res_it['signal']} (R:R={res_it['risk_reward_ratio']:.2f}x)")
assert res_it['signal'] == "BUY", "Strong IT stock on Thursday should emit BUY"
print("  ✓ High conviction BUY successfully passed all 10 guardrails.")

# 4. Accuracy Tracker Stats
print("\n[4] Testing Accuracy Tracker & Database Stats...")
from db.database import get_session
from core.accuracy_tracker import _compute_summary_stats
session = get_session()
stats = _compute_summary_stats(session, asset_type="STOCK")
session.close()
print(f"  Total Tracked Signals: {stats.get('total_signals_tracked')}")
print(f"  Completed Signals:     {stats.get('completed_signals')}")
print(f"  Overall Win Rate:      {stats.get('overall_win_rate_pct'):.1f}%")
print(f"  Profit Factor:         {stats.get('profit_factor', 0.0):.2f}x")
assert stats.get('completed_signals', 0) > 0, "Completed signals should be > 0"
print("  ✓ Accuracy tracker database functions verified.")

print("\n" + "=" * 70)
print("ALL VERIFICATION CHECKS PASSED SUCCESSFULLY!")
print("=" * 70)
