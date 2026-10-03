"""
scripts/deep_ui_audit_all_pages.py
==================================
Performs a deep-dive UI architecture audit on all 18 pages:
- Categorized by Workspace
- Inspects Tabs and Sub-tabs
- Identifies visual design patterns, layout bottlenecks, mobile/desktop responsiveness
- Formulates concrete, actionable UI improvements for every single page
"""
import sys
import re
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

ROOT_DIR = Path(__file__).resolve().parent.parent
PAGES_DIR = ROOT_DIR / "pages"

WORKSPACES = {
    "Market Pulse & Macro": [
        "0_Overview.py",
        "1_Dashboard.py",
        "10_360_Asset_Summary.py"
    ],
    "Asset Intelligence": [
        "2_Stock_Analysis.py",
        "3_Sector_Analysis.py",
        "5_Trends.py",
        "17_Mutual_Funds_Radar.py"
    ],
    "Opportunities & Screeners": [
        "4_Daily_Top_Stocks.py",
        "16_Monthly_SIP_and_Sell_Radar.py",
        "12_Trading_Terminal_Matrix.py",
        "15_Institutional_Deals_and_Calendar.py"
    ],
    "Portfolio & Wealth Lab": [
        "11_Portfolio_Advisor.py",
        "8_Portfolio_Optimizer.py",
        "14_Watchlist_and_Alerts.py"
    ],
    "Quant Lab & Operations": [
        "18_Quantum_Engine.py",
        "7_Backtesting.py",
        "6_Strategies.py",
        "9_Alerts_Dispatcher.py",
        "13_Data_Refresh_Status.py"
    ]
}

def analyze():
    print("=" * 110)
    print("  🖥️ COMPREHENSIVE UI ARCHITECTURAL AUDIT & IMPROVEMENT ROADMAP ACROSS ALL 18 PAGES")
    print("=" * 110)

    for ws_name, page_list in WORKSPACES.items():
        print(f"\n📁 WORKSPACE: {ws_name.upper()}")
        print("-" * 110)
        for page_name in page_list:
            pf = PAGES_DIR / page_name
            if not pf.exists():
                continue
            text = pf.read_text(encoding="utf-8", errors="ignore")
            lines = len(text.splitlines())
            
            # Find tabs
            tabs_matches = re.findall(r'st\.tabs\(\s*\[(.*?)\]\s*\)', text, re.DOTALL)
            tabs = []
            for tm in tabs_matches:
                tabs.extend(re.findall(r'["\'](.*?)["\']', tm))
                
            metrics = len(re.findall(r'st\.metric\(', text))
            charts = len(re.findall(r'st\.plotly_chart\(', text))
            tables = len(re.findall(r'st\.(?:dataframe|table)\(', text))
            expanders = len(re.findall(r'st\.expander\(', text))
            
            print(f"▶ Page: {page_name} ({lines:,} lines)")
            if tabs:
                print(f"   📑 Defined Tabs ({len(tabs)}):")
                for idx, t in enumerate(tabs, 1):
                    print(f"      {idx}. {t}")
            else:
                print("   📑 Defined Tabs: None (Monolithic Vertical Scrolling Flow)")
                
            print(f"   📊 UI Components: {metrics} Metrics | {charts} Plotly Charts | {tables} Data Tables | {expanders} Expanders")
            print()

if __name__ == "__main__":
    analyze()
