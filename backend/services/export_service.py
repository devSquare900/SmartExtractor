"""
SmartExtractor Enterprise Export Service
Compiles AI chat responses into presentation-ready Excel (.xlsx), Word (.docx), and PDF (.pdf) documents.
Zero disk footprint: compiles entirely in-memory using BytesIO.
"""

import io
import re
from datetime import datetime
from typing import Dict, Any, List, Tuple

# Excel
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# Word
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls

# PDF (ReportLab)
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, KeepTogether
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas


# ---------------------------------------------------------------------------
# 1. MARKDOWN PARSER FOR CHAT RESPONSES
# ---------------------------------------------------------------------------

def parse_chat_markdown(markdown_text: str) -> Dict[str, Any]:
    """
    Parses chat markdown into structured document blocks:
    - title
    - summary_paragraphs (lead text)
    - tables (headers + rows)
    - bullets (lead_bold + text)
    - citations
    """
    if not markdown_text:
        return {"title": "AI Intelligence Report", "paragraphs": [], "tables": [], "bullets": [], "citations": []}

    lines = markdown_text.strip().splitlines()
    
    title = None
    paragraphs: List[str] = []
    tables: List[Dict[str, Any]] = []
    bullets: List[Tuple[str, str]] = []
    citations: List[str] = []
    
    in_table = False
    current_table_lines: List[str] = []
    in_sources = False

    for line in lines:
        stripped = line.strip()

        # Detect sources divider
        if stripped in ("---", "***") or "Sources:" in stripped:
            if "Sources:" in stripped or stripped.startswith("**Sources"):
                in_sources = True
            continue

        if in_sources:
            if stripped.startswith(("•", "-", "*")):
                clean_cite = re.sub(r"^[•\-\*]\s*", "", stripped)
                clean_cite = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", clean_cite)
                citations.append(clean_cite)
            elif stripped:
                citations.append(stripped)
            continue

        # Detect Markdown Table Rows
        if stripped.startswith("|") and stripped.endswith("|"):
            in_table = True
            current_table_lines.append(stripped)
            continue
        else:
            if in_table:
                # End of table
                parsed_table = _parse_markdown_table_block(current_table_lines)
                if parsed_table:
                    tables.append(parsed_table)
                current_table_lines = []
                in_table = False

        if not stripped:
            continue

        # Extract Title (# ...)
        if stripped.startswith("# ") and not title:
            title = stripped[2:].strip()
            continue
        elif stripped.startswith("## ") and not title:
            title = stripped[3:].strip()
            continue

        # Bullets
        if re.match(r"^[•\-\*]\s+", stripped):
            bullet_body = re.sub(r"^[•\-\*]\s+", "", stripped)
            # Check for bold lead: **Label:** rest
            match = re.match(r"^\*\*(.*?)\*\*:?\s*(.*)$", bullet_body)
            if match:
                bullets.append((match.group(1).strip(), match.group(2).strip()))
            else:
                bullets.append(("", bullet_body))
            continue

        # Numbered list
        num_match = re.match(r"^\d+\.\s+\*\*(.*?)\*\*:?\s*(.*)$", stripped)
        if num_match:
            bullets.append((num_match.group(1).strip(), num_match.group(2).strip()))
            continue

        # Normal paragraph (clean bold markdown if any)
        clean_para = re.sub(r"\*\*(.*?)\*\*", r"\1", stripped)
        paragraphs.append(clean_para)

    if in_table and current_table_lines:
        parsed_table = _parse_markdown_table_block(current_table_lines)
        if parsed_table:
            tables.append(parsed_table)

    return {
        "title": title or "Executive Intelligence Report",
        "paragraphs": paragraphs,
        "tables": tables,
        "bullets": bullets,
        "citations": citations,
    }


