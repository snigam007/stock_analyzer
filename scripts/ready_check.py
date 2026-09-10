import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db.database import get_global_engine, get_session
from sqlalchemy import text
from datetime import datetime, timedelta
import pandas as pd
import math

engine = get_global_engine()
session = get_session(engine)

# We can test modifying core/sip_audit_backtester.py directly or test it
print("Ready to update core/sip_audit_backtester.py")
session.close()
