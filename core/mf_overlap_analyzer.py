"""
core/mf_overlap_analyzer.py
Institutional Stock vs. Mutual Fund Overlap & True Concentration Analytics Engine.

Provides:
  1. Curated institutional holdings repository for 25 marquee Indian mutual fund schemes across categories.
  2. Point-in-time and look-through portfolio deconstruction (Direct Equity + MF units).
  3. True Effective Concentration (Look-Through HHI vs. Naive HHI).
  4. Capital Duplication & Fee Cannibalization Analysis (paying TER on directly held stocks).
  5. Cross-fund pairwise overlap matrix calculation.
"""

from typing import Dict, List, Any, Optional, Tuple
import math

# Curated Institutional Top Holdings Knowledgebase across 25 Marquee Schemes
TOP_MF_SCHEMES: Dict[int, Dict[str, Any]] = {
    # ── Flexi Cap & Multi Cap ──
    122639: {
        "name": "Parag Parikh Flexi Cap Fund",
        "category": "Flexi Cap",
        "ter_pct": 0.63,
        "holdings": {
            "HDFCBANK": 8.1, "BAJAJHLDNG": 6.8, "ITC": 6.2, "ICICIBANK": 5.9, "POWERGRID": 4.8,
            "INFY": 4.2, "COALINDIA": 3.9, "HCLTECH": 3.5, "AXISBANK": 3.2, "TCS": 2.8
        }
    },
    118955: {
        "name": "HDFC Flexi Cap Fund",
        "category": "Flexi Cap",
        "ter_pct": 0.81,
        "holdings": {
            "ICICIBANK": 9.4, "HDFCBANK": 8.7, "INFY": 6.8, "SBIN": 5.9, "LICI": 4.5,
            "AXISBANK": 4.2, "BHARTIARTL": 3.8, "NTPC": 3.4, "LT": 3.1, "TCS": 2.9
        }
    },
    125354: {
        "name": "Quant Flexi Cap Fund",
        "category": "Flexi Cap",
        "ter_pct": 0.77,
        "holdings": {
            "RELIANCE": 9.8, "JIOFIN": 7.2, "ADANIPOWER": 5.8, "SAIL": 4.9, "HDFCBANK": 4.6,
            "TATAPOWER": 4.1, "SAMVARDHANA": 3.8, "BRITANNIA": 3.5, "GAIL": 3.2, "HINDALCO": 3.0
        }
    },
    120503: {
        "name": "JM Flexicap Fund",
        "category": "Flexi Cap",
        "ter_pct": 0.72,
        "holdings": {
            "HDFCBANK": 6.5, "ICICIBANK": 5.8, "LT": 5.2, "RELIANCE": 4.9, "INFY": 4.5,
            "REC": 3.8, "PFC": 3.7, "BHEL": 3.4, "NTPC": 3.1, "TRENT": 2.9
        }
    },
    120828: {
        "name": "Kotak Flexicap Fund",
        "category": "Flexi Cap",
        "ter_pct": 0.69,
        "holdings": {
            "ICICIBANK": 8.5, "HDFCBANK": 7.8, "INFY": 5.6, "RELIANCE": 5.2, "LT": 4.8,
            "TCS": 3.9, "AXISBANK": 3.6, "BHARTIARTL": 3.3, "MARUTI": 3.0, "ULTRACEMCO": 2.7
        }
    },

    # ── Large Cap & Large/Mid Cap ──
    119063: {
        "name": "ICICI Prudential Bluechip Fund",
        "category": "Large Cap",
        "ter_pct": 0.92,
        "holdings": {
            "ICICIBANK": 9.2, "RELIANCE": 8.8, "HDFCBANK": 8.1, "INFY": 6.4, "LT": 5.5,
            "BHARTIARTL": 4.7, "AXISBANK": 4.1, "TCS": 3.8, "MARUTI": 3.2, "ULTRACEMCO": 2.8
        }
    },
    119598: {
        "name": "Mirae Asset Large Cap Fund",
        "category": "Large Cap",
        "ter_pct": 0.61,
        "holdings": {
            "HDFCBANK": 9.8, "ICICIBANK": 8.6, "INFY": 7.1, "RELIANCE": 6.5, "TCS": 4.2,
            "AXISBANK": 3.9, "LT": 3.8, "BHARTIARTL": 3.6, "SBIN": 3.2, "KOTAKBANK": 2.9
        }
    },
    119717: {
        "name": "SBI Bluechip Fund",
        "category": "Large Cap",
        "ter_pct": 0.84,
        "holdings": {
            "HDFCBANK": 8.9, "ICICIBANK": 7.6, "RELIANCE": 6.8, "INFY": 5.9, "LT": 4.8,
            "ITC": 4.2, "TCS": 3.9, "AXISBANK": 3.5, "BHARTIARTL": 3.1, "M&M": 2.8
        }
    },
    118989: {
        "name": "HDFC Top 100 Fund",
        "category": "Large Cap",
        "ter_pct": 1.05,
        "holdings": {
            "ICICIBANK": 9.8, "HDFCBANK": 9.1, "RELIANCE": 8.2, "INFY": 6.1, "LT": 4.9,
            "SBIN": 4.5, "AXISBANK": 3.9, "TCS": 3.5, "NTPC": 3.1, "BHARTIARTL": 3.0
        }
    },
    120586: {
        "name": "Canara Robeco Emerging Equities",
        "category": "Large & Mid Cap",
        "ter_pct": 0.74,
        "holdings": {
            "ICICIBANK": 6.2, "HDFCBANK": 5.8, "INFY": 4.9, "LT": 4.2, "BHARATFORG": 3.8,
            "RELIANCE": 3.5, "FEDERALBNK": 3.2, "TRENT": 3.1, "MAXHEALTH": 2.9, "AXISBANK": 2.7
        }
    },

    # ── Mid Cap ──
    120152: {
        "name": "Motilal Oswal Midcap Fund",
        "category": "Mid Cap",
        "ter_pct": 0.70,
        "holdings": {
            "PERSISTENT": 7.8, "TRENT": 6.9, "BSOFT": 6.1, "POLYCAB": 5.4, "COFORGE": 4.8,
            "DIXON": 4.2, "SUZLON": 3.9, "APARINDS": 3.6, "TUBEINVEST": 3.2, "VOLTAS": 2.9
        }
    },
    118988: {
        "name": "HDFC Mid-Cap Opportunities Fund",
        "category": "Mid Cap",
        "ter_pct": 0.79,
        "holdings": {
            "TATACOMM": 4.2, "INDHOTEL": 3.9, "FEDERALBNK": 3.7, "BHARATFORG": 3.5, "ASTRAL": 3.2,
            "MAXHEALTH": 3.1, "APOLLOTYRE": 2.9, "COFORGE": 2.8, "VOLTAS": 2.7, "BALKRISIND": 2.5
        }
    },
    119797: {
        "name": "Kotak Emerging Equity Fund",
        "category": "Mid Cap",
        "ter_pct": 0.78,
        "holdings": {
            "SUPREMEIND": 4.8, "PERSISTENT": 4.2, "SCHAEFFLER": 3.8, "THERMAX": 3.6, "CUMMINSIND": 3.4,
            "POLYCAB": 3.1, "SOLARINDS": 2.9, "OBEROIRLTY": 2.8, "ASTRAL": 2.7, "BHARATFORG": 2.6
        }
    },
    120847: {
        "name": "Nippon India Growth Fund",
        "category": "Mid Cap",
        "ter_pct": 0.88,
        "holdings": {
            "CHOLAFIN": 3.9, "POWERFIN": 3.6, "VARUN": 3.4, "BHARATFORG": 3.2, "FORTIS": 3.1,
            "SUPREMEIND": 2.9, "MAXHEALTH": 2.8, "FEDERALBNK": 2.7, "VOLTAS": 2.5, "TRENT": 2.4
        }
    },
    125494: {
        "name": "Quant Mid Cap Fund",
        "category": "Mid Cap",
        "ter_pct": 0.76,
        "holdings": {
            "RELIANCE": 8.5, "JIOFIN": 6.8, "TATACOMM": 5.2, "SAIL": 4.6, "ADANIPOWER": 4.2,
            "ESCORTS": 3.8, "BHEL": 3.5, "GAIL": 3.1, "CANBK": 2.9, "SUNTV": 2.7
        }
    },

    # ── Small Cap ──
    120823: {
        "name": "Nippon India Small Cap Fund",
        "category": "Small Cap",
        "ter_pct": 0.72,
        "holdings": {
            "TUBEINVEST": 3.1, "APARINDS": 2.8, "HDFCBANK": 2.5, "KEC": 2.4, "CREDITACC": 2.2,
            "VOLTAS": 2.1, "CROMPTON": 1.9, "BHEL": 1.8, "GLAXO": 1.7, "PRESTIGE": 1.6
        }
    },
    125497: {
        "name": "Quant Small Cap Fund",
        "category": "Small Cap",
        "ter_pct": 0.75,
        "holdings": {
            "RELIANCE": 9.1, "JIOFIN": 6.5, "IRB": 4.8, "HINDCOPPER": 4.2, "SAIL": 3.9,
            "BIKAJI": 3.5, "HFCL": 3.2, "ADANIPOWER": 2.9, "RITES": 2.7, "NATIONALUM": 2.5
        }
    },
    118959: {
        "name": "HDFC Small Cap Fund",
        "category": "Small Cap",
        "ter_pct": 0.71,
        "holdings": {
            "FIRSTSOURCE": 4.1, "SONATSOFTW": 3.7, "BANKBARODA": 3.4, "EQUITASBNK": 3.1, "BALRAMCHIN": 2.9,
            "KALPATPOWR": 2.7, "ELECON": 2.5, "ECLERX": 2.4, "SKFINDIA": 2.3, "CYIENT": 2.2
        }
    },
    125307: {
        "name": "Bandhan Small Cap Fund",
        "category": "Small Cap",
        "ter_pct": 0.65,
        "holdings": {
            "ARVIND": 3.2, "APARINDS": 2.9, "MOTILALOFS": 2.7, "RADICO": 2.5, "CENTURYPLY": 2.3,
            "REC": 2.1, "CHOLAMANDALAM": 2.0, "CERA": 1.9, "CARBORUNIV": 1.8, "BSE": 1.7
        }
    },

    # ── Index Funds ──
    120716: {
        "name": "UTI Nifty 50 Index Fund",
        "category": "Index",
        "ter_pct": 0.18,
        "holdings": {
            "HDFCBANK": 11.8, "RELIANCE": 9.4, "ICICIBANK": 7.8, "INFY": 5.9, "ITC": 4.2,
            "TCS": 3.8, "BHARTIARTL": 3.7, "LT": 3.4, "AXISBANK": 3.1, "SBIN": 2.9
        }
    },
    120717: {
        "name": "UTI Nifty Next 50 Index Fund",
        "category": "Index",
        "ter_pct": 0.28,
        "holdings": {
            "BEL": 4.8, "TRENT": 4.5, "TATAMTRDVR": 3.9, "HAL": 3.7, "CHOLAFIN": 3.5,
            "VBL": 3.3, "REC": 3.1, "PFC": 3.0, "TVSMOTOR": 2.8, "JIOFIN": 2.7
        }
    },
    119062: {
        "name": "ICICI Prudential Nifty 50 Index Fund",
        "category": "Index",
        "ter_pct": 0.17,
        "holdings": {
            "HDFCBANK": 11.8, "RELIANCE": 9.4, "ICICIBANK": 7.8, "INFY": 5.9, "ITC": 4.2,
            "TCS": 3.8, "BHARTIARTL": 3.7, "LT": 3.4, "AXISBANK": 3.1, "SBIN": 2.9
        }
    },
    148943: {
        "name": "Motilal Oswal Nifty Midcap 150 Index Fund",
        "category": "Index",
        "ter_pct": 0.30,
        "holdings": {
            "MAXHEALTH": 2.4, "SUZLON": 2.2, "PERSISTENT": 2.1, "INDIANB": 2.0, "BHARATFORG": 1.9,
            "CUMMINSIND": 1.8, "POLYCAB": 1.7, "TUBEINVEST": 1.6, "HDFCAMC": 1.5, "FEDERALBNK": 1.5
        }
    },

    # ── Hybrid & Balanced Advantage ──
    119065: {
        "name": "ICICI Prudential Balanced Advantage Fund",
        "category": "Hybrid",
        "ter_pct": 0.90,
        "holdings": {
            "ICICIBANK": 6.5, "RELIANCE": 5.8, "HDFCBANK": 5.2, "INFY": 4.1, "BHARTIARTL": 3.5,
            "LT": 3.2, "AXISBANK": 2.8, "MARUTI": 2.4, "TCS": 2.2, "NTPC": 2.0
        }
    },
    118968: {
        "name": "HDFC Balanced Advantage Fund",
        "category": "Hybrid",
        "ter_pct": 0.85,
        "holdings": {
            "ICICIBANK": 7.2, "HDFCBANK": 6.8, "SBIN": 5.4, "INFY": 4.8, "LICI": 4.1,
            "COALINDIA": 3.5, "NTPC": 3.2, "LT": 2.9, "ITC": 2.7, "AXISBANK": 2.5
        }
    }
}


