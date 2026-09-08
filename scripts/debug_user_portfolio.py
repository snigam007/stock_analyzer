import sys
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

sys.stdout.reconfigure(encoding="utf-8")
from db.database import get_global_engine, get_session
from sqlalchemy import text
from core.portfolio_analyzer import get_searchable_assets_catalog, analyze_custom_portfolio

engine = get_global_engine()
session = get_session(engine)

print("=== 1. CHECK MAHANAGAR GAS IN STOCKS ===")
mgl = session.execute(text("SELECT symbol, name, sector FROM stocks WHERE symbol = 'MGL'")).fetchone()
mgl_p = session.execute(text("SELECT date, close FROM daily_prices WHERE symbol = 'MGL' ORDER BY date DESC LIMIT 1")).fetchone()
print(f"MGL: {mgl} -> Latest price: {mgl_p}")

print("\n=== 2. CHECK ICICI PRUDENTIAL SHORT TERM FUND (120754) ===")
icici = session.execute(text("SELECT scheme_code, scheme_name, category, sub_category FROM mutual_funds WHERE scheme_code = 120754")).fetchone()
icici_n = session.execute(text("SELECT date, nav FROM mutual_fund_navs WHERE scheme_code = 120754 ORDER BY date DESC LIMIT 1")).fetchone()
print(f"ICICI Short Term: {icici} -> Latest NAV: {icici_n}")

print("\n=== 3. CHECK HDFC SILVER ETF FOF (150737) ===")
silver = session.execute(text("SELECT scheme_code, scheme_name, category, sub_category FROM mutual_funds WHERE scheme_code = 150737")).fetchone()
silver_n = session.execute(text("SELECT date, nav FROM mutual_fund_navs WHERE scheme_code = 150737 ORDER BY date DESC LIMIT 1")).fetchone()
print(f"HDFC Silver FoF: {silver} -> Latest NAV: {silver_n}")

print("\n=== 4. CHECK PARAG PARIKH (122639) NAV ===")
pp_nav = session.execute(text("SELECT date, nav, daily_return FROM mutual_fund_navs WHERE scheme_code = 122639 ORDER BY date DESC LIMIT 3")).fetchall()
print("Parag Parikh NAVs in DB:")
for n in pp_nav:
    print(f"  {n[0]}: ₹{n[1]} ({n[2]}%)")

print("\n=== 5. CHECK ASSET SEARCH CATALOG SEARCHABILITY ===")
catalog = get_searchable_assets_catalog(session, category="All Asset Classes")
mgl_in_catalog = [item for item in catalog if "MGL" in item["symbol"] or "Mahanagar" in item["name"]]
icici_in_catalog = [item for item in catalog if item["symbol"] == "120754"]
silver_in_catalog = [item for item in catalog if item["symbol"] == "150737"]
pp_in_catalog = [item for item in catalog if item["symbol"] == "122639"]

print("\n=== 6. SIMULATE FULL USER PORTFOLIO WITH ALL ASSETS ===")
test_portfolio = [
    {"symbol": "MGL", "shares": 50, "buy_price": 1050.0},
    {"symbol": "120754", "shares": 1000, "buy_price": 69.50},
    {"symbol": "150737", "shares": 500, "buy_price": 36.00},
    {"symbol": "MUTHOOTFIN", "shares": 20, "buy_price": 2700.0},
    {"symbol": "122639", "shares": 528, "buy_price": 94.729}
]

res = analyze_custom_portfolio(test_portfolio, session)
print("Portfolio Composite Score:", res["summary"].get("weighted_score", "N/A"), "/ 100")
print("Total Invested: ₹", res["summary"]["total_invested"])
print("Total Current: ₹", res["summary"]["total_current"])
print("Total PnL: ₹", res["summary"]["total_pnl_inr"], f"({res['summary']['total_pnl_pct']}%)")

print("\nHoldings Diagnostics:")
for h in res["holdings"]:
    print(f"  • {h['symbol']} ({h['name'][:35]}): CMP=₹{h['cmp']} | Invested=₹{h['invested_val']} | P&L=₹{h['unrealized_pnl_inr']} ({h['unrealized_pnl_pct']}%) | Advice={h['advice_badge']}")

session.close()
print("\nAll checks completed successfully!")
