import os
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def patch_file(filepath: Path):
    content = filepath.read_text(encoding="utf-8")
    if "try:\n    st.set_page_config" in content or "try:\r\n    st.set_page_config" in content:
        print(f"Already patched: {filepath.name}")
        return

    # Match st.set_page_config(...) including multi-line
    pattern = r"(st\.set_page_config\s*\([\s\S]*?\n\))"
    match = re.search(pattern, content)
    if not match:
        pattern2 = r"(st\.set_page_config\s*\(.*?\))"
        match = re.search(pattern2, content)
        if not match:
            print(f"No set_page_config found: {filepath.name}")
            return

    original_call = match.group(1)
    indented_call = "    " + original_call.replace("\n", "\n    ")
    replacement = f"try:\n{indented_call}\nexcept Exception:\n    pass"

    new_content = content[:match.start()] + replacement + content[match.end():]
    filepath.write_text(new_content, encoding="utf-8")
    print(f"Patched: {filepath.name}")

if __name__ == "__main__":
    base_dir = Path(__file__).resolve().parent.parent
    for folder in [base_dir / "app" / "pages", base_dir / "pages"]:
        if folder.exists():
            for py_file in folder.glob("*.py"):
                patch_file(py_file)
