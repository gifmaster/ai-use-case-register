"""PDF reports: the PDF must say exactly what the Markdown report says."""

import io
import re
from datetime import date
from pathlib import Path

import pytest

pypdf = pytest.importorskip("pypdf")

from usecasereg import Checks, council_report, read_csv  # noqa: E402
from usecasereg.pdf import fpdf_markdown, markdown_to_pdf, plain, spans  # noqa: E402


def pdf_text(data: bytes) -> str:
    """The PDF's text with the running page header and footer removed, so text that breaks across pages reads on."""
    pages = []
    for n, page in enumerate(pypdf.PdfReader(io.BytesIO(data)).pages):
        lines = (page.extract_text() or "").splitlines()
        lines = [ln for ln in lines if not re.search(r"\|\s+page \d+ of \d+$", ln)]
        if n > 0 and lines:
            lines = lines[1:]  # the running header repeats the title on every page after the first
        pages.append(" ".join(lines))
    return re.sub(r"\s+", " ", " ".join(pages))


def assert_same_content(md: str, data: bytes) -> int:
    """Every heading, bullet, checklist item and quote of the Markdown report is in the PDF."""
    assert data.startswith(b"%PDF")
    text = pdf_text(data)
    checked = 0
    for line in md.splitlines():
        if line.startswith(("#", "- ", ">")):
            body = re.sub(r"\s+", " ", plain(re.sub(r"^(#+ |- \[[ xX]\] |- |> ?)", "", line))).strip()
            if body:
                assert body in text, body
                checked += 1
    return checked


def test_danish_and_markdown_characters_render():
    md = "# Rapport: Østerbro Ølbryggeri\n\n- **Ejer:** Søren Ærø\n- Navn med A--B og __x__\n\n| Kolonne | Værdi |\n|---|---|\n| Åbent | ja |"
    text = pdf_text(markdown_to_pdf(md, "Test"))
    for needle in ("Østerbro Ølbryggeri", "Søren Ærø", "A--B og __x__", "Åbent"):
        assert needle in text, needle


def test_inline_parsing():
    assert spans("a **b** *c* [d](https://x.y)") == [
        ("", "a ", None), ("B", "b", None), ("", " ", None), ("I", "c", None), ("", " ", None), ("", "d", "https://x.y")]
    assert fpdf_markdown("*(Art. 4)* A--B") == "__(Art. 4)__ A\\--B"


ROOT = Path(__file__).parents[1]


def test_council_review_pdf_matches_markdown():
    rows = read_csv((ROOT / "samples" / "fjordvik_logistik_register.csv").read_bytes())
    today = date(2026, 10, 27)
    md = council_report(rows, Checks().run(rows, today), "Fjordvik Logistik", today)
    assert assert_same_content(md, markdown_to_pdf(md, "AI Use Case Register")) >= 5
    text = pdf_text(markdown_to_pdf(md, "AI Use Case Register"))
    assert "UC-005" in text  # table rows are there too
