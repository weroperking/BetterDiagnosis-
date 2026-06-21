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
MARGIN_TOP_MM    = 16
MARGIN_BOTTOM_MM = 18
MARGIN_OUTER_MM  = 14
MARGIN_INNER_MM  = 16

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
  line-height: {T['line_height']};
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

/* ── Headings ── */
h1 {{
  font-size: {pt(T['size_h1']*0.72)}pt; font-weight: bold;
  color: {C['text_primary']};
  line-height: {T['h_line_height']};
  margin: 16px 0 8px;
  padding-bottom: 6px;
  border-bottom: 2px solid {C['border_light']};
}}
h2 {{
  font-size: {pt(T['size_h2']*0.78)}pt; font-weight: bold;
  color: {C['text_primary']};
  margin: 14px 0 7px;
  padding-right: 11px;
  border-right: 3px solid {C['accent']};
}}
h2.prereq {{ border-right-color: {C['prereq_accent']}; }}
h2.extra  {{ border-right-color: {C['section_accent']}; }}
h3 {{
  font-size: {pt(T['size_h3']*0.85)}pt; font-weight: bold;
  color: {C['text_secondary']};
  margin: 11px 0 6px;
}}
h4 {{
  font-size: {pt(T['size_h4']*0.9)}pt; font-weight: bold;
  color: {C['text_secondary']};
  margin: 9px 0 4px;
}}

/* ── Body ── */
p {{ margin-bottom: 7px; }}
strong {{ font-weight: bold; color: {C['text_primary']}; }}
em {{ font-style: italic; }}
code {{
  font-family: 'Courier New', 'DejaVu Sans Mono', monospace;
  background: {C['accent_light']};
  padding: 1px 4px; border-radius: 3px;
  font-size: {pt(8)}pt;
}}

ul, ol {{ padding-right: 17px; margin: 6px 0 9px; }}
li {{ margin-bottom: 3px; line-height: {T['line_height']}; }}

/* ── Topic divider ── */
.topic-divider {{
  display: table;
  width: 100%;
  margin: 16px 0 10px;
  page-break-inside: avoid;
}}
.topic-divider .td-row {{ display: table-row; }}
.topic-divider .td-label {{
  display: table-cell;
  font-size: {pt(T['size_h2']*0.78)}pt; font-weight: bold;
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

def visual_placeholder(label="مساحة للصورة التوضيحية", sub="تُضاف لاحقاً"):
    return (f'<div class="visual-placeholder"><div class="vp-cell">'
            f'<div class="vp-label">[ {esc(label)} ]</div>'
            f'<div class="vp-sub">{esc(sub)}</div>'
            f'</div></div>\n')

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
def md2html(md, h2_class=""):
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
        # just emit the chapter-illustration placeholder once.
        if line.startswith('# '):
            flush_list(); flush_box(); flush_scenario()
            out.append(visual_placeholder("صورة توضيحية للفصل"))
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
    return (
        f'<div class="chapter-header" style="background:{color}">'
        f'<div class="ch-bgnum ltr">{item["num"]}</div>'
        '<div class="ch-inner">'
        f'<div class="ch-label">{lbl}</div>'
        f'<div class="ch-title">{esc(item["title_ar"])}</div>'
        '</div></div>\n'
    )

def title_page():
    return (
        '<div class="title-page"><div class="tp-cell">'
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

# ═══════════════════════════════════════════════════════════════════════
# BUILD
# ═══════════════════════════════════════════════════════════════════════
def build():
    css = build_css()
    parts = [f"""<!DOCTYPE html>
<html lang="ar" dir="rtl"><head><meta charset="UTF-8"/><title>BetterDiagnosis</title>
<style>{css}</style></head><body>
{title_page()}
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
            parts.append(md2html(md, h2_class=h2c))
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
    except Exception as e:
        print(f"\n✗ WeasyPrint error:\n{e}")
        sys.exit(1)
