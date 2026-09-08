import py_compile
from pathlib import Path

def test_all_pages_compile():
    pages_dir = Path("app/pages")
    page_files = list(pages_dir.glob("*.py"))
    assert len(page_files) >= 17, f"Expected at least 17 pages, got {len(page_files)}"
    
    for pf in page_files:
        print(f"Compiling {pf.name}...")
        py_compile.compile(str(pf), doraise=True)
    
    print("Compiling app/main.py...")
    py_compile.compile("app/main.py", doraise=True)
    print("All UI pages compiled successfully!")

if __name__ == "__main__":
    test_all_pages_compile()
