"""
Monthly SIP Investment Planner & Sell Reminder Radar Engine
- Computes exact integer share counts for customizable monthly wallet (default ₹20,000)
- Supports 2 Strategies:
    1. 'PURE_STOCKS' (100% Direct Equities across 5-6 core sectors)
    2. 'MULTI_ASSET' (Equities + Benchmark Index ETFs + Gold/Commodities)
- 1-Click deploy to monthly watchlists with share count notes, targets, and stop losses
- Real-time Sell Reminder Scanner: evaluates Stop-Loss breaches, Model SELL ratings, and 200-EMA breakdowns
"""
import math
import logging
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional
import pandas as pd
import numpy as np
from sqlalchemy.orm import Session
from sqlalchemy import text

import importlib
import db.database
if not hasattr(db.database, "MutualFund"):
    importlib.reload(db.database)
from db.database import Watchlist, WatchlistItem, Stock, PriceAlert, MutualFund, MutualFundNAV

logger = logging.getLogger(__name__)


# ─── 1. Monthly SIP Basket Generation ─────────────────────────────────────────
def generate_monthly_sip_basket(
    session: Session,
    monthly_wallet: float = 20000.0,
    strategy: str = "PURE_STOCKS",     # PURE_STOCKS or MULTI_ASSET
    include_mutual_funds: bool = False, # Toggle to include Mutual Funds as Core allocation
    risk_profile: str = "BALANCED",    # SAFE, BALANCED, RISKY
    target_stock_count: int = 5,
    exit_protocol: str = "ADAPTIVE_STRUCTURAL", # ADAPTIVE_STRUCTURAL, STRUCTURAL_TRAILING, BUY_AND_HOLD, TIGHT_SWING
    as_of_date: Optional[str] = None,
    pyramid_winners: bool = True,
    min_momentum_hurdle_pct: float = 20.0,
    enable_dip_buying: bool = True,
    enable_parabolic_skim: bool = True,
    max_position_cap_pct: float = 45.0,
    annual_step_up_pct: float = 10.0
) -> Dict:
    """
    Generates an optimized monthly investment basket with exact integer share quantities
    that fit neatly inside the monthly wallet amount, integrating Winner Pyramiding,
    Momentum Hurdles, Tactical Dip-Buying, and Parabolic Profit Skims.
    """
    monthly_wallet = max(5000.0, float(monthly_wallet))
    target_stock_count = max(3, min(10, target_stock_count))

    if not as_of_date:
        max_d_row = session.execute(text("SELECT MAX(date) FROM signals")).first()
        as_of_date = str(max_d_row[0]) if max_d_row and max_d_row[0] else str(date.today())

    # Expected CAGR based on strategy, protocol & risk (Calibrated with empirical 5-year simulation: 35.6% XIRR)
    if exit_protocol == "ADAPTIVE_STRUCTURAL":
        cagr_map = {"SAFE": 26.5, "BALANCED": 31.0, "RISKY": 35.6} if strategy == "PURE_STOCKS" else {"SAFE": 19.5, "BALANCED": 22.5, "RISKY": 25.0}
    elif exit_protocol == "STRUCTURAL_TRAILING":
        cagr_map = {"SAFE": 18.0, "BALANCED": 21.5, "RISKY": 24.8} if strategy == "PURE_STOCKS" else {"SAFE": 14.5, "BALANCED": 17.0, "RISKY": 19.5}
    elif exit_protocol == "BUY_AND_HOLD":
        cagr_map = {"SAFE": 16.0, "BALANCED": 19.5, "RISKY": 21.8} if strategy == "PURE_STOCKS" else {"SAFE": 13.5, "BALANCED": 15.5, "RISKY": 17.5}
    else: # TIGHT_SWING
        cagr_map = {"SAFE": 8.5, "BALANCED": 10.5, "RISKY": 12.5} if strategy == "PURE_STOCKS" else {"SAFE": 7.5, "BALANCED": 9.5, "RISKY": 11.0}

    expected_cagr = cagr_map.get(risk_profile, 29.5)

    # Tracked symbols for Winner Pyramiding
    tracked_symbols = set()
    try:
        wl_rows = session.query(WatchlistItem.symbol).all()
        tracked_symbols = {r[0] for r in wl_rows}
    except Exception:
        pass

    selected_assets = []
    equity_budget_pool = monthly_wallet
    target_stocks_to_pick = target_stock_count

    # Core Mutual Funds Allocation (when toggle enabled)
    if include_mutual_funds:
        mf_budget = monthly_wallet * 0.50
        top_mfs = session.query(MutualFund).filter_by(is_active=True).all()
        fc = next((f for f in top_mfs if f.scheme_code == 122639), top_mfs[0] if top_mfs else None)
        mc = next((f for f in top_mfs if f.scheme_code == 120823), top_mfs[1] if len(top_mfs) > 1 else None)
        idx = next((f for f in top_mfs if f.scheme_code == 120716), top_mfs[2] if len(top_mfs) > 2 else None)
        chosen_mfs = [f for f in [fc, mc, idx] if f]

        if chosen_mfs:
            mf_portion = round(mf_budget / len(chosen_mfs), 2)
            for f in chosen_mfs:
                nav_val = session.execute(
                    text("SELECT nav FROM mutual_fund_navs WHERE scheme_code = :sc ORDER BY date DESC LIMIT 1"),
                    {"sc": f.scheme_code}
                ).scalar() or 100.0
                units = round(mf_portion / nav_val, 3)
                selected_assets.append({
                    "symbol": f"MF_{f.scheme_code}",
                    "name": f.scheme_name,
                    "asset_class": "Mutual Fund",
                    "sector": f.sub_category,
                    "tier": "Core Compounder",
                    "current_price": round(nav_val, 2),
                    "shares_to_buy": units,
                    "total_cost": mf_portion,
                    "stop_loss": None,
                    "target_price": round(nav_val * 1.50, 2),
                    "composite_score": 85.0,
                    "signal": "ACCUMULATE",
                    "risk_level": "SAFE" if "Index" in f.sub_category or "Liquid" in f.sub_category else "MODERATE",
                    "is_pyramided": False,
                    "is_mutual_fund": True,
                    "scheme_code": f.scheme_code,
                    "rationale": f"Institutional Core {f.sub_category} anchor ({f.fund_house})"
                })
            equity_budget_pool = max(1000.0, monthly_wallet - (mf_portion * len(chosen_mfs)))
            target_stocks_to_pick = max(2, target_stock_count - len(chosen_mfs))

    if strategy == "PURE_STOCKS":
        # 100% Direct Equities across distinct sectors
        # Query top candidate stocks with 6-month momentum lookup
        lookback_180d = (datetime.strptime(as_of_date, "%Y-%m-%d").date() - timedelta(days=180)).strftime("%Y-%m-%d")
        sql = f"""
            SELECT sig.symbol, s.name, s.sector, s.market_cap_tier, sig.current_price,
                   cs.composite_score, sig.signal, sig.risk_level, sig.stop_loss, sig.target_price_1,
                   cs.beta,
                   (sig.current_price - dp_past.close) / NULLIF(dp_past.close, 0.0) as ret_6m
            FROM signals sig
            JOIN stocks s ON sig.symbol = s.symbol
            JOIN composite_scores cs ON sig.symbol = cs.symbol AND cs.date = sig.date
            LEFT JOIN daily_prices dp_past ON dp_past.symbol = sig.symbol AND dp_past.date = (
                SELECT MIN(date) FROM daily_prices WHERE symbol = sig.symbol AND date >= '{lookback_180d}'
            )
            WHERE sig.date = :d
            AND s.is_active = 1
            AND sig.current_price > 50.0
            AND sig.current_price <= (:wallet * 0.45)
            AND sig.signal IN ('BUY', 'STRONG BUY', 'WATCH')
            ORDER BY
                CASE WHEN sig.signal = 'BUY' THEN 1 WHEN sig.signal = 'STRONG BUY' THEN 1 ELSE 2 END,
                (
                    COALESCE((sig.current_price - dp_past.close) / NULLIF(dp_past.close, 0.0), 0.0) * 50.0
                    + cs.composite_score * 0.5
                ) DESC
        """
        candidates = session.execute(text(sql), {"d": as_of_date, "wallet": equity_budget_pool}).fetchall()

        # If candidates are too few with price filter, relax price filter
        if len(candidates) < target_stocks_to_pick:
            sql_fallback = f"""
                SELECT sig.symbol, s.name, s.sector, s.market_cap_tier, sig.current_price,
                       cs.composite_score, sig.signal, sig.risk_level, sig.stop_loss, sig.target_price_1,
                       cs.beta,
                       (sig.current_price - dp_past.close) / NULLIF(dp_past.close, 0.0) as ret_6m
                FROM signals sig
                JOIN stocks s ON sig.symbol = s.symbol
                JOIN composite_scores cs ON sig.symbol = cs.symbol AND cs.date = sig.date
                LEFT JOIN daily_prices dp_past ON dp_past.symbol = sig.symbol AND dp_past.date = (
                    SELECT MIN(date) FROM daily_prices WHERE symbol = sig.symbol AND date >= '{lookback_180d}'
                )
                WHERE sig.date = :d
                AND s.is_active = 1
                AND sig.current_price > 50.0
                AND sig.signal != 'SELL'
                ORDER BY cs.composite_score DESC
            """
            candidates = session.execute(text(sql_fallback), {"d": as_of_date}).fetchall()

        # Pick top stocks with strict sector diversification (1 stock per sector)
        chosen_sectors = set()
        picked_stocks = []

        for c in candidates:
            if len(picked_stocks) >= target_stocks_to_pick:
                break
            sec = c[2] or "General"
            if sec in chosen_sectors and len(candidates) > 8:
                continue

            # Momentum Hurdle Check
            if min_momentum_hurdle_pct > 0 and len(candidates) > (target_stocks_to_pick + 3):
                ret_6m = float(c[11]) if len(c) > 11 and c[11] is not None else 0.0
                if ret_6m < (min_momentum_hurdle_pct / 100.0):
                    continue
            elif min_momentum_hurdle_pct == 0:
                ret_6m_raw = c[11] if len(c) > 11 else None
                if ret_6m_raw is None:
                    continue
            
            # Risk profile filter
            r_risk = c[7] or "MODERATE"
            if risk_profile == "SAFE" and r_risk == "RISKY":
                continue

            chosen_sectors.add(sec)
            picked_stocks.append(c)

        # In case fewer sectors found, fill from remaining top candidates
        if len(picked_stocks) < target_stocks_to_pick:
            for c in candidates:
                if len(picked_stocks) >= target_stocks_to_pick:
                    break
                if c[0] not in [x[0] for x in picked_stocks]:
                    picked_stocks.append(c)

        # Initial capital per stock
        target_allocation_per_stock = equity_budget_pool / max(1, len(picked_stocks))
        
        # Calculate whole shares
        for c in picked_stocks:
            sym = str(c[0])
            name = str(c[1]) if c[1] else sym
            sec = str(c[2]) if c[2] else "General"
            tier = str(c[3]) if c[3] else "large"
            price = float(c[4]) if c[4] else 1000.0
            score = float(c[5]) if c[5] else 55.0
            sig = str(c[6]) if c[6] else "BUY"
            risk = str(c[7]) if c[7] else "MODERATE"
            t_lower = tier.lower()
            if exit_protocol == "BUY_AND_HOLD":
                sl = None
                t1 = round(price * 2.50, 2)
                proto_desc = "Buy & Hold (Uncapped, No SL)"
            elif exit_protocol == "TIGHT_SWING":
                sl = round(price * 0.93, 2)
                t1 = round(price * 1.15, 2)
                proto_desc = "Tight Swing (-7% SL / +15% Tgt)"
            elif exit_protocol == "ADAPTIVE_STRUCTURAL":
                if t_lower == "large":
                    sl = round(price * 0.87, 2)
                    t1 = round(price * 1.50, 2)
                    proto_desc = "Adaptive Large-Cap (-13% SL / +25% BE / 22% Trail)"
                elif t_lower == "small":
                    sl = round(price * 0.83, 2)
                    t1 = round(price * 1.80, 2)
                    proto_desc = "Adaptive Small-Cap (-17% SL / +30% BE / 25% Trail)"
                else:
                    sl = round(price * 0.86, 2)
                    t1 = round(price * 1.60, 2)
                    proto_desc = "Adaptive Mid-Cap (-14% SL / +25% BE / 25% Trail)"
            elif exit_protocol == "STRUCTURAL_TRAILING":
                sl = round(price * 0.86, 2)
                t1 = round(price * 2.00, 2)
                proto_desc = "Structural Trailing (-14% SL / +45% BE / 30% Trail)"
            else:
                sl = round(price * 0.86, 2)
                t1 = round(price * 2.00, 2)
                proto_desc = "Structural Trailing (-14% SL / +45% BE / 30% Trail)"

            shares = int(math.floor(target_allocation_per_stock / max(0.01, price)))
            if shares == 0 and price <= (monthly_wallet * 0.40):
                shares = 1

            is_pyr = (sym in tracked_symbols and pyramid_winners)
            # Determine thematic rationale
            if is_pyr:
                rat = "🚀 Pyramided Winner: Averaging up into existing holding with strong momentum"
            elif "Bank" in sec or "Finance" in sec:
                rat = "Core Banking & Credit expansion engine with high ROE"
            elif "IT" in sec or "Tech" in sec:
                rat = "Cash-rich digital compounding & enterprise AI growth"
            elif "FMCG" in sec or "Staple" in sec:
                rat = "Defensive low-beta consumer anchor with pricing power"
            elif "Capital Goods" in sec or "Power" in sec or "Energy" in sec:
                rat = "Domestic capex & industrial modernization tailwind"
            elif "Pharma" in sec or "Health" in sec:
                rat = "Resilient export earnings & biosimilar pipeline"
            elif "Auto" in sec:
                rat = "Mobility upcycle & global component supply chain"
            else:
                rat = f"High-ranking {sec} leader (Composite Score: {score:.1f})"

            selected_assets.append({
                "symbol": sym,
                "name": name,
                "asset_class": "Equity",
                "sector": sec,
                "tier": tier,
                "current_price": price,
                "shares_to_buy": shares,
                "total_cost": round(shares * price, 2),
                "stop_loss": sl,
                "target_price": t1,
                "composite_score": round(score, 1),
                "signal": sig,
                "risk_level": risk,
                "is_pyramided": is_pyr,
                "rationale": rat
            })

    else:
        # MULTI_ASSET: Equities (65%) + Benchmark Index (20%) + Gold/Commodity (15%)
        eq_budget = equity_budget_pool * 0.65
        idx_budget = equity_budget_pool * 0.20
        comm_budget = equity_budget_pool * 0.15

        # 1. Equities
        eq_target_n = max(2, target_stocks_to_pick - 2)
        eq_per_stock = eq_budget / eq_target_n
        
        sql_eq = """
            SELECT sig.symbol, s.name, s.sector, s.market_cap_tier, sig.current_price,
                   cs.composite_score, sig.signal, sig.risk_level, sig.stop_loss, sig.target_price_1
            FROM signals sig
            JOIN stocks s ON sig.symbol = s.symbol
            JOIN composite_scores cs ON sig.symbol = cs.symbol AND cs.date = sig.date
            WHERE sig.date = :d AND s.is_active = 1 AND sig.current_price <= :max_p
            AND sig.signal IN ('BUY', 'STRONG BUY', 'WATCH')
            ORDER BY cs.composite_score DESC
        """
        eq_rows = session.execute(text(sql_eq), {"d": as_of_date, "max_p": eq_per_stock * 1.5}).fetchall()
        
        picked_secs = set()
        for r in eq_rows:
            if len([x for x in selected_assets if x["asset_class"] == "Equity"]) >= eq_target_n:
                break
            sec = r[2] or "General"
            if sec in picked_secs:
                continue
            picked_secs.add(sec)
            
            p = float(r[4])
            sh = max(1, int(math.floor(eq_per_stock / max(0.01, p))))
            t_lower = (r[3] or "mid").lower()
            if exit_protocol == "BUY_AND_HOLD":
                sl = None
                t1 = round(p * 2.50, 2)
            elif exit_protocol == "TIGHT_SWING":
                sl = round(p * 0.93, 2)
                t1 = round(p * 1.15, 2)
            elif exit_protocol in ("ADAPTIVE_STRUCTURAL", "STRUCTURAL_TRAILING"):
                if t_lower == "large":
                    # Fix 6: Align MULTI_ASSET large-cap SL with backtester (0.87 = 13% SL, was 0.90)
                    sl = round(p * 0.87, 2)
                    t1 = round(p * 1.35, 2)
                elif t_lower == "small":
                    sl = round(p * 0.83, 2)
                    t1 = round(p * 1.80, 2)
                else:
                    sl = round(p * 0.86, 2)
                    t1 = round(p * 1.50, 2)
            else:
                sl = round(p * 0.86, 2)
                t1 = round(p * 1.50, 2)
            selected_assets.append({
                "symbol": r[0], "name": r[1], "asset_class": "Equity", "sector": sec,
                "tier": r[3], "current_price": p, "shares_to_buy": sh,
                "total_cost": round(sh * p, 2), "stop_loss": sl, "target_price": t1,
                "composite_score": round(r[5], 1), "signal": r[6], "risk_level": r[7],
                "rationale": f"High conviction {sec} equity compounding anchor"
            })

        # 2. Benchmark Index / ETF proxy
        # Fix 5: Fetch real NIFTYBEES price from DB instead of hardcoded 265.0
        idx_price_row = session.execute(text("""
            SELECT close FROM index_prices
            WHERE symbol IN ('NIFTYBEES.NS', 'NIFTYBEES')
            ORDER BY date DESC LIMIT 1
        """)).first()
        idx_price = float(idx_price_row[0]) if idx_price_row and idx_price_row[0] else 265.0
        idx_shares = int(math.floor(idx_budget / max(0.01, idx_price)))
        selected_assets.append({
            "symbol": "NIFTYBEES", "name": "Nippon India Nifty 50 ETF", "asset_class": "Index / ETF",
            "sector": "Broad Market Index", "tier": "macro", "current_price": idx_price,
            "shares_to_buy": idx_shares, "total_cost": round(idx_shares * idx_price, 2),
            "stop_loss": round(idx_price * 0.95, 2), "target_price": round(idx_price * 1.08, 2),
            "composite_score": 75.0, "signal": "BUY", "risk_level": "SAFE",
            "rationale": "Broad market index core capturing overall Indian GDP growth"
        })

        # 3. Gold / Commodity
        # Fix 5: Fetch real GOLDBEES price from DB instead of hardcoded 72.0
        gold_price_row = session.execute(text("""
            SELECT close FROM index_prices
            WHERE symbol IN ('GOLDBEES.NS', 'GOLDBEES')
            ORDER BY date DESC LIMIT 1
        """)).first()
        gold_price = float(gold_price_row[0]) if gold_price_row and gold_price_row[0] else 72.0
        gold_shares = int(math.floor(comm_budget / max(0.01, gold_price)))
        selected_assets.append({
            "symbol": "GOLDBEES", "name": "Nippon India Gold ETF", "asset_class": "Commodity",
            "sector": "Precious Metals", "tier": "macro", "current_price": gold_price,
            "shares_to_buy": gold_shares, "total_cost": round(gold_shares * gold_price, 2),
            "stop_loss": round(gold_price * 0.94, 2), "target_price": round(gold_price * 1.07, 2),
            "composite_score": 70.0, "signal": "BUY", "risk_level": "SAFE",
            "rationale": "Strategic safe-haven hedge against currency depreciation & equity shocks"
        })

    # Adjust share counts dynamically to fill leftover wallet
    # Adjust share counts dynamically to fill leftover wallet
    # Enforce strict monthly wallet limit (preserving mutual fund core allocations)
    while sum(x["total_cost"] for x in selected_assets) > monthly_wallet:
        reducible = [x for x in selected_assets if not x.get("is_mutual_fund") and x["shares_to_buy"] > 1]
        if reducible:
            reducible.sort(key=lambda x: x["current_price"], reverse=True)
            reducible[0]["shares_to_buy"] -= 1
            reducible[0]["total_cost"] = round(reducible[0]["shares_to_buy"] * reducible[0]["current_price"], 2)
        else:
            stock_items = [x for x in selected_assets if not x.get("is_mutual_fund")]
            if len(stock_items) > 1:
                stock_items.sort(key=lambda x: x["total_cost"], reverse=True)
                selected_assets.remove(stock_items[0])
            else:
                break

    current_spent = sum(x["total_cost"] for x in selected_assets)
    leftover = monthly_wallet - current_spent

    # Greedily allocate remaining cash into lowest priced high-ranking stocks
    if leftover > 0 and selected_assets:
        sortable = sorted([x for x in selected_assets if not x.get("is_mutual_fund")], key=lambda x: (x["current_price"]))
        for item in sortable:
            if item["current_price"] <= leftover and item["current_price"] > 0:
                extra_shares = int(math.floor(leftover / item["current_price"]))
                if extra_shares > 0:
                    item["shares_to_buy"] += extra_shares
                    item["total_cost"] = round(item["shares_to_buy"] * item["current_price"], 2)
                    leftover -= (extra_shares * item["current_price"])

    total_spent = round(sum(x["total_cost"] for x in selected_assets), 2)
    cash_buffer = round(max(0.0, monthly_wallet - total_spent), 2)

    # Compute actual weights
    for item in selected_assets:
        item["weight_pct"] = round((item["total_cost"] / max(1.0, total_spent)) * 100.0, 1)

    # Compounding Calculator (Monthly SIP FV with optional Annual Step-Up)
    r_monthly = (expected_cagr / 100.0) / 12.0
    def sip_future_val(months, monthly_pmt):
        if r_monthly <= 0:
            return months * monthly_pmt
        return round(monthly_pmt * (((1.0 + r_monthly) ** months - 1.0) / r_monthly) * (1.0 + r_monthly), 0)

    def sip_step_up_val(years, initial_pmt, step_up):
        r_mo = (1.0 + expected_cagr / 100.0) ** (1.0 / 12.0) - 1.0
        corpus = 0.0
        total_inv = 0.0
        pmt = initial_pmt
        for yr in range(years):
            for m in range(12):
                corpus = (corpus + pmt) * (1.0 + r_mo)
                total_inv += pmt
            pmt *= (1.0 + step_up / 100.0)
        return round(corpus, 0), round(total_inv, 0)

    wealth_projections = {}
    for yrs in [5, 10, 15, 20]:
        key = f"{yrs}_years"
        flat_corp = sip_future_val(yrs * 12, monthly_wallet)
        flat_inv = monthly_wallet * yrs * 12
        if annual_step_up_pct > 0:
            step_corp, step_inv = sip_step_up_val(yrs, monthly_wallet, annual_step_up_pct)
            wealth_projections[key] = {
                "invested": step_inv,
                "projected": step_corp,
                "invested_flat": flat_inv,
                "projected_flat": flat_corp,
                "cagr": expected_cagr,
                "annual_step_up_pct": annual_step_up_pct
            }
        else:
            wealth_projections[key] = {
                "invested": flat_inv,
                "projected": flat_corp,
                "invested_flat": flat_inv,
                "projected_flat": flat_corp,
                "cagr": expected_cagr,
                "annual_step_up_pct": 0.0
            }

    # Tactical Dip-Buying Regime Assessment
    tactical_dip_alert = None
    if enable_dip_buying:
        nifty_rows = session.execute(text("""
            SELECT date, close FROM index_prices
            WHERE symbol = 'NIFTYBEES.NS'
            ORDER BY date DESC LIMIT 25
        """)).fetchall()
        if nifty_rows and len(nifty_rows) >= 5:
            curr_nifty = float(nifty_rows[0][1])
            high_20d = max(float(r[1]) for r in nifty_rows)
            drop_pct = (high_20d - curr_nifty) / high_20d * 100.0
            tactical_dip_alert = {
                "is_dip": drop_pct >= 4.0,
                "drop_pct": round(drop_pct, 1),
                "curr_nifty": curr_nifty,
                "high_20d": high_20d,
                "message": f"Benchmark is down -{drop_pct:.1f}% from its 20-day high (₹{high_20d:,.1f} → ₹{curr_nifty:,.1f}). " + 
                           ("⚡ Excellent tactical regime to deploy up to 70% dry powder into top winners at a discount!" if drop_pct >= 4.0 else "Normal market regime. Regular disciplined SIP deployment recommended.")
            }

    # Parabolic Multi-Bagger Milestone Scanner
    parabolic_skim_alerts = []
    if enable_parabolic_skim:
        try:
            wl_items = session.query(WatchlistItem).all()
            for w in wl_items:
                if w.target_buy_price and w.target_buy_price > 0:
                    latest_p = session.execute(text(f"SELECT close FROM daily_prices WHERE symbol = '{w.symbol}' ORDER BY date DESC LIMIT 1")).scalar()
                    if latest_p and float(latest_p) >= w.target_buy_price * 3.0:
                        gain = (float(latest_p) - w.target_buy_price) / w.target_buy_price * 100.0
                        parabolic_skim_alerts.append({
                            "symbol": w.symbol,
                            "buy_price": w.target_buy_price,
                            "current_price": float(latest_p),
                            "gain_pct": round(gain, 1),
                            "action": f"Trim 20% to bank risk-free capital (+{gain:.0f}% multi-bagger)"
                        })
        except Exception:
            pass

    return {
        "monthly_wallet": monthly_wallet,
        "strategy": strategy,
        "risk_profile": risk_profile,
        "exit_protocol": exit_protocol,
        "as_of_date": as_of_date,
        "total_spent": total_spent,
        "cash_buffer": cash_buffer,
        "expected_cagr_pct": expected_cagr,
        "n_assets": len(selected_assets),
        "assets": selected_assets,
        "wealth_projections": wealth_projections,
        "tactical_dip_alert": tactical_dip_alert,
        "parabolic_skim_alerts": parabolic_skim_alerts,
        "pyramid_winners": pyramid_winners,
        "max_position_cap_pct": max_position_cap_pct,
        "min_momentum_hurdle_pct": min_momentum_hurdle_pct,
        "enable_dip_buying": enable_dip_buying,
        "enable_parabolic_skim": enable_parabolic_skim,
        "annual_step_up_pct": annual_step_up_pct
    }


