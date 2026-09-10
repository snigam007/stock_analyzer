import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db.database import get_global_engine, get_session
import core.sip_audit_backtester as bt_mod

engine = get_global_engine()
session = get_session(engine)

# Let's inspect test_blended_sl
print("Testing blended sl...")
session.close()
