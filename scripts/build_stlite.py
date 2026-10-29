"""Build a static copy of the app that runs fully in the browser (stlite).

Usage: python scripts/build_stlite.py [OUT_DIR]   (default: build/stlite)

The output folder can be served by any static host, for example GitHub Pages.
The app code is NOT changed: app.py and src/ are copied as they are. Uploaded
files never leave the visitor's browser.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

STLITE_VERSION = "1.12.0"
ROOT = Path(__file__).resolve().parent.parent
# Everything the app reads at run time. Tests and docs stay out, except files the app reads.
INCLUDE = ["app.py", "NOTICE", "LICENSE", "samples/fjordvik_logistik_register.csv", "samples/fjordvik_logistik_training_log.csv"]
INCLUDE_DIRS = ["src/usecasereg"]
SKIP = {"__pycache__", ".pyc"}


def collect() -> list[str]:
    paths = list(INCLUDE)
    for d in INCLUDE_DIRS:
        for p in sorted((ROOT / d).rglob("*")):
            if p.is_file() and not (set(p.parts) & SKIP) and p.suffix != ".pyc":
                paths.append(p.relative_to(ROOT).as_posix())
    return paths


def build(out: Path) -> list[str]:
    if out.exists():
        shutil.rmtree(out)
    paths = collect()
    for rel in paths:
        dest = out / "app" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, dest)
    files = {rel: {"url": f"app/{rel}"} for rel in paths}
    html = (ROOT / "stlite" / "index.template.html").read_text(encoding="utf-8")
    html = html.replace("__STLITE_VERSION__", STLITE_VERSION).replace("__FILES__", json.dumps(files, indent=8))
    (out / "index.html").write_text(html, encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    return paths


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "build" / "stlite"
    built = build(target)
    print(f"Built {len(built)} files into {target}")
