"""PDF versions of the Markdown reports.

The PDF is rendered from the Markdown report itself, so the two downloads can never say different things.
Only the small Markdown subset the reports use is understood: headings, bullets, checklist items, quotes,
tables, rules, **bold**, *italic* and [links](url). Fonts: DejaVu Sans (bundled, see fonts/LICENSE-DejaVu.txt),
so Danish and other European scripts render.
"""

from __future__ import annotations

import re
from pathlib import Path

from fpdf import FPDF
from fpdf.fonts import FontFace

FONT_DIR = Path(__file__).parent / "fonts"
FONT = "DejaVu"

INK = (28, 32, 36)
MUTED = (104, 112, 118)
ACCENT = (14, 94, 92)  # deep governance teal, as on senderovitz.eu
RULE = (214, 218, 220)
HEAD_FILL = (232, 240, 239)

INLINE = re.compile(r"\*\*(?P<bold>.+?)\*\*|\[(?P<label>.+?)\]\((?P<url>[^)\s]+)\)|\*(?P<italic>.+?)\*")
TABLE_SEPARATOR = re.compile(r"^\|(\s*:?-+:?\s*\|)+$")


def spans(text: str) -> list[tuple[str, str, str | None]]:
    """Split one line of inline Markdown into (style, text, link) pieces."""
    out, pos = [], 0
    for m in INLINE.finditer(text):
        if m.start() > pos:
            out.append(("", text[pos:m.start()], None))
        if m["bold"] is not None:
            out.append(("B", m["bold"], None))
        elif m["label"] is not None:
            out.append(("", m["label"], m["url"]))
        else:
            out.append(("I", m["italic"], None))
        pos = m.end()
    if pos < len(text):
        out.append(("", text[pos:], None))
    return out


def plain(text: str) -> str:
    """Inline Markdown with the markup removed."""
    return "".join(t for _, t, _ in spans(text))


def _escape(text: str) -> str:
    """Make text literal for fpdf2's markdown, so a name like 'A--B' is not underlined."""
    text = text.replace("\\", "\\\\")
    for marker in ("**", "__", "~~", "--"):
        text = text.replace(marker, "\\" + marker)
    return text


def fpdf_markdown(text: str) -> str:
    """Translate the reports' inline Markdown into fpdf2's dialect (italics are __x__ there)."""
    out = []
    for style, piece, link in spans(text):
        if link:
            out.append(f"[{piece.replace('[', '(').replace(']', ')')}]({link})")
        elif style == "B":
            out.append(f"**{_escape(piece)}**")
        elif style == "I":
            out.append(f"__{_escape(piece)}__")
        else:
            out.append(_escape(piece))
    return "".join(out)


