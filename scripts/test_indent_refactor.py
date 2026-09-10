import re
from pathlib import Path

content = Path("app/pages/4_Daily_Top_Stocks.py").read_text(encoding="utf-8")

# Let's find each tab's start index
tab_matches = list(re.finditer(r"^with tabs\[(\d+)\]:\s*$", content, re.MULTILINE))
print(f"Found {len(tab_matches)} tabs")
for m in tab_matches:
    print(m.group(0))
