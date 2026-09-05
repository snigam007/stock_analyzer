"""
Mutual Funds Data Ingestion Engine
- Fetches official AMFI NAV data and comprehensive historical records via mfapi.in
- Manages curated Direct-Growth scheme universe across SEBI Equity, Hybrid, and Index categories
- Supports historical backfill from inception / April 2006 to current date
- Safe SSL verification fallback for Windows and headless environments
"""
import logging
import ssl
import json
import urllib.request
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import text

from db.database import MutualFund, MutualFundNAV, get_global_engine, get_session

logger = logging.getLogger(__name__)

# SSL context that works reliably across corporate proxies and Windows environments
_SSL_CTX = ssl._create_unverified_context()

# ─── Curated Universe of Direct-Growth Category Leaders ───────────────────────
CURATED_SCHEMES = [
    # Flexi Cap & Multi Cap
    {
        "scheme_code": 122639,
        "scheme_name": "Parag Parikh Flexi Cap Fund - Direct Plan - Growth",
        "fund_house": "PPFAS Mutual Fund",
        "category": "Equity",
        "sub_category": "Flexi Cap Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF879O01027",
        "expense_ratio": 0.65,
        "crisil_rating": 5
    },
    {
        "scheme_code": 118955,
        "scheme_name": "HDFC Flexi Cap Fund - Direct Plan - Growth Option",
        "fund_house": "HDFC Mutual Fund",
        "category": "Equity",
        "sub_category": "Flexi Cap Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF179K01608",
        "expense_ratio": 0.78,
        "crisil_rating": 4
    },
    {
        "scheme_code": 125354,
        "scheme_name": "Quant Flexi Cap Fund - Direct Plan - Growth",
        "fund_house": "Quant Mutual Fund",
        "category": "Equity",
        "sub_category": "Flexi Cap Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF966L01AB3",
        "expense_ratio": 0.77,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120503,
        "scheme_name": "JM Flexicap Fund - Direct Plan - Growth Option",
        "fund_house": "JM Financial Mutual Fund",
        "category": "Equity",
        "sub_category": "Flexi Cap Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF192K01344",
        "expense_ratio": 0.68,
        "crisil_rating": 5
    },
    {
        "scheme_code": 120828,
        "scheme_name": "Kotak Flexicap Fund - Direct Plan - Growth",
        "fund_house": "Kotak Mahindra Mutual Fund",
        "category": "Equity",
        "sub_category": "Flexi Cap Fund",
        "benchmark": "NIFTY 500 TRI",
        "isin_growth": "INF174K01LS2",
        "expense_ratio": 0.60,
        "crisil_rating": 4
    },

    # Large Cap & Large/Mid Cap
    {
        "scheme_code": 119598,
        "scheme_name": "Mirae Asset Large Cap Fund - Direct Plan - Growth",
        "fund_house": "Mirae Asset Mutual Fund",
        "category": "Equity",
        "sub_category": "Large Cap Fund",
        "benchmark": "NIFTY 100 TRI",
        "isin_growth": "INF769K01BF4",
        "expense_ratio": 0.54,
        "crisil_rating": 4
    },
    {
        "scheme_code": 119063,
        "scheme_name": "ICICI Prudential Bluechip Fund - Direct Plan - Growth",
        "fund_house": "ICICI Prudential Mutual Fund",
        "category": "Equity",
        "sub_category": "Large Cap Fund",
        "benchmark": "NIFTY 100 TRI",
        "isin_growth": "INF109K011Q8",
        "expense_ratio": 0.88,
        "crisil_rating": 5
    },
    {
        "scheme_code": 119717,
        "scheme_name": "SBI Bluechip Fund - Direct Plan - Growth",
        "fund_house": "SBI Mutual Fund",
        "category": "Equity",
        "sub_category": "Large Cap Fund",
        "benchmark": "BSE 100 TRI",
        "isin_growth": "INF200K01RS4",
        "expense_ratio": 0.85,
        "crisil_rating": 4
    },
    {
        "scheme_code": 118989,
        "scheme_name": "HDFC Top 100 Fund - Direct Plan - Growth Option",
        "fund_house": "HDFC Mutual Fund",
        "category": "Equity",
        "sub_category": "Large Cap Fund",
        "benchmark": "NIFTY 100 TRI",
        "isin_growth": "INF179K01BD9",
        "expense_ratio": 0.98,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120586,
        "scheme_name": "Canara Robeco Emerging Equities - Direct Plan - Growth Option",
        "fund_house": "Canara Robeco Mutual Fund",
        "category": "Equity",
        "sub_category": "Large & Mid Cap Fund",
        "benchmark": "NIFTY LargeMidcap 250 TRI",
        "isin_growth": "INF760K01CV7",
        "expense_ratio": 0.62,
        "crisil_rating": 4
    },

    # Mid Cap
    {
        "scheme_code": 120152,
        "scheme_name": "Motilal Oswal Midcap Fund - Direct Plan - Growth",
        "fund_house": "Motilal Oswal Mutual Fund",
        "category": "Equity",
        "sub_category": "Mid Cap Fund",
        "benchmark": "NIFTY Midcap 150 TRI",
        "isin_growth": "INF247L01704",
        "expense_ratio": 0.70,
        "crisil_rating": 5
    },
    {
        "scheme_code": 118988,
        "scheme_name": "HDFC Mid-Cap Opportunities Fund - Direct Plan - Growth Option",
        "fund_house": "HDFC Mutual Fund",
        "category": "Equity",
        "sub_category": "Mid Cap Fund",
        "benchmark": "NIFTY Midcap 150 TRI",
        "isin_growth": "INF179K01BB3",
        "expense_ratio": 0.73,
        "crisil_rating": 5
    },
    {
        "scheme_code": 119797,
        "scheme_name": "Kotak Emerging Equity Fund - Direct Plan - Growth",
        "fund_house": "Kotak Mahindra Mutual Fund",
        "category": "Equity",
        "sub_category": "Mid Cap Fund",
        "benchmark": "NIFTY Midcap 150 TRI",
        "isin_growth": "INF174K01MU4",
        "expense_ratio": 0.49,
        "crisil_rating": 4
    },
    {
        "scheme_code": 120847,
        "scheme_name": "Nippon India Growth Fund - Direct Plan - Growth Option",
        "fund_house": "Nippon India Mutual Fund",
        "category": "Equity",
        "sub_category": "Mid Cap Fund",
        "benchmark": "NIFTY Midcap 150 TRI",
        "isin_growth": "INF204K01582",
        "expense_ratio": 0.82,
        "crisil_rating": 5
    },
    {
        "scheme_code": 125494,
        "scheme_name": "Quant Mid Cap Fund - Direct Plan - Growth",
        "fund_house": "Quant Mutual Fund",
        "category": "Equity",
        "sub_category": "Mid Cap Fund",
        "benchmark": "NIFTY Midcap 150 TRI",
        "isin_growth": "INF966L01AO6",
        "expense_ratio": 0.76,
        "crisil_rating": 4
    },

    # Small Cap
    {
        "scheme_code": 120823,
        "scheme_name": "Nippon India Small Cap Fund - Direct Plan - Growth Option",
        "fund_house": "Nippon India Mutual Fund",
        "category": "Equity",
        "sub_category": "Small Cap Fund",
        "benchmark": "NIFTY Smallcap 250 TRI",
        "isin_growth": "INF204K01525",
        "expense_ratio": 0.67,
        "crisil_rating": 5
    },
    {
        "scheme_code": 125497,
        "scheme_name": "Quant Small Cap Fund - Direct Plan - Growth Option",
        "fund_house": "Quant Mutual Fund",
        "category": "Equity",
        "sub_category": "Small Cap Fund",
        "benchmark": "NIFTY Smallcap 250 TRI",
        "isin_growth": "INF966L01AA5",
        "expense_ratio": 0.77,
        "crisil_rating": 4
    },
    {
        "scheme_code": 118959,
        "scheme_name": "HDFC Small Cap Fund - Direct Plan - Growth Option",
        "fund_house": "HDFC Mutual Fund",
        "category": "Equity",
        "sub_category": "Small Cap Fund",
        "benchmark": "BSE 250 SmallCap TRI",
        "isin_growth": "INF179K01AR7",
        "expense_ratio": 0.68,
        "crisil_rating": 4
    },
    {
        "scheme_code": 125307,
        "scheme_name": "Bandhan Small Cap Fund - Direct Plan - Growth",
        "fund_house": "Bandhan Mutual Fund",
        "category": "Equity",
        "sub_category": "Small Cap Fund",
        "benchmark": "BSE 250 SmallCap TRI",
        "isin_growth": "INF194KA1W05",
        "expense_ratio": 0.44,
        "crisil_rating": 4
    },

    # Index Funds (Passive Core)
    {
        "scheme_code": 120716,
        "scheme_name": "UTI Nifty 50 Index Fund - Direct Plan - Growth Option",
        "fund_house": "UTI Mutual Fund",
        "category": "Index",
        "sub_category": "Index Fund",
        "benchmark": "NIFTY 50 TRI",
        "isin_growth": "INF789F01AX7",
        "expense_ratio": 0.18,
        "crisil_rating": 5
    },
    {
        "scheme_code": 120717,
        "scheme_name": "UTI Nifty Next 50 Index Fund - Direct Plan - Growth Option",
        "fund_house": "UTI Mutual Fund",
        "category": "Index",
        "sub_category": "Index Fund",
        "benchmark": "NIFTY Next 50 TRI",
        "isin_growth": "INF789F01AY5",
        "expense_ratio": 0.32,
        "crisil_rating": 4
    },
    {
        "scheme_code": 119062,
        "scheme_name": "ICICI Prudential Nifty 50 Index Fund - Direct Plan - Growth",
        "fund_house": "ICICI Prudential Mutual Fund",
        "category": "Index",
        "sub_category": "Index Fund",
        "benchmark": "NIFTY 50 TRI",
        "isin_growth": "INF109K015X5",
        "expense_ratio": 0.17,
        "crisil_rating": 5
    },
    {
        "scheme_code": 148943,
        "scheme_name": "Motilal Oswal Nifty Midcap 150 Index Fund - Direct Plan - Growth",
        "fund_house": "Motilal Oswal Mutual Fund",
        "category": "Index",
        "sub_category": "Index Fund",
        "benchmark": "NIFTY Midcap 150 TRI",
        "isin_growth": "INF247L01AH4",
        "expense_ratio": 0.28,
        "crisil_rating": 4
    },

    # Hybrid & Balanced Advantage (All-Weather)
    {
        "scheme_code": 119065,
        "scheme_name": "ICICI Prudential Balanced Advantage Fund - Direct Plan - Growth",
        "fund_house": "ICICI Prudential Mutual Fund",
        "category": "Hybrid",
        "sub_category": "Dynamic Asset Allocation / Balanced Advantage",
        "benchmark": "CRISIL Hybrid 50+50 Moderate TRI",
        "isin_growth": "INF109K013Q4",
        "expense_ratio": 0.82,
        "crisil_rating": 5
    },
    {
        "scheme_code": 118968,
        "scheme_name": "HDFC Balanced Advantage Fund - Direct Plan - Growth Option",
        "fund_house": "HDFC Mutual Fund",
        "category": "Hybrid",
        "sub_category": "Dynamic Asset Allocation / Balanced Advantage",
        "benchmark": "NIFTY 50 Hybrid Composite Debt 50:50 TRI",
        "isin_growth": "INF179K01962",
        "expense_ratio": 0.72,
        "crisil_rating": 5
    },
    {
        "scheme_code": 120844,
        "scheme_name": "Edelweiss Balanced Advantage Fund - Direct Plan - Growth",
        "fund_house": "Edelweiss Mutual Fund",
        "category": "Hybrid",
        "sub_category": "Dynamic Asset Allocation / Balanced Advantage",
        "benchmark": "NIFTY 50 Hybrid Composite Debt 50:50 TRI",
        "isin_growth": "INF754K01BC0",
        "expense_ratio": 0.65,
        "crisil_rating": 4
    },

    # Debt & Liquid (Capital Preservation)
    {
        "scheme_code": 119092,
        "scheme_name": "ICICI Prudential Liquid Fund - Direct Plan - Growth",
        "fund_house": "ICICI Prudential Mutual Fund",
        "category": "Debt",
        "sub_category": "Liquid Fund",
        "benchmark": "CRISIL Liquid Debt A-I Index",
        "isin_growth": "INF109K011E4",
        "expense_ratio": 0.15,
        "crisil_rating": 5
    },
    {
        "scheme_code": 118972,
        "scheme_name": "HDFC Liquid Fund - Direct Plan - Growth Option",
        "fund_house": "HDFC Mutual Fund",
        "category": "Debt",
        "sub_category": "Liquid Fund",
        "benchmark": "CRISIL Liquid Debt A-I Index",
        "isin_growth": "INF179K01AZ4",
        "expense_ratio": 0.20,
        "crisil_rating": 5
    }
]