class _Doc(FPDF):
    def __init__(self, title: str, footer: str):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.doc_title, self.footer_text = title, footer
        self.set_margins(18, 18, 18)
        self.set_auto_page_break(True, margin=18)
        for style, file in (("", "DejaVuSans.ttf"), ("B", "DejaVuSans-Bold.ttf"),
                            ("I", "DejaVuSans-Oblique.ttf"), ("BI", "DejaVuSans-BoldOblique.ttf")):
            self.add_font(FONT, style, str(FONT_DIR / file))
        self.set_title(title)
        self.set_creator(footer)
        self.MARKDOWN_LINK_COLOR = ACCENT
        self.MARKDOWN_LINK_UNDERLINE = False

    def header(self):
        if self.page_no() > 1:
            self.set_font(FONT, "", 8)
            self.set_text_color(*MUTED)
            self.set_x(self.l_margin)
            self.cell(0, 4, self.doc_title, new_x="LMARGIN", new_y="NEXT")
            self.ln(4)

    def footer(self):
        self.set_y(-12)
        self.set_font(FONT, "", 8)
        self.set_text_color(*MUTED)
        self.cell(0, 4, f"{self.footer_text}  |  page {self.page_no()} of {{nb}}", align="R")

    def rich(self, text: str, size: float = 10, color=INK, indent: float = 0, marker: str = "", base_style: str = ""):
        """A wrapped line of inline Markdown with an optional hanging marker. Whole words wrap, also across pages."""
        height = size * 0.5
        x = self.l_margin + indent
        self.set_text_color(*color)
        if marker:
            self.set_font(FONT, "", size)
            self.set_x(x)
            self.cell(5, height, marker)
            x += 5
        self.set_font(FONT, base_style, size)
        self.set_x(x)
        self.multi_cell(self.w - self.r_margin - x, height, fpdf_markdown(text), markdown=True, align="L",
                        new_x="LMARGIN", new_y="NEXT")
        self.ln(1)

    def keep_room(self, mm: float):
        if self.get_y() + mm > self.h - self.b_margin:
            self.add_page()

    def heading(self, text: str, level: int):
        if level == 1:
            self.set_font(FONT, "B", 18)
            self.set_text_color(*INK)
            self.multi_cell(0, 8.5, plain(text), new_x="LMARGIN", new_y="NEXT")
            self.set_draw_color(*ACCENT)
            self.set_line_width(0.8)
            self.line(self.l_margin, self.get_y() + 1, self.l_margin + 24, self.get_y() + 1)
            self.ln(6)
            return
        self.keep_room(24 if level == 2 else 18)
        self.ln(3 if level == 2 else 2)
        size, height = (14, 7) if level == 2 else (11.5, 6)
        self.set_font(FONT, "B", size)
        self.set_text_color(*ACCENT)
        self.multi_cell(0, height, plain(text), new_x="LMARGIN", new_y="NEXT")
        self.ln(1)

    def table_block(self, rows: list[list[str]]):
        ncols = max(len(r) for r in rows)
        rows = [r + [""] * (ncols - len(r)) for r in rows]
        self.ln(1)
        self.set_font(FONT, "", 8.5)
        self.set_text_color(*INK)
        self.set_draw_color(*RULE)
        self.set_line_width(0.2)
        with self.table(col_widths=self.column_widths(rows), line_height=4.6, padding=1.4, text_align="LEFT",
                        headings_style=FontFace(emphasis="BOLD", fill_color=HEAD_FILL, color=INK),
                        borders_layout="HORIZONTAL_LINES") as table:
            for r in rows:
                row = table.row()
                for cell in r:
                    row.cell(plain(cell))
        self.ln(3)

    def column_widths(self, rows: list[list[str]], padding: float = 1.4) -> tuple[float, ...]:
        """Widths in mm: every column fits its longest word, and the spare width goes to the columns with long text."""
        mins, wants = [], []
        for col in range(len(rows[0])):
            cells = [plain(r[col]) for r in rows]
            longest = 0.0
            for n, c in enumerate(cells):
                self.set_font(FONT, "B" if n == 0 else "", 8.5)
                longest = max([longest] + [self.get_string_width(w) for w in c.split()])
            mins.append(longest + 2 * padding + 1)
            self.set_font(FONT, "", 8.5)
            wants.append(sum(self.get_string_width(c) for c in cells[1:]) / max(len(cells) - 1, 1) + 2 * padding)
        room = self.epw - sum(mins)
        if room <= 0:
            return tuple(mins)
        extra = [max(w - m, 0) for w, m in zip(wants, mins)]
        total = sum(extra) or len(extra)
        return tuple(m + room * ((e / total) if sum(extra) else 1 / len(extra)) for m, e in zip(mins, extra))

    def rule(self):
        self.ln(2)
        self.set_draw_color(*RULE)
        self.set_line_width(0.3)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(3)


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def markdown_to_pdf(md: str, footer: str = "Report", title: str | None = None) -> bytes:
    """Render one of the tool's Markdown reports as an A4 PDF."""
    lines = md.splitlines()
    first = next((ln[2:] for ln in lines if ln.startswith("# ")), footer)
    doc = _Doc(plain(title or first), footer)
    doc.add_page()
    i = 0
    while i < len(lines):
        ln = lines[i].rstrip()
        if ln.startswith("|"):
            block = []
            while i < len(lines) and lines[i].startswith("|"):
                if not TABLE_SEPARATOR.match(lines[i].strip()):
                    block.append(_cells(lines[i]))
                i += 1
            doc.table_block(block)
            continue
        m = re.match(r"^(#{1,6}) (.*)", ln)
        if m:
            doc.heading(m.group(2), min(len(m.group(1)), 3))
        elif ln.startswith(("- [ ] ", "- [x] ", "- [X] ")):
            doc.rich(ln[6:], size=9.5, marker="☑" if ln[3] in "xX" else "☐", indent=1)
        elif ln.startswith(("- ", "* ")):
            doc.rich(ln[2:], size=10, marker="•", indent=1)
        elif ln.startswith(">"):
            doc.rich(ln[1:].lstrip(), size=9.5, color=MUTED, indent=4, base_style="I")
        elif ln.strip() in ("---", "***"):
            doc.rule()
        elif ln == "":
            doc.ln(1.5)
        else:
            doc.rich(ln)
        i += 1
    return bytes(doc.output())
