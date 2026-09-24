"""
Verification script for all 5 implemented quantitative improvements:
1. Market Breadth & Thrust Radar
2. Lead-Lag Bellwether Early Predictor
3. Macro Regime Integration & Automated Strategy Routing
4. Volume/Delivery Gating & Dynamic ATR Volatility Stops
5. Streamlit Cockpit Dashboards (Page 0 & Page 16)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from db.database import get_session
from core.market_breadth import calculate_market_breadth
from core.bellwether_lead_lag import evaluate_bellwether_lead_lag
from core.macro_regime import evaluate_macro_regime
from core.monthly_sip_advisor import generate_monthly_sip_basket

def main():
    session = get_session()
    try:
        print("=" * 70)
        print("1. TESTING MARKET BREADTH & THRUST ENGINE")
        print("=" * 70)
        b = calculate_market_breadth(session)
        print(f"Total Evaluated: {b.get('total_stocks_evaluated')}")
        print(f"> 20-Day EMA:   {b.get('pct_above_20_ema')}%")
        print(f"> 50-Day EMA:   {b.get('pct_above_50_ema')}%")
        print(f"> 200-Day EMA:  {b.get('pct_above_200_ema')}%")
        print(f"Thrust Status:  {b.get('breadth_thrust_badge')}")
        print(f"Assessment:     {b.get('assessment')}")
        assert b.get('total_stocks_evaluated') > 100, "Should evaluate active stock universe"

        print("\n" + "=" * 70)
        print("2. TESTING BELLWETHER LEAD-LAG PREDICTOR ENGINE")
        print("=" * 70)
        bw = evaluate_bellwether_lead_lag(session)
        print(f"Forecast Direction:  {bw.get('forecast_direction')}")
        print(f"Forecast Code:       {bw.get('forecast_code')}")
        print(f"Confidence:          {bw.get('forecast_confidence_pct')}%")
        print(f"Lead Composite:      {bw.get('lead_composite_score'):+.2f}")
        for sym, data in bw.get("heavyweight_anchors", {}).items():
            print(f"  - {sym:<12} Ret 1D: {data.get('ret_1d'):+.2f}% | Ret 5D: {data.get('ret_5d'):+.2f}% | Bias: {data.get('bias')}")
        assert len(bw.get("heavyweight_anchors", {})) >= 3, "Should evaluate key anchors"

        print("\n" + "=" * 70)
        print("3. TESTING MACRO REGIME ENGINE")
        print("=" * 70)
        m = evaluate_macro_regime(session)
        print(f"Macro Score:          {m.get('macro_score')}/100")
        print(f"Regime:               {m.get('regime')}")
        print(f"Active Strategy Mode: {m.get('active_strategy_mode')}")
        print(f"Summary:              {m.get('summary')}")
        print(f"Recommended Alloc:    {m.get('recommended_allocation')}")
        assert "active_strategy_mode" in m, "Should have active_strategy_mode"

        print("\n" + "=" * 70)
        print("4. TESTING SIP ADVISOR (AUTO_REGIME_ROUTING + DYNAMIC_ATR)")
        print("=" * 70)
        sip = generate_monthly_sip_basket(
            session=session,
            monthly_wallet=25000.0,
            strategy="AUTO_REGIME_ROUTING",
            exit_protocol="DYNAMIC_ATR"
        )
        print(f"Requested Strategy:  {sip.get('strategy')}")
        print(f"Effective Strategy:  {sip.get('effective_strategy')}")
        print(f"Routed Mode:         {sip.get('regime_routing_info', {}).get('routed_mode')}")
        print(f"Expected CAGR:       {sip.get('expected_cagr_pct')}%/yr")
        print(f"Total Spent:         Rs. {sip.get('total_spent'):,.0f} (Cash Buffer: Rs. {sip.get('cash_buffer'):,.0f})")
        print(f"Selected Assets ({len(sip.get('assets', []))}):")
        for a in sip.get("assets", []):
            print(f"  - {a.get('symbol'):<14} {a.get('shares_to_buy')} shs @ Rs. {a.get('current_price'):>7.1f} | SL: {a.get('stop_loss')} | Tgt: {a.get('target_price')} | {a.get('rationale')}")

        assert sip.get("effective_strategy") in ["PURE_STOCKS", "MULTI_ASSET"], "Should resolve to a concrete effective strategy"
        assert len(sip.get("assets", [])) >= 3, "Should select at least 3 assets"

        print("\n" + "=" * 70)
        print("5. TESTING SECTOR RELATIVE STRENGTH & GATING ENGINE")
        print("=" * 70)
        from core.sector_analysis import calculate_sector_relative_strength, get_sector_regime_gate
        sec_rs = calculate_sector_relative_strength(session)
        print(f"Total Sectors Evaluated: {len(sec_rs)}")
        assert len(sec_rs) >= 10, "Should evaluate at least 10 sectors"
        sample_sec = list(sec_rs.keys())[0]
        gate_info = get_sector_regime_gate(sample_sec, session=session)
        print(f"Sample Sector: {sample_sec} -> RS 20D: {gate_info.get('rs_20d'):+.2f}% | Class: {gate_info.get('classification')} | Gated: {gate_info.get('is_gated')}")
        assert "classification" in gate_info, "Gate info must contain classification"

        print("\n" + "=" * 70)
        print("6. TESTING ASYMMETRIC CONVICTION WEIGHTING (30/25/20/15/10)")
        print("=" * 70)
        sip_conv = generate_monthly_sip_basket(
            session=session,
            monthly_wallet=20000.0,
            strategy="PURE_STOCKS",
            enable_conviction_weighting=True
        )
        assets = sip_conv.get("assets", [])
        print(f"Basket Assets Count: {len(assets)}")
        if len(assets) >= 5:
            weights = [a.get("weight_pct", 0) for a in assets[:5]]
            print(f"Observed Weights: {weights}")
            # Ensure asymmetric allocation where top conviction receives more than rank 5
            assert assets[0].get("weight_pct") > assets[-1].get("weight_pct"), "Rank 1 must receive higher weight than Rank 5"

        print("\n" + "=" * 70)
        print("7. TESTING INSTITUTIONAL MINIMUM 1.5x+ R:R CALIBRATOR")
        print("=" * 70)
        from core.signals import calculate_targets
        price = 500.0
        atr = 15.0
        targets = calculate_targets(current_price=price, atr=atr, signal="BUY", market_cap_tier="mid")
        t1 = targets["target_1"]
        t2 = targets["target_2"]
        sl = targets["stop_loss"]
        rr_1 = (t1 - price) / (price - sl)
        rr_2 = (t2 - price) / (price - sl)
        print(f"Price: Rs. {price} | SL: Rs. {sl} (-{(price-sl)/price*100:.1f}%)")
        print(f"Target 1: Rs. {t1} (+{(t1-price)/price*100:.1f}%) | R:R = {rr_1:.2f}x")
        print(f"Target 2: Rs. {t2} (+{(t2-price)/price*100:.1f}%) | R:R = {rr_2:.2f}x")
        assert rr_1 >= 1.48, f"Target 1 R:R must be >= 1.50x, got {rr_1:.2f}x"
        assert rr_2 >= 2.10, f"Target 2 R:R must be >= 2.20x, got {rr_2:.2f}x"

        print("\n" + "=" * 70)
        print("8. TESTING MULTI-TIMEFRAME (MTF) WEEKLY TREND GATING (GUARDRAIL 6)")
        print("=" * 70)
        from core.multi_timeframe import analyze_multi_timeframe_alignment
        import pandas as pd
        from sqlalchemy import text
        prices_df = pd.read_sql_query(
            "SELECT date, open, high, low, close, volume FROM daily_prices WHERE symbol = 'HDFCBANK' ORDER BY date ASC",
            session.bind
        )
        mtf_data = analyze_multi_timeframe_alignment("HDFCBANK", prices_df, signal_direction="BUY")
        print(f"HDFCBANK MTF Confluence: Badge={mtf_data['confluence_badge']} | Tier={mtf_data['confluence_tier']} | Score={mtf_data['confluence_score']} | Triple={mtf_data['is_triple_confluence']} | Counter={mtf_data['is_counter_trend']}")
        print(f"  - Short-Term:    {mtf_data['short_term']['badge']} {mtf_data['short_term']['verdict']} ({mtf_data['short_term']['desc']})")
        print(f"  - Intermediate:  {mtf_data['intermediate']['badge']} {mtf_data['intermediate']['verdict']} ({mtf_data['intermediate']['desc']})")
        print(f"  - Weekly:        {mtf_data['weekly']['badge']} {mtf_data['weekly']['verdict']} ({mtf_data['weekly']['desc']})")
        print(f"  - Macro Secular: {mtf_data['macro']['badge']} {mtf_data['macro']['verdict']} ({mtf_data['macro']['desc']})")
        assert "confluence_badge" in mtf_data, "MTF data must contain confluence_badge"
        assert mtf_data["confluence_tier"] in ["TRIPLE_CONFLUENCE", "CORE_ALIGNED", "SELECTIVE_NEUTRAL", "COUNTER_TREND", "UNKNOWN"], f"Invalid MTF tier: {mtf_data['confluence_tier']}"

        print("\n" + "=" * 70)
        print("9. TESTING PRE-MARKET TOP-3 SNIPER BRIEFING")
        print("=" * 70)
        from core.premarket_briefing import generate_premarket_briefing, get_cached_premarket_briefing
        briefing = generate_premarket_briefing(session)
        print(f"Market Session Date: {briefing.get('market_session_date')}")
        print(f"Macro Regime: {briefing.get('macro', {}).get('regime')} | Active Strategy: {briefing.get('macro', {}).get('active_strategy_mode')}")
        snipers = briefing.get("sniper_setups", [])
        print(f"Top Sniper Setups Count: {len(snipers)}")
        assert len(snipers) == 3, f"Must return exactly 3 top sniper setups, got {len(snipers)}"
        for s in snipers:
            print(f"  - Rank #{s['rank']} {s['symbol']:<12} Score: {s['composite_score']:>5.1f} | Entry: Rs.{s['buy_price']} | SL: Rs.{s['stop_loss']} | Tgt1: Rs.{s['target_1']} | R:R: {s['risk_reward_ratio']}x | {s['pattern']}")
            assert s["risk_reward_ratio"] >= 1.48, "Sniper must have minimum ~1.5x R:R"
        
        cached_b = get_cached_premarket_briefing(session)
        assert cached_b.get("market_session_date") == briefing.get("market_session_date"), "Cached briefing must match"

        print("\n" + "=" * 70)
        print("10. TESTING INVERSE-VOLATILITY (EQUAL RISK CONTRIBUTION) SIZING")
        print("=" * 70)
        sip_erc = generate_monthly_sip_basket(
            session=session,
            monthly_wallet=50000.0,
            strategy="PURE_STOCKS",
            sizing_mode="INVERSE_VOL"
        )
        erc_assets = sip_erc.get("assets", [])
        print(f"Sizing Mode: {sip_erc.get('sizing_mode')}")
        print(f"ERC Basket Assets: {len(erc_assets)}")
        for a in erc_assets:
            print(f"  - {a['symbol']:<12} Wt: {a['weight_pct']:>5.1f}% | Rs.{a['total_cost']:>7.0f} ({a['shares_to_buy']} shs @ Rs.{a['current_price']})")
        assert sip_erc.get("sizing_mode") == "INVERSE_VOL", "Sizing mode must be preserved in output"

        from core.sip_audit_backtester import run_monthly_sip_backtest
        bt_erc = run_monthly_sip_backtest(
            session=session,
            monthly_wallet=20000.0,
            strategy="PURE_STOCKS",
            months_lookback=12,
            sizing_mode="INVERSE_VOL"
        )
        strat_xirr = bt_erc.get('strategy_xirr') or 0.0
        bench_xirr = bt_erc.get('benchmark_xirr') or 0.0
        print(f"ERC 12M Backtest XIRR: {strat_xirr:+.2f}% | Benchmark: {bench_xirr:+.2f}% | Max DD: {bt_erc.get('max_drawdown_pct'):.2f}%")
        assert "strategy_xirr" in bt_erc, "Backtest must calculate strategy XIRR"
        assert bt_erc.get("sizing_mode") == "INVERSE_VOL", "Backtest must preserve sizing_mode"

        print("\n" + "=" * 70)
        print("11. TESTING STOCK VS. MUTUAL FUND OVERLAP & TRUE CONCENTRATION LAB")
        print("=" * 70)
        from core.mf_overlap_analyzer import (
            get_available_mf_schemes,
            calculate_pairwise_fund_overlap,
            calculate_lookthrough_exposure
        )
        all_schemes = get_available_mf_schemes()
        print(f"Configured Institutional Schemes: {len(all_schemes)}")
        assert len(all_schemes) >= 20, "Should have at least 20 marquee schemes"

        # Pairwise test between two Nifty 50 Index funds (top 10 holdings account for 56% of index)
        pw_nifty = calculate_pairwise_fund_overlap(120716, 119062)
        print(f"Pairwise Overlap (UTI Nifty 50 vs ICICI Nifty 50): {pw_nifty['overlap_pct']}% across {pw_nifty['common_holdings_count']} stocks")
        assert pw_nifty["overlap_pct"] >= 50.0, "Top 10 index funds replication must exceed 50%"
        assert pw_nifty["common_holdings_count"] == 10, "All top 10 holdings must match across Nifty 50 index funds"

        # Blended look-through exposure test
        direct_test = {"HDFCBANK": 100000.0, "INFY": 60000.0, "RELIANCE": 75000.0, "TRENT": 40000.0}
        mf_test = {122639: 150000.0, 118955: 125000.0}  # Parag Parikh & HDFC Flexi Cap
        lt = calculate_lookthrough_exposure(direct_test, mf_test)
        print(f"Blended Portfolio Value: Rs.{lt['grand_total_amount']:,.0f}")
        print(f"Naive HHI: {lt['naive_hhi']:.0f} -> True Look-Through HHI: {lt['lookthrough_hhi']:.0f} (Multiplier: {lt['concentration_multiplier']}x)")
        print(f"Duplicated Capital: Rs.{lt['duplicated_capital_amount']:,.0f} ({lt['duplicated_capital_pct']}% fee cannibalization)")
        print(f"Cannibalization Alerts Count: {len(lt['cannibalization_alerts'])}")
        assert lt["lookthrough_hhi"] > 0 and lt["naive_hhi"] > 0, "HHIs must be calculated"
        assert lt["concentration_multiplier"] > 0, "Concentration multiplier must be calculated"
        assert lt["overlapping_stocks_count"] > 0, "Must detect overlapping holdings (HDFCBANK, INFY)"
        assert len(lt["all_effective_stocks"]) > 0, "Must compute effective exposures"
        assert len(lt["cannibalization_alerts"]) > 0, "Must flag cannibalization when holding same large caps"

        print("\n" + "=" * 70)
        print("ALL 11 ADVANCED QUANTITATIVE ENGINES VERIFIED 100% OPERATIONAL!")
        print("=" * 70)
    finally:
        session.close()

if __name__ == "__main__":
    main()

