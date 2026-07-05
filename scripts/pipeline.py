"""Build the dashboard: inject data/dashboard.json into template.html and write
docs/index.html (the GitHub-Pages output).

The template keeps `INJECTED_DATA = null` and fetches data/ at runtime for
standalone dev; the built page inlines the data so it is self-contained. Only
DERIVED series are in dashboard.json (Norgate personal-use licence).

Run:  python scripts/export_dashboard_data.py   # refresh data first
      python scripts/pipeline.py                # -> docs/index.html
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "template.html"
DATA = ROOT / "data" / "dashboard.json"
OUT = ROOT / "docs" / "index.html"
MARKER = "const INJECTED_DATA = null; /*__DATA__*/"


def main() -> int:
    tpl = TEMPLATE.read_text(encoding="utf-8")
    if MARKER not in tpl:
        raise SystemExit("injection marker not found in template.html")
    data = DATA.read_text(encoding="utf-8").strip()
    built = tpl.replace(MARKER, f"const INJECTED_DATA = {data}; /*__DATA__*/")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(built, encoding="utf-8")
    print(f"template.html : {len(tpl)//1024} KB")
    print(f"dashboard.json: {len(data)//1024} KB")
    print(f"docs/index.html: {len(built)//1024} KB -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