def get_available_mf_schemes() -> List[Dict[str, Any]]:
    """Returns a list of all configured institutional schemes."""
    return [
        {
            "scheme_code": code,
            "name": data["name"],
            "category": data["category"],
            "ter_pct": data.get("ter_pct", 0.75),
            "top10_weight": round(sum(data["holdings"].values()), 1)
        }
        for code, data in TOP_MF_SCHEMES.items()
    ]


def calculate_pairwise_fund_overlap(scheme_code_1: int, scheme_code_2: int) -> Dict[str, Any]:
    """
    Computes weighted portfolio overlap between two mutual fund schemes:
      Overlap = sum(min(w1_i, w2_i))
    """
    fund1 = TOP_MF_SCHEMES.get(scheme_code_1)
    fund2 = TOP_MF_SCHEMES.get(scheme_code_2)
    if not fund1 or not fund2:
        return {"error": "Invalid scheme code(s) provided."}

    h1 = fund1["holdings"]
    h2 = fund2["holdings"]
    common_syms = set(h1.keys()).intersection(set(h2.keys()))

    common_details = []
    overlap_weight = 0.0
    for sym in common_syms:
        w1 = h1[sym]
        w2 = h2[sym]
        common_min = min(w1, w2)
        overlap_weight += common_min
        common_details.append({
            "symbol": sym,
            "weight_fund1": w1,
            "weight_fund2": w2,
            "overlap_contribution": round(common_min, 2)
        })

    common_details.sort(key=lambda x: x["overlap_contribution"], reverse=True)

    return {
        "fund1": {"code": scheme_code_1, "name": fund1["name"], "category": fund1["category"]},
        "fund2": {"code": scheme_code_2, "name": fund2["name"], "category": fund2["category"]},
        "overlap_pct": round(overlap_weight, 2),
        "common_holdings_count": len(common_syms),
        "common_holdings": common_details,
        "is_high_overlap": overlap_weight >= 25.0
    }


