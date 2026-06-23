#!/usr/bin/env python3
"""
BetterDiagnosis — PDF Book Builder  (v4 — ENGINE SWITCH: wkhtmltopdf → WeasyPrint)
════════════════════════════════════════════════════════════════════════
ENGINE SWITCH (v4):
  wkhtmltopdf is unmaintained since 2020 and its old Qt-WebKit bidi
  (Arabic/Latin mixed-direction text) engine has confirmed, unfixable
  rendering bugs — see BUG 1 history below, where extensive debugging
  traced multiple visual glyph-collision issues directly to WebKit's
  bidi reordering algorithm itself, not to our HTML/CSS.

  Switched to WeasyPrint: actively maintained, uses Pango + HarfBuzz
  for text shaping (the same industry-standard libraries GTK/LibreOffice
  use), with correct, modern Unicode BiDi (UAX #9) support out of the
  box. Same HTML/CSS pipeline — only the final "render to PDF" call
  changed from a wkhtmltopdf subprocess to a native Python import.

  Practical effect: the punctuation-swallowing workarounds below (BUG 1
  fixes) are kept for safety/backwards-compatibility, but should no
  longer be strictly necessary — WeasyPrint resolves mixed Arabic/Latin
  text correctly without them. If you want to simplify the regex later,
  test first; for now nothing is removed, only the renderer changed.

  Page numbers + running footer also moved from wkhtmltopdf's
  --footer-* CLI flags into native CSS `@page { @bottom-center {...} }`
  margin boxes, which is the standards-compliant way WeasyPrint expects.

WHAT WAS BROKEN IN v2/v3 (confirmed by visual page-render audit,
kept here for history — still relevant since some fixes are HTML/CSS
structure, not engine-specific):

 BUG 1 — CRITICAL: isolate_ltr() ran AFTER inline_md() built real HTML
         tags (<strong>, <em>, <code>). Its Latin-word regex then matched
         the tag names themselves ("strong","code","class","ltr") and
         wrapped THEM in extra <span> tags, corrupting every single
         styled element in the book → visible "<code class="ltr">" text,
         broken tables, garbled boxes. THIS WAS THE #1 ROOT CAUSE.
         FIX: isolate_ltr() now runs FIRST, on raw text only, before any
         HTML tags exist. inline_md() then wraps remaining markdown.

 BUG 2 — Section divider pages: content stuck to TOP of page instead of
         vertically centered. CSS flexbox `justify-content:center` does
         NOT reliably center in print engines.
         FIX: replaced flexbox centering with table-cell vertical-align,
         which works reliably in both wkhtmltopdf and WeasyPrint.

 BUG 3 — Massive empty space after short chapters (half-blank pages).
         FIX: removed forced page-break-after on every chapter; only
         break before the NEXT chapter starts, so content flows
         naturally and short chapters don't waste a half page.

 BUG 4 — Page felt oversized / "zoomed" / like a sheet of paper, not a
         book. Content sat in a narrow column with massive surrounding
         margin (a "rectangle inside a border" look) and wasn't usable
         on phone/tablet screens.
         FIX: switched trim size from full A4 (210×297mm) to a proper
         compact BOOK trim size — 6"×9" (152×229mm), which is the
         actual industry-standard size for printed non-fiction
         paperbacks and reads MUCH better on phone/tablet screens
         (closer to the device aspect ratio). Margins tightened
         proportionally.

 BUG 5 — --zoom 1.33 was a wrong fix for a non-existent problem; it
         scaled content unevenly against fixed-mm margins, creating the
         double-border illusion. REMOVED (and N/A under WeasyPrint,
         which has no zoom concept — it lays out CSS units at their
         true scale).

 BUG 6 — Patient-quote / bold-line regex occasionally failed to close
         (markdown like "**مثال:**" alone on a line), leaving literal
         asterisks that then got mangled by the (now-fixed) LTR isolator.
         FIX: with isolate_ltr() reordered, this self-resolves; added
         a defensive raw-asterisk cleanup pass as a second safety net.

 BUG 7 — Confirmed via isolated minimal-HTML test cases: wkhtmltopdf's
         WebKit bidi engine visually overlaps Latin/Arabic glyphs when a
         neutral character (=, (, )) sits between an RTL run and an
         isolated LTR span — e.g. "= Otitis Media (التهاب...)" collided
         but "Otitis Media (" as one isolated unit did not. Root cause
         was in wkhtmltopdf itself (confirmed by testing identical CSS
         with synthetic-bold vs real bold-font-face, inline vs
         inline-block, RLM marks, thin-space chars — all wkhtmltopdf-
         side mitigations). Should no longer manifest under WeasyPrint's
         correct bidi implementation; the regex fix is kept as a
         defensive no-op safety net.
════════════════════════════════════════════════════════════════════════
USAGE:
  1. Place this file inside your BetterDiagnosis/ folder
     (same level as README.md, the_book.json, prereq_*.md)
  2. Run: pip install weasyprint   (one-time; see install_env.sh)
  3. Run: python3 build_book_local.py
  4. Output: BetterDiagnosis_book.pdf (same folder)
════════════════════════════════════════════════════════════════════════
"""

import json, os, re, subprocess, sys
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════════
# PATHS
# ═══════════════════════════════════════════════════════════════════════
SCRIPT_DIR = Path(__file__).parent.resolve()
BOOK_ROOT  = SCRIPT_DIR
MAIN_DIR   = SCRIPT_DIR / "main_content"
JSON_FILE  = SCRIPT_DIR / "the_book.json"
FONTS_DIR  = SCRIPT_DIR / "fonts"
OUT_HTML   = SCRIPT_DIR / "_book_build.html"
OUT_PDF    = SCRIPT_DIR / "BetterDiagnosis_book.pdf"
IMAGES_DIR = SCRIPT_DIR / "images"   # 0.png .. 25.png — see visual_placeholder()

if not JSON_FILE.exists():
    print(f"ERROR: {JSON_FILE} not found.")
    sys.exit(1)

with open(JSON_FILE, encoding="utf-8") as f:
    CFG = json.load(f)

C    = CFG["colors"]
T    = CFG["typography"]
CO   = CFG["components"]
META = CFG["meta"]

# ═══════════════════════════════════════════════════════════════════════
# TRIM SIZE — compact book format (was: full A4 — too big / "zoomed")
# 6in x 9in is the real-world standard trade-paperback size, and reads
# far better on phones/tablets than scaled-down A4.
# ═══════════════════════════════════════════════════════════════════════
PAGE_W_MM = 152      # 6 in
PAGE_H_MM = 229      # 9 in
MARGIN_TOP_MM    = 14
MARGIN_BOTTOM_MM = 15
MARGIN_OUTER_MM  = 12
MARGIN_INNER_MM  = 14