def _parse_markdown_table_block(lines: List[str]) -> Dict[str, Any] | None:
    """Parses raw lines of a Markdown table into headers and data rows."""
    if len(lines) < 2:
        return None

    def split_row(row_str: str) -> List[str]:
        # Split by pipe, drop empty outer splits
        parts = row_str.strip().split("|")
        if parts and not parts[0].strip():
            parts = parts[1:]
        if parts and not parts[-1].strip():
            parts = parts[:-1]
        return [p.strip() for p in parts]

    raw_headers = split_row(lines[0])
    # Line 1 is usually separator (|---|---|)
    start_idx = 1
    if len(lines) > 1 and re.match(r"^\|?\s*[-:]+[-| :]*$", lines[1]):
        start_idx = 2

    # Clean headers of markdown bold/italic
    clean_headers = [re.sub(r"[\*_]", "", h) for h in raw_headers]

    rows = []
    for line in lines[start_idx:]:
        if not line.strip():
            continue
        cells = split_row(line)
        clean_cells = [re.sub(r"\*\*(.*?)\*\*", r"\1", c) for c in cells]
        # Pad cells if necessary
        while len(clean_cells) < len(clean_headers):
            clean_cells.append("")
        rows.append(clean_cells[:len(clean_headers)])

    if not rows and not clean_headers:
        return None

    return {"headers": clean_headers, "rows": rows}


# ---------------------------------------------------------------------------
# 2. NUMERIC & CURRENCY VALUE DETECTION (FOR EXCEL)
# ---------------------------------------------------------------------------

def _parse_excel_cell_value(val: str) -> Tuple[Any, str | None]:
    """
    Detects if a string is a Currency, Integer, Float, or Date.
    Returns (python_val, excel_number_format_or_None).
    """
    if not isinstance(val, str):
        return val, None

    cleaned = val.strip()
    if not cleaned:
        return "", None

    # Date ISO format YYYY-MM-DD
    if re.match(r"^\d{4}-\d{2}-\d{2}$", cleaned):
        return cleaned, "yyyy-mm-dd"

    # Percentage: e.g. 15.5% or 95%
    pct_match = re.match(r"^([\d,]+(?:\.\d+)?)\s*%$", cleaned)
    if pct_match:
        try:
            num = float(pct_match.group(1).replace(",", "")) / 100.0
            return num, "0.0%"
        except ValueError:
            pass

    # Currency with PKR / USD / $ / Rs / EUR
    curr_match = re.match(r"^(PKR|\$|€|£|Rs\.?)\s*([\d,]+(?:\.\d+)?)$", cleaned, re.IGNORECASE)
    if curr_match:
        curr_symbol = curr_match.group(1).upper()
        num_str = curr_match.group(2).replace(",", "")
        try:
            val_num = float(num_str) if "." in num_str else int(num_str)
            fmt = f'"{curr_symbol} " #,##0.00' if "." in num_str else f'"{curr_symbol} " #,##0'
            return val_num, fmt
        except ValueError:
            pass

    # Raw numbers with commas: e.g. 1,250,000 or 450.50
    if re.match(r"^-?[\d,]+(?:\.\d+)?$", cleaned) and ("," in cleaned or len(cleaned) < 12):
        num_str = cleaned.replace(",", "")
        try:
            if "." in num_str:
                return float(num_str), "#,##0.00"
            return int(num_str), "#,##0"
        except ValueError:
            pass

    return cleaned, None


# ---------------------------------------------------------------------------
# 3. EXCEL BUILDER (.xlsx via openpyxl)
# ---------------------------------------------------------------------------