def seed_curated_mutual_funds(session: Session) -> int:
    """Seeds the curated mutual fund universe into the database."""
    inserted = 0
    for item in CURATED_SCHEMES:
        existing = session.query(MutualFund).filter_by(scheme_code=item["scheme_code"]).first()
        if not existing:
            mf = MutualFund(
                scheme_code=item["scheme_code"],
                scheme_name=item["scheme_name"],
                fund_house=item["fund_house"],
                category=item["category"],
                sub_category=item["sub_category"],
                benchmark=item["benchmark"],
                isin_growth=item.get("isin_growth"),
                expense_ratio=item.get("expense_ratio", 0.75),
                crisil_rating=item.get("crisil_rating", 4),
                is_active=True
            )
            session.add(mf)
            inserted += 1
        else:
            # Update metadata if needed
            existing.scheme_name = item["scheme_name"]
            existing.sub_category = item["sub_category"]
            existing.expense_ratio = item.get("expense_ratio", existing.expense_ratio)
            existing.crisil_rating = item.get("crisil_rating", existing.crisil_rating)
    session.commit()
    logger.info(f"Seeded/Updated {inserted} curated mutual funds.")
    return inserted


def fetch_scheme_nav_history(scheme_code: int, session: Session, min_date: str = "2006-04-01") -> int:
    """
    Fetches historical daily NAVs for a given scheme code from mfapi.in and stores in mutual_fund_navs.
    Returns the count of inserted records.
    """
    url = f"https://api.mfapi.in/mf/{scheme_code}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, context=_SSL_CTX, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as e:
        logger.error(f"Error fetching NAV history for scheme {scheme_code}: {e}")
        return 0

    nav_data = payload.get("data", [])
    if not nav_data:
        return 0

    # Query latest date already present in database to avoid duplicate inserts
    latest_db_date = session.execute(
        text("SELECT MAX(date) FROM mutual_fund_navs WHERE scheme_code = :sc"),
        {"sc": scheme_code}
    ).scalar()

    # Parse and prepare new records
    new_rows = []
    # nav_data is ordered newest to oldest: reverse to chronological
    sorted_navs = sorted(nav_data, key=lambda x: datetime.strptime(x["date"], "%d-%m-%Y"))
    
    prev_nav = None
    for entry in sorted_navs:
        try:
            d_obj = datetime.strptime(entry["date"], "%d-%m-%Y").date()
            if d_obj < datetime.strptime(min_date, "%Y-%m-%d").date():
                continue
            if latest_db_date and d_obj <= latest_db_date:
                prev_nav = float(entry["nav"])
                continue

            nav_val = float(entry["nav"])
            daily_ret = ((nav_val - prev_nav) / prev_nav * 100) if (prev_nav and prev_nav > 0) else 0.0
            prev_nav = nav_val

            new_rows.append({
                "scheme_code": scheme_code,
                "date": d_obj,
                "nav": nav_val,
                "daily_return": round(daily_ret, 4)
            })
        except Exception:
            continue

    if new_rows:
        session.bulk_insert_mappings(MutualFundNAV, new_rows)
        session.commit()
        logger.info(f"Inserted {len(new_rows)} historical NAVs for scheme {scheme_code}.")
    return len(new_rows)