# ═══════════════════════════════════════════════════════════════════════
# FONT DETECTION  (no zoom hack — sizes are真 print pt values directly)
# ═══════════════════════════════════════════════════════════════════════
def find_font(name):
    for ext in ["ttf", "TTF", "otf", "OTF"]:
        p = FONTS_DIR / f"{name}.{ext}"
        if p.exists():
            return str(p)
    return None

AMIRI_REG  = find_font("Amiri-Regular")
AMIRI_BOLD = find_font("Amiri-Bold")
FREESERIF_REG  = "/usr/share/fonts/truetype/freefont/FreeSerif.ttf"
FREESERIF_BOLD = "/usr/share/fonts/truetype/freefont/FreeSerifBold.ttf"

if AMIRI_REG and AMIRI_BOLD:
    FONT_REG, FONT_BOLD, FONT_NAME = AMIRI_REG, AMIRI_BOLD, "Amiri"
    print("✓ Using Amiri font (best quality)")
elif os.path.exists(FREESERIF_REG):
    FONT_REG, FONT_BOLD, FONT_NAME = FREESERIF_REG, FREESERIF_BOLD, "FreeSerif"
    print("⚠ Amiri not found — using FreeSerif (run install_env.sh for better quality)")
else:
    FONT_REG, FONT_BOLD, FONT_NAME = None, None, "serif"
    print("⚠ No Arabic TTF found — using system serif font")

# Since we removed the zoom hack, font sizes in the_book.json are used AS-IS.
def pt(size):
    return size

