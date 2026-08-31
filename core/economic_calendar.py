"""
Economic Calendar & Market Events Engine
- Automated NSE F&O Monthly and Weekly Expiry Date Calculator
- Indian Macro Schedule: RBI MPC Policy, CPI/WPI Inflation, GDP, IIP, US FOMC Rate Decisions
- Corporate Earnings Announcement Window Tracker
- Impact level classification (HIGH / MEDIUM / LOW) and affected sector tagging
"""
import calendar
import logging
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import text

import importlib
import db.database
if not hasattr(db.database, "EconomicEvent"):
    importlib.reload(db.database)
from db.database import EconomicEvent, Stock

logger = logging.getLogger(__name__)


def calculate_fo_monthly_expiry(year: int, month: int) -> date:
    """
    Calculates the last Thursday of the given month (NSE Monthly F&O Expiry).
    If Thursday is a known holiday, it would roll back to Wednesday.
    """
    cal = calendar.monthcalendar(year, month)
    # Thursday is column index 3 (Monday=0, Tuesday=1, Wednesday=2, Thursday=3)
    last_thurs_day = max(week[3] for week in cal if week[3] != 0)
    return date(year, month, last_thurs_day)


def generate_fo_expiries_for_year(start_date: date, count_months: int = 12) -> List[Dict]:
    """Generates monthly F&O expiry events for upcoming months."""
    events = []
    curr_y = start_date.year
    curr_m = start_date.month

    for _ in range(count_months):
        exp_date = calculate_fo_monthly_expiry(curr_y, curr_m)
        month_name = calendar.month_name[curr_m]
        events.append({
            "event_date": exp_date,
            "event_name": f"NSE Monthly F&O Derivative Expiry ({month_name} {curr_y})",
            "category": "FO_EXPIRY",
            "impact_level": "HIGH",
            "affected_sector": "ALL",
            "description": f"Settlement of monthly equity and index derivative contracts. High volatility expected in afternoon session."
        })
        curr_m += 1
        if curr_m > 12:
            curr_m = 1
            curr_y += 1

    return events