def build_excel(data: Dict[str, Any], query: str = "", scope: str = "") -> bytes:
    """
    Builds a corporate Wall-Street quality Excel workbook from structured data.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Intelligence Report"
    ws.views.sheetView[0].showGridLines = True

    # Color Tokens
    NAVY_HEADER = "0F172A"      # Slate 900
    ICE_BLUE_ZEBRA = "F8FAFC"   # Slate 50
    ACCENT_BLUE = "2563EB"      # Royal Blue 600
    BORDER_GRAY = "E2E8F0"      # Slate 200
    TEXT_MUTED = "64748B"       # Slate 500

    thin_border = Border(
        left=Side(style="thin", color=BORDER_GRAY),
        right=Side(style="thin", color=BORDER_GRAY),
        top=Side(style="thin", color=BORDER_GRAY),
        bottom=Side(style="thin", color=BORDER_GRAY),
    )

    current_row = 1

    # 1. Company Banner & Report Title
    ws.cell(row=current_row, column=1, value="SMARTEXTRACTOR AI · EXECUTIVE INTELLIGENCE REPORT")
    ws.cell(row=current_row, column=1).font = Font(name="Calibri", size=14, bold=True, color="0F172A")
    current_row += 1

    # 2. Subtitle with Query and Metadata
    timestamp_str = datetime.now().strftime("%d %b %Y, %I:%M %p")
    meta_line = f"Generated: {timestamp_str} | Scope: {scope or 'Contract Portfolio'}"
    if query:
        meta_line += f' | Query: "{query}"'
    ws.cell(row=current_row, column=1, value=meta_line)
    ws.cell(row=current_row, column=1).font = Font(name="Calibri", size=9.5, italic=True, color=TEXT_MUTED)
    current_row += 2  # Blank row

    # 3. Executive Summary / Lead Paragraphs (if any)
    if data.get("paragraphs"):
        ws.cell(row=current_row, column=1, value="EXECUTIVE SUMMARY")
        ws.cell(row=current_row, column=1).font = Font(name="Calibri", size=11, bold=True, color=ACCENT_BLUE)
        current_row += 1
        for p in data["paragraphs"]:
            ws.cell(row=current_row, column=1, value=p)
            ws.cell(row=current_row, column=1).font = Font(name="Calibri", size=10.5, color="1E293B")
            ws.cell(row=current_row, column=1).alignment = Alignment(wrap_text=True)
            current_row += 1
        current_row += 1

    # 4. Tables
    header_row_indices = []
    if data.get("tables"):
        for table in data["tables"]:
            headers = table.get("headers", [])
            rows = table.get("rows", [])
            if not headers:
                continue

            header_row_idx = current_row
            header_row_indices.append(header_row_idx)

            # Render Table Headers
            for col_idx, h in enumerate(headers, start=1):
                cell = ws.cell(row=header_row_idx, column=col_idx, value=h.upper())
                cell.font = Font(name="Calibri", size=10.5, bold=True, color="FFFFFF")
                cell.fill = PatternFill(start_color=NAVY_HEADER, end_color=NAVY_HEADER, fill_type="solid")
                cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
                cell.border = thin_border
            ws.row_dimensions[header_row_idx].height = 26
            current_row += 1

            # Render Rows with Zebra Striping
            for row_idx, r_data in enumerate(rows):
                is_zebra = (row_idx % 2 == 1)
                row_fill = PatternFill(start_color=ICE_BLUE_ZEBRA, end_color=ICE_BLUE_ZEBRA, fill_type="solid") if is_zebra else None

                for col_idx, cell_str in enumerate(r_data, start=1):
                    val, num_format = _parse_excel_cell_value(cell_str)
                    cell = ws.cell(row=current_row, column=col_idx, value=val)
                    cell.font = Font(name="Calibri", size=10.5, color="1E293B")
                    if row_fill:
                        cell.fill = row_fill
                    cell.border = thin_border

                    # Alignment and number formatting
                    if num_format:
                        cell.number_format = num_format
                        cell.alignment = Alignment(horizontal="right", vertical="center")
                    elif isinstance(val, (int, float)):
                        cell.alignment = Alignment(horizontal="right", vertical="center")
                    else:
                        cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)

                ws.row_dimensions[current_row].height = 21
                current_row += 1

            current_row += 1

    # 5. Bullets / Recommendations (if any)
    if data.get("bullets"):
        ws.cell(row=current_row, column=1, value="KEY FINDINGS & RECOMMENDATIONS")
        ws.cell(row=current_row, column=1).font = Font(name="Calibri", size=11, bold=True, color=ACCENT_BLUE)
        current_row += 1
        for lead, body in data["bullets"]:
            bullet_text = f"• {lead}: {body}" if lead else f"• {body}"
            ws.cell(row=current_row, column=1, value=bullet_text)
            ws.cell(row=current_row, column=1).font = Font(name="Calibri", size=10, color="334155")
            current_row += 1
        current_row += 1

    # 6. Citations & Audit Trail (if any)
    if data.get("citations"):
        ws.cell(row=current_row, column=1, value="AUDIT SOURCES & CITATIONS")
        ws.cell(row=current_row, column=1).font = Font(name="Calibri", size=9.5, bold=True, color=TEXT_MUTED)
        current_row += 1
        for cite in data["citations"]:
            ws.cell(row=current_row, column=1, value=f"[Source] {cite}")
            ws.cell(row=current_row, column=1).font = Font(name="Calibri", size=9, italic=True, color=TEXT_MUTED)
            current_row += 1

    # Auto-calculate and set generous Column Widths
    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            # Skip title row from calculation
            if cell.row in (1, 2):
                continue
            v = str(cell.value or "")
            if len(v) > max_len:
                max_len = len(v)
        # Apply padding and clamp
        ws.column_dimensions[col_letter].width = max(min(max_len + 4, 55), 14)

    # Freeze Header Panes at first table
    if header_row_indices:
        ws.freeze_panes = f"A{header_row_indices[0] + 1}"

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


# ---------------------------------------------------------------------------
# 4. WORD BUILDER (.docx via python-docx)
# ---------------------------------------------------------------------------

def _set_cell_background(cell, hex_color: str):
    """Sets background shading of a docx table cell."""
    shading_xml = f'<w:shd {nsdecls("w")} w:fill="{hex_color}"/>'
    cell._tc.get_or_add_tcPr().append(parse_xml(shading_xml))


def _set_cell_margins(cell, top=100, bottom=100, left=150, right=150):
    """Sets cell padding in twips (1/20th of a pt)."""
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = parse_xml(
        f'<w:tcMar {nsdecls("w")}>'
        f'<w:top w:w="{top}" w:type="dxa"/>'
        f'<w:bottom w:w="{bottom}" w:type="dxa"/>'
        f'<w:left w:w="{left}" w:type="dxa"/>'
        f'<w:right w:w="{right}" w:type="dxa"/>'
        f'</w:tcMar>'
    )
    tcPr.append(tcMar)


def build_word(data: Dict[str, Any], query: str = "", scope: str = "") -> bytes:
    """
    Builds an executive-level Word (.docx) briefing memo.
    """
    doc = Document()

    # 1-inch margins
    sections = doc.sections
    for s in sections:
        s.top_margin = Inches(1.0)
        s.bottom_margin = Inches(1.0)
        s.left_margin = Inches(1.0)
        s.right_margin = Inches(1.0)

    # Header / Footer
    footer = sections[0].footer
    footer_para = footer.paragraphs[0]
    footer_para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    f_run = footer_para.add_run("SmartExtractor AI Intelligence Briefing · Strictly Confidential")
    f_run.font.size = Pt(8.5)
    f_run.font.color.rgb = RGBColor(148, 163, 184)

    # Title & Metadata
    title_text = data.get("title") or "Executive Contract Intelligence Briefing"
    title_p = doc.add_paragraph()
    title_run = title_p.add_run(title_text)
    title_run.font.name = "Calibri"
    title_run.font.size = Pt(22)
    title_run.font.bold = True
    title_run.font.color.rgb = RGBColor(15, 23, 42)  # Slate 900
    title_p.paragraph_format.space_after = Pt(2)

    timestamp_str = datetime.now().strftime("%d %B %Y, %I:%M %p")
    sub_p = doc.add_paragraph()
    sub_run = sub_p.add_run(f"Generated: {timestamp_str}  |  Scope: {scope or 'All Contracts'}")
    sub_run.font.name = "Calibri"
    sub_run.font.size = Pt(9.5)
    sub_run.font.color.rgb = RGBColor(100, 116, 139)
    if query:
        q_run = sub_p.add_run(f'\nOriginal Query: "{query}"')
        q_run.font.size = Pt(9.5)
        q_run.font.italic = True
        q_run.font.color.rgb = RGBColor(71, 85, 105)
    sub_p.paragraph_format.space_after = Pt(14)

    # Executive Summary (Callout Shaded Box)
    if data.get("paragraphs"):
        callout_table = doc.add_table(rows=1, cols=1)
        callout_table.alignment = WD_TABLE_ALIGNMENT.CENTER
        callout_cell = callout_table.cell(0, 0)
        _set_cell_background(callout_cell, "F8FAFC")
        _set_cell_margins(callout_cell, top=140, bottom=140, left=200, right=200)

        # 3pt blue left border
        left_border_xml = (
            f'<w:tcBorders {nsdecls("w")}>'
            f'<w:left w:val="single" w:sz="24" w:space="0" w:color="2563EB"/>'
            f'<w:top w:val="none"/>'
            f'<w:bottom w:val="none"/>'
            f'<w:right w:val="none"/>'
            f'</w:tcBorders>'
        )
        callout_cell._tc.get_or_add_tcPr().append(parse_xml(left_border_xml))

        c_para = callout_cell.paragraphs[0]
        c_lead = c_para.add_run("EXECUTIVE SUMMARY\n")
        c_lead.font.name = "Calibri"
        c_lead.font.size = Pt(10.5)
        c_lead.font.bold = True
        c_lead.font.color.rgb = RGBColor(37, 99, 235)

        for p_idx, para_text in enumerate(data["paragraphs"]):
            if p_idx > 0:
                p_elem = callout_cell.add_paragraph()
            else:
                p_elem = c_para
            p_run = p_elem.add_run(para_text)
            p_run.font.name = "Calibri"
            p_run.font.size = Pt(10)
            p_run.font.color.rgb = RGBColor(30, 41, 59)
            p_elem.paragraph_format.space_after = Pt(4)

        doc.add_paragraph().paragraph_format.space_after = Pt(12)

    # Tables
    if data.get("tables"):
        for t_idx, table_data in enumerate(data["tables"]):
            headers = table_data.get("headers", [])
            rows = table_data.get("rows", [])
            if not headers:
                continue

            tbl = doc.add_table(rows=len(rows) + 1, cols=len(headers))
            tbl.alignment = WD_TABLE_ALIGNMENT.CENTER

            # Header row
            hdr_cells = tbl.rows[0].cells
            for col_idx, h_text in enumerate(headers):
                cell = hdr_cells[col_idx]
                _set_cell_background(cell, "0F172A")
                _set_cell_margins(cell, top=120, bottom=120, left=120, right=120)
                hp = cell.paragraphs[0]
                hr = hp.add_run(h_text.upper())
                hr.font.name = "Calibri"
                hr.font.size = Pt(9.5)
                hr.font.bold = True
                hr.font.color.rgb = RGBColor(255, 255, 255)

            # Data rows
            for r_idx, row_values in enumerate(rows):
                row_cells = tbl.rows[r_idx + 1].cells
                is_zebra = (r_idx % 2 == 1)
                bg_color = "F8FAFC" if is_zebra else "FFFFFF"

                for col_idx, cell_text in enumerate(row_values):
                    cell = row_cells[col_idx]
                    _set_cell_background(cell, bg_color)
                    _set_cell_margins(cell, top=90, bottom=90, left=120, right=120)

                    # Subtle border
                    border_xml = (
                        f'<w:tcBorders {nsdecls("w")}>'
                        f'<w:top w:val="single" w:sz="4" w:space="0" w:color="E2E8F0"/>'
                        f'<w:bottom w:val="single" w:sz="4" w:space="0" w:color="E2E8F0"/>'
                        f'<w:left w:val="single" w:sz="4" w:space="0" w:color="E2E8F0"/>'
                        f'<w:right w:val="single" w:sz="4" w:space="0" w:color="E2E8F0"/>'
                        f'</w:tcBorders>'
                    )
                    cell._tc.get_or_add_tcPr().append(parse_xml(border_xml))

                    cp = cell.paragraphs[0]
                    cr = cp.add_run(str(cell_text))
                    cr.font.name = "Calibri"
                    cr.font.size = Pt(9.5)
                    cr.font.color.rgb = RGBColor(30, 41, 59)

            doc.add_paragraph().paragraph_format.space_after = Pt(14)

    # Bullets / Key Points
    if data.get("bullets"):
        sec_p = doc.add_paragraph()
        sec_r = sec_p.add_run("KEY FINDINGS & STRATEGIC RECOMMENDATIONS")
        sec_r.font.name = "Calibri"
        sec_r.font.size = Pt(12)
        sec_r.font.bold = True
        sec_r.font.color.rgb = RGBColor(15, 23, 42)
        sec_p.paragraph_format.space_after = Pt(6)

        for lead, body in data["bullets"]:
            bp = doc.add_paragraph(style="List Bullet")
            if lead:
                lr = bp.add_run(f"{lead}: ")
                lr.font.name = "Calibri"
                lr.font.size = Pt(10)
                lr.font.bold = True
                lr.font.color.rgb = RGBColor(15, 23, 42)
            br = bp.add_run(body)
            br.font.name = "Calibri"
            br.font.size = Pt(10)
            br.font.color.rgb = RGBColor(51, 65, 85)
            bp.paragraph_format.space_after = Pt(3)

        doc.add_paragraph().paragraph_format.space_after = Pt(12)

    # Citations
    if data.get("citations"):
        cit_p = doc.add_paragraph()
        cit_r = cit_p.add_run("AUDIT SOURCES")
        cit_r.font.name = "Calibri"
        cit_r.font.size = Pt(10)
        cit_r.font.bold = True
        cit_r.font.color.rgb = RGBColor(100, 116, 139)
        cit_p.paragraph_format.space_after = Pt(4)

        for c_text in data["citations"]:
            cp = doc.add_paragraph()
            cr = cp.add_run(f"• {c_text}")
            cr.font.name = "Calibri"
            cr.font.size = Pt(8.5)
            cr.font.italic = True
            cr.font.color.rgb = RGBColor(100, 116, 139)
            cp.paragraph_format.space_after = Pt(2)

    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


# ---------------------------------------------------------------------------
# 5. PDF BUILDER (.pdf via ReportLab)
# ---------------------------------------------------------------------------

class NumberedCanvas(canvas.Canvas):
    """Dynamic two-pass canvas that renders Page X of Y on all pages."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_footer(num_pages)
            super().showPage()
        super().save()

    def draw_footer(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 8.5)
        self.setFillColor(colors.HexColor("#64748B"))
        self.setStrokeColor(colors.HexColor("#E2E8F0"))
        self.setLineWidth(0.5)

        # Thin footer rule
        self.line(40, 42, self._pagesize[0] - 40, 42)
        self.drawString(40, 28, "SmartExtractor AI Intelligence Briefing · Confidential")
        self.drawRightString(self._pagesize[0] - 40, 28, f"Page {self._pageNumber} of {page_count}")
        self.restoreState()