# ═══════════════════════════════════════════════════════════════════════
# CSS
# ═══════════════════════════════════════════════════════════════════════
def build_css():
    ff = ""
    if FONT_REG:
        ff += f"""
@font-face {{
  font-family: 'BookFont';
  src: url('file://{FONT_REG}') format('truetype');
  font-weight: normal; font-style: normal;
}}"""
    if FONT_BOLD:
        ff += f"""
@font-face {{
  font-family: 'BookFont';
  src: url('file://{FONT_BOLD}') format('truetype');
  font-weight: bold; font-style: normal;
}}"""

    fam = "'BookFont', 'FreeSerif', 'Arial Unicode MS', serif"

    return f"""
{ff}

* {{ box-sizing: border-box; margin: 0; padding: 0; }}

@page {{
  size: {PAGE_W_MM}mm {PAGE_H_MM}mm;
  margin: {MARGIN_TOP_MM}mm {MARGIN_OUTER_MM}mm {MARGIN_BOTTOM_MM}mm {MARGIN_INNER_MM}mm;

  /* ── Running footer (WeasyPrint renders @page margin boxes natively —
     no command-line --footer-* flags needed like wkhtmltopdf required) ── */
  @bottom-center {{
    content: "BetterDiagnosis — {META['title_ar']}";
    font-family: {fam};
    font-size: 6.5pt;
    color: {C['footer_text']};
  }}
  @bottom-left {{
    content: counter(page);
    font-family: {fam};
    font-size: 6.5pt;
    color: {C['footer_text']};
  }}
}}

/* No footer on the title page */
@page :first {{
  @bottom-center {{ content: none; }}
  @bottom-left   {{ content: none; }}
}}

html, body {{
  font-family: {fam};
  font-size: {pt(T['size_body'])}pt;
  /* FIX: 1.5 instead of the_book.json's 1.85 — 1.85 is manuscript/
     draft-style spacing, not print-book spacing, and was a major
     contributor to pages feeling under-filled with too much
     whitespace between every line of body text. */
  line-height: 1.5;
  color: {C['text_primary']};
  background: {C['page_bg']};
  direction: rtl;
  unicode-bidi: embed;
}}

/* ── LTR isolation (for Latin codes inside RTL flow) ── */
.ltr {{
  direction: ltr !important;
  unicode-bidi: isolate !important;
  display: inline-block !important;
  vertical-align: baseline;
  max-width: 100%;
}}
code.ltr-inline {{
  direction: ltr !important;
  unicode-bidi: isolate !important;
  display: inline-block !important;
  vertical-align: baseline;
}}
.ltr-block {{
  direction: ltr !important;
  unicode-bidi: isolate !important;
  display: block;
}}

/* ── Page break control ── */
.page-break    {{ page-break-after: always; height: 0; display:block; }}
.no-break      {{ page-break-inside: avoid; }}
.break-before  {{ page-break-before: always; }}

/* ── SECTION DIVIDER PAGE ──
   FIX: table-cell vertical-align used instead of flexbox, because
   wkhtmltopdf's print engine does not reliably center flex content. */
.section-page {{
  page-break-before: always;
  page-break-after:  always;
  display: table;
  table-layout: fixed;
  width: 100%;
  min-height: 220mm;
  background: {C['page_bg']};
}}
.section-page .sp-cell {{
  display: table-cell;
  vertical-align: middle;
  text-align: center;
  height: 220mm;
}}
.section-page .sp-label {{
  font-size: {pt(10)}pt;
  color: {C['text_muted']};
  letter-spacing: .15em;
  margin-bottom: 14px;
  text-transform: uppercase;
}}
.section-page .sp-title {{
  font-size: {pt(22)}pt;
  font-weight: bold;
  color: {C['text_primary']};
  margin-bottom: 18px;
  line-height: 1.3;
}}
.section-page .sp-bar {{
  width: 46px; height: 3px;
  border-radius: 2px; margin: 0 auto;
}}

/* ── TITLE PAGE (same centering fix) ── */
.title-page {{
  display: table;
  table-layout: fixed;
  width: 100%;
  min-height: 220mm;
}}
.title-page .tp-cell {{
  display: table-cell;
  vertical-align: middle;
  text-align: center;
  height: 220mm;
}}

/* ── CHAPTER HEADER ──
   FIX: no longer forces a full empty page below short chapters;
   page-break-before only (starts new page), no break-after. */
.chapter-header {{
  page-break-before: always;
  padding: 22px 20px 18px;
  margin-bottom: 18px;
  position: relative;
  overflow: hidden;
  border-radius: 0 0 8px 8px;
  min-height: 70px;
}}
.chapter-header .ch-bgnum {{
  position: absolute;
  left: 10px; top: -10px;
  font-size: {pt(58)}pt;
  font-weight: bold;
  color: rgba(255,255,255,0.13);
  line-height: 1;
  direction: ltr;
  unicode-bidi: isolate;
  z-index: 0;
  pointer-events: none;
}}
.chapter-header .ch-inner {{
  position: relative; z-index: 1;
  max-width: 82%;
}}
.chapter-header .ch-label {{
  font-size: {pt(8)}pt;
  letter-spacing: .18em;
  color: rgba(255,255,255,0.75);
  margin-bottom: 7px;
  text-transform: uppercase;
  white-space: nowrap;
}}
.chapter-header .ch-title {{
  font-size: {pt(15)}pt;
  font-weight: bold;
  color: #FFFFFF;
  line-height: 1.4;
  word-wrap: break-word;
}}

/* ── Visual placeholder ── */
.visual-placeholder {{
  width: 100%;
  min-height: 110px;
  border: 1.3px dashed {C['placeholder_border']};
  border-radius: 7px;
  background: {C['placeholder_bg']};
  display: table;
  margin: 12px 0 16px;
  page-break-inside: avoid;
  text-align: center;
  /* aspect-ratio is set inline per-instance (e.g. "16/9") via the
     visual_placeholder() Python function — WeasyPrint supports the
     CSS aspect-ratio property natively. */
}}
.visual-placeholder .vp-cell {{
  display: table-cell;
  vertical-align: middle;
}}
.visual-placeholder .vp-label {{
  font-size: {pt(9.5)}pt;
  font-weight: bold;
  color: {C['placeholder_text']};
  margin-bottom: 3px;
}}
.visual-placeholder .vp-sub {{
  font-size: {pt(8)}pt;
  color: {C['placeholder_text']};
  opacity: 0.7;
}}
.visual-placeholder .vp-marker {{
  /* Real (searchable) text in the PDF's text layer, kept visually
     unobtrusive. Used by generate_image_spec() to locate which actual
     printed page each placeholder landed on after rendering. */
  font-size: 5pt;
  color: {C['placeholder_bg']};
  opacity: 0.35;
  margin-top: 2px;
  direction: ltr;
  unicode-bidi: isolate;
}}

/* ── Visual placeholder WITH a real image dropped in ──
   Same outer box / aspect-ratio as the dashed placeholder above, but
   the caption text is replaced by an actual <img>. Falls back to the
   dashed placeholder automatically whenever images/{{slot}}.png is
   missing, so a partial image set still produces a complete PDF. */
.visual-placeholder.has-image {{
  border: none;
  background: transparent;
  display: block;
  padding: 0;
  position: relative;
  overflow: hidden;
}}
.visual-placeholder.has-image .vp-img {{
  width: 100%;
  height: 100%;
  display: block;
  object-fit: cover;
  border-radius: 7px;
}}
.visual-placeholder.has-image .vp-marker {{
  /* Kept in the text layer for generate_image_spec(), but visually
     fully suppressed now that a real photo sits underneath it. */
  position: absolute;
  bottom: 1px; left: 3px;
  color: rgba(0,0,0,0.01);
  opacity: 1;
}}

/* ── Headings ──
   FIX: removed stale *0.72/*0.78/*0.85/*0.9 shrink multipliers. These
   were defensive compensation for the old 96-DPI zoom hack on an
   oversized A4 page (both since removed). On the correct 6"×9" trim
   with direct-pt sizing, full the_book.json sizes are used as-is —
   this is also a major contributor to the "content doesn't fill the
   page" complaint: headings were rendering ~25% smaller than intended,
   leaving more white space relative to body text mass. */
h1 {{
  font-size: {pt(T['size_h1'])}pt; font-weight: bold;
  color: {C['text_primary']};
  line-height: {T['h_line_height']};
  margin: 18px 0 10px;
  padding-bottom: 7px;
  border-bottom: 2px solid {C['border_light']};
}}
h2 {{
  font-size: {pt(T['size_h2'])}pt; font-weight: bold;
  color: {C['text_primary']};
  margin: 16px 0 8px;
  padding-right: 12px;
  border-right: 3px solid {C['accent']};
}}
h2.prereq {{ border-right-color: {C['prereq_accent']}; }}
h2.extra  {{ border-right-color: {C['section_accent']}; }}
h3 {{
  font-size: {pt(T['size_h3'])}pt; font-weight: bold;
  color: {C['text_secondary']};
  margin: 13px 0 7px;
}}
h4 {{
  font-size: {pt(T['size_h4'])}pt; font-weight: bold;
  color: {C['text_secondary']};
  margin: 10px 0 5px;
}}

/* ── Body ──
   FIX: line-height tightened from 1.85 (manuscript/draft spacing) to
   1.5 (standard printed-book spacing). 1.85 was a major cause of pages
   looking sparse/under-filled — each paragraph consumed far more
   vertical space than its character count justified. */
p {{ margin-bottom: 8px; }}
strong {{ font-weight: bold; color: {C['text_primary']}; }}
em {{ font-style: italic; }}
code {{
  font-family: 'Courier New', 'DejaVu Sans Mono', monospace;
  background: {C['accent_light']};
  padding: 1px 4px; border-radius: 3px;
  font-size: {pt(8.5)}pt;
}}

ul, ol {{ padding-right: 18px; margin: 7px 0 10px; }}
li {{ margin-bottom: 4px; line-height: 1.5; }}

/* ── Topic divider ── */
.topic-divider {{
  display: table;
  width: 100%;
  margin: 18px 0 11px;
  page-break-inside: avoid;
}}
.topic-divider .td-row {{ display: table-row; }}
.topic-divider .td-label {{
  display: table-cell;
  font-size: {pt(T['size_h2'])}pt; font-weight: bold;
  color: {C['text_primary']};
  white-space: nowrap;
  padding-left: 8px;
}}
.topic-divider .td-line {{
  display: table-cell;
  width: 100%;
  border-bottom: 1px solid {C['border_light']};
  vertical-align: middle;
}}

/* ── Scenario card ── */
.scenario-card {{
  border: 1px solid {C['scenario_border']};
  border-radius: 7px; margin: 10px 0 14px;
  overflow: hidden; page-break-inside: avoid;
  background: {C['white']};
}}
.scenario-card .sc-head {{
  background: {C['scenario_header_bg']};
  padding: 7px 12px;
  border-bottom: 1px solid {C['border_light']};
}}
.scenario-card .sc-title {{
  font-size: {pt(9.5)}pt; font-weight: bold;
  color: {C['text_primary']};
}}
.scenario-card .sc-body {{ padding: 12px; }}

/* ── Patient quote ── */
.patient-quote {{
  background: {C['scenario_header_bg']};
  border-right: 3px solid {C['accent']};
  border-radius: 0 5px 5px 0;
  padding: 7px 11px; margin: 5px 0 10px;
  font-style: italic; color: {C['text_primary']};
}}

/* ── Boxes ── */
.box {{
  border-radius: 6px; padding: 10px 14px; margin: 7px 0;
  page-break-inside: avoid;
  overflow: hidden;
}}
.box .box-head {{
  font-size: {pt(8.5)}pt; font-weight: bold;
  margin-bottom: 5px;
}}
.box ul, .box ol {{
  padding-right: 15px;
  margin: 4px 0 2px;
}}
.box li {{
  margin-bottom: 4px;
  word-wrap: break-word;
}}
.box-warning  {{ background:{C['warning_bg']};  border:1px solid {C['warning_border']};  border-right:3px solid {C['warning_border']};  color:{C['warning_text']}; }}
.box-tip      {{ background:{C['tip_bg']};      border:1px solid {C['tip_border']};      border-right:3px solid {C['tip_border']};      color:{C['tip_text']}; }}
.box-question {{ background:{C['question_bg']}; border:1px solid {C['question_border']}; border-right:3px solid {C['question_border']}; }}
.box-dont     {{ background:{C['dont_bg']};     border:1px solid {C['dont_border']};     border-right:3px solid {C['dont_border']};     color:{C['dont_text']}; }}
.box-diag     {{ background:{C['diagnosis_bg']}; border:1px solid {C['diagnosis_border']}; border-right:3px solid {C['diagnosis_border']}; }}
.box-rec      {{ background:#EFF8FF; border:1px solid #4A9CBF; border-right:3px solid #4A9CBF; }}
.box-summary  {{ background:{C['accent_light']}; border:1px solid {C['accent']}; border-right:3px solid {C['accent']}; }}

/* ── Tables ──
   FIX: table-layout fixed + explicit column wrapping so Latin codes
   never overflow the cell border (the "text outside tables" bug). */
table {{
  width: 100%;
  table-layout: fixed;
  border-collapse: collapse;
  margin: 8px 0 12px; font-size: {pt(8)}pt;
  page-break-inside: avoid;
}}
thead tr {{ background: {C['table_header_bg']}; }}
thead th {{
  padding: 6px 8px; font-weight: bold;
  font-size: {pt(8)}pt; text-align: right;
  border: 1px solid {C['border_medium']};
  color: {C['text_primary']};
  word-wrap: break-word; overflow-wrap: break-word;
}}
tbody tr {{ background: {C['white']}; }}
tbody tr:nth-child(even) {{ background: {C['table_row_alt']}; }}
tbody td {{
  padding: 6px 8px; border: 1px solid {C['border_light']};
  vertical-align: top; text-align: right;
  word-wrap: break-word; overflow-wrap: break-word;
}}

/* ── Blockquote ── */
blockquote {{
  border-right: 3px solid {C['accent']};
  background: {C['accent_light']};
  border-radius: 0 6px 6px 0;
  padding: 8px 11px; margin: 8px 0;
  color: {C['accent_dark']}; font-style: italic;
  font-size: {pt(9)}pt;
}}

/* ── Pre / code block ── */
pre {{
  background: #F5F2ED; border: 1px solid {C['border_light']};
  border-radius: 5px; padding: 8px;
  font-size: {pt(7.5)}pt;
  overflow-x: auto; margin: 8px 0;
  white-space: pre-wrap; word-break: break-word;
}}

/* ── Chapter footer ── */
.ch-footer {{
  margin-top: 16px; padding-top: 8px;
  border-top: 1px solid {C['border_light']};
  font-size: {pt(7)}pt; color: {C['footer_text']};
  text-align: center;
}}

hr {{ border: none; border-top: 1px solid {C['border_light']}; margin: 10px 0; }}

/* ── Table of Contents ──
   .toc-pagenum::after uses CSS target-counter(), a Paged-Media feature
   WeasyPrint implements correctly: it resolves to the actual final page
   number of whatever element the <a href="#..."> link points to, at
   render time. No Python page-counting pass needed. */
.toc-page {{
  padding-top: 4px;
}}
.toc-heading {{
  font-size: {pt(26)}pt;
  font-weight: bold;
  color: {C['text_primary']};
  text-align: center;
  margin-bottom: 2px;
}}
.toc-heading-sub {{
  font-size: {pt(9)}pt;
  color: {C['text_muted']};
  text-align: center;
  letter-spacing: .15em;
  text-transform: uppercase;
  direction: ltr;
  margin-bottom: 22px;
}}
.toc-section-row {{
  margin: 18px 0 8px;
  padding-bottom: 5px;
  border-bottom: 1.5px solid {C['accent']};
  display: flex;
  justify-content: space-between;
  align-items: baseline;
}}
.toc-section-row:first-child {{ margin-top: 0; }}
.toc-section-label {{
  font-size: {pt(8.5)}pt;
  color: {C['text_muted']};
  letter-spacing: .1em;
}}
.toc-section-title {{
  font-size: {pt(13)}pt;
  font-weight: bold;
  color: {C['accent_dark']};
}}
.toc-row {{ margin: 0; }}
.toc-link {{
  display: flex;
  align-items: baseline;
  gap: 6px;
  padding: 5px 2px;
  text-decoration: none;
  color: {C['text_primary']};
  font-size: {pt(10)}pt;
}}
.toc-chapter-num {{
  color: {C['text_muted']};
  font-size: {pt(8.5)}pt;
  flex-shrink: 0;
  min-width: 16px;
}}
.toc-chapter-title {{
  flex-shrink: 0;
}}
.toc-dots {{
  flex: 1;
  border-bottom: 1px dotted {C['border_medium']};
  margin: 0 4px;
  transform: translateY(-3px);
}}
.toc-pagenum {{
  flex-shrink: 0;
  font-size: {pt(9.5)}pt;
  color: {C['accent_dark']};
  font-weight: bold;
  direction: ltr;
  min-width: 20px;
  text-align: left;
}}
/* The actual page-number magic: */
.toc-pagenum::after {{
  content: target-counter(attr(href), page);
}}
"""

