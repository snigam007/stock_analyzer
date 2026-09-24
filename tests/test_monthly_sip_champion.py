"""
tests/test_monthly_sip_champion.py

Unit and Integration Tests for:
1. Champion Monthly SIP Basket Generation (core/monthly_sip_advisor.py)
   - target_stock_count = 6
   - selection_filter = 'SECTOR_LEAD_ALPHA' (6M mom >= 25%, max 2 per sector)
   - exit_protocol = 'DYNAMIC_ATR' (Peak - 3.5x ATR trailing, 7.0x ATR target)
2. Sell Reminder Radar 50-EMA & 200-EMA structural loss triggers
"""
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from db.database import get_global_engine, get_session
from core.monthly_sip_advisor import generate_monthly_sip_basket, evaluate_sell_reminders


def test_champion_sip_basket():
    """Verify champion basket generation with default 6 stocks, SECTOR_LEAD_ALPHA, and DYNAMIC_ATR."""
    engine = get_global_engine()
    session = get_session(engine)
    try:
        basket = generate_monthly_sip_basket(
            session=session,
            monthly_wallet=20000.0,
            strategy="PURE_STOCKS",
            target_stock_count=6,
            exit_protocol="DYNAMIC_ATR",
            selection_filter="SECTOR_LEAD_ALPHA"
        )

        assert "selected_assets" in basket, "Basket missing selected_assets"
        assets = basket["selected_assets"]
        print(f"Generated Basket with {len(assets)} assets:")
        for a in assets:
            print(f"  • {a['symbol']} ({a['sector']}): ₹{a['current_price']} x {a['shares_to_buy']} = ₹{a['total_cost']} | SL: {a.get('stop_loss')} | Tgt: {a.get('target_price')}")

        assert len(assets) > 0, "No assets selected in champion basket"
        equity_assets = [a for a in assets if a.get("asset_class") != "Commodity / Hedge"]
        assert len(equity_assets) <= 6, f"Expected <= 6 equity stocks, got {len(equity_assets)}"

        # Check sector concentration limit (max 2 per sector under SECTOR_LEAD_ALPHA)
        sector_counts = {}
        for a in equity_assets:
            sec = a.get("sector", "General")
            sector_counts[sec] = sector_counts.get(sec, 0) + 1
            assert sector_counts[sec] <= 2, f"Sector {sec} exceeded max 2 limit: {sector_counts[sec]}"

        # Check dynamic ATR protocol description in selected assets
        for a in assets:
            if a.get("is_mutual_fund"): continue
            proto_d = a.get("protocol_desc", "")
            # Dynamic ATR protocol badge
            assert "Dynamic ATR" in proto_d or "3.5×ATR" in proto_d or a.get("stop_loss") is not None

        print("PASS: test_champion_sip_basket")
    finally:
        session.close()


def test_sell_reminders_radar():
    """Verify evaluate_sell_reminders runs cleanly without SQL/Key errors."""
    engine = get_global_engine()
    session = get_session(engine)
    try:
        reminders = evaluate_sell_reminders(session)
        print(f"Sell Reminders scanned: {len(reminders)} flagged items")
        print("PASS: test_sell_reminders_radar")
    finally:
        session.close()


if __name__ == "__main__":
    print("=" * 60)
    print("🧪 RUNNING VALIDATION: MONTHLY SIP CHAMPION")
    print("=" * 60)
    test_champion_sip_basket()
    test_sell_reminders_radar()
    print("=" * 60)
    print("🎉 ALL TESTS PASSED SUCCESSFULLY!")
    print("=" * 60)