def calculate_lookthrough_exposure(
    direct_stocks: Dict[str, float],
    mf_allocations: Dict[int, float]
) -> Dict[str, Any]:
    """
    Performs full look-through portfolio deconstruction across direct equity holdings
    and mutual fund units to compute True Effective Exposure and Concentration Risk.

    Args:
        direct_stocks: Dict mapping stock symbol to invested amount (₹) or weight.
        mf_allocations: Dict mapping scheme_code to invested amount (₹) or weight.

    Returns:
        Comprehensive dictionary containing look-through exposures, HHI indices,
        hidden concentration multipliers, fee cannibalization, and rebalancing recommendations.
    """
    # Clean inputs
    cleaned_direct = {str(k).strip().upper(): max(0.0, float(v)) for k, v in direct_stocks.items() if float(v) > 0}
    cleaned_mfs = {int(k): max(0.0, float(v)) for k, v in mf_allocations.items() if float(v) > 0 and int(k) in TOP_MF_SCHEMES}

    direct_total = sum(cleaned_direct.values())
    mf_total = sum(cleaned_mfs.values())
    grand_total = direct_total + mf_total

    if grand_total <= 0.0:
        return {"error": "Portfolio total value must be greater than zero."}

    direct_share_pct = (direct_total / grand_total) * 100.0
    mf_share_pct = (mf_total / grand_total) * 100.0

    # Stock aggregation: Direct vs. Indirect
    stock_breakdown: Dict[str, Dict[str, Any]] = {}

    # 1. Process Direct Stocks
    for sym, val in cleaned_direct.items():
        direct_wt = (val / grand_total) * 100.0
        stock_breakdown[sym] = {
            "symbol": sym,
            "direct_weight_pct": round(direct_wt, 2),
            "indirect_weight_pct": 0.0,
            "total_effective_weight_pct": round(direct_wt, 2),
            "contributing_mfs": [],
            "direct_amount": val,
            "indirect_amount": 0.0,
            "total_amount": val
        }

    # 2. Process Mutual Funds Look-Through
    for code, mf_val in cleaned_mfs.items():
        mf_info = TOP_MF_SCHEMES[code]
        mf_weight_in_portfolio = mf_val / grand_total  # ratio
        for sym, holding_pct in mf_info["holdings"].items():
            sym_clean = sym.strip().upper()
            # holding_pct is out of 100 in the fund
            indirect_wt_contrib = mf_weight_in_portfolio * holding_pct  # in pct
            indirect_amt_contrib = (indirect_wt_contrib / 100.0) * grand_total

            if sym_clean not in stock_breakdown:
                stock_breakdown[sym_clean] = {
                    "symbol": sym_clean,
                    "direct_weight_pct": 0.0,
                    "indirect_weight_pct": 0.0,
                    "total_effective_weight_pct": 0.0,
                    "contributing_mfs": [],
                    "direct_amount": 0.0,
                    "indirect_amount": 0.0,
                    "total_amount": 0.0
                }

            stock_breakdown[sym_clean]["indirect_weight_pct"] += indirect_wt_contrib
            stock_breakdown[sym_clean]["indirect_amount"] += indirect_amt_contrib
            stock_breakdown[sym_clean]["contributing_mfs"].append({
                "scheme_code": code,
                "scheme_name": mf_info["name"],
                "fund_weight_pct": holding_pct,
                "portfolio_contrib_pct": round(indirect_wt_contrib, 2)
            })

    # 3. Finalize totals and identify overlaps
    all_effective_stocks = []
    overlapping_stocks = []
    duplicated_capital = 0.0

    for sym, d in stock_breakdown.items():
        d["direct_weight_pct"] = round(d["direct_weight_pct"], 2)
        d["indirect_weight_pct"] = round(d["indirect_weight_pct"], 2)
        total_eff = round(d["direct_weight_pct"] + d["indirect_weight_pct"], 2)
        d["total_effective_weight_pct"] = total_eff
        d["total_amount"] = round(d["direct_amount"] + d["indirect_amount"], 2)
        d["is_overexposed"] = total_eff >= 8.0  # Alert threshold: >= 8% of total net worth in 1 stock

        if d["direct_weight_pct"] > 0 and d["indirect_weight_pct"] > 0:
            dup_wt = min(d["direct_weight_pct"], d["indirect_weight_pct"])
            duplicated_capital += (dup_wt / 100.0) * grand_total
            overlapping_stocks.append(d)

        all_effective_stocks.append(d)

    all_effective_stocks.sort(key=lambda x: x["total_effective_weight_pct"], reverse=True)
    overlapping_stocks.sort(key=lambda x: x["total_effective_weight_pct"], reverse=True)

    # 4. Compute Concentration Indices (HHI)
    # Naive HHI: treating each MF unit as 1 diversified instrument
    naive_weights = [(val / grand_total) * 100.0 for val in cleaned_direct.values()] + \
                    [(val / grand_total) * 100.0 for val in cleaned_mfs.values()]
    naive_hhi = sum(w ** 2 for w in naive_weights)

    # Look-through HHI: treating underlying stocks directly
    # Note: Unallocated MF remainder (small stocks not in top 10) is treated as a diversified pool
    top10_sum_weights = sum(d["indirect_weight_pct"] for d in all_effective_stocks if d["indirect_weight_pct"] > 0)
    unallocated_mf_pct = max(0.0, mf_share_pct - top10_sum_weights)
    
    lookthrough_weights = [d["total_effective_weight_pct"] for d in all_effective_stocks]
    if unallocated_mf_pct > 0:
        # Assume residual is split across ~40 tail stocks (~0.5% each)
        lookthrough_hhi = sum(w ** 2 for w in lookthrough_weights) + 40 * ((unallocated_mf_pct / 40) ** 2)
    else:
        lookthrough_hhi = sum(w ** 2 for w in lookthrough_weights)

    concentration_multiplier = round(lookthrough_hhi / max(1.0, naive_hhi), 2)

    # Risk level classification
    if lookthrough_hhi < 1000:
        hhi_status = "WELL_DIVERSIFIED"
        hhi_label = "Optimal Low Risk (< 1,000)"
        hhi_color = "#10b981"
    elif lookthrough_hhi < 1800:
        hhi_status = "MODERATE_CONCENTRATION"
        hhi_label = "Moderate Concentration (1,000 - 1,800)"
        hhi_color = "#38bdf8"
    else:
        hhi_status = "HIGH_CONCENTRATION"
        hhi_label = "High Single-Shock Risk (> 1,800)"
        hhi_color = "#ef4444"

    # 5. Cannibalization / Duplication Warnings
    cannibalization_alerts = []
    for d in overlapping_stocks:
        if d["total_effective_weight_pct"] >= 7.0:
            mf_names = ", ".join([m["scheme_name"] for m in d["contributing_mfs"]])
            cannibalization_alerts.append({
                "symbol": d["symbol"],
                "total_effective_weight_pct": d["total_effective_weight_pct"],
                "direct_weight_pct": d["direct_weight_pct"],
                "indirect_weight_pct": d["indirect_weight_pct"],
                "warning": (
                    f"⚠️ **{d['symbol']}** constitutes **{d['total_effective_weight_pct']}%** of total portfolio! "
                    f"You hold it directly ({d['direct_weight_pct']}%) AND indirectly ({d['indirect_weight_pct']}%) "
                    f"via {mf_names}. You are paying mutual fund expense ratios (TER) on a stock you already own directly."
                )
            })

    top_5_effective_weight = sum(d["total_effective_weight_pct"] for d in all_effective_stocks[:5])

    return {
        "grand_total_amount": round(grand_total, 2),
        "direct_share_pct": round(direct_share_pct, 1),
        "mf_share_pct": round(mf_share_pct, 1),
        "naive_hhi": round(naive_hhi, 1),
        "lookthrough_hhi": round(lookthrough_hhi, 1),
        "concentration_multiplier": concentration_multiplier,
        "hhi_status": hhi_status,
        "hhi_label": hhi_label,
        "hhi_color": hhi_color,
        "top_5_effective_weight_pct": round(top_5_effective_weight, 1),
        "overlapping_stocks_count": len(overlapping_stocks),
        "duplicated_capital_amount": round(duplicated_capital, 2),
        "duplicated_capital_pct": round((duplicated_capital / grand_total) * 100.0, 1),
        "cannibalization_alerts": cannibalization_alerts,
        "all_effective_stocks": all_effective_stocks,
        "overlapping_stocks": overlapping_stocks
    }