# ═══════════════════════════════════════════════════════════════════════
# TEXT HELPERS
# ═══════════════════════════════════════════════════════════════════════
def esc(t):
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

# Matches a Latin run together with any directly-touching neutral/weak
# bidi punctuation (=, (, ), +, -, :) on either side. Swallowing this
# punctuation INTO the same isolated unit as the Latin run is the fix
# for a confirmed wkhtmltopdf/WebKit bidi-reordering bug: when a neutral
# character like "=" or "(" is left stranded between an RTL run and an
# isolated LTR run, the renderer's bidi algorithm visually overlaps the
# glyphs at that seam (reproduced and confirmed via isolated test cases,
# e.g. "= Otitis Media (التهاب..." collided; "Otitis Media (" as one
# isolated unit does not).
#
# SECOND FIX (found in full-book render audit): a bare leading numeral
# like "4." (list numbering) or "5-10" (a day range) was matching this
# pattern on its OWN, "stealing" the match before a LATER real Latin
# word's leading "(" could attach to it — e.g. in
# "4. ... العمل (Mechanism of Action)", the "4." consumed itself as an
# isolated unit, leaving "(Mechanism" with its opening paren stranded
# and uncollided-free. Requiring at least one actual LETTER in the
# core (via lookahead) excludes pure-numeral noise from ever matching,
# so the next real word's leading punctuation is free to attach.
_LATIN_CORE = (
    r'(?=[A-Za-z0-9\-\._%+/]*[A-Za-z])'   # lookahead: must contain ≥1 letter
    r'[A-Za-z0-9][A-Za-z0-9\-\._%+/]*'    # so bare numerals (e.g. "4.", "15-15")
    r'(?:\s+[A-Za-z0-9\-\._%+/]+)*'       # never falsely "steal" isolation from
)                                          # a following parenthesis (see FIX below)
_LATIN_PAT = re.compile(
    r'((?:[=\(\)\+\-:]\s*)?)'        # optional leading neutral punctuation
    r'(' + _LATIN_CORE + r')'        # the Latin run itself
    r'((?:\s*[=\(\)\+\-:])?)'        # optional trailing neutral punctuation
)

