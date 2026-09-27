"""
Main Streamlit App — Indian Stock Market Analyzer & Institutional Powerhouse
Master UI Entrypoint (Delegates directly to root streamlit_app.py for single codebase parity)
"""
import sys
from pathlib import Path
import runpy

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Execute canonical master entrypoint
runpy.run_path(str(BASE_DIR / "streamlit_app.py"), run_name="__main__")
