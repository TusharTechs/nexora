"""Rendering helpers — turn the Composer's content into *beautifully formatted*
Google Docs / Slides / Sheets / HTML email (ADR-067).

The Composer produces Markdown (documents), a list of {title, bullets} (slides),
and {headers, rows} (sheets). These helpers translate that into the batchUpdate
request payloads and CSS/HTML that make the real artifacts look designed rather
than dumped.
"""
from __future__ import annotations

import html as _html
import re
from typing import Dict, List, Tuple

# NEXORA accent palette
ACCENT = {"red": 0.153, "green": 0.463, "blue": 0.412}      # deep teal-green #277668
INK = {"red": 0.11, "green": 0.12, "blue": 0.13}
MUTED = {"red": 0.42, "green": 0.45, "blue": 0.49}


# ------------------------------------------------------------------ Markdown model

_BOLD = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_INLINE_CODE = re.compile(r"`([^`]+)`")
_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_MD_LINK = re.compile(r"\[([^\]]+)\]\(([^)]*)\)")


def _strip_inline(text: str) -> Tuple[str, List[Tuple[int, int]]]:
    """Return (plain_text, [(bold_start, bold_end), ...]) with markdown removed."""
    text = _MD_IMAGE.sub("", text)
    text = _MD_LINK.sub(lambda m: m.group(1) if m.group(1) else m.group(2), text)
    text = _INLINE_CODE.sub(r"\1", text)
    out = []
    bolds: List[Tuple[int, int]] = []
    i = 0
    for m in _BOLD.finditer(text):
        out.append(text[i:m.start()])
        seg = m.group(1) or m.group(2) or ""
        start = sum(len(s) for s in out)
        out.append(seg)
        bolds.append((start, start + len(seg)))
        i = m.end()
    out.append(text[i:])
    return "".join(out), bolds


def first_h1(md: str) -> str:
    """The document's own leading `# ` title, if it has one."""
    for line in (md or "").replace("\r\n", "\n").split("\n"):
        m = re.match(r"^\s*#\s+(.+?)\s*$", line)
        if m:
            return _strip_inline(m.group(1))[0].strip()
        if line.strip():
            return ""
    return ""