def isolate_ltr_raw(raw_text):
    """
    Runs on RAW escaped text only — BEFORE any markdown (**, *, `) is
    converted to real HTML tags. This ordering is critical: doing this
    after tag creation was the v2 root-cause bug (it matched literal
    tag names like 'strong' as if they were Latin drug-name text).
    """
    def repl(m):
        lead, core, trail = m.group(1), m.group(2), m.group(3)
        # NOTE: \x02 placed AFTER `trail`, not before — ensures trailing
        # punctuation like "(" stays INSIDE the isolated span boundary.
        return f"{lead}\x01{core}{trail}\x02"
    return _LATIN_PAT.sub(repl, raw_text)

def normalize_adjacent_bold(text):
    """
    FIX: merge **X** = **Y**  →  **X = Y**  (single <strong> span).
    Two adjacent <strong> elements separated only by neutral punctuation
    triggers the same WebKit bidi bug even when each side is individually
    isolated correctly. This is rare in the source content (found once
    across all 26 files) but merging proactively removes the trigger.
    """
    pattern = re.compile(r'\*\*([^*]+?)\*\*(\s*[=\-:]\s*)\*\*([^*]+?)\*\*')
    # Run twice to catch chains of 3+ adjacent bold spans, if any.
    text = pattern.sub(lambda m: f'**{m.group(1)}{m.group(2)}{m.group(3)}**', text)
    text = pattern.sub(lambda m: f'**{m.group(1)}{m.group(2)}{m.group(3)}**', text)
    return text

def finalize_ltr_markers(html_text):
    """
    Convert \x01...\x02 markers into real <span class='ltr'> tags.

    FIX v3 (final) — root cause of the visual collision was wkhtmltopdf's
    WebKit engine re-flowing inline-level bidi-isolated spans alongside
    bold Arabic text using its (buggy) Unicode bidi reordering. Neither
    RLM marks nor thin-space characters reliably fixed this (confirmed
    by render tests). The robust fix: render every .ltr span as
    `display:inline-block`. This removes it from the surrounding line's
    bidi reordering algorithm ENTIRELY — the browser treats it as an
    atomic box, like an image, so it can never be glyph-overlapped with
    neighboring RTL text regardless of bold/nesting context.

    UPDATE (final root-cause fix): inline-block alone did NOT fix the
    collision (confirmed by render test). The actual fix was upstream,
    in isolate_ltr_raw() — swallowing adjacent neutral punctuation
    (=, (, ), etc.) into the SAME isolated unit as the Latin run. Kept
    as inline-block here too since it's a harmless additional safeguard.
    """
    html_text = html_text.replace("\x01", '<span class="ltr">')
    html_text = html_text.replace("\x02", '</span>')
    return html_text

def inline_md(raw):
    """
    Correct pipeline order (fully debugged):
      1. Normalize adjacent bold spans joined by neutral punctuation
         (fixes the **X** = **Y** WebKit bidi trigger)
      2. Escape HTML special chars on RAW text
      3. Isolate Latin runs + their touching neutral punctuation
         (marker tokens \\x01..\\x02 — not real tags yet)
      4. Apply markdown bold/italic/code (creates real tags; regex only
         matches literal '**','*','`' chars, never touches the markers)
      5. Finalize LTR markers into real <span class="ltr"> tags
    """
    t = normalize_adjacent_bold(raw)
    t = esc(t)
    t = isolate_ltr_raw(t)
    # Bold
    t = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', t)
    # Italic (after bold, so ** is consumed first)
    t = re.sub(r'\*(.+?)\*', r'<em>\1</em>', t)
    # Inline code
    t = re.sub(r'`([^`]+)`', r'<code class="ltr-inline">\1</code>', t)
    t = finalize_ltr_markers(t)
    return t

def make_table(lines):
    rows = []
    for ln in lines:
        ln = ln.strip()
        if re.match(r'^\|[-:\s|]+\|$', ln):
            continue
        cells = [c.strip() for c in ln.strip('|').split('|')]
        rows.append(cells)
    if not rows:
        return ""
    ncols = len(rows[0])
    html = ['<table class="no-break">']
    html.append('<colgroup>' + f'<col style="width:{100/ncols:.1f}%">' * ncols + '</colgroup>')
    html.append('<thead><tr>' + ''.join(f'<th>{inline_md(c)}</th>' for c in rows[0]) + '</tr></thead>')
    html.append('<tbody>')
    for row in rows[1:]:
        cells = row + [''] * (ncols - len(row))  # pad short rows
        html.append('<tr>' + ''.join(f'<td>{inline_md(c)}</td>' for c in cells[:ncols]) + '</tr>')
    html.append('</tbody></table>')
    return '\n'.join(html) + '\n'

# ═══════════════════════════════════════════════════════════════════════
# IMAGE PLACEHOLDER REGISTRY
# ═══════════════════════════════════════════════════════════════════════
# Every visual_placeholder() call appends one entry here. After the PDF is
# rendered, a second pass (see generate_image_spec() at the bottom of this
# file) searches the PDF's text layer for each entry's unique marker
# string to find which real page it landed on, then writes
# image_specs.md — a reference file listing every image slot in the book
# with: page number, a content-aware description of what the image
# should depict, and the intended aspect ratio (derived from the actual
# CSS box it renders inside, so the ratio matches the real printed slot).
IMAGE_REGISTRY = []