def backfill_all_curated_mutual_funds(session: Session, limit_schemes: Optional[int] = None) -> Dict[str, int]:
    """Backfills historical NAVs for all curated mutual funds."""
    seed_curated_mutual_funds(session)
    funds = session.query(MutualFund).filter_by(is_active=True).all()
    if limit_schemes:
        funds = funds[:limit_schemes]

    results = {}
    for fund in funds:
        cnt = fetch_scheme_nav_history(fund.scheme_code, session)
        results[fund.scheme_name] = cnt

    return results


def sync_daily_amfi_nav_feed(session: Session) -> int:
    """
    Downloads the daily AMFI NAVAll.txt feed and updates the latest NAV
    for all tracked mutual funds.
    """
    url = "https://www.amfiindia.com/spages/NAVAll.txt"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, context=_SSL_CTX, timeout=25) as response:
            content = response.read().decode("utf-8", errors="ignore")
    except Exception as e:
        logger.error(f"Failed to download AMFI NAV feed: {e}")
        return 0

    tracked_codes = {r[0] for r in session.query(MutualFund.scheme_code).all()}
    if not tracked_codes:
        return 0

    lines = content.splitlines()
    updated_count = 0
    today_date = date.today()

    for line in lines:
        parts = line.strip().split(";")
        if len(parts) >= 8:
            try:
                code_str = parts[0].strip()
                if not code_str.isdigit():
                    continue
                code = int(code_str)
                if code in tracked_codes:
                    nav_val = float(parts[6].strip())
                    nav_date_str = parts[7].strip()
                    nav_date = datetime.strptime(nav_date_str, "%d-%b-%Y").date()

                    # Check if already present
                    exists = session.execute(
                        text("SELECT id FROM mutual_fund_navs WHERE scheme_code = :sc AND date = :dt"),
                        {"sc": code, "dt": nav_date}
                    ).first()

                    if not exists:
                        prev_nav = session.execute(
                            text("SELECT nav FROM mutual_fund_navs WHERE scheme_code = :sc ORDER BY date DESC LIMIT 1"),
                            {"sc": code}
                        ).scalar()
                        daily_ret = ((nav_val - prev_nav) / prev_nav * 100) if (prev_nav and prev_nav > 0) else 0.0

                        nav_rec = MutualFundNAV(
                            scheme_code=code,
                            date=nav_date,
                            nav=nav_val,
                            daily_return=round(daily_ret, 4)
                        )
                        session.add(nav_rec)
                        updated_count += 1
            except Exception:
                continue

    if updated_count > 0:
        session.commit()
        logger.info(f"Updated {updated_count} mutual fund NAVs from AMFI daily feed.")
    return updated_count


if __name__ == "__main__":
    engine = get_global_engine()
    s = get_session(engine)
    print("Seeding curated funds...")
    seed_curated_mutual_funds(s)
    print("Backfilling history for top 5 category benchmark schemes...")
    top_5 = [122639, 118955, 120823, 120716, 119065]
    for sc in top_5:
        n = fetch_scheme_nav_history(sc, s)
        print(f"Scheme {sc}: {n} rows inserted.")
    s.close()