def parse_markdown_blocks(md: str) -> List[Dict]:
    """Very small block parser: heading / bullet / number / paragraph / rule."""
    blocks: List[Dict] = []
    for raw in md.replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        if not line.strip():
            continue
        if re.match(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$", line):
            blocks.append({"type": "rule"})
            continue
        h = re.match(r"^(#{1,6})\s+(.*)$", line)
        if h:
            blocks.append({"type": "heading", "level": len(h.group(1)), "text": h.group(2).strip()})
            continue
        b = re.match(r"^\s*[-*+]\s+(.*)$", line)
        if b:
            blocks.append({"type": "bullet", "text": b.group(1).strip()})
            continue
        n = re.match(r"^\s*\d+[.)]\s+(.*)$", line)
        if n:
            blocks.append({"type": "number", "text": n.group(1).strip()})
            continue
        blocks.append({"type": "para", "text": line.strip()})
    return blocks


# ------------------------------------------------------------------ Google Docs

_DOCS_STYLE = {
    1: ("HEADING_1", 20, True),
    2: ("HEADING_2", 15, True),
    3: ("HEADING_3", 12, True),
}


def markdown_to_docs_requests(md: str, title: str) -> List[Dict]:
    """Build a batchUpdate request list that renders `md` as a styled document.

    Everything is inserted at index 1 in document order; we keep a running cursor
    and emit style ranges as we go.
    """
    blocks = parse_markdown_blocks(md)
    # If the content leads with an H1, promote it to the document title.
    if blocks and blocks[0]["type"] == "heading" and blocks[0]["level"] == 1:
        title = _strip_inline(blocks[0]["text"])[0] or title
        blocks = blocks[1:]

    requests: List[Dict] = []
    style_ops: List[Dict] = []

    # We build the whole document text once, then insert it at index 1 and apply
    # style ranges by absolute offset into that single insert.
    title_txt = title.strip() + "\n"
    bullet_ranges: List[Tuple[int, int, str]] = []
    running: List[str] = []

    def emit(segment: str):
        running.append(segment)

    emit(title_txt)
    title_range = (1, 1 + len(title_txt) - 1)

    for blk in blocks:
        if blk["type"] == "rule":
            emit("\n")
            continue
        if blk["type"] == "heading":
            plain, bolds = _strip_inline(blk["text"])
            seg = plain + "\n"
            start = 1 + sum(len(s) for s in running)
            emit(seg)
            lvl = min(blk["level"], 3)
            style_ops.append({"type": "heading", "range": (start, start + len(plain)),
                              "level": lvl})
            continue
        if blk["type"] in ("bullet", "number"):
            plain, bolds = _strip_inline(blk["text"])
            seg = plain + "\n"
            start = 1 + sum(len(s) for s in running)
            emit(seg)
            bullet_ranges.append((start, start + len(plain), blk["type"]))
            for bs, be in bolds:
                style_ops.append({"type": "bold", "range": (start + bs, start + be)})
            continue
        # paragraph
        plain, bolds = _strip_inline(blk["text"])
        seg = plain + "\n"
        start = 1 + sum(len(s) for s in running)
        emit(seg)
        for bs, be in bolds:
            style_ops.append({"type": "bold", "range": (start + bs, start + be)})

    full_text = "".join(running)
    requests.append({"insertText": {"location": {"index": 1}, "text": full_text}})

    # Title styling
    requests.append({"updateParagraphStyle": {
        "range": {"startIndex": title_range[0], "endIndex": title_range[1] + 1},
        "paragraphStyle": {"namedStyleType": "TITLE",
                           "spaceBelow": {"magnitude": 12, "unit": "PT"}},
        "fields": "namedStyleType,spaceBelow"}})
    requests.append({"updateTextStyle": {
        "range": {"startIndex": title_range[0], "endIndex": title_range[1] + 1},
        "textStyle": {"foregroundColor": {"color": {"rgbColor": ACCENT}},
                      "bold": True},
        "fields": "foregroundColor,bold"}})

    for op in style_ops:
        s, e = op["range"]
        if op["type"] == "heading":
            named, _, _ = _DOCS_STYLE[op["level"]]
            requests.append({"updateParagraphStyle": {
                "range": {"startIndex": s, "endIndex": e + 1},
                "paragraphStyle": {"namedStyleType": named,
                                   "spaceAbove": {"magnitude": 10, "unit": "PT"},
                                   "spaceBelow": {"magnitude": 4, "unit": "PT"}},
                "fields": "namedStyleType,spaceAbove,spaceBelow"}})
            if op["level"] <= 2:
                requests.append({"updateTextStyle": {
                    "range": {"startIndex": s, "endIndex": e + 1},
                    "textStyle": {"foregroundColor": {"color": {"rgbColor": ACCENT}}},
                    "fields": "foregroundColor"}})
        elif op["type"] == "bold":
            requests.append({"updateTextStyle": {
                "range": {"startIndex": s, "endIndex": e},
                "textStyle": {"bold": True}, "fields": "bold"}})

    for s, e, kind in bullet_ranges:
        preset = ("NUMBERED_DECIMAL_ALPHA_ROMAN" if kind == "number"
                  else "BULLET_DISC_CIRCLE_SQUARE")
        requests.append({"createParagraphBullets": {
            "range": {"startIndex": s, "endIndex": e + 1}, "bulletPreset": preset}})

    return requests


# ------------------------------------------------------------------ HTML email

def markdown_to_html(md: str, *, title: str = "", preheader: str = "") -> str:
    blocks = parse_markdown_blocks(md)
    body: List[str] = []
    list_open = None

    def close_list():
        nonlocal list_open
        if list_open:
            body.append(f"</{list_open}>")
            list_open = None

    for blk in blocks:
        if blk["type"] == "rule":
            close_list()
            body.append('<hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0"/>')
        elif blk["type"] == "heading":
            close_list()
            lvl = min(blk["level"], 4)
            size = {1: 22, 2: 18, 3: 15, 4: 13}[lvl]
            txt, _ = _strip_inline(blk["text"])
            body.append(f'<h{lvl} style="margin:22px 0 8px;font-size:{size}px;'
                        f'color:#183f38;font-weight:700">{_html.escape(txt)}</h{lvl}>')
        elif blk["type"] in ("bullet", "number"):
            want = "ol" if blk["type"] == "number" else "ul"
            if list_open != want:
                close_list()
                body.append(f'<{want} style="margin:8px 0 8px 20px;padding:0">')
                list_open = want
            txt = _html_inline(blk["text"])
            body.append(f'<li style="margin:4px 0;line-height:1.6">{txt}</li>')
        else:
            close_list()
            body.append(f'<p style="margin:10px 0;line-height:1.65;color:#1f2937">'
                        f'{_html_inline(blk["text"])}</p>')
    close_list()

    return f"""\
<!doctype html><html><body style="margin:0;background:#f4f5f7;
 font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#1f2937">
<span style="display:none;max-height:0;overflow:hidden">{_html.escape(preheader)}</span>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f5f7">
<tr><td align="center" style="padding:32px 16px">
  <table role="presentation" width="600" cellpadding="0" cellspacing="0"
   style="max-width:600px;background:#ffffff;border-radius:14px;overflow:hidden;
   box-shadow:0 1px 3px rgba(16,24,40,.08)">
    <tr><td style="background:#277668;padding:20px 28px">
      <div style="color:#fff;font-weight:700;letter-spacing:.14em;font-size:12px">NEXORA</div>
      <div style="color:#d6efe9;font-size:18px;font-weight:700;margin-top:4px">
        {_html.escape(title)}</div>
    </td></tr>
    <tr><td style="padding:24px 28px 8px">{''.join(body)}</td></tr>
    <tr><td style="padding:16px 28px 26px;border-top:1px solid #eef0f2">
      <div style="color:#8a9099;font-size:12px">Prepared autonomously by NEXORA.</div>
    </td></tr>
  </table>
</td></tr></table></body></html>"""


def _html_inline(text: str) -> str:
    text = _INLINE_CODE.sub(lambda m: f'<code style="background:#f1f5f4;padding:1px 4px;'
                                      f'border-radius:4px">{_html.escape(m.group(1))}</code>', text)
    parts, i = [], 0
    for m in _BOLD.finditer(text):
        parts.append(_html.escape(text[i:m.start()]))
        parts.append(f"<strong>{_html.escape(m.group(1) or m.group(2) or '')}</strong>")
        i = m.end()
    parts.append(_html.escape(text[i:]))
    return "".join(parts)


# ------------------------------------------------------------------ Slides

def slide_deck_requests(deck: List[Dict], title: str, subtitle: str = "") -> Tuple[List[Dict], List[Dict]]:
    """Return (structure_requests, text_requests).

    structure: createSlide + shape placement.  text: insertText + styling, run
    in a second batch once object ids exist.
    """
    struct: List[Dict] = []
    text: List[Dict] = []

    # Slide 0 → a real title layout. Prefer the composed deck's own first slide
    # (its title is punchier than the raw goal); fall back to `title`.
    lead = deck[0] if deck else {}
    lead_title = str(lead.get("title") or title)[:120]
    lead_sub = " · ".join(str(b) for b in (lead.get("bullets") or [])[:2]) or subtitle
    struct.append({"createSlide": {"objectId": "nx_slide_title",
                                   "slideLayoutReference": {"predefinedLayout": "TITLE"},
                                   "placeholderIdMappings": [
                                       {"layoutPlaceholder": {"type": "CENTERED_TITLE"}, "objectId": "nx_ttl_title"},
                                       {"layoutPlaceholder": {"type": "SUBTITLE"}, "objectId": "nx_ttl_sub"}]}})
    text.append({"insertText": {"objectId": "nx_ttl_title", "text": lead_title}})
    if lead_sub:
        text.append({"insertText": {"objectId": "nx_ttl_sub", "text": lead_sub[:200]}})

    for i, slide in enumerate(deck[1:] if deck else []):
        sid, tid, bid = f"nx_slide_{i:02d}", f"nx_title_{i:02d}", f"nx_body_{i:02d}"
        struct.append({"createSlide": {"objectId": sid,
                                       "slideLayoutReference": {"predefinedLayout": "TITLE_AND_BODY"},
                                       "placeholderIdMappings": [
                                           {"layoutPlaceholder": {"type": "TITLE"}, "objectId": tid},
                                           {"layoutPlaceholder": {"type": "BODY"}, "objectId": bid}]}})
        text.append({"insertText": {"objectId": tid, "text": str(slide.get("title", ""))[:160]}})
        bullets = [str(b) for b in (slide.get("bullets") or [])]
        if bullets:
            text.append({"insertText": {"objectId": bid, "text": "\n".join(bullets)}})
            text.append({"createParagraphBullets": {
                "objectId": bid, "textRange": {"type": "ALL"},
                "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE"}})

    return struct, text


def slide_theme_requests(presentation: Dict) -> List[Dict]:
    """Recolor title text on every slide to the accent and enlarge it a touch."""
    reqs: List[Dict] = []
    for s in presentation.get("slides", []):
        for el in s.get("pageElements", []):
            shape = el.get("shape", {})
            ph = shape.get("placeholder", {})
            if ph.get("type") in ("TITLE", "CENTERED_TITLE"):
                reqs.append({"updateTextStyle": {
                    "objectId": el["objectId"], "textRange": {"type": "ALL"},
                    "style": {"foregroundColor": {"opaqueColor": {"rgbColor": ACCENT}},
                              "bold": True},
                    "fields": "foregroundColor,bold"}})
    return reqs


# ------------------------------------------------------------------ Sheets

def sheet_format_requests(sheet_id: int, n_cols: int, n_rows: int,
                          money_cols: List[int]) -> List[Dict]:
    reqs: List[Dict] = [
        {"updateSheetProperties": {
            "properties": {"sheetId": sheet_id,
                           "gridProperties": {"frozenRowCount": 1}},
            "fields": "gridProperties.frozenRowCount"}},
        {"repeatCell": {
            "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1},
            "cell": {"userEnteredFormat": {
                "backgroundColor": ACCENT,
                "textFormat": {"bold": True,
                               "foregroundColor": {"red": 1, "green": 1, "blue": 1}}}},
            "fields": "userEnteredFormat(backgroundColor,textFormat)"}},
        {"addBanding": {"bandedRange": {
            "range": {"sheetId": sheet_id, "startRowIndex": 0,
                      "endRowIndex": max(n_rows, 2), "startColumnIndex": 0,
                      "endColumnIndex": max(n_cols, 1)},
            "rowProperties": {
                "headerColor": ACCENT,
                "firstBandColor": {"red": 1, "green": 1, "blue": 1},
                "secondBandColor": {"red": 0.965, "green": 0.976, "blue": 0.973}}}}},
        {"autoResizeDimensions": {"dimensions": {
            "sheetId": sheet_id, "dimension": "COLUMNS",
            "startIndex": 0, "endIndex": max(n_cols, 1)}}},
    ]
    for c in money_cols:
        reqs.append({"repeatCell": {
            "range": {"sheetId": sheet_id, "startRowIndex": 1,
                      "startColumnIndex": c, "endColumnIndex": c + 1},
            "cell": {"userEnteredFormat": {"numberFormat": {
                "type": "CURRENCY", "pattern": "\"$\"#,##0.00"}}},
            "fields": "userEnteredFormat.numberFormat"}})
    # bold the TOTAL row if present (last row)
    if n_rows >= 2:
        reqs.append({"repeatCell": {
            "range": {"sheetId": sheet_id, "startRowIndex": n_rows - 1, "endRowIndex": n_rows},
            "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
            "fields": "userEnteredFormat.textFormat.bold"}})
    return reqs


def guess_money_columns(headers: List[str]) -> List[int]:
    keys = ("cost", "price", "amount", "usd", "$", "budget", "total", "spend", "value", "estimate")
    return [i for i, h in enumerate(headers) if any(k in str(h).lower() for k in keys)]