def visual_placeholder(kind, description_ar, description_en, aspect_ratio,
                        context_title="", min_height_px=110):
    """
    kind            : short machine tag, e.g. 'chapter-cover', 'scenario'
    description_ar  : what the image should depict (Arabic, for the book)
    description_en  : same, in English (for the image_specs.md reference file)
    aspect_ratio     : intended W:H ratio as a string, e.g. "16:9", "4:3", "1:1"
    context_title    : chapter/topic title this placeholder belongs to,
                        used only for the spec file, not shown in the PDF
    min_height_px    : controls the rendered box height in the PDF itself

    IMAGE INSERTION: each call gets a 0-indexed slot number equal to its
    registration order (front-cover = slot 0, then one slot per file in
    book order: prereqs, then chapters, then extra sections — exactly
    the order they appear in the_book.json's "structure"). If
    images/{slot}.png exists on disk, it's embedded as a real <img>
    instead of the dashed placeholder box. Missing files fall back to
    the placeholder automatically, so a partial image set still builds
    a complete PDF.
    """
    idx  = len(IMAGE_REGISTRY) + 1     # 1-indexed marker (IMGSLOT-001, 002, ...)
    slot = idx - 1                     # 0-indexed image filename (0.png, 1.png, ...)
    marker = f"IMGSLOT-{idx:03d}"

    img_path  = IMAGES_DIR / f"{slot}.png"
    has_image = img_path.exists()

    IMAGE_REGISTRY.append({
        "id": marker,
        "kind": kind,
        "context": context_title,
        "description_ar": description_ar,
        "description_en": description_en,
        "aspect_ratio": aspect_ratio,
        "slot": slot,
        "has_image": has_image,
    })

    ar_css = aspect_ratio.replace(":", "/")

    if has_image:
        # Relative path resolves against base_url=SCRIPT_DIR, which is
        # passed into HTML(...).write_pdf() in __main__ — no need for
        # an absolute file:// URL here.
        rel_path = f"images/{slot}.png"
        return (
            f'<div class="visual-placeholder has-image" style="aspect-ratio:{ar_css}; min-height:{min_height_px}px">'
            f'<img class="vp-img" src="{rel_path}" alt="{esc(description_ar)}">'
            f'<div class="vp-marker">{marker}</div>'
            f'</div>\n'
        )

    # The marker is rendered as real (tiny, unobtrusive) text in the PDF
    # so the post-render pass can locate its page via text search. It is
    # styled to be visually negligible but NOT removed from the layout,
    # since WeasyPrint (correctly) does not expose a page-number-lookup
    # API from Python — searching rendered text is the reliable approach.
    return (
        f'<div class="visual-placeholder" style="aspect-ratio:{ar_css}; min-height:{min_height_px}px">'
        f'<div class="vp-cell">'
        f'<div class="vp-label">[ {esc(description_ar)} ]</div>'
        f'<div class="vp-sub">نسبة الأبعاد المقترحة: {esc(aspect_ratio)} &nbsp;·&nbsp; تُضاف لاحقاً</div>'
        f'<div class="vp-marker">{marker}</div>'
        f'</div></div>\n'
    )

BOX_MAP = {
    '⚡': ('box-question', 'اسأل أولاً'),
    '🔍': ('box-diag',     'التشخيص'),
    '💊': ('box-rec',      'التوصية'),
    '🚨': ('box-warning',  'تحذير — أحوّله فوراً'),
    '❌': ('box-dont',     'لا تعطي'),
    '💡': ('box-tip',      'ملاحظة مهمة'),
    '📋': ('box-summary',  'ملخص'),
}

def render_box(emoji, items):
    if not emoji or not items:
        return ""
    cls, label = BOX_MAP.get(emoji, ('box-tip', ''))
    li = ''.join(f'<li>{inline_md(x)}</li>' for x in items)
    return f'<div class="box {cls} no-break"><div class="box-head">{esc(label)}</div><ul>{li}</ul></div>\n'

# ═══════════════════════════════════════════════════════════════════════
# MARKDOWN → HTML PARSER
# ═══════════════════════════════════════════════════════════════════════
def md2html(md, h2_class="", chapter_title="", chapter_num=""):
    lines   = md.split('\n')
    out     = []
    i       = 0
    box_em  = None
    box_buf = []
    lst_buf = []
    lst_tag = None
    in_code = False
    code_buf= []
    in_sc   = False
    sc_head = ""
    sc_buf  = []
    current_topic = ""   # tracks the most recent ## 📌 topic, for placeholder context

    def push(el):
        (sc_buf if in_sc else out).append(el)

    def flush_list():
        nonlocal lst_buf, lst_tag
        if not lst_buf:
            return
        tag = 'ol' if lst_tag == 'ol' else 'ul'
        items = ''.join(f'<li>{inline_md(x)}</li>' for x in lst_buf)
        push(f'<{tag}>{items}</{tag}>\n')
        lst_buf = []; lst_tag = None

    def flush_box():
        nonlocal box_em, box_buf
        if box_em and box_buf:
            push(render_box(box_em, box_buf))
        box_em = None; box_buf = []

    def flush_scenario():
        nonlocal in_sc, sc_buf, sc_head
        if not in_sc:
            return
        body = '\n'.join(sc_buf)
        out.append(
            '<div class="scenario-card no-break">'
            f'<div class="sc-head"><div class="sc-title">{sc_head}</div></div>'
            f'<div class="sc-body">{body}</div></div>\n'
        )
        in_sc = False; sc_buf = []; sc_head = ""

    while i < len(lines):
        raw  = lines[i]
        line = raw.rstrip()

        # Code fence
        if line.strip().startswith('```'):
            if in_code:
                in_code = False
                code_html = esc('\n'.join(code_buf))
                push(f'<pre class="ltr-block"><code>{code_html}</code></pre>\n')
                code_buf = []
            else:
                flush_list(); flush_box()
                in_code = True
            i += 1; continue
        if in_code:
            code_buf.append(raw); i += 1; continue

        # Blank line
        if not line.strip():
            flush_list(); i += 1; continue

        # H1 — SKIP rendering text (chapter header from JSON used instead);
        # just emit ONE chapter-cover illustration placeholder, with a
        # description tailored to this specific chapter's subject.
        if line.startswith('# '):
            flush_list(); flush_box(); flush_scenario()
            out.append(visual_placeholder(
                kind="chapter-cover",
                description_ar=f"صورة غلاف توضيحية لفصل: {chapter_title}",
                description_en=(
                    f"Chapter-opening illustration for '{chapter_title}'. "
                    f"Should visually represent the chapter's medical subject "
                    f"area at a glance (e.g. a clean icon-style or editorial "
                    f"illustration relevant to the topic) — this is the large "
                    f"image readers see first when opening the chapter, right "
                    f"under the colored chapter-title banner."
                ),
                aspect_ratio="16:9",
                context_title=f"الفصل {chapter_num} — {chapter_title}",
                min_height_px=140,
            ))
            i += 1; continue

        # Topic divider  ## 📌 ...
        if re.match(r'^##\s*📌', line):
            flush_list(); flush_box(); flush_scenario()
            txt = re.sub(r'^##\s*📌\s*', '', line).strip()
            out.append(
                '<div class="topic-divider"><div class="td-row">'
                f'<div class="td-label">{inline_md(txt)}</div>'
                '<div class="td-line"></div>'
                '</div></div>\n'
            )
            i += 1; continue

        # H2
        if line.startswith('## '):
            flush_list(); flush_box(); flush_scenario()
            txt = line[3:].strip()
            out.append(f'<h2 class="{h2_class}">{inline_md(txt)}</h2>\n')
            i += 1; continue

        # Scenario header  ### 🗣️ ...
        if re.match(r'^###\s*🗣', line):
            flush_list(); flush_box(); flush_scenario()
            txt = re.sub(r'^###\s*🗣️?\s*', '', line).strip()
            in_sc, sc_head = True, inline_md(txt)
            i += 1; continue

        # H3
        if line.startswith('### '):
            flush_list(); flush_box(); flush_scenario()
            txt = line[4:].strip()
            push(f'<h3>{inline_md(txt)}</h3>\n')
            i += 1; continue

        # H4
        if line.startswith('#### '):
            flush_list(); flush_box()
            txt = line[5:].strip()
            push(f'<h4>{inline_md(txt)}</h4>\n')
            i += 1; continue

        # Table
        if line.strip().startswith('|'):
            flush_list(); flush_box()
            tbl_lines = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                tbl_lines.append(lines[i]); i += 1
            push(make_table(tbl_lines))
            continue

        # HR
        if re.match(r'^[-*_]{3,}$', line.strip()):
            flush_list(); flush_box()
            push('<hr/>\n'); i += 1; continue

        # Blockquote
        if line.startswith('>'):
            flush_list(); flush_box()
            txt = line.lstrip('> ').strip()
            push(f'<blockquote>{inline_md(txt)}</blockquote>\n')
            i += 1; continue

        # Emoji box header   **⚡ ...**
        m = re.match(r'^\*\*(⚡|🔍|💊|🚨|❌|💡|📋)[^*]*\*\*\s*:?\s*$', line.strip())
        if m:
            flush_list()
            if box_em:
                flush_box()
            box_em, box_buf = m.group(1), []
            i += 1; continue

        # Patient dialogue   **المريض:** "..."
        pm = re.match(
            r'^\*\*(المريض[^:*]*|المريضة[^:*]*|الأم[^:*]*)\*\*\s*:\s*[\*"\'\u201c](.+?)[\*"\'\u201d]?\s*$',
            line.strip()
        )
        if pm:
            flush_list(); flush_box()
            who, quote = pm.group(1), pm.group(2).strip().strip('*"\'')
            push(f'<p><strong>{esc(who)}:</strong></p>'
                 f'<div class="patient-quote">&quot;{inline_md(quote)}&quot;</div>\n')
            i += 1; continue

        # Lists
        bm = re.match(r'^(\s*)[-*]\s+(.+)', line)
        nm = re.match(r'^(\s*)\d+\.\s+(.+)', line)
        if bm or nm:
            txt  = (bm or nm).group(2)
            kind = 'ol' if nm else 'ul'
            if box_em:
                box_buf.append(txt)
            else:
                if lst_tag != kind:
                    flush_list(); lst_tag = kind
                lst_buf.append(txt)
            i += 1; continue

        # Paragraph
        flush_list()
        if box_em:
            box_buf.append(line.strip())
        else:
            push(f'<p>{inline_md(line.strip())}</p>\n')
        i += 1

    flush_list(); flush_box(); flush_scenario()
    return ''.join(out)