def build_pdf(data: Dict[str, Any], query: str = "", scope: str = "") -> bytes:
    """
    Builds a vector-grade, print-ready PDF executive briefing.
    """
    out = io.BytesIO()
    doc = SimpleDocTemplate(
        out,
        pagesize=letter,
        leftMargin=40,
        rightMargin=40,
        topMargin=45,
        bottomMargin=55,
    )

    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#0F172A"),
        spaceAfter=4,
    )
    meta_style = ParagraphStyle(
        "ReportMeta",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#64748B"),
        spaceAfter=14,
    )
    section_h_style = ParagraphStyle(
        "SectionHeader",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=15,
        textColor=colors.HexColor("#0F172A"),
        spaceBefore=10,
        spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "ReportBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9.5,
        leading=14,
        textColor=colors.HexColor("#1E293B"),
        spaceAfter=6,
    )
    bullet_style = ParagraphStyle(
        "ReportBullet",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#334155"),
        leftIndent=12,
        spaceAfter=4,
    )
    table_cell_style = ParagraphStyle(
        "TableCell",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#1E293B"),
    )
    table_hdr_style = ParagraphStyle(
        "TableHdr",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=11,
        textColor=colors.white,
    )

    story = []

    # Title & Subtitle
    title_text = data.get("title") or "Executive Contract Intelligence Report"
    story.append(Paragraph(title_text, title_style))

    timestamp_str = datetime.now().strftime("%d %b %Y, %I:%M %p")
    meta_text = f"Generated: {timestamp_str} &nbsp;|&nbsp; Scope: {scope or 'All Contracts'}"
    if query:
        meta_text += f'<br/><i>Query: "{query}"</i>'
    story.append(Paragraph(meta_text, meta_style))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#E2E8F0"), spaceAfter=14))

    # Executive Summary Box
    if data.get("paragraphs"):
        summary_paragraphs = [Paragraph(f"<b>EXECUTIVE SUMMARY</b>", ParagraphStyle(
            "SummaryHdr", fontName="Helvetica-Bold", fontSize=10, leading=13, textColor=colors.HexColor("#2563EB"), spaceAfter=4
        ))]
        for p in data["paragraphs"]:
            summary_paragraphs.append(Paragraph(p, body_style))

        # Wrap in 1x1 table with shading
        summary_table = Table([[summary_paragraphs]], colWidths=[doc.width])
        summary_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
            ("LINEBEFORE", (0, 0), (0, -1), 3, colors.HexColor("#2563EB")),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ("LEFTPADDING", (0, 0), (-1, -1), 12),
            ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ]))
        story.append(summary_table)
        story.append(Spacer(1, 14))

    # Tables
    if data.get("tables"):
        for t_idx, table_data in enumerate(data["tables"]):
            headers = table_data.get("headers", [])
            rows = table_data.get("rows", [])
            if not headers:
                continue

            num_cols = len(headers)
            col_width = doc.width / float(num_cols)

            table_matrix = []
            # Header Row
            hdr_row = [Paragraph(h.upper(), table_hdr_style) for h in headers]
            table_matrix.append(hdr_row)

            # Data Rows
            for r_vals in rows:
                row_cells = [Paragraph(str(val), table_cell_style) for val in r_vals]
                table_matrix.append(row_cells)

            t_elem = Table(table_matrix, colWidths=[col_width] * num_cols, repeatRows=1)
            t_style = [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ]

            # Zebra striping
            for r_idx in range(1, len(table_matrix)):
                if r_idx % 2 == 0:
                    t_style.append(("BACKGROUND", (0, r_idx), (-1, r_idx), colors.HexColor("#F8FAFC")))

            t_elem.setStyle(TableStyle(t_style))
            story.append(KeepTogether([t_elem]))
            story.append(Spacer(1, 14))

    # Bullets
    if data.get("bullets"):
        story.append(Paragraph("Key Findings & Recommendations", section_h_style))
        for lead, body in data["bullets"]:
            b_text = f"<b>{lead}:</b> {body}" if lead else body
            story.append(Paragraph(f"• &nbsp; {b_text}", bullet_style))
        story.append(Spacer(1, 12))

    # Citations
    if data.get("citations"):
        story.append(Paragraph("Audit Citations", ParagraphStyle(
            "CiteHdr", fontName="Helvetica-Bold", fontSize=9, textColor=colors.HexColor("#64748B"), spaceAfter=3
        )))
        for c in data["citations"]:
            story.append(Paragraph(f"• <i>{c}</i>", ParagraphStyle(
                "CiteBody", fontName="Helvetica", fontSize=8, textColor=colors.HexColor("#64748B"), spaceAfter=2
            )))

    doc.build(story, canvasmaker=NumberedCanvas)
    return out.getvalue()


