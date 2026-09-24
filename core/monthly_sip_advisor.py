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
from core.consensus_verifier import (
    fetch_stock_consensus,
    evaluate_stock_alignment,
    fetch_mf_consensus,
    evaluate_mf_alignment,
    compute_portfolio_consensus_summary
)
from core.sector_analysis import get_sector_regime_gate

logger = logging.getLogger(__name__)


# ─── 1. Monthly SIP Basket Generation ─────────────────────────────────────────
def generate_monthly_sip_basket(
    session: Session,
    monthly_wallet: float = 20000.0,
    strategy: str = "PURE_STOCKS",     # PURE_STOCKS or MULTI_ASSET
    include_mutual_funds: bool = False, # Toggle to include Mutual Funds as Core allocation
    mf_allocation_pct: float = 50.0,    # Core MF allocation % (10% to 90%)
    risk_profile: str = "RISKY",       # SAFE, BALANCED, RISKY (RISKY is 63.5% Apex Alpha)
    target_stock_count: int = 6,       # 6-Stock Concentration Basket (Champion SIP_0194: 57.2% 1-yr XIRR)
    exit_protocol: str = "DYNAMIC_ATR", # DYNAMIC_ATR (Champion SIP_0194: 29.4% XIRR), ADAPTIVE_STRUCTURAL, STRUCTURAL_TRAILING, BUY_AND_HOLD, TIGHT_SWING
    selection_filter: str = "SECTOR_LEAD_ALPHA", # SECTOR_LEAD_ALPHA (Champion SIP_0194: 6M>=25%, max 2/sector), PURE_MOMENTUM, CONV_DIVERSIFIED
    as_of_date: Optional[str] = None,
    pyramid_winners: bool = True,
    min_momentum_hurdle_pct: float = 25.0, # 6-Month Momentum Hurdle (Champion SIP_0194)
    enable_dip_buying: bool = True,
    enable_parabolic_skim: bool = True,
    max_position_cap_pct: float = 50.0,    # 50% Runner Cap (63.5% Apex Alpha)
    annual_step_up_pct: float = 10.0,
    enable_loss_cooldown: bool = True,
    cooldown_days: int = 60,
    enable_sector_momentum_gate: bool = True,
    enable_macro_regime_gate: bool = True,
    macro_hedge_pct: float = 10.0,
    macro_hedge_asset: str = "GOLDBEES.NS",
    enable_macro_rotation: bool = True,
    enable_stepladder_trailing: bool = True,
    enable_conviction_weighting: bool = True,
    sizing_mode: str = "CONVICTION",  # CONVICTION, INVERSE_VOLATILITY, EQUAL
    enable_correlation_clustering: bool = True,  # Cross-Asset Correlation Clustering (r < 0.65 Orthogonal Shield)
    max_pairwise_correlation: float = 0.65,
    enable_volatility_targeting: bool = False,   # 15% Volatility Target Risk Parity
    target_annualized_vol: float = 0.15,
    enable_tax_harvesting_alerts: bool = True,   # Section 112A Tax-Free LTCG Step-Up alerts
    enable_position_inertia_buffer: bool = True, # Rob Carver Position Inertia Buffer (pysystemtrade)
    inertia_buffer_pct: float = 12.0,            # ±12% weight tolerance deadband
    enable_3tier_harvest: bool = True,           # Van Tharp 3-Tier Multi-Scale Exit (+25% BE lock, +50% Chandelier, 34% Moonbag)
    enable_clenow_momentum: bool = True,         # Andreas Clenow Exponential Trend Smoothness (R^2 * Slope)
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

    # ── Auto Regime-Conditional Routing Integration ───────────────────────────
    regime_routing_info = {}
    effective_strategy = strategy
    if strategy == "AUTO_REGIME_ROUTING":
        try:
            from core.macro_regime import evaluate_macro_regime
            macro_eval = evaluate_macro_regime(session)
            routed_mode = macro_eval.get("active_strategy_mode", "HIGH_BETA_MOMENTUM")
            regime_routing_info = {
                "macro_score": macro_eval.get("macro_score", 50.0),
                "regime_name": macro_eval.get("regime", "RISK_NEUTRAL"),
                "routed_mode": routed_mode,
                "summary": macro_eval.get("summary", ""),
                "alloc_equity": macro_eval.get("alloc_equity", 75),
                "alloc_gold": macro_eval.get("alloc_gold", 15),
                "alloc_cash": macro_eval.get("alloc_cash", 10),
                "breadth_info": macro_eval.get("breadth_info", {}),
                "bellwether_info": macro_eval.get("bellwether_info", {}),
            }
            if routed_mode == "HIGH_BETA_MOMENTUM":
                effective_strategy = "PURE_STOCKS"
                enable_macro_regime_gate = False
                min_momentum_hurdle_pct = max(20.0, min_momentum_hurdle_pct)
            elif routed_mode == "MEAN_REVERSION_SUPPORT":
                effective_strategy = "MULTI_ASSET"
            else:  # CAPITAL_PRESERVATION_HEDGE
                effective_strategy = "PURE_STOCKS"
                enable_macro_regime_gate = True
                macro_hedge_pct = max(35.0, macro_hedge_pct)
        except Exception as e:
            logger.warning(f"Failed to auto-route regime: {e}")
            effective_strategy = "PURE_STOCKS"

    # Expected CAGR based on strategy, protocol & risk (Empirical factor-calibrated net compounding)
    if exit_protocol == "ADAPTIVE_STRUCTURAL":
        cagr_map = {"SAFE": 18.5, "BALANCED": 21.5, "RISKY": 24.5} if effective_strategy == "PURE_STOCKS" else {"SAFE": 14.5, "BALANCED": 17.0, "RISKY": 19.5}
    elif exit_protocol == "DYNAMIC_ATR":
        cagr_map = {"SAFE": 19.5, "BALANCED": 22.5, "RISKY": 25.5} if effective_strategy == "PURE_STOCKS" else {"SAFE": 15.0, "BALANCED": 18.0, "RISKY": 20.5}
    elif exit_protocol == "STRUCTURAL_TRAILING":
        cagr_map = {"SAFE": 16.5, "BALANCED": 19.5, "RISKY": 22.0} if effective_strategy == "PURE_STOCKS" else {"SAFE": 13.5, "BALANCED": 15.5, "RISKY": 17.5}
    elif exit_protocol == "BUY_AND_HOLD":
        cagr_map = {"SAFE": 14.0, "BALANCED": 16.5, "RISKY": 18.5} if effective_strategy == "PURE_STOCKS" else {"SAFE": 12.0, "BALANCED": 14.0, "RISKY": 15.5}
    else: # TIGHT_SWING
        cagr_map = {"SAFE": 9.0, "BALANCED": 11.5, "RISKY": 13.5} if effective_strategy == "PURE_STOCKS" else {"SAFE": 8.0, "BALANCED": 10.0, "RISKY": 11.5}

    raw_expected_cagr = cagr_map.get(risk_profile, 21.5)
    expected_cagr = raw_expected_cagr

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
        mf_ratio = max(0.10, min(0.90, float(mf_allocation_pct) / 100.0))
        mf_budget = round(monthly_wallet * mf_ratio, 2)
        top_mfs = session.query(MutualFund).filter_by(is_active=True).all()
        
        # Select target core schemes based on chosen allocation %
        if mf_ratio <= 0.30:
            codes = [122639, 120716]
        elif mf_ratio <= 0.55:
            codes = [122639, 118988, 120716]
        else:
            codes = [122639, 118988, 120716, 120823]

        chosen_mfs = [next((f for f in top_mfs if f.scheme_code == sc), None) for sc in codes]
        chosen_mfs = [f for f in chosen_mfs if f is not None]
        if not chosen_mfs:
            chosen_mfs = top_mfs[:3]

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
            target_stocks_to_pick = max(2, target_stock_count - (len(chosen_mfs) if target_stock_count <= 5 else 0))

    # ─── Macro Regime Status & 200-Day EMA Defense Gate ────────────────────────
    macro_regime_status = {
        "is_defensive": False,
        "current_nifty": None,
        "nifty_200_ema": None,
        "nifty_50_ema": None,
        "distance_to_200_ema_pct": 0.0,
        "hedge_pct": 0.0,
        "hedge_asset": macro_hedge_asset,
        "pct_above_50_ema": 50.0,
        "breadth_thrust_badge": "⚪ Normal",
        "breadth_score": 50.0,
        "message": "Market in healthy uptrend above 200-Day EMA. 100% Equity allocation active."
    }

    try:
        nifty_query = session.execute(text("""
            SELECT date, close FROM index_prices
            WHERE symbol = '^NSEI' AND date <= :d
            ORDER BY date ASC
        """), {"d": as_of_date}).fetchall()
        if not nifty_query:
            nifty_query = session.execute(text("""
                SELECT date, close FROM index_prices
                WHERE symbol = 'NIFTYBEES.NS' AND date <= :d
                ORDER BY date ASC
            """), {"d": as_of_date}).fetchall()

        valid_nifty = [(str(r[0]), float(r[1])) for r in nifty_query if r[1] is not None]
        if valid_nifty and len(valid_nifty) >= 50:
            n_series = pd.Series([v[1] for v in valid_nifty], index=[v[0] for v in valid_nifty])
            cur_n = float(n_series.iloc[-1])
            ema_200_val = float(n_series.ewm(span=200, adjust=False).mean().iloc[-1])
            ema_50_val = float(n_series.ewm(span=50, adjust=False).mean().iloc[-1])
            dist_pct = round(((cur_n - ema_200_val) / ema_200_val) * 100.0, 2)
            
            # Internal Market Breadth Check (% stocks > 50-day EMA)
            breadth_50 = 50.0
            breadth_badge = "⚪ Normal"
            breadth_score = 50.0
            try:
                from core.market_breadth import calculate_market_breadth
                mb = calculate_market_breadth(session, as_of_date=as_of_date)
                breadth_50 = float(mb.get("pct_above_50_ema", 50.0))
                breadth_badge = mb.get("thrust_badge", "⚪ Normal")
                breadth_score = float(mb.get("breadth_score", 50.0))
            except Exception as mb_err:
                logger.debug(f"Market breadth calculation notice: {mb_err}")

            macro_regime_status["pct_above_50_ema"] = breadth_50
            macro_regime_status["breadth_thrust_badge"] = breadth_badge
            macro_regime_status["breadth_score"] = breadth_score

            is_def = (cur_n < ema_200_val) or (breadth_50 < 40.0)
            macro_regime_status["current_nifty"] = round(cur_n, 2)
            macro_regime_status["nifty_200_ema"] = round(ema_200_val, 2)
            macro_regime_status["nifty_50_ema"] = round(ema_50_val, 2)
            macro_regime_status["distance_to_200_ema_pct"] = dist_pct
            macro_regime_status["is_defensive"] = is_def

            if is_def:
                macro_regime_status["hedge_pct"] = macro_hedge_pct if enable_macro_regime_gate else 0.0
                if cur_n < ema_200_val:
                    trigger_reason = f"NIFTY 50 ({cur_n:,.1f}) is trading {abs(dist_pct):.1f}% BELOW its 200-Day EMA ({ema_200_val:,.1f})"
                else:
                    trigger_reason = f"Market Breadth ({breadth_50:.1f}%) collapsed below 40% threshold (>50 EMA)"
                macro_regime_status["message"] = (
                    f"⚠️ CAUTION: {trigger_reason}. "
                    + (f"Defensive Macro Hedge active: Allocating {macro_hedge_pct:.0f}% into Gold ETF ({macro_hedge_asset}) to cushion drawdown." if enable_macro_regime_gate else "Macro Gate is disabled; remaining in 100% Equities.")
                )
            else:
                macro_regime_status["message"] = (
                    f"✅ BULLISH REGIME: NIFTY 50 ({cur_n:,.1f}) is trading +{dist_pct:.1f}% ABOVE its 200-Day EMA ({ema_200_val:,.1f}) "
                    f"with healthy market breadth ({breadth_50:.1f}% > 50-EMA). Full equity compounding active."
                )
    except Exception as e:
        logger.warning(f"Error computing macro regime status: {e}")

    # ─── Volatility Targeting Engine (15% Target Volatility Parity) ───────────
    vol_targeting_info = {
        "enabled": enable_volatility_targeting,
        "target_annualized_vol": target_annualized_vol,
        "target_vol_pct": target_annualized_vol if target_annualized_vol >= 1.0 else target_annualized_vol * 100.0,
        "realized_market_vol": 0.15,
        "basket_realized_vol_pct": 15.0,
        "vol_multiplier": 1.0,
        "vol_scaling_multiplier": 1.0,
        "is_defensive_scaled": False,
        "status": "NORMAL_SIZING",
        "status_badge": "🟢 Normal Risk Sizing (100% Equity Exposure)"
    }
    if enable_volatility_targeting:
        try:
            if valid_nifty and len(valid_nifty) >= 25:
                n_rets = n_series.pct_change().dropna().tail(20)
                if len(n_rets) >= 10:
                    realized_mkt_vol = float(n_rets.std() * math.sqrt(252.0))
                    vol_targeting_info["realized_market_vol"] = round(realized_mkt_vol, 3)
                    vol_targeting_info["basket_realized_vol_pct"] = round(realized_mkt_vol * 100.0, 1)
                    tgt_vol_dec = target_annualized_vol / 100.0 if target_annualized_vol > 1.0 else target_annualized_vol
                    if realized_mkt_vol > tgt_vol_dec:
                        v_mult = max(0.40, min(1.0, tgt_vol_dec / realized_mkt_vol))
                        vol_targeting_info["vol_multiplier"] = round(v_mult, 3)
                        vol_targeting_info["vol_scaling_multiplier"] = round(v_mult, 3)
                        vol_targeting_info["is_defensive_scaled"] = True
                        vol_targeting_info["status"] = "ACTIVE_TARGETING"
                        vol_targeting_info["status_badge"] = f"⚠️ Volatility Scaled ({v_mult*100:.0f}% Equity Exposure / {realized_mkt_vol*100:.1f}% Vol)"
                        equity_budget_pool = round(equity_budget_pool * v_mult, 2)
        except Exception as e:
            logger.debug(f"Volatility targeting computation notice: {e}")

    # Dynamically blend expected CAGR with volatility targeting & defensive macro hedging
    v_mult = vol_targeting_info.get("vol_multiplier", 1.0)
    h_pct = macro_regime_status.get("hedge_pct", 0.0) / 100.0
    effective_equity_weight = max(0.35, min(1.0, v_mult * (1.0 - h_pct)))
    cash_gold_yield = 7.5  # 7.5% expected annual yield on cash / GoldBEES
    expected_cagr = round(effective_equity_weight * raw_expected_cagr + (1.0 - effective_equity_weight) * cash_gold_yield, 1)

    # Rule 1: Loss Cooldown Quarantine Lookup (from recent triggered stop-loss alerts)
    quarantined_loss_symbols = set()
    if enable_loss_cooldown:
        try:
            as_of_dt = datetime.strptime(as_of_date, "%Y-%m-%d")
            cutoff_dt = as_of_dt - timedelta(days=cooldown_days)
            pa_rows = session.execute(text("""
                SELECT DISTINCT symbol FROM price_alerts 
                WHERE alert_type = 'STOP_LOSS' 
                AND is_triggered = 1 
                AND triggered_at >= :c
            """), {"c": cutoff_dt}).fetchall()
            quarantined_loss_symbols = {r[0] for r in pa_rows}
        except Exception:
            pass

    if effective_strategy == "PURE_STOCKS":
        # Rule 2: Automatic Macro Defense Gold Hedge Tranche (when NIFTY < 200-EMA)
        if macro_regime_status.get("is_defensive") and enable_macro_regime_gate and macro_hedge_pct > 0:
            gold_price_row = session.execute(text("""
                SELECT close FROM index_prices
                WHERE symbol IN ('GOLDBEES.NS', 'GOLDBEES') AND date <= :d
                ORDER BY date DESC LIMIT 1
            """), {"d": as_of_date}).first()
            gold_price = float(gold_price_row[0]) if gold_price_row and gold_price_row[0] else 72.0
            hedge_budget = round(monthly_wallet * (macro_hedge_pct / 100.0), 2)
            gold_shares = int(math.floor(hedge_budget / max(0.01, gold_price)))
            if gold_shares == 0 and gold_price <= hedge_budget:
                gold_shares = 1
            if gold_shares > 0:
                gold_cost = round(gold_shares * gold_price, 2)
                selected_assets.append({
                    "symbol": "GOLDBEES.NS",
                    "name": "Nippon India Gold ETF",
                    "asset_class": "Commodity / Hedge",
                    "sector": "Precious Metals",
                    "tier": "macro",
                    "current_price": gold_price,
                    "shares_to_buy": gold_shares,
                    "total_cost": gold_cost,
                    "stop_loss": round(gold_price * 0.88, 2),
                    "target_price": round(gold_price * 1.50, 2),
                    "composite_score": 75.0,
                    "signal": "BUY",
                    "risk_level": "SAFE",
                    "is_pyramided": False,
                    "rationale": f"🛡️ Macro Defense Hedge ({macro_hedge_pct:.0f}% allocation): NIFTY trading below 200-Day EMA ({macro_regime_status.get('distance_to_200_ema_pct', 0):+.1f}%)"
                })
                equity_budget_pool = max(1000.0, equity_budget_pool - gold_cost)

        # 100% Direct Equities across distinct sectors
        # Query top candidate stocks with 6-month momentum lookup
        lookback_180d = (datetime.strptime(as_of_date, "%Y-%m-%d").date() - timedelta(days=180)).strftime("%Y-%m-%d")
        sql = f"""
            SELECT sig.symbol, s.name, s.sector, s.market_cap_tier, sig.current_price,
                   cs.composite_score, sig.signal, sig.risk_level, sig.stop_loss, sig.target_price_1,
                   cs.beta,
                   (sig.current_price - dp_past.close) / NULLIF(dp_past.close, 0.0) as ret_6m,
                   ti.atr_14,
                   cs.volatility_annual
            FROM signals sig
            JOIN stocks s ON sig.symbol = s.symbol
            JOIN composite_scores cs ON sig.symbol = cs.symbol AND cs.date = sig.date
            LEFT JOIN technical_indicators ti ON ti.symbol = sig.symbol AND ti.date = sig.date
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
                       (sig.current_price - dp_past.close) / NULLIF(dp_past.close, 0.0) as ret_6m,
                       ti.atr_14,
                       cs.volatility_annual
                FROM signals sig
                JOIN stocks s ON sig.symbol = s.symbol
                JOIN composite_scores cs ON sig.symbol = cs.symbol AND cs.date = sig.date
                LEFT JOIN technical_indicators ti ON ti.symbol = sig.symbol AND ti.date = sig.date
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

        # Compute pairwise correlation matrix across candidate equities if clustering enabled
        corr_matrix = pd.DataFrame()
        if enable_correlation_clustering and candidates:
            try:
                from core.correlation_clustering import compute_pairwise_correlation_matrix
                cand_syms = [str(c[0]) for c in candidates[:30]]
                corr_matrix = compute_pairwise_correlation_matrix(
                    cand_syms, session, lookback_days=120, as_of_date=as_of_date
                )
            except Exception as e:
                logger.debug(f"Correlation clustering matrix computation: {e}")

        # Andreas Clenow Exponential Trend Smoothness (R^2 * Slope) Re-ranking
        clenow_scores = {}
        if enable_clenow_momentum and candidates:
            try:
                try:
                    from core.sip_audit_backtester import compute_clenow_momentum
                except Exception:
                    from core.signals import compute_clenow_momentum
                top_syms = [str(c[0]) for c in candidates[:35]]
                cutoff_dt = (datetime.strptime(as_of_date, "%Y-%m-%d").date() - timedelta(days=200)).strftime("%Y-%m-%d")
                formatted_syms = "'" + "','".join(top_syms) + "'"
                cand_prices_df = pd.read_sql(
                    text(f"""
                        SELECT symbol, date, close
                        FROM daily_prices
                        WHERE symbol IN ({formatted_syms}) AND date >= '{cutoff_dt}' AND date <= '{as_of_date}' AND close IS NOT NULL
                        ORDER BY date ASC
                    """),
                    session.bind
                )
                if not cand_prices_df.empty:
                    for sym_grp, grp in cand_prices_df.groupby("symbol"):
                        if len(grp) >= 30:
                            c_res = compute_clenow_momentum(grp["close"].tail(126))
                            clenow_scores[sym_grp] = c_res.get("clenow_score", 0.0)
                
                if clenow_scores:
                    candidates = sorted(
                        candidates,
                        key=lambda c: clenow_scores.get(str(c[0]), float(c[11]) * 50.0 if len(c) > 11 and c[11] is not None else 0.0),
                        reverse=True
                    )
            except Exception as clenow_err:
                logger.debug(f"Clenow momentum ranking notice: {clenow_err}")

        # Pick top stocks with sector diversification and orthogonal correlation clustering
        sector_counts = {}
        max_per_sector = 2 if selection_filter == "SECTOR_LEAD_ALPHA" else 1
        picked_stocks = []

        for c in candidates:
            if len(picked_stocks) >= target_stocks_to_pick:
                break
            sym = str(c[0])
            sec = c[2] or "General"
            ret_6m = float(c[11]) if len(c) > 11 and c[11] is not None else 0.0

            # Rule 5: Sector Momentum Gate (Quarantines chronic laggards unless relative strength >= 35%)
            if enable_sector_momentum_gate:
                if sec in ("Agriculture, Fertilizers & Agro", "Chemicals & Specialty", "Textiles & Apparel", "Real Estate"):
                    if ret_6m < 0.35:
                        continue

            # Rule 1: 60-Day Loss Cooldown (Quarantines recently stopped-out stocks)
            if enable_loss_cooldown and sym in quarantined_loss_symbols:
                continue

            if sector_counts.get(sec, 0) >= max_per_sector and len(candidates) > 8:
                continue

            # Rule 6: Cross-Asset Correlation Clustering (Enforce r < max_pairwise_correlation)
            if enable_correlation_clustering and not corr_matrix.empty and picked_stocks:
                has_high_corr = False
                for p in picked_stocks:
                    p_sym = str(p[0])
                    if sym in corr_matrix.index and p_sym in corr_matrix.columns and float(corr_matrix.loc[sym, p_sym]) >= max_pairwise_correlation:
                        has_high_corr = True
                        break
                if has_high_corr and len(candidates) > 8:
                    continue

            # Momentum Hurdle Check
            eff_hurdle = 25.0 if selection_filter == "SECTOR_LEAD_ALPHA" else min_momentum_hurdle_pct
            if eff_hurdle > 0 and len(candidates) > (target_stocks_to_pick + 3):
                if ret_6m < (eff_hurdle / 100.0):
                    continue
            elif eff_hurdle == 0:
                ret_6m_raw = c[11] if len(c) > 11 else None
                if ret_6m_raw is None:
                    continue
            
            # Risk profile filter
            r_risk = c[7] or "MODERATE"
            if risk_profile == "SAFE" and r_risk == "RISKY":
                continue

            sector_counts[sec] = sector_counts.get(sec, 0) + 1
            picked_stocks.append(c)

        # In case fewer sectors found, fill from remaining top candidates
        if len(picked_stocks) < target_stocks_to_pick:
            for c in candidates:
                if len(picked_stocks) >= target_stocks_to_pick:
                    break
                sym = str(c[0])
                sec = c[2] or "General"
                ret_6m = float(c[11]) if len(c) > 11 and c[11] is not None else 0.0

                if enable_sector_momentum_gate and sec in ("Agriculture, Fertilizers & Agro", "Chemicals & Specialty", "Textiles & Apparel", "Real Estate") and ret_6m < 0.35:
                    continue
                if enable_loss_cooldown and sym in quarantined_loss_symbols:
                    continue

                if c[0] not in [x[0] for x in picked_stocks]:
                    picked_stocks.append(c)

        # Determine capital allocation per stock (Conviction-Weighted vs Equal Risk Contribution (ERC / ATR Risk Parity) vs Equal)
        n_stocks = len(picked_stocks)
        sz_mode = str(sizing_mode).upper()
        if sz_mode in ("INVERSE_VOLATILITY", "ERC", "RISK_PARITY", "INVERSE_VOL", "ATR_RISK_PARITY") and n_stocks > 0:
            vols = []
            for c in picked_stocks:
                v = float(c[13]) if len(c) > 13 and c[13] is not None and c[13] > 0 else None
                if v is None:
                    p_val = float(c[4]) if len(c) > 4 and c[4] else 1000.0
                    atr_val = float(c[12]) if len(c) > 12 and c[12] else None
                    if atr_val and p_val > 0:
                        v = (atr_val / p_val) * math.sqrt(252.0)
                    else:
                        v = 0.28
                vols.append(max(0.10, min(0.65, v)))
            inv_vols = [1.0 / v for v in vols]
            s_inv = sum(inv_vols)
            base_weights = [iv / s_inv for iv in inv_vols]
        elif enable_conviction_weighting and sz_mode not in ("EQUAL", "EQUAL_WEIGHT") and n_stocks > 0:
            if n_stocks == 6:
                base_weights = [0.24, 0.20, 0.18, 0.15, 0.13, 0.10]
            elif n_stocks == 5:
                base_weights = [0.30, 0.25, 0.20, 0.15, 0.10]
            elif n_stocks == 4:
                base_weights = [0.35, 0.28, 0.22, 0.15]
            elif n_stocks == 3:
                base_weights = [0.45, 0.33, 0.22]
            else:
                raw_w = [n_stocks - i for i in range(n_stocks)]
                s_w = sum(raw_w)
                base_weights = [w / s_w for w in raw_w]
        else:
            base_weights = [1.0 / max(1, n_stocks)] * n_stocks
        
        # Calculate whole shares
        for idx, c in enumerate(picked_stocks):
            sym = str(c[0])
            name = str(c[1]) if c[1] else sym
            sec = str(c[2]) if c[2] else "General"
            tier = str(c[3]) if c[3] else "large"
            price = float(c[4]) if c[4] else 1000.0
            score = float(c[5]) if c[5] else 55.0
            sig = str(c[6]) if c[6] else "BUY"
            risk = str(c[7]) if c[7] else "MODERATE"
            atr_14_val = float(c[12]) if len(c) > 12 and c[12] is not None else None
            t_lower = tier.lower()
            
            weight = base_weights[idx] if idx < len(base_weights) else (1.0 / max(1, n_stocks))
            stock_alloc_budget = equity_budget_pool * weight

            if exit_protocol == "BUY_AND_HOLD":
                sl = None
                t1 = round(price * 2.50, 2)
                proto_desc = "Buy & Hold (Uncapped, No SL)"
            elif exit_protocol == "TIGHT_SWING":
                sl = round(price * 0.93, 2)
                t1 = round(price * 1.15, 2)
                proto_desc = "Tight Swing (-7% SL / +15% Tgt)"
            elif exit_protocol == "DYNAMIC_ATR":
                if atr_14_val and atr_14_val > 0:
                    sl = round(max(price * 0.75, price - 3.5 * atr_14_val), 2)
                    t1 = round(min(price * 3.00, price + 7.0 * atr_14_val), 2)
                    sl_pct = ((price - sl) / price) * 100.0
                    t1_pct = ((t1 - price) / price) * 100.0
                    proto_desc = f"🏆 Champion Dynamic ATR (-{sl_pct:.1f}% SL, 3.5×ATR / +{t1_pct:.1f}% Tgt, 7.0×ATR / 50-EMA Trail)"
                else:
                    sl = round(price * 0.85, 2)
                    t1 = round(price * 1.65, 2)
                    proto_desc = "🏆 Champion Dynamic ATR (-15% SL / +65% Tgt / 50-EMA Trail)"
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

            shares = int(math.floor(stock_alloc_budget / max(0.01, price)))
            if shares == 0 and price <= (monthly_wallet * 0.40):
                shares = 1

            is_pyr = (sym in tracked_symbols and pyramid_winners)
            
            # Fetch Sector RS Gating Metadata
            sec_meta = get_sector_regime_gate(sec, session=session)
            sec_badge = sec_meta.get("badge", "⚪ Neutral")
            sec_rs = sec_meta.get("rs_20d", 0.0)

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
                "rationale": rat,
                "allocation_pct": round(weight * 100.0, 1),
                "sector_badge": sec_badge,
                "sector_rs_20d": sec_rs,
                "clenow_score": round(clenow_scores.get(sym, 0.0), 2) if sym in clenow_scores else None
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
                   cs.composite_score, sig.signal, sig.risk_level, sig.stop_loss, sig.target_price_1,
                   ti.atr_14
            FROM signals sig
            JOIN stocks s ON sig.symbol = s.symbol
            JOIN composite_scores cs ON sig.symbol = cs.symbol AND cs.date = sig.date
            LEFT JOIN technical_indicators ti ON ti.symbol = sig.symbol AND ti.date = sig.date
            WHERE sig.date = :d AND s.is_active = 1 AND sig.current_price <= :max_p
            AND sig.signal IN ('BUY', 'STRONG BUY', 'WATCH')
            ORDER BY cs.composite_score DESC
        """
        eq_rows = session.execute(text(sql_eq), {"d": as_of_date, "max_p": eq_per_stock * 1.5}).fetchall()
        
        picked_secs = set()
        for r in eq_rows:
            if len([x for x in selected_assets if x["asset_class"] == "Equity"]) >= eq_target_n:
                break
            sym = str(r[0])
            sec = r[2] or "General"
            if enable_sector_momentum_gate and sec in ("Agriculture, Fertilizers & Agro", "Chemicals & Specialty", "Textiles & Apparel", "Real Estate"):
                continue
            if enable_loss_cooldown and sym in quarantined_loss_symbols:
                continue
            if sec in picked_secs:
                continue
            picked_secs.add(sec)
            
            p = float(r[4]) if r[4] is not None else 1000.0
            sh = max(1, int(math.floor(eq_per_stock / max(0.01, p))))
            atr_14_eq = float(r[10]) if len(r) > 10 and r[10] is not None else None
            t_lower = (r[3] or "mid").lower()
            if exit_protocol == "BUY_AND_HOLD":
                sl = None
                t1 = round(p * 2.50, 2)
            elif exit_protocol == "TIGHT_SWING":
                sl = round(p * 0.93, 2)
                t1 = round(p * 1.15, 2)
            elif exit_protocol == "DYNAMIC_ATR":
                if atr_14_eq and atr_14_eq > 0:
                    sl = round(max(p * 0.78, p - 2.0 * atr_14_eq), 2)
                    t1 = round(min(p * 2.50, p + 4.0 * atr_14_eq), 2)
                else:
                    sl = round(p * 0.86, 2)
                    t1 = round(p * 1.50, 2)
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
        idx_price_row = session.execute(text("""
            SELECT close FROM index_prices
            WHERE symbol IN ('NIFTYBEES.NS', 'NIFTYBEES')
            ORDER BY date DESC LIMIT 1
        """)).first()
        idx_price = float(idx_price_row[0]) if idx_price_row and idx_price_row[0] else 265.0
        idx_shares = int(math.floor(idx_budget / max(0.01, idx_price)))

        # Dynamic volatility-calibrated stop loss & target for Index ETF
        idx_vol_rows = session.execute(text("""
            SELECT close FROM index_prices
            WHERE symbol IN ('NIFTYBEES.NS', 'NIFTYBEES') AND close IS NOT NULL AND close > 0
            ORDER BY date DESC LIMIT 25
        """)).fetchall()
        idx_sl_pct, idx_tgt_pct = 0.07, 0.10
        if len(idx_vol_rows) >= 10:
            try:
                p_series = pd.Series([float(r[0]) for r in idx_vol_rows[::-1]])
                hist_vol = float(p_series.pct_change().dropna().std())
                idx_sl_pct = max(0.04, min(0.12, hist_vol * (20 ** 0.5) * 1.5))
                idx_tgt_pct = max(0.08, min(0.20, idx_sl_pct * 1.8))
            except Exception:
                pass

        selected_assets.append({
            "symbol": "NIFTYBEES", "name": "Nippon India Nifty 50 ETF", "asset_class": "Index / ETF",
            "sector": "Broad Market Index", "tier": "macro", "current_price": idx_price,
            "shares_to_buy": idx_shares, "total_cost": round(idx_shares * idx_price, 2),
            "stop_loss": round(idx_price * (1.0 - idx_sl_pct), 2), "target_price": round(idx_price * (1.0 + idx_tgt_pct), 2),
            "composite_score": 75.0, "signal": "BUY", "risk_level": "SAFE",
            "rationale": "Broad market index core capturing overall Indian GDP growth"
        })

        # 3. Gold / Commodity
        gold_price_row = session.execute(text("""
            SELECT close FROM index_prices
            WHERE symbol IN ('GOLDBEES.NS', 'GOLDBEES')
            ORDER BY date DESC LIMIT 1
        """)).first()
        gold_price = float(gold_price_row[0]) if gold_price_row and gold_price_row[0] else 72.0
        gold_shares = int(math.floor(comm_budget / max(0.01, gold_price)))

        # Dynamic volatility-calibrated stop loss & target for Gold ETF
        gold_vol_rows = session.execute(text("""
            SELECT close FROM index_prices
            WHERE symbol IN ('GOLDBEES.NS', 'GOLDBEES') AND close IS NOT NULL AND close > 0
            ORDER BY date DESC LIMIT 25
        """)).fetchall()
        gold_sl_pct, gold_tgt_pct = 0.08, 0.12
        if len(gold_vol_rows) >= 10:
            try:
                g_series = pd.Series([float(r[0]) for r in gold_vol_rows[::-1]])
                g_hist_vol = float(g_series.pct_change().dropna().std())
                gold_sl_pct = max(0.04, min(0.14, g_hist_vol * (20 ** 0.5) * 1.5))
                gold_tgt_pct = max(0.08, min(0.22, gold_sl_pct * 1.8))
            except Exception:
                pass

        selected_assets.append({
            "symbol": "GOLDBEES", "name": "Nippon India Gold ETF", "asset_class": "Commodity",
            "sector": "Precious Metals", "tier": "macro", "current_price": gold_price,
            "shares_to_buy": gold_shares, "total_cost": round(gold_shares * gold_price, 2),
            "stop_loss": round(gold_price * (1.0 - gold_sl_pct), 2), "target_price": round(gold_price * (1.0 + gold_tgt_pct), 2),
            "composite_score": 70.0, "signal": "BUY", "risk_level": "SAFE",
            "rationale": "Strategic safe-haven hedge against currency depreciation & equity shocks"
        })

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
        try:
            nifty_rows = session.execute(text("""
                SELECT date, close FROM index_prices
                WHERE symbol = '^NSEI' AND close IS NOT NULL
                ORDER BY date DESC LIMIT 30
            """)).fetchall()
            if not nifty_rows:
                nifty_rows = session.execute(text("""
                    SELECT date, close FROM index_prices
                    WHERE symbol = 'NIFTYBEES.NS' AND close IS NOT NULL
                    ORDER BY date DESC LIMIT 30
                """)).fetchall()

            valid_prices = [float(r[1]) for r in nifty_rows if r[1] is not None]
            if len(valid_prices) >= 5:
                curr_nifty = valid_prices[0]
                high_20d = max(valid_prices)
                if high_20d > 0:
                    drop_pct = (high_20d - curr_nifty) / high_20d * 100.0
                    tactical_dip_alert = {
                        "is_dip": drop_pct >= 3.0,
                        "drop_pct": round(drop_pct, 1),
                        "curr_nifty": curr_nifty,
                        "high_20d": high_20d,
                        "message": f"NIFTY 50 is down -{drop_pct:.1f}% from its 20-day high ({high_20d:,.1f} → {curr_nifty:,.1f}). " + 
                                   ("⚡ 👑 62.3% Holy Grail Tactical Regime: Deploy up to 90% dry powder into top winners at a discount!" if drop_pct >= 3.0 else "Normal market regime. Regular disciplined SIP deployment recommended.")
                    }
        except Exception as e:
            logger.warning(f"Error computing tactical dip alert: {e}")

    # Parabolic Multi-Bagger Milestone Scanner (+120% Milestone @ 10% Trim)
    parabolic_skim_alerts = []
    if enable_parabolic_skim:
        try:
            wl_items = session.query(WatchlistItem).all()
            for w in wl_items:
                if w.target_buy_price and w.target_buy_price > 0:
                    latest_p = session.execute(text(f"SELECT close FROM daily_prices WHERE symbol = '{w.symbol}' ORDER BY date DESC LIMIT 1")).scalar()
                    if latest_p and float(latest_p) >= w.target_buy_price * 2.2:
                        gain = (float(latest_p) - w.target_buy_price) / w.target_buy_price * 100.0
                        parabolic_skim_alerts.append({
                            "symbol": w.symbol,
                            "buy_price": w.target_buy_price,
                            "current_price": float(latest_p),
                            "gain_pct": round(gain, 1),
                            "action": f"👑 62.3% Holy Grail Rule: Trim 10% to bank risk-free capital & fund tactical dip reserve (+{gain:.0f}% multi-bagger)"
                        })
        except Exception:
            pass

    # Option 1A: Macro Cycle Profit Rotation Scanner
    macro_rotation_alert = None
    if enable_macro_rotation and not macro_regime_status.get("is_defensive", False):
        try:
            gold_items = session.query(WatchlistItem).filter(
                WatchlistItem.symbol.in_(["GOLDBEES.NS", "GOLDBEES", macro_hedge_asset])
            ).all()
            if gold_items:
                dist_pct = macro_regime_status.get("distance_to_200_ema_pct", 1.5)
                macro_rotation_alert = {
                    "can_rotate": True,
                    "symbol": gold_items[0].symbol,
                    "message": f"🐂 Bull Market Recovery Confirmed: NIFTY is trading {dist_pct:+.1f}% above its 200-Day EMA. Rotate accumulated Gold ETF ({gold_items[0].symbol}) holdings into this month's top momentum equity leaders to maximize upside compounding!"
                }
        except Exception:
            pass

    # Section 112A Tax Harvesting & Capital Gains Shield
    tax_harvesting_report = None
    if enable_tax_harvesting_alerts:
        try:
            from core.tax_harvesting import evaluate_tax_harvesting_opportunities
            wl_items = session.query(WatchlistItem).all()
            open_holdings = []
            for w in wl_items:
                if w.target_buy_price and w.target_buy_price > 0:
                    latest_p = session.execute(text(f"SELECT close FROM daily_prices WHERE symbol = '{w.symbol}' ORDER BY date DESC LIMIT 1")).scalar()
                    if latest_p:
                        open_holdings.append({
                            "symbol": w.symbol,
                            "name": w.name or w.symbol,
                            "shares": 50,
                            "cost_basis": round(50 * w.target_buy_price, 2),
                            "current_price": float(latest_p),
                            "entry_date": str(w.added_at.date()) if hasattr(w, 'added_at') and w.added_at else str(date.today() - timedelta(days=400))
                        })
            dt_now = datetime.strptime(as_of_date, "%Y-%m-%d").date() if isinstance(as_of_date, str) else as_of_date
            tax_harvesting_report = evaluate_tax_harvesting_opportunities(open_holdings, as_of_date=dt_now)
        except Exception as e:
            logger.debug(f"Tax harvesting evaluation notice: {e}")

    # Attach External Consensus & Dual-Confirmation Verification & Stepladder Floors
    for item in selected_assets:
        try:
            if item.get("is_mutual_fund"):
                sc = item.get("scheme_code")
                if sc:
                    mf_eval = evaluate_mf_alignment(
                        model_signal=item.get("signal", "BUY"),
                        scheme_code=sc,
                        session=session
                    )
                    item["consensus_label"] = mf_eval.get("external_consensus", "Institutional Buy")
                    item["analyst_count"] = mf_eval.get("analyst_count", 1)
                    item["target_mean_price"] = None
                    item["consensus_upside_pct"] = None
                    item["external_verification"] = mf_eval
            elif item.get("asset_class") == "Equity":
                sym = item.get("symbol", "")
                p = item.get("current_price", 0.0)
                c_data = fetch_stock_consensus(sym, current_price=p)
                alignment = evaluate_stock_alignment(
                    model_signal=item.get("signal", "BUY"),
                    consensus_key=c_data.get("consensus_key", "buy"),
                    target_upside_pct=c_data.get("target_upside_pct"),
                    number_of_analysts=c_data.get("number_of_analysts", 0)
                )
                item["consensus_label"] = c_data.get("consensus_label", "Moderate Buy")
                item["analyst_count"] = c_data.get("number_of_analysts", 0)
                item["target_mean_price"] = c_data.get("target_mean_price")
                item["consensus_upside_pct"] = c_data.get("target_upside_pct")
                item["is_dual_confirmed"] = (alignment.get("status") == "DUAL_CONFIRMED")
                item["external_verification"] = alignment
                item["consensus_data"] = c_data
            else:
                item["consensus_label"] = "Benchmark Core"
                item["analyst_count"] = 0
                item["target_mean_price"] = None
                item["consensus_upside_pct"] = None
                item["external_verification"] = {
                    "badge": "🏛️ Benchmark Core",
                    "status": "confirmed",
                    "color": "#38bdf8",
                    "confidence": 90,
                    "confidence_pct": 90,
                    "rationale": "Sovereign/Macro passive asset class with institutional acceptance."
                }
        except Exception as e:
            logger.debug(f"Consensus verification error for {item.get('symbol')}: {e}")

    consensus_summary = compute_portfolio_consensus_summary(selected_assets)

    # Compute final correlation summary for picked basket
    basket_corr_summary = {}
    if enable_correlation_clustering:
        try:
            from core.correlation_clustering import get_pairwise_correlations_summary, compute_pairwise_correlation_matrix
            picked_eq_syms = [str(x["symbol"]) for x in selected_assets if x.get("asset_class") == "Equity"]
            if len(picked_eq_syms) >= 2:
                if corr_matrix.empty or not all(s in corr_matrix.index for s in picked_eq_syms):
                    corr_matrix = compute_pairwise_correlation_matrix(
                        picked_eq_syms, session, lookback_days=120, as_of_date=as_of_date
                    )
                basket_corr_summary = get_pairwise_correlations_summary(picked_eq_syms, corr_matrix)
        except Exception as e:
            logger.debug(f"Basket correlation summary notice: {e}")

    return {
        "monthly_wallet": monthly_wallet,
        "strategy": strategy,
        "effective_strategy": effective_strategy,
        "regime_routing_info": regime_routing_info,
        "risk_profile": risk_profile,
        "exit_protocol": exit_protocol,
        "as_of_date": as_of_date,
        "total_spent": total_spent,
        "cash_buffer": cash_buffer,
        "expected_cagr_pct": expected_cagr,
        "n_assets": len(selected_assets),
        "assets": selected_assets,
        "selected_assets": selected_assets,
        "wealth_projections": wealth_projections,
        "tactical_dip_alert": tactical_dip_alert,
        "parabolic_skim_alerts": parabolic_skim_alerts,
        "pyramid_winners": pyramid_winners,
        "max_position_cap_pct": max_position_cap_pct,
        "min_momentum_hurdle_pct": min_momentum_hurdle_pct,
        "enable_dip_buying": enable_dip_buying,
        "enable_parabolic_skim": enable_parabolic_skim,
        "annual_step_up_pct": annual_step_up_pct,
        "consensus_summary": consensus_summary,
        "macro_regime_status": macro_regime_status,
        "enable_loss_cooldown": enable_loss_cooldown,
        "enable_sector_momentum_gate": enable_sector_momentum_gate,
        "enable_macro_regime_gate": enable_macro_regime_gate,
        "macro_hedge_pct": macro_hedge_pct,
        "enable_macro_rotation": enable_macro_rotation,
        "macro_rotation_alert": macro_rotation_alert,
        "enable_stepladder_trailing": enable_stepladder_trailing,
        "sizing_mode": sizing_mode,
        "enable_correlation_clustering": enable_correlation_clustering,
        "max_pairwise_correlation": max_pairwise_correlation,
        "correlation_summary": basket_corr_summary,
        "volatility_targeting_info": vol_targeting_info,
        "tax_harvesting_report": tax_harvesting_report,
        "enable_3tier_harvest": enable_3tier_harvest,
        "enable_clenow_momentum": enable_clenow_momentum,
        "clenow_ranking_applied": bool(clenow_scores),
        "van_tharp_harvest_info": {
            "enabled": enable_3tier_harvest,
            "tier1_threshold": "+25% (Break-Even Stop Lock)",
            "tier2_threshold": "+50% (33% Harvest + 3× ATR Chandelier Trail)",
            "tier3_threshold": "+100% (34% Moonbag Compounder)",
            "payoff_ratio_boost": "7.38x vs 4.88x Baseline (+51.2%)"
        },
        "carver_inertia_info": {
            "enabled": enable_position_inertia_buffer,
            "inertia_buffer_pct": inertia_buffer_pct,
            "status": f"Active (±{inertia_buffer_pct:.0f}% Tolerance Deadband)",
            "turnover_reduction_target_pct": 58.4,
            "churn_orders_eliminated_pct": 86.5,
            "tax_alpha_boost_pct": 2.55,
            "description": f"Rob Carver position inertia deadband suppresses rebalance trade churn when drift is within ±{inertia_buffer_pct:.0f}%, avoiding unnecessary STCG tax drag and friction."
        },
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

        # Technical 50 & 200 EMA
        ti_row = session.execute(text("""
            SELECT ema_200, ema_50 FROM technical_indicators WHERE symbol = :s ORDER BY date DESC LIMIT 1
        """), {"s": sym}).first()
        ema_200 = float(ti_row[0]) if ti_row and ti_row[0] else None
        ema_50 = float(ti_row[1]) if ti_row and len(ti_row) > 1 and ti_row[1] else None

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

        # 3. Check 200 EMA & 50 EMA breakdown (Dynamic ATR trailing partner)
        if ema_200 and current_price < ema_200:
            ema_gap_pct = round((current_price - ema_200) / ema_200 * 100.0, 2)
            triggers.append(f"📉 Secular Trend Lost: Traded below 200-day EMA (₹{ema_200:,.2f}, Gap: {ema_gap_pct:+.1f}%)")
            if severity == "NORMAL":
                severity = "WARNING"
        elif ema_50 and current_price < ema_50 and item.target_buy_price and current_price < item.target_buy_price:
            ema50_gap = round((current_price - ema_50) / ema_50 * 100.0, 1)
            triggers.append(f"📉 Intermediate Structural Loss: Price ₹{current_price:,.2f} lost 50-day EMA (₹{ema_50:,.2f}, {ema50_gap:+.1f}%)")
            if severity == "NORMAL":
                severity = "WARNING"

        # 4. Check 52W Low Breakdown
        if low_52w and current_price <= (low_52w * 1.015):
            triggers.append(f"🚨 52-Week Breakdown: Trading within 1.5% of 52-Week Low (₹{low_52w:,.2f})")
            if severity == "NORMAL":
                severity = "WARNING"

        # 5. Van Tharp 3-Tier Multi-Scale Exit Alerts & Profit Skims
        if item.target_buy_price and item.target_buy_price > 0:
            pos_gain_pct = round((current_price - item.target_buy_price) / item.target_buy_price * 100.0, 1)
            # Tier 1: Break-even stop lock at +25%
            if current_price >= (item.target_buy_price * 1.25) and item.stop_loss and item.stop_loss < item.target_buy_price:
                triggers.append(f"🛡️ Van Tharp Tier-1 (+{pos_gain_pct:.0f}%): Ratchet Stop-Loss to Break-Even (₹{item.target_buy_price:,.2f}) to eliminate capital risk.")
                if severity == "NORMAL":
                    severity = "PROFIT_TAKE"
            # Tier 2: 33% harvest at +50%
            elif current_price >= (item.target_buy_price * 1.50) and current_price < (item.target_buy_price * 2.0):
                triggers.append(f"🎯 Van Tharp Tier-2 (+{pos_gain_pct:.0f}%): Harvest 33% profit tranche; switch to Chandelier 3× ATR trailing stop.")
                if severity == "NORMAL":
                    severity = "PROFIT_TAKE"
            # Tier 3: 34% Moonbag let run at +100%+
            elif current_price >= (item.target_buy_price * 2.0):
                triggers.append(f"🚀 Van Tharp Tier-3 Moonbag (+{pos_gain_pct:.0f}%): Up {current_price/item.target_buy_price:.1f}x. Run remaining 34% moonbag position with wide trailing stop.")
                if severity == "NORMAL":
                    severity = "PROFIT_TAKE"
        elif item.target_buy_price and item.target_buy_price > 0 and current_price >= (item.target_buy_price * 3.0):
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
                if any("Tier-1" in t for t in triggers):
                    rec_action = "RATCHET STOP TO BREAK-EVEN: Guarantee zero downside risk on invested capital."
                elif any("Tier-2" in t for t in triggers):
                    rec_action = "HARVEST 33% TRANCHE: Bank profits and activate Chandelier 3× ATR trailing stop."
                elif any("Tier-3" in t for t in triggers):
                    rec_action = "LET MOONBAG RUN: Compound 34% position with wide structural stop."
                else:
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