# ═══════════════════════════════════════════════════════════════════════
# PAGE BUILDERS
# ═══════════════════════════════════════════════════════════════════════
def section_page(sec):
    color = sec["accent"]
    return (
        '<div class="section-page"><div class="sp-cell">'
        f'<div class="sp-label">{esc(sec["label"])}</div>'
        f'<div class="sp-title">{esc(sec["title_ar"])}</div>'
        f'<div class="sp-bar" style="background:{color}"></div>'
        '</div></div>\n'
    )

def chapter_header(item, sec):
    color = sec["accent"]
    lbl   = f'{esc(sec["label"])} — الفصل {esc(item["num"])}'
    anchor_id = f'ch-{sec["id"]}-{item["num"]}'
    return (
        f'<div class="chapter-header" id="{anchor_id}" style="background:{color}">'
        f'<div class="ch-bgnum ltr">{item["num"]}</div>'
        '<div class="ch-inner">'
        f'<div class="ch-label">{lbl}</div>'
        f'<div class="ch-title">{esc(item["title_ar"])}</div>'
        '</div></div>\n'
    )

def title_page():
    cover_img = visual_placeholder(
        kind="front-cover",
        description_ar="صورة غلاف الكتاب الرئيسية",
        description_en=(
            "Main front-cover illustration for the whole book. Should "
            "capture the book's identity at a glance — pharmacy/medical "
            "still-life elements (e.g. mortar and pestle, pill blister "
            "pack, medicine bottles, a stethoscope, or similar pharmacy-"
            "themed iconography), in a style that reads as professional "
            "and editorial rather than clinical/sterile. This is the "
            "single most important image in the book — it sets the tone "
            "for everything after it."
        ),
        aspect_ratio="4:3",
        context_title="غلاف الكتاب — Front Cover",
        min_height_px=180,
    )
    return (
        '<div class="title-page"><div class="tp-cell">'
        f'<div style="max-width:78%; margin:0 auto 18px">{cover_img}</div>'
        f'<div style="font-family:\'{FONT_NAME}\',serif;font-size:{pt(30)}pt;font-weight:bold;'
        f'color:{C["accent"]};letter-spacing:-.01em;margin-bottom:4px;direction:ltr">'
        'BetterDiagnosis</div>'
        f'<div style="font-size:{pt(19)}pt;font-weight:bold;color:{C["text_primary"]};margin-bottom:10px">'
        f'{esc(META["title_ar"])}</div>'
        f'<div style="width:42px;height:3px;background:{C["accent"]};border-radius:2px;margin:0 auto 14px"></div>'
        f'<div style="font-size:{pt(10)}pt;color:{C["text_secondary"]};margin-bottom:28px">'
        f'{esc(META["tagline_ar"])}</div>'
        f'<div style="font-size:{pt(7.5)}pt;color:{C["text_muted"]}">'
        f'{esc(META["edition"])} &nbsp;&middot;&nbsp; {esc(META["copyright"])}</div>'
        '</div></div>\n'
    )

def resolve(filename, sec_id):
    return (BOOK_ROOT if sec_id == "prereqs" else MAIN_DIR) / filename