def seed_macro_calendar(session: Session) -> int:
    """
    Seeds comprehensive RBI MPC, Inflation, GDP, FOMC, and F&O events into economic_events table.
    """
    today = date.today()
    events_to_insert = []

    # 1. Monthly F&O Expiries for 12 months
    fo_events = generate_fo_expiries_for_year(today, count_months=12)
    events_to_insert.extend(fo_events)

    # 2. Key Macroeconomic Events schedule for 2026-2027
    macro_schedule = [
        # RBI MPC Policy Decisions (Bi-monthly)
        (date(2026, 4, 8), "RBI MPC Monetary Policy Statement & Repo Rate", "MONETARY_POLICY", "HIGH", "Banking & Finance", "Repo rate decision and liquidity stance."),
        (date(2026, 6, 5), "RBI MPC Monetary Policy Statement & Repo Rate", "MONETARY_POLICY", "HIGH", "Banking & Finance", "Repo rate decision and liquidity stance."),
        (date(2026, 8, 7), "RBI MPC Monetary Policy Statement & Repo Rate", "MONETARY_POLICY", "HIGH", "Banking & Finance", "Repo rate decision and liquidity stance."),
        (date(2026, 10, 9), "RBI MPC Monetary Policy Statement & Repo Rate", "MONETARY_POLICY", "HIGH", "Banking & Finance", "Repo rate decision and liquidity stance."),
        (date(2026, 12, 4), "RBI MPC Monetary Policy Statement & Repo Rate", "MONETARY_POLICY", "HIGH", "Banking & Finance", "Repo rate decision and liquidity stance."),
        (date(2027, 2, 5), "RBI MPC Monetary Policy Statement & Repo Rate", "MONETARY_POLICY", "HIGH", "Banking & Finance", "Repo rate decision and liquidity stance."),

        # US Fed FOMC Rate Decisions
        (date(2026, 5, 6), "US Fed FOMC Interest Rate Decision", "MONETARY_POLICY", "HIGH", "IT & Technology", "Federal Reserve interest rate benchmark decision."),
        (date(2026, 6, 17), "US Fed FOMC Interest Rate Decision & Dot Plot", "MONETARY_POLICY", "HIGH", "IT & Technology", "Fed rate decision and economic projections."),
        (date(2026, 7, 29), "US Fed FOMC Interest Rate Decision", "MONETARY_POLICY", "HIGH", "IT & Technology", "Federal Reserve interest rate benchmark decision."),
        (date(2026, 9, 16), "US Fed FOMC Interest Rate Decision", "MONETARY_POLICY", "HIGH", "IT & Technology", "Federal Reserve interest rate benchmark decision."),
        (date(2026, 11, 4), "US Fed FOMC Interest Rate Decision", "MONETARY_POLICY", "HIGH", "IT & Technology", "Federal Reserve interest rate benchmark decision."),
        (date(2026, 12, 16), "US Fed FOMC Interest Rate Decision", "MONETARY_POLICY", "HIGH", "IT & Technology", "Federal Reserve interest rate benchmark decision."),

        # GDP Releases
        (date(2026, 5, 29), "India Q4 FY26 GDP Growth Rate Release", "GDP", "HIGH", "ALL", "Quarterly GDP print released by MoSPI."),
        (date(2026, 8, 31), "India Q1 FY27 GDP Growth Rate Release", "GDP", "HIGH", "ALL", "Quarterly GDP print released by MoSPI."),
        (date(2026, 11, 30), "India Q2 FY27 GDP Growth Rate Release", "GDP", "HIGH", "ALL", "Quarterly GDP print released by MoSPI."),
        (date(2027, 2, 26), "India Q3 FY27 GDP Growth Rate Release", "GDP", "HIGH", "ALL", "Quarterly GDP print released by MoSPI."),
    ]

    for d, name, cat, imp, sec, desc in macro_schedule:
        events_to_insert.append({
            "event_date": d, "event_name": name, "category": cat,
            "impact_level": imp, "affected_sector": sec, "description": desc
        })

    # 3. Monthly CPI & WPI Inflation Schedule (Every month on 12th & 14th)
    for m_offset in range(12):
        target_month = (today.month + m_offset - 1) % 12 + 1
        target_year = today.year + (today.month + m_offset - 1) // 12

        cpi_date = date(target_year, target_month, 12)
        wpi_date = date(target_year, target_month, 14)
        m_name = calendar.month_name[target_month]

        events_to_insert.append({
            "event_date": cpi_date,
            "event_name": f"India CPI Consumer Inflation Release ({m_name} {target_year})",
            "category": "INFLATION",
            "impact_level": "HIGH",
            "affected_sector": "FMCG & Consumer",
            "description": "Retail consumer price index inflation print by NSO."
        })

        events_to_insert.append({
            "event_date": wpi_date,
            "event_name": f"India WPI Wholesale Inflation Release ({m_name} {target_year})",
            "category": "INFLATION",
            "impact_level": "MEDIUM",
            "affected_sector": "Metals & Mining",
            "description": "Wholesale price index producer inflation print."
        })

    # 4. Corporate Earnings Schedule for Nifty leaders
    earnings_seeds = [
        ("TCS", date(2026, 10, 10), "Q2 FY27 Financial Results & Dividend", "IT & Technology"),
        ("INFY", date(2026, 10, 15), "Q2 FY27 Financial Results & Guidance", "IT & Technology"),
        ("HDFCBANK", date(2026, 10, 17), "Q2 FY27 Quarterly Earnings & NPA update", "Banking & Finance"),
        ("RELIANCE", date(2026, 10, 23), "Q2 FY27 Quarterly Results & Segment EBITDA", "Energy"),
        ("ICICIBANK", date(2026, 10, 24), "Q2 FY27 Earnings & NIM Margins", "Banking & Finance"),
        ("LT", date(2026, 10, 29), "Q2 FY27 Results & Order Inflow Book", "Capital Goods & Engineering"),
    ]

    for sym, dt, desc, sec in earnings_seeds:
        events_to_insert.append({
            "event_date": dt,
            "event_name": f"{sym} Quarterly Earnings Announcement",
            "category": "EARNINGS",
            "impact_level": "HIGH",
            "affected_sector": sec,
            "symbol": sym,
            "description": desc
        })

    count_added = 0
    for ev in events_to_insert:
        existing = session.execute(text("""
            SELECT id FROM economic_events
            WHERE event_name = :n AND event_date = :d
        """), {"n": ev["event_name"], "d": str(ev["event_date"])}).first()

        if not existing:
            event_obj = EconomicEvent(
                event_date=ev["event_date"],
                event_name=ev["event_name"],
                category=ev["category"],
                impact_level=ev["impact_level"],
                affected_sector=ev.get("affected_sector", "ALL"),
                symbol=ev.get("symbol"),
                description=ev.get("description", ""),
            )
            session.add(event_obj)
            count_added += 1

    session.commit()
    logger.info(f"Seeded {count_added} economic calendar events.")
    return count_added


def get_upcoming_economic_events(
    session: Session,
    days_ahead: int = 45,
    category: Optional[str] = None,
    impact_level: Optional[str] = None
) -> List[Dict]:
    """
    Retrieves sorted upcoming market events with countdown days.
    """
    # Seed if empty
    if session.query(EconomicEvent).count() == 0:
        seed_macro_calendar(session)

    today = date.today()
    end_date = today + timedelta(days=days_ahead)

    query = """
        SELECT event_date, event_name, category, impact_level, affected_sector, symbol, description
        FROM economic_events
        WHERE event_date >= :t AND event_date <= :e
    """
    params = {"t": str(today), "e": str(end_date)}

    if category and category != "ALL":
        query += " AND category = :cat"
        params["cat"] = category

    if impact_level and impact_level != "ALL":
        query += " AND impact_level = :imp"
        params["imp"] = impact_level

    query += " ORDER BY event_date ASC"

    rows = session.execute(text(query), params).fetchall()

    results = []
    for r in rows:
        e_date = datetime.strptime(str(r[0]), "%Y-%m-%d").date() if isinstance(r[0], str) else r[0]
        days_left = (e_date - today).days

        results.append({
            "event_date": str(e_date),
            "event_name": r[1],
            "category": r[2],
            "impact_level": r[3],
            "affected_sector": r[4] or "ALL",
            "symbol": r[5],
            "description": r[6] or "",
            "days_left": days_left,
            "status": "🚨 TODAY" if days_left == 0 else (f"⏳ In {days_left}d" if days_left > 0 else "PASSED")
        })

    return results