# ─── 2. Deploy SIP Basket Directly to Watchlist ───────────────────────────────
def deploy_sip_basket_to_watchlist(
    session: Session,
    basket: Dict,
    watchlist_name: Optional[str] = None,
    replace_existing: bool = True
) -> Dict:
    """
    1-Click adds or updates the monthly SIP basket into a dedicated Watchlist with
    exact share quantities, target prices, stop losses, and investment rationales.
    """
    if not watchlist_name:
        month_label = datetime.now().strftime("%b %Y")
        strategy_label = "Direct_Stocks" if basket.get("strategy") == "PURE_STOCKS" else "Multi_Asset"
        watchlist_name = f"Monthly SIP ({strategy_label}) - {month_label}"

    try:
        # Check if watchlist already exists
        wl = session.query(Watchlist).filter(Watchlist.name == watchlist_name).first()
        if not wl:
            wl = Watchlist(
                name=watchlist_name,
                description=f"Monthly SIP Wallet: ₹{basket.get('monthly_wallet', 20000):,.0f} | Strategy: {basket.get('strategy')} | Generated on {date.today()}"
            )
            session.add(wl)
            session.commit()
        elif replace_existing:
            # Clear old items if replacing
            session.query(WatchlistItem).filter(WatchlistItem.watchlist_id == wl.id).delete()
            session.commit()

        added_count = 0
        for item in basket.get("assets", []):
            sym = item["symbol"]
            # Check if stock exists in stocks table
            stock_exists = session.query(Stock).filter(Stock.symbol == sym).first()
            if not stock_exists and item.get("asset_class") == "Equity":
                continue # Skip if not in universe

            note_text = (
                f"🛒 SIP Qty: {item['shares_to_buy']} shares (₹{item['total_cost']:,.0f}) | "
                f"Weight: {item.get('weight_pct', 0)}% | {item.get('rationale', '')}"
            )

            w_item = WatchlistItem(
                watchlist_id=wl.id,
                symbol=sym,
                target_buy_price=item["current_price"],
                target_sell_price=item["target_price"],
                stop_loss=item["stop_loss"],
                notes=note_text
            )
            session.add(w_item)
            added_count += 1

        session.commit()
        return {
            "status": "SUCCESS",
            "watchlist_id": wl.id,
            "watchlist_name": wl.name,
            "added_count": added_count,
            "message": f"Successfully created/updated watchlist '{wl.name}' with {added_count} assets!"
        }
    except Exception as e:
        session.rollback()
        logger.error(f"Error deploying SIP basket to watchlist: {e}")
        return {"status": "ERROR", "message": str(e)}


