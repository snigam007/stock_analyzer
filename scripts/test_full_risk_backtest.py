import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db.database import get_global_engine, get_session
import core.sip_audit_backtester as bt_mod

# Let's write a patched backtester runner in this script to verify before modifying sip_audit_backtester.py
engine = get_global_engine()
session = get_session(engine)

print("Starting verification of backtest simulation...")
session.close()
