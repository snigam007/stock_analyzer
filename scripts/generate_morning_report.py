"""
Script: generate_morning_report.py
Generates the daily morning HTML quantitative briefing report.
Can be saved to reports/ or opened in browser.
"""
import sys
import io
import os
from pathlib import Path
from datetime import date

# Universal Root Directory Finder
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from db.database import get_global_engine, get_session
from core.report_generator import generate_morning_report_html

def main():
    engine = get_global_engine()
    session = get_session(engine)
    try:
        html = generate_morning_report_html(session)
        reports_dir = BASE_DIR / "reports"
        reports_dir.mkdir(exist_ok=True)
        today_str = date.today().strftime("%Y-%m-%d")
        report_file = reports_dir / f"Morning_Briefing_{today_str}.html"
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"[OK] Daily Morning Report generated successfully: {report_file}")
        return str(report_file)
    finally:
        session.close()

if __name__ == "__main__":
    main()