# ─── 3. Intelligent Sell Reminder Scanner ─────────────────────────────────────
def evaluate_sell_reminders(
    session: Session,
    watchlist_id: Optional[int] = None
) -> List[Dict]:
    """
    Scans all tracked stocks in user watchlists (or a specific watchlist) to detect
    deteriorating conditions and generate urgent SELL reminders:
    1. 🛑 Hard Stop-Loss Breach (Price <= Stop Loss)
    2. ⚠️ Algorithmic Signal Deterioration (Signal turned SELL or Score < 45)
    3. 📉 Structural Trend Loss (Price below 200-day EMA)
    4. 🚨 52-Week Low Breakdown (Price within 0.75% of 52W Low)
    """
    # Build query for watchlist items
    if watchlist_id:
        items_query = session.query(WatchlistItem).filter(WatchlistItem.watchlist_id == watchlist_id).all()
    else:
        items_query = session.query(WatchlistItem).all()

    if not items_query:
        return []

    # Query latest prices, signals, and EMAs
    sell_reminders = []

    for item in items_query:
        sym = item.symbol
        wl_name = item.watchlist.name if item.watchlist else "Watchlist"

        # Latest price
        price_row = session.execute(text("""
            SELECT close, daily_return FROM daily_prices WHERE symbol = :s ORDER BY date DESC LIMIT 1
        """), {"s": sym}).first()
        if not price_row:
            continue

        current_price = float(price_row[0] or 0.0)
        daily_return = float(price_row[1] or 0.0)

        # Signals & Scores
        sig_row = session.execute(text("""
            SELECT sig.signal, sig.signal_strength, cs.composite_score
            FROM signals sig
            LEFT JOIN composite_scores cs ON sig.symbol = cs.symbol AND sig.date = cs.date
            WHERE sig.symbol = :s ORDER BY sig.date DESC LIMIT 1
        """), {"s": sym}).first()

        model_signal = sig_row[0] if sig_row and sig_row[0] else "WATCH"
        composite_score = float(sig_row[2] or 50.0) if sig_row else 50.0

        # Technical 200 EMA
        ti_row = session.execute(text("""
            SELECT ema_200 FROM technical_indicators WHERE symbol = :s ORDER BY date DESC LIMIT 1
        """), {"s": sym}).first()
        ema_200 = float(ti_row[0]) if ti_row and ti_row[0] else None

        # 52W Low
        stats_52w = session.execute(text("""
            SELECT MIN(low) FROM daily_prices WHERE symbol = :s AND date >= date((SELECT MAX(date) FROM daily_prices), '-365 days')
        """), {"s": sym}).scalar()
        low_52w = float(stats_52w) if stats_52w else None

        triggers = []
        severity = "NORMAL"

        # 1. Check Stop Loss Violation
        if item.stop_loss and current_price <= item.stop_loss:
            loss_pct = round((current_price - item.stop_loss) / item.stop_loss * 100.0, 2)
            triggers.append(f"🛑 Stop-Loss Breached: Price ₹{current_price:,.2f} dropped below Stop-Loss ₹{item.stop_loss:,.2f} ({loss_pct:+.1f}%)")
            severity = "CRITICAL"

        # 2. Check Model Signal Flip to SELL or severe score drop
        if model_signal == "SELL" or composite_score < 45.0:
            triggers.append(f"⚠️ Model Turn Bearish: Algorithm flipped to SELL (Composite Score: {composite_score:.1f}/100)")
            if severity != "CRITICAL":
                severity = "CRITICAL"

        # 3. Check 200 EMA breakdown
        if ema_200 and current_price < ema_200:
            ema_gap_pct = round((current_price - ema_200) / ema_200 * 100.0, 2)
            triggers.append(f"📉 Trend Lost: Traded below 200-day EMA (₹{ema_200:,.2f}, Gap: {ema_gap_pct:+.1f}%)")
            if severity == "NORMAL":
                severity = "WARNING"

        # 4. Check 52W Low Breakdown
        if low_52w and current_price <= (low_52w * 1.015):
            triggers.append(f"🚨 52-Week Breakdown: Trading within 1.5% of 52-Week Low (₹{low_52w:,.2f})")
            if severity == "NORMAL":
                severity = "WARNING"

        # 5. Check Parabolic Multi-Bagger Milestone (Profit Skim Alert)
        if item.target_buy_price and item.target_buy_price > 0 and current_price >= (item.target_buy_price * 3.0):
            gain_pct = round((current_price - item.target_buy_price) / item.target_buy_price * 100.0, 1)
            triggers.append(f"💰 Parabolic Multi-Bagger (+{gain_pct:.0f}%): Position is up {current_price/item.target_buy_price:.1f}x. Consider locking 20% profit.")
            if severity == "NORMAL":
                severity = "PROFIT_TAKE"

        if triggers:
            # Action recommendation
            if severity == "CRITICAL":
                if item.stop_loss and current_price <= item.stop_loss:
                    rec_action = "EXIT IMMEDIATELY: Stop-loss violated. Preserve capital."
                else:
                    rec_action = "TIGHTEN STOP / TRIM: Model turned SELL. Cut weak exposure."
            elif severity == "PROFIT_TAKE":
                rec_action = "TRIM 20% PROFIT: Multi-bagger milestone reached. Bank risk-free capital & let remaining 80% run."
            else:
                rec_action = "MONITOR CLOSELY: Underlying technical support broken."

            sell_reminders.append({
                "symbol": sym,
                "watchlist_name": wl_name,
                "current_price": current_price,
                "daily_return": daily_return,
                "stop_loss": item.stop_loss,
                "target_price": item.target_sell_price,
                "ema_200": ema_200,
                "model_signal": model_signal,
                "composite_score": composite_score,
                "severity": severity,
                "triggers": triggers,
                "primary_trigger": triggers[0],
                "recommended_action": rec_action,
                "user_notes": item.notes or ""
            })

    # Sort critical first, then by composite score ascending (worst first)
    sell_reminders.sort(key=lambda x: (0 if x["severity"] == "CRITICAL" else 1, x["composite_score"]))
    return sell_reminders