# ---------------------------------------------------------------------------
# 6. UNIVERSAL EXPORT DISPATCHER
# ---------------------------------------------------------------------------

def export_chat_response(
    content: str,
    export_format: str,
    query: str = "",
    scope: str = "SmartExtractor Intelligence"
) -> Tuple[bytes, str, str]:
    """
    Main entry point:
    Parses chat content and compiles it into the requested format.
    Returns (file_bytes, media_type, filename).
    """
    report_data = parse_chat_markdown(content)
    date_stamp = datetime.now().strftime("%Y%m%d_%H%M")
    clean_title = re.sub(r"[^\w\-]", "_", report_data.get("title") or "Report")[:30]

    fmt = (export_format or "excel").lower()

    if fmt in ("excel", "xlsx"):
        file_bytes = build_excel(report_data, query=query, scope=scope)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = f"SmartExtractor_{clean_title}_{date_stamp}.xlsx"
        return file_bytes, media_type, filename

    elif fmt in ("word", "docx"):
        file_bytes = build_word(report_data, query=query, scope=scope)
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        filename = f"SmartExtractor_{clean_title}_{date_stamp}.docx"
        return file_bytes, media_type, filename

    elif fmt in ("pdf",):
        file_bytes = build_pdf(report_data, query=query, scope=scope)
        media_type = "application/pdf"
        filename = f"SmartExtractor_{clean_title}_{date_stamp}.pdf"
        return file_bytes, media_type, filename

    else:
        raise ValueError(f"Unsupported export format: {export_format}. Use 'excel', 'word', or 'pdf'.")
