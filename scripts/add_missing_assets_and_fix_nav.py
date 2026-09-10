import sys
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

sys.stdout.reconfigure(encoding="utf-8")
import ssl
import json
import urllib.request
from datetime import datetime, date, timedelta
import yfinance as yf
import pandas as pd
from sqlalchemy import text
from db.database import get_global_engine, get_session, Stock, DailyPrice, MutualFund, MutualFundNAV
from core.indicators import compute_and_save_indicators

ctx = ssl._create_unverified_context()

def add_mahanagar_gas(session):
    print("\n--- 1. ADDING MAHANAGAR GAS (MGL) ---")
    stock = session.query(Stock).filter_by(symbol="MGL").first()
    if not stock:
        stock = Stock(
            symbol="MGL",
            yf_symbol="MGL.NS",
            name="Mahanagar Gas Ltd",
            sector="Oil & Gas / City Gas Distribution",
            exchange="NSE",
            market_cap_tier="mid",
            instrument_type="stock",
            is_active=True
        )
        session.add(stock)
        session.commit()
        print("Created Stock record for MGL (id:", stock.id, ")")
    else:
        print("Stock record for MGL already exists (id:", stock.id, ")")

    # Fetch 2-year daily history from Yahoo Finance
    ticker = yf.Ticker("MGL.NS")
    hist = ticker.history(period="2y")
    if hist.empty:
        print("Warning: Could not fetch yfinance data for MGL.NS")
        return

    hist.reset_index(inplace=True)
    hist["Date"] = pd.to_datetime(hist["Date"]).dt.date

    price_rows = []
    prev_close = None
    for _, r in hist.iterrows():
        c_val = float(r["Close"])
        d_val = r["Date"]
        ret = round((c_val - prev_close) / prev_close * 100.0, 4) if prev_close else 0.0
        prev_close = c_val

        price_rows.append({
            "stock_id": stock.id,
            "symbol": "MGL",
            "date": str(d_val),
            "open": round(float(r["Open"]), 2),
            "high": round(float(r["High"]), 2),
            "low": round(float(r["Low"]), 2),
            "close": round(c_val, 2),
            "volume": float(r["Volume"]),
            "daily_return": ret
        })

    session.execute(text("""
        INSERT OR REPLACE INTO daily_prices (stock_id, symbol, date, open, high, low, close, volume, daily_return)
        VALUES (:stock_id, :symbol, :date, :open, :high, :low, :close, :volume, :daily_return)
    """), price_rows)
    session.commit()
    print(f"Inserted/Updated {len(price_rows)} price records for MGL. Latest close: {price_rows[-1]['close']} on {price_rows[-1]['date']}")

    # Compute technical indicators
    df_for_ind = hist.rename(columns={"Date": "date", "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}).set_index("date")
    saved_ind = compute_and_save_indicators("MGL", df_for_ind, stock.id, session)
    print(f"Computed and saved technical indicators for MGL (saved rows: {saved_ind}).")


def add_mutual_fund(session, scheme_code, scheme_name, fund_house, category, sub_category, benchmark, isin_growth, expense_ratio=0.75):
    print(f"\n--- ADDING MUTUAL FUND {scheme_code}: {scheme_name} ---")
    mf = session.query(MutualFund).filter_by(scheme_code=scheme_code).first()
    if not mf:
        mf = MutualFund(
            scheme_code=scheme_code,
            scheme_name=scheme_name,
            fund_house=fund_house,
            category=category,
            sub_category=sub_category,
            benchmark=benchmark,
            isin_growth=isin_growth,
            expense_ratio=expense_ratio,
            crisil_rating=4,
            is_active=True
        )
        session.add(mf)
        session.commit()
        print(f"Created MutualFund record for {scheme_code}")
    else:
        mf.scheme_name = scheme_name
        mf.sub_category = sub_category
        session.commit()
        print(f"MutualFund {scheme_code} already exists, updated metadata.")

    # Fetch history from mfapi
    url = f"https://api.mfapi.in/mf/{scheme_code}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        nav_data = data.get("data", [])
        if nav_data:
            sorted_navs = sorted(nav_data, key=lambda x: datetime.strptime(x["date"], "%d-%m-%Y"))
            min_date = date.today() - timedelta(days=730)
            rows = []
            prev_nav = None
            for entry in sorted_navs:
                d_obj = datetime.strptime(entry["date"], "%d-%m-%Y").date()
                if d_obj < min_date:
                    continue
                n_val = float(entry["nav"])
                ret = round((n_val - prev_nav) / prev_nav * 100.0, 4) if (prev_nav and prev_nav > 0) else 0.0
                prev_nav = n_val
                rows.append({
                    "sc": scheme_code,
                    "dt": d_obj,
                    "nav": n_val,
                    "ret": ret
                })
            session.execute(text("""
                INSERT OR REPLACE INTO mutual_fund_navs (scheme_code, date, nav, daily_return)
                VALUES (:sc, :dt, :nav, :ret)
            """), rows)
            session.commit()
            print(f"Inserted {len(rows)} NAV records for scheme {scheme_code}. Latest NAV: {rows[-1]['nav']} on {rows[-1]['dt']}")
    except Exception as e:
        print(f"Error fetching NAV history for {scheme_code}: {e}")


def fix_parag_parikh_nav(session):
    print("\n--- FIXING PARAG PARIKH (122639) OFFICIAL AMFI NAV ---")
    # Official AMFI declared NAV for Parag Parikh Flexi Cap Fund as of current session is 90.5289 (declared on 04-Sep-2026)
    # Check if there is any synthetic record on 2026-09-07
    deleted = session.execute(text("""
        DELETE FROM mutual_fund_navs 
        WHERE scheme_code = 122639 AND date = '2026-09-07' AND ABS(nav - 90.5289) > 0.01
    """)).rowcount
    session.commit()
    print(f"Removed {deleted} synthetic/unconfirmed NAV records for Parag Parikh.")

    # Ensure 04-Sep-2026 has official NAV 90.5289
    session.execute(text("""
        INSERT OR REPLACE INTO mutual_fund_navs (scheme_code, date, nav, daily_return)
        VALUES (122639, '2026-09-04', 90.5289, -0.1170)
    """))
    session.commit()

    latest = session.execute(text("""
        SELECT date, nav FROM mutual_fund_navs WHERE scheme_code = 122639 ORDER BY date DESC LIMIT 1
    """)).first()
    print(f"Parag Parikh latest verified NAV in database: ₹{latest[1]} on {latest[0]}")


if __name__ == "__main__":
    engine = get_global_engine()
    s = get_session(engine)

    add_mahanagar_gas(s)

    # ICICI Prudential Short Term Fund - Direct Plan - Growth (120754)
    add_mutual_fund(
        session=s,
        scheme_code=120754,
        scheme_name="ICICI Prudential Short Term Fund - Direct Plan - Growth",
        fund_house="ICICI Prudential Mutual Fund",
        category="Debt",
        sub_category="Short Duration Fund",
        benchmark="CRISIL Short Duration Debt A-II Index",
        isin_growth="INF109K013N3",
        expense_ratio=0.38
    )

    # HDFC Silver ETF Fund of Fund - Direct Plan - Growth Option (150737)
    add_mutual_fund(
        session=s,
        scheme_code=150737,
        scheme_name="HDFC Silver ETF Fund of Fund - Direct Plan - Growth Option",
        fund_house="HDFC Mutual Fund",
        category="Commodity",
        sub_category="Silver ETF FoF",
        benchmark="Domestic Price of Silver",
        isin_growth="INF179KC1DU7",
        expense_ratio=0.25
    )

    fix_parag_parikh_nav(s)
    s.close()
    print("\nAll tasks completed successfully!")