def scan_tactical_dip_boosters(session: Session, monthly_wallet: float = 20000.0) -> List[Dict]:
    """
    Scans active direct stock compounders and curated mutual funds for high-probability
    technical dip-buying demand zones (pulling back to 50-EMA support with bullish structure).
    Recommends tactical top-up tranche amounts to lower the long-term rupee-cost average.
    """
    dip_alerts = []

    # 1. Stocks dipping into 50-EMA with high composite score
    sql_stock_dips = """
        SELECT sig.symbol, s.name, s.sector, sig.current_price, t.ema_50, t.ema_200, t.rsi_14, cs.composite_score
        FROM signals sig
        JOIN stocks s ON sig.symbol = s.symbol
        JOIN technical_indicators t ON sig.symbol = t.symbol AND sig.date = t.date
        JOIN composite_scores cs ON sig.symbol = cs.symbol AND sig.date = cs.date
        WHERE sig.date = (SELECT MAX(date) FROM signals)
        AND s.is_active = 1
        AND sig.current_price >= t.ema_200
        AND t.ema_50 IS NOT NULL
        AND abs(sig.current_price - t.ema_50) / t.ema_50 <= 0.035
        AND cs.composite_score >= 58.0
        ORDER BY cs.composite_score DESC
        LIMIT 6
    """
    try:
        rows = session.execute(text(sql_stock_dips)).fetchall()
        for r in rows:
            sym, name, sec, price, ema50, ema200, rsi, score = r
            tranche_amt = round(min(monthly_wallet * 0.25, max(1500.0, price * 2)), 0)
            shares = max(1, int(tranche_amt / price))
            dip_alerts.append({
                "symbol": sym,
                "name": name,
                "asset_type": "Direct Equity",
                "category": sec,
                "current_price": round(price, 2),
                "support_level": round(ema50, 2),
                "support_type": "50-Day EMA Support",
                "rsi_14": round(rsi or 45.0, 1),
                "composite_score": round(score, 1),
                "recommended_topup_inr": round(shares * price, 2),
                "shares_to_buy": shares,
                "advisory": f"Healthy pullback into 50-EMA demand zone (₹{ema50:,.2f}). Deploy tactical tranche of {shares} shares."
            })
    except Exception as e:
        logger.warning(f"Error scanning stock dip boosters: {e}")

    # 2. Mutual funds with TACTICAL_BUY_DIP signals
    try:
        mf_rows = session.execute(text("""
            SELECT m.scheme_code, m.scheme_name, m.sub_category, s.nav, s.ema_50, s.rsi_14, s.strength_score, s.signal_rationale
            FROM mutual_fund_signals s
            JOIN mutual_funds m ON s.scheme_code = m.scheme_code
            WHERE s.date = (SELECT MAX(date) FROM mutual_fund_signals)
            AND s.signal = 'TACTICAL_BUY_DIP'
            ORDER BY s.strength_score DESC
            LIMIT 4
        """)).fetchall()
        for mf in mf_rows:
            sc, name, subcat, nav, ema50, rsi, score, rat = mf
            topup = round(monthly_wallet * 0.20, 0)
            dip_alerts.append({
                "symbol": f"MF_{sc}",
                "name": name,
                "asset_type": "Mutual Fund",
                "category": subcat,
                "current_price": round(nav, 2),
                "support_level": round(ema50 or nav, 2),
                "support_type": "50-Day EMA Support",
                "rsi_14": round(rsi or 40.0, 1),
                "composite_score": round(score or 80.0, 1),
                "recommended_topup_inr": topup,
                "shares_to_buy": round(topup / nav, 2),
                "advisory": rat
            })
    except Exception as e:
        logger.warning(f"Error scanning MF dip boosters: {e}")

    return dip_alerts