def toc_page():
    """
    Table of Contents — placed after the title page, before Section 1.

    Page numbers are resolved automatically by WeasyPrint at render time
    using CSS target-counter(), which reads the actual final page number
    of the element with the matching #id — no Python-side page-counting
    pass or post-processing needed. This is a native CSS Paged Media
    feature WeasyPrint implements correctly (and wkhtmltopdf did not
    support reliably, which is part of why this wasn't attempted with
    the old engine).
    """
    rows = []
    for sec in CFG["structure"]["sections"]:
        rows.append(
            f'<div class="toc-section-row">'
            f'<span class="toc-section-label">{esc(sec["label"])}</span>'
            f'<span class="toc-section-title">{esc(sec["title_ar"])}</span>'
            f'</div>'
        )
        for item in sec["files"]:
            anchor_id = f'ch-{sec["id"]}-{item["num"]}'
            rows.append(
                '<div class="toc-row">'
                f'<a class="toc-link" href="#{anchor_id}">'
                f'<span class="toc-chapter-num ltr">{esc(item["num"])}</span>'
                f'<span class="toc-chapter-title">{esc(item["title_ar"])}</span>'
                '<span class="toc-dots"></span>'
                '<span class="toc-pagenum"></span>'
                '</a>'
                '</div>'
            )

    return (
        '<div class="toc-page break-before">'
        f'<div class="toc-heading">الفهرس</div>'
        f'<div class="toc-heading-sub">Table of Contents</div>'
        '<div class="toc-body">'
        + ''.join(rows) +
        '</div></div>\n'
    )

# ═══════════════════════════════════════════════════════════════════════
# BUILD
# ═══════════════════════════════════════════════════════════════════════
def build():
    css = build_css()
    parts = [f"""<!DOCTYPE html>
<html lang="ar" dir="rtl"><head><meta charset="UTF-8"/><title>BetterDiagnosis</title>
<style>{css}</style></head><body>
{title_page()}
{toc_page()}
"""]

    for sec in CFG["structure"]["sections"]:
        h2c = {"prereqs": "prereq", "extra": "extra"}.get(sec["id"], "")
        parts.append(section_page(sec))

        for item in sec["files"]:
            path = resolve(item["file"], sec["id"])
            if not path.exists():
                print(f"  ⚠  MISSING: {path}", file=sys.stderr)
                continue
            md = path.read_text(encoding="utf-8")
            print(f"  ✓  {item['file']}")
            parts.append(chapter_header(item, sec))
            parts.append(md2html(md, h2_class=h2c, chapter_title=item["title_ar"], chapter_num=item["num"]))
            parts.append(
                f'<div class="ch-footer">{esc(sec["label"])} — {esc(item["title_ar"])} '
                f'&nbsp;&middot;&nbsp; BetterDiagnosis {esc(META["edition"])}</div>\n'
            )
            # NOTE: page-break-before is on the NEXT chapter-header, not forced here,
            # so short chapters no longer leave a half-empty page (FIX for BUG 3).

    parts.append("</body></html>")
    return ''.join(parts)

# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════
def generate_image_spec(pdf_path: Path, out_path: Path):
    """
    Second pass, run after the PDF exists: searches every page's text
    layer for each IMGSLOT-NNN marker (rendered as near-invisible real
    text by visual_placeholder()) to find which actual page it landed
    on, then writes image_specs.md — a single reference file listing
    every image slot in the book with its page number, a description
    of what it should depict, and its intended aspect ratio.

    This has to be a post-render pass (not computed during HTML build)
    because page numbers only exist after WeasyPrint has paginated the
    full flowed content — there is no reliable way to predict final
    page numbers from the source HTML alone.
    """
    try:
        from pypdf import PdfReader
    except ImportError:
        print("\n⚠ pypdf not installed — skipping image_specs.md generation.")
        print("  Run: pip install pypdf")
        return

    print("\nLocating image placeholders in rendered PDF...")
    reader = PdfReader(str(pdf_path))
    marker_to_page = {}
    for entry in IMAGE_REGISTRY:
        marker_to_page[entry["id"]] = None

    for page_num, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        for marker in marker_to_page:
            if marker_to_page[marker] is None and marker in text:
                marker_to_page[marker] = page_num

    lines = [
        "# BetterDiagnosis — Image Specification Sheet",
        "",
        "> Auto-generated by build_book_local.py after PDF render.",
        "> Each entry below corresponds to one dashed placeholder box in the PDF.",
        "> Page numbers refer to the actual printed page in BetterDiagnosis_book.pdf.",
        "> Colors, line style, and exact visual treatment are intentionally left",
        "> undefined here — only content/composition and aspect ratio are specified.",
        "",
        f"**Total image slots:** {len(IMAGE_REGISTRY)}",
        "",
        "---",
        "",
    ]

    for entry in IMAGE_REGISTRY:
        page_num = marker_to_page.get(entry["id"])
        page_str = f"Page {page_num}" if page_num else "Page: NOT FOUND (check marker rendering)"
        lines.append(f"## {entry['id']} — {page_str}")
        lines.append("")
        lines.append(f"- **Kind:** `{entry['kind']}`")
        if entry["context"]:
            lines.append(f"- **Context:** {entry['context']}")
        lines.append(f"- **Aspect ratio:** {entry['aspect_ratio']}")
        lines.append(f"- **Description (AR):** {entry['description_ar']}")
        lines.append(f"- **Description (EN):** {entry['description_en']}")
        lines.append("")
        lines.append("---")
        lines.append("")

    out_path.write_text('\n'.join(lines), encoding="utf-8")
    found = sum(1 for v in marker_to_page.values() if v is not None)
    print(f"✓ image_specs.md written: {found}/{len(IMAGE_REGISTRY)} placeholders located")
    print(f"  → {out_path}")

# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("\nBetterDiagnosis Book Builder v4 (WeasyPrint engine)")
    print("─" * 44)
    print(f"Book root : {BOOK_ROOT}")
    print(f"Font      : {FONT_NAME}")
    print(f"Trim size : {PAGE_W_MM}mm × {PAGE_H_MM}mm  (6in × 9in book format)")
    print(f"Engine    : WeasyPrint")
    print(f"Output    : {OUT_PDF}")
    print("─" * 44)

    print("\nBuilding HTML...")
    html = build()
    OUT_HTML.write_text(html, encoding="utf-8")
    print(f"HTML done: {len(html)//1024} KB")

    print("\nConverting to PDF (WeasyPrint)...")
    try:
        from weasyprint import HTML
    except ImportError:
        print("\n✗ WeasyPrint not installed.")
        print("  Run: pip install weasyprint")
        print("  (or re-run install_env.sh, which now installs it automatically)")
        sys.exit(1)

    try:
        HTML(string=html, base_url=str(SCRIPT_DIR)).write_pdf(str(OUT_PDF))
        mb = OUT_PDF.stat().st_size / 1_000_000
        print(f"\n✓ Done! PDF: {OUT_PDF}")
        print(f"  Size: {mb:.1f} MB")

        OUT_IMAGE_SPEC = SCRIPT_DIR / "image_specs.md"
        generate_image_spec(OUT_PDF, OUT_IMAGE_SPEC)

    except Exception as e:
        print(f"\n✗ WeasyPrint error:\n{e}")
        sys.exit(1)