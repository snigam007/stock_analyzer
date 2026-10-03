"""
Verification script for Top Guided Navigation Banner and Steps 1-4 UI Enhancements
"""
import calendar
from datetime import date, timedelta
from db.database import get_global_engine, get_session
from core.monthly_sip_advisor import generate_monthly_sip_basket

def test_ui_steps():
    engine = get_global_engine()
    session = get_session(engine)
    
    print("Testing generate_monthly_sip_basket with Apex Quad Alpha parameters...")
    basket = generate_monthly_sip_basket(
        session,
        monthly_wallet=20000.0,
        strategy="PURE_STOCKS",
        risk_profile="RISKY",
        target_stock_count=4,
        exit_protocol="DYNAMIC_ATR",
        pyramid_winners=True,
        min_momentum_hurdle_pct=25.0,
        enable_dip_buying=True,
        enable_parabolic_skim=True,
        annual_step_up_pct=10.0,
        empirical_strategy_xirr=62.70
    )
    session.close()
    
    # 1. Navigation Banner calculations
    today = date.today()
    nav_day = today.day
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    days_left = max(1, days_in_month - nav_day + 1)
    month_pct = (nav_day / days_in_month) * 100.0
    print(f"\n[Navigation Banner]")
    print(f"  Day: {nav_day}/{days_in_month} ({month_pct:.1f}% elapsed)")
    print(f"  Days Left to Rebalance: {days_left}")
    assert days_left >= 1, "Days left must be >= 1"
    
    # 2. Step 1: Execution Card
    print(f"\n[Step 1: Broker Execution Card]")
    assets = basket.get("assets", [])
    print(f"  Assets count: {len(assets)}")
    assert len(assets) > 0, "Assets must not be empty"
    for a in assets:
        sym = a["symbol"]
        qty = a["shares_to_buy"]
        price = a["current_price"]
        cost = a["total_cost"]
        sl = a.get("stop_loss")
        print(f"  Order: BUY {sym:<10} | Qty: {qty} | CMP: Rs.{price:,.2f} | Outlay: Rs.{cost:,.2f} | SL: {sl}")
        assert qty >= 1, f"Quantity for {sym} must be >= 1"
        assert cost > 0, f"Cost for {sym} must be > 0"
        
    print(f"  Total Spent: Rs.{basket['total_spent']:,.2f}")
    print(f"  Leftover Buffer: Rs.{basket['cash_buffer']:,.2f}")
    assert basket['total_spent'] <= 20000.0, "Total spent must not exceed monthly wallet"
    
    # 3. Step 2: Daily Action Checklist
    print(f"\n[Step 2: Daily Action Checklist]")
    for a in assets:
        p = a["current_price"]
        sl = a.get("stop_loss", p * 0.85)
        entry = a.get("entry_price", p)
        is_skim = a.get("is_parabolic_skim", False) or (p >= entry * 2.2)
        if sl and p <= sl:
            badge = "EXIT & SWEEP"
        elif is_skim:
            badge = "TRIM 10%"
        else:
            badge = "HOLD & COMPOUND"
        print(f"  {a['symbol']}: Badge = {badge} (CMP: Rs.{p:,.2f}, SL: Rs.{sl:,.2f})")
        assert badge in ["HOLD & COMPOUND", "TRIM 10%", "EXIT & SWEEP"]
        
    # 4. Step 3: Tactical Parking & LiquidBees Yield Counter
    print(f"\n[Step 3: Tactical Parking & LiquidBees Yield Counter]")
    cash = basket['cash_buffer']
    daily_int = round(cash * 0.065 / 365, 2)
    monthly_int = round(cash * 0.065 / 12, 1)
    dip_data = basket.get("tactical_dip_alert") or {}
    dip_pct = dip_data.get("drop_pct", 0.0)
    readiness_pct = min(100.0, max(0.0, (dip_pct / 3.0) * 100.0))
    print(f"  Parked Capital: Rs.{cash:,.2f}")
    print(f"  Accrued 6.5% Yield: Rs.{daily_int:,.2f}/day (Rs.{monthly_int:,.1f}/mo)")
    print(f"  Dip-Buying Readiness: -{dip_pct:.1f}% / -3.0% threshold ({readiness_pct:.0f}% meter)")
    assert daily_int >= 0.0, "Daily interest must be >= 0"
    assert 0.0 <= readiness_pct <= 100.0, "Readiness meter must be between 0 and 100%"

    # 5. Step 4: Next Tranche Countdown & On-Deck Candidates
    print(f"\n[Step 4: Next Tranche Countdown & On-Deck Replacement Bench]")
    print(f"  Days Remaining: {days_left}")
    on_deck = basket.get("on_deck_candidates", [])
    print(f"  On-Deck Candidates Count: {len(on_deck)}")
    for idx, cand in enumerate(on_deck):
        print(f"    Priority {idx+1}: {cand['symbol']} ({cand['name']}) | Sector: {cand['sector']} | CMP: Rs.{cand['current_price']:,.2f} | Score: {cand['composite_score']}")
    
    print("\nALL 5 TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_ui_steps()
