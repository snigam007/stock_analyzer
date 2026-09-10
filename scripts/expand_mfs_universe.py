"""
Script to expand Curated Mutual Funds universe to ~200 schemes:
1. Keeps the original 28 schemes intact.
2. Selects 172 premier Direct-Growth funds across SEBI categories from top AMCs.
3. Updates CURATED_SCHEMES in core/mf_fetcher.py.
4. Seeds all 200 funds into the database.
5. Populates latest NAVs from AMFI NAVAll.txt and backfills historical NAVs.
6. Generates daily tactical signals for all funds.
"""
import ssl
import json
import urllib.request
from datetime import datetime, date, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import sys
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from db.database import get_global_engine, get_session, MutualFund, MutualFundNAV
import core.mf_fetcher

ctx = ssl._create_unverified_context()

def build_200_mf_universe():
    # 1. Start with the existing 28 curated schemes
    existing = list(core.mf_fetcher.CURATED_SCHEMES)
    existing_codes = set(s["scheme_code"] for s in existing)
    print(f"Loaded {len(existing)} existing schemes.")

    # 2. Fetch latest AMFI data
    print("Fetching AMFI NAVAll.txt...")
    req = urllib.request.Request(
        "https://www.amfiindia.com/spages/NAVAll.txt",
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    )
    with urllib.request.urlopen(req, context=ctx, timeout=20) as resp:
        lines = [l.decode("utf-8", errors="ignore").strip() for l in resp.readlines()]

    TOP_HOUSES = [
        "HDFC", "ICICI Prudential", "SBI", "Nippon India", "Kotak Mahindra", "Axis",
        "Parag Parikh", "Mirae Asset", "Quant", "Motilal Oswal", "DSP", "UTI",
        "Tata", "Bandhan", "Canara Robeco", "Edelweiss", "Invesco", "Franklin Templeton",
        "Sundaram", "JM Financial", "360 ONE", "HSBC", "Mahindra Manulife", "Navi"
    ]

    current_cat = ""
    current_house = ""
    amfi_records = []
    nav_lookup = {}

    for line in lines:
        if not line:
            continue
        if line.startswith("Open Ended Schemes(") or line.startswith("Close Ended Schemes("):
            current_cat = line.split("(")[1].rstrip(")")
        elif ";" not in line:
            current_house = line
        else:
            parts = line.split(";")
            if len(parts) >= 8:
                code_str, isin, isin_reinv, sname, plan, option, nav_str, dt = parts[:8]
                code = int(code_str) if code_str.isdigit() else 0
                if not code:
                    continue
                try:
                    nav_val = float(nav_str)
                    nav_lookup[code] = {
                        "nav": nav_val,
                        "date_str": dt,
                        "name": sname,
                        "isin": isin if isin != "-" else None,
                        "house": current_house
                    }
                except ValueError:
                    continue

                if code in existing_codes:
                    continue

                if ("Direct" in sname or "Direct" in plan) and \
                   ("Growth" in sname or "Growth" in option) and \
                   ("IDCW" not in sname and "Dividend" not in sname and "Bonus" not in sname and "Segregated" not in sname):
                    matched_house = next((th for th in TOP_HOUSES if th.lower() in current_house.lower()), None)
                    if matched_house:
                        amfi_records.append({
                            "code": code,
                            "name": sname,
                            "house": current_house,
                            "amfi_cat": current_cat,
                            "isin": isin if isin != "-" else None,
                            "nav": nav_val,
                            "date": dt
                        })

    print(f"Found {len(amfi_records)} eligible Direct Growth candidates from top AMCs.")

    # Target allocations to reach exactly 200 total (28 + 172 = 200)
    CAT_RULES = [
        ("Flexi / Multi Cap", ["Flexi Cap", "Multi Cap"], "Equity", "Flexi Cap Fund", "NIFTY 500 TRI", 0.70, 16),
        ("Large Cap", ["Large Cap"], "Equity", "Large Cap Fund", "NIFTY 100 TRI", 0.65, 14),
        ("Large & Mid Cap", ["Large & Mid"], "Equity", "Large & Mid Cap Fund", "NIFTY LargeMidcap 250 TRI", 0.65, 14),
        ("Mid Cap", ["Mid Cap"], "Equity", "Mid Cap Fund", "NIFTY Midcap 150 TRI", 0.68, 15),
        ("Small Cap", ["Small Cap"], "Equity", "Small Cap Fund", "NIFTY Smallcap 250 TRI", 0.65, 16),
        ("Focused", ["Focused"], "Equity", "Focused Fund", "NIFTY 500 TRI", 0.70, 14),
        ("ELSS", ["ELSS"], "Equity", "ELSS (Tax Saver)", "NIFTY 500 TRI", 0.65, 16),
        ("Value / Contra", ["Value", "Contra"], "Equity", "Value / Contra Fund", "NIFTY 500 TRI", 0.70, 12),
        ("Sectoral / Thematic", ["Thematic", "Sectoral"], "Sectoral/Thematic", "Sectoral / Thematic Fund", "NIFTY 500 TRI", 0.75, 22),
        ("Index Funds", ["Index Funds"], "Index", "Index Fund", "NIFTY 50 TRI", 0.20, 15),
        ("Hybrid / Multi-Asset", ["Balanced Advantage", "Dynamic Asset Allocation", "Multi Asset", "Aggressive Hybrid", "Arbitrage"], "Hybrid", "Hybrid / Multi-Asset Fund", "CRISIL Hybrid 50+50 Moderate TRI", 0.70, 12),
        ("Debt / Liquid", ["Liquid Fund", "Money Market", "Corporate Bond", "Banking and PSU"], "Debt", "Debt / Liquid Fund", "CRISIL Liquid Debt A-I Index", 0.20, 6),
    ]

    def refine_subcat(name, amfi_cat, default_subcat):
        n = name.lower()
        c = amfi_cat.lower()
        if "flexi cap" in n or "flexi cap" in c: return "Flexi Cap Fund"
        if "multi cap" in n or "multi cap" in c: return "Multi Cap Fund"
        if "large & mid" in n or "large and mid" in n: return "Large & Mid Cap Fund"
        if "large cap" in n or "large cap" in c or "bluechip" in n: return "Large Cap Fund"
        if "mid cap" in n or "midcap" in n: return "Mid Cap Fund"
        if "small cap" in n or "smallcap" in n: return "Small Cap Fund"
        if "focused" in n: return "Focused Fund"
        if "elss" in n or "tax" in n: return "ELSS (Tax Saver)"
        if "contra" in n: return "Contra Fund"
        if "value" in n: return "Value Fund"
        if "tech" in n or "digital" in n: return "Sectoral - Technology"
        if "pharma" in n or "health" in n: return "Sectoral - Healthcare / Pharma"
        if "bank" in n or "financial" in n: return "Sectoral - Banking & Financials"
        if "infra" in n: return "Sectoral - Infrastructure"
        if "auto" in n: return "Sectoral - Automobile"
        if "power" in n or "energy" in n: return "Sectoral - Energy & Power"
        if "consumer" in n or "consumption" in n: return "Thematic - Consumption"
        if "manufacturing" in n: return "Thematic - Manufacturing"
        if "balanced advantage" in n or "dynamic" in n: return "Dynamic Asset Allocation / Balanced Advantage"
        if "multi asset" in n: return "Multi Asset Allocation"
        if "arbitrage" in n: return "Arbitrage Fund"
        if "aggressive" in n or "hybrid equity" in n: return "Aggressive Hybrid Fund"
        if "liquid" in n: return "Liquid Fund"
        if "money market" in n: return "Money Market Fund"
        if "corporate bond" in n: return "Corporate Bond Fund"
        if "banking and psu" in n: return "Banking and PSU Debt Fund"
        if "index" in n or "nifty" in n or "sensex" in n or "nasdaq" in n: return "Index Fund"
        if "thematic" in c: return "Thematic Fund"
        if "sectoral" in c: return "Sectoral Fund"
        return default_subcat or "Equity Scheme"

    new_selected = []
    used_codes = set(existing_codes)

    for label, match_terms, cat, subcat, bench, ter, max_take in CAT_RULES:
        taken = 0
        for r in amfi_records:
            if r["code"] in used_codes:
                continue
            match_cat = any(t.lower() in r["amfi_cat"].lower() for t in match_terms)
            match_name = any(t.lower() in r["name"].lower() for t in match_terms)
            if match_cat or match_name:
                final_subcat = refine_subcat(r["name"], r["amfi_cat"], subcat)
                new_selected.append({
                    "scheme_code": r["code"],
                    "scheme_name": r["name"],
                    "fund_house": r["house"],
                    "category": cat,
                    "sub_category": final_subcat,
                    "benchmark": bench,
                    "isin_growth": r["isin"],
                    "expense_ratio": ter,
                    "crisil_rating": 4
                })
                used_codes.add(r["code"])
                taken += 1
                if taken >= max_take:
                    break
        print(f"  {label}: {taken}/{max_take}")

    all_schemes = existing + new_selected
    print(f"Final combined universe length: {len(all_schemes)} (Existing: {len(existing)}, New: {len(new_selected)})")
    return all_schemes, nav_lookup


