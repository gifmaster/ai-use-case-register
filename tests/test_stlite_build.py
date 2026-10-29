"""The browser build must copy the app unchanged and include every file it reads."""
import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location("build_stlite", ROOT / "scripts" / "build_stlite.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_build_copies_app_unchanged_and_lists_every_file(tmp_path):
    mod = _load()
    paths = mod.build(tmp_path)
    assert (tmp_path / "app" / "app.py").read_bytes() == (ROOT / "app.py").read_bytes()
    for needed in ["src/usecasereg/rules/schema.yaml", "samples/fjordvik_logistik_register.csv"]:
        assert needed in paths and (tmp_path / "app" / needed).is_file()
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "__FILES__" not in html and "__STLITE_VERSION__" not in html
    listed = json.loads(re.search(r"const files = (\{.*?\n\});", html, re.S).group(1))
    assert set(listed) == set(paths)
    assert not any(p.startswith("tests/") and p not in ["src/usecasereg/rules/schema.yaml", "samples/fjordvik_logistik_register.csv"] for p in paths)
    assert "—" not in html
