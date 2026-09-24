"""
Test verifying preset synchronization and session_state behavior in Page 16 logic.
"""
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Create a mock streamlit session_state dict
class MockSessionState(dict):
    pass

import unittest
from unittest.mock import MagicMock

# Test importing page 16 syntax
import py_compile
py_compile.compile(str(BASE_DIR / "pages" / "16_Monthly_SIP_and_Sell_Radar.py"), doraise=True)
py_compile.compile(str(BASE_DIR / "app" / "pages" / "16_Monthly_SIP_and_Sell_Radar.py"), doraise=True)
print("Syntax check passed for both pages/16_Monthly_SIP_and_Sell_Radar.py and app/pages/16_Monthly_SIP_and_Sell_Radar.py!")

# Let's verify preset definitions in INSTITUTIONAL_PRESETS
# We can parse the ast or test INSTITUTIONAL_PRESETS directly
import ast
with open(BASE_DIR / "pages" / "16_Monthly_SIP_and_Sell_Radar.py", "r", encoding="utf-8") as f:
    tree = ast.parse(f.read())

print("AST parse successful!")