def update_core_mf_fetcher(all_schemes):
    fetcher_path = BASE_DIR / "core" / "mf_fetcher.py"
    with open(fetcher_path, "r", encoding="utf-8") as f:
        content = f.read()

    start_idx = content.find("CURATED_SCHEMES = [")
    if start_idx == -1:
        raise ValueError("Could not find CURATED_SCHEMES definition in core/mf_fetcher.py")

    end_marker = "\ndef seed_curated_mutual_funds"
    end_idx = content.find(end_marker, start_idx)
    if end_idx == -1:
        raise ValueError("Could not find end of CURATED_SCHEMES in core/mf_fetcher.py")

    schemes_repr = "CURATED_SCHEMES = " + json.dumps(all_schemes, indent=4) + "\n"

    new_content = content[:start_idx] + schemes_repr + content[end_idx:]
    with open(fetcher_path, "w", encoding="utf-8") as f:
        f.write(new_content)
    print(f"Successfully updated {fetcher_path} with {len(all_schemes)} schemes.")


from sqlalchemy import text


def seed_and_sync_all(all_schemes, nav_lookup):
    engine = get_global_engine()
    session = get_session(engine)

    import importlib
    import core.mf_fetcher
    importlib.reload(core.mf_fetcher)

    # 1. Seed schemes
    print("Seeding curated mutual funds into database...")
    inserted = core.mf_fetcher.seed_curated_mutual_funds(session)
    print(f"Seeded/updated {inserted} schemes in mutual_funds table.")

    # 2. Insert today's AMFI NAV for every scheme if missing
    print("Seeding latest AMFI NAVs...")
    today_dt = date.today()
    nav_inserted = 0
    for s in all_schemes:
        code = s["scheme_code"]
        info = nav_lookup.get(code)
        if not info:
            continue
        try:
            # Check if this scheme already has today's NAV or any NAV
            existing_nav = session.execute(
                text("SELECT nav FROM mutual_fund_navs WHERE scheme_code = :sc ORDER BY date DESC LIMIT 1"),
                {"sc": code}
            ).scalar()

            try:
                dt_parsed = datetime.strptime(info["date_str"], "%d-%b-%Y").date()
            except Exception:
                dt_parsed = today_dt
            
            # Check if entry exists for this exact date
            exact_exists = session.execute(
                text("SELECT 1 FROM mutual_fund_navs WHERE scheme_code = :sc AND date = :dt"),
                {"sc": code, "dt": dt_parsed}
            ).scalar()

            if not exact_exists:
                daily_ret = 0.0
                if existing_nav and existing_nav > 0:
                    daily_ret = round((info["nav"] - existing_nav) / existing_nav * 100, 4)

                session.execute(text("""
                    INSERT INTO mutual_fund_navs (scheme_code, date, nav, daily_return)
                    VALUES (:sc, :dt, :nav, :ret)
                """), {
                    "sc": code,
                    "dt": dt_parsed,
                    "nav": info["nav"],
                    "ret": daily_ret
                })
                nav_inserted += 1
        except Exception as e:
            print(f"Error seeding NAV for scheme {code}: {e}")
            continue

    session.commit()
    print(f"Seeded {nav_inserted} latest NAV records from AMFI.")

    # 3. Backfill history for schemes with fewer than 50 days of data
    print("Checking schemes that need historical NAV backfill...")
    schemes_to_backfill = []
    for s in all_schemes:
        code = s["scheme_code"]
        cnt = session.execute(
            text("SELECT COUNT(*) FROM mutual_fund_navs WHERE scheme_code = :sc"),
            {"sc": code}
        ).scalar()
        if cnt < 50:
            schemes_to_backfill.append(code)

    print(f"{len(schemes_to_backfill)} schemes need historical NAV backfill from mfapi.in.")

    def fetch_one(code):
        try:
            url = f"https://api.mfapi.in/mf/{code}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return code, data.get("data", [])
        except Exception:
            return code, []

    if schemes_to_backfill:
        print(f"Fetching historical NAVs in parallel (max 12 workers) for {len(schemes_to_backfill)} schemes...")
        with ThreadPoolExecutor(max_workers=12) as executor:
            future_to_code = {executor.submit(fetch_one, sc): sc for sc in schemes_to_backfill}
            completed = 0
            for future in as_completed(future_to_code):
                sc, raw_navs = future.result()
                completed += 1
                if completed % 25 == 0 or completed == len(schemes_to_backfill):
                    print(f"  Progress: {completed}/{len(schemes_to_backfill)} downloaded.")

                if raw_navs:
                    sorted_navs = sorted(raw_navs, key=lambda x: datetime.strptime(x["date"], "%d-%m-%Y"))
                    # Filter for last 2 years
                    min_date = date.today() - timedelta(days=730)
                    rows_to_insert = []
                    prev_nav = None
                    for entry in sorted_navs:
                        try:
                            d_obj = datetime.strptime(entry["date"], "%d-%m-%Y").date()
                            if d_obj < min_date:
                                continue
                            n_val = float(entry["nav"])
                            ret = round((n_val - prev_nav) / prev_nav * 100, 4) if (prev_nav and prev_nav > 0) else 0.0
                            prev_nav = n_val
                            rows_to_insert.append({
                                "sc": sc,
                                "dt": d_obj,
                                "nav": n_val,
                                "ret": ret
                            })
                        except Exception:
                            continue

                    if rows_to_insert:
                        # Batch insert ignoring duplicates
                        session.execute(text("""
                            INSERT OR IGNORE INTO mutual_fund_navs (scheme_code, date, nav, daily_return)
                            VALUES (:sc, :dt, :nav, :ret)
                        """), rows_to_insert)
                        session.commit()

    # 4. Generate daily signals
    print("Generating daily quantitative MF signals for all 200 schemes...")
    import core.mf_signals
    importlib.reload(core.mf_signals)
    sigs = core.mf_signals.generate_daily_mf_signals(session)
    print(f"Generated {len(sigs)} tactical signals.")

    total_mf_count = session.execute(text("SELECT COUNT(*) FROM mutual_funds")).scalar()
    total_nav_funds = session.execute(text("SELECT COUNT(DISTINCT scheme_code) FROM mutual_fund_navs")).scalar()
    print(f"Summary: Total MFs in DB = {total_mf_count}, Funds with NAVs = {total_nav_funds}")
    session.close()


if __name__ == "__main__":
    schemes, nav_lookup = build_200_mf_universe()
    update_core_mf_fetcher(schemes)
    seed_and_sync_all(schemes, nav_lookup)

