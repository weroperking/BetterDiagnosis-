
#!/usr/bin/env python3
"""
BetterDiagnosis — PDF Book Builder (Local Version v2)
─────────────────────────────────────────────────────
Fixes applied vs v1:
  1. H1 from markdown SKIPPED — chapter header from JSON is authoritative
  2. Latin codes in tables wrapped in <span class="ltr"> for bidi isolation
  3. --zoom 1.33 corrects 96-DPI screen → 72-DPI PDF mismatch (content fills page)
  4. --disable-smart-shrinking prevents wkhtmltopdf from auto-shrinking content
  5. Font: uses Amiri from fonts/ dir if present; falls back to FreeSerif
  6. CSS font sizes divided by 1.33 so they render correct after zoom
  7. Visual placeholder uses text-only (no emoji that won't render)
  8. RTL table cells fixed with explicit direction on every td/th
  9. Code blocks properly isolated as LTR
  10. Box icons use ASCII fallbacks in case emoji unsupported
─────────────────────────────────────────────────────
USAGE:
  1. Place this file inside your BetterDiagnosis/ folder (same level as README.md)
  2. Run: python3 build_book_local.py
  3. Output: BetterDiagnosis_book.pdf  (same folder)
─────────────────────────────────────────────────────
"""

import json, os, re, subprocess, sys
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════════
# PATH CONFIG  — script auto-detects based on its own location
# ═══════════════════════════════════════════════════════════════════════
SCRIPT_DIR = Path(__file__).parent.resolve()
BOOK_ROOT  = SCRIPT_DIR                  # prereq files live here
MAIN_DIR   = SCRIPT_DIR / "main_content" # ch* and section_* files
JSON_FILE  = SCRIPT_DIR / "the_book.json"
FONTS_DIR  = SCRIPT_DIR / "fonts"
OUT_HTML   = SCRIPT_DIR / "_book_build.html"
OUT_PDF    = SCRIPT_DIR / "BetterDiagnosis_book.pdf"

# ── Load config ───────────────────────────────────────────────────────
if not JSON_FILE.exists():
    print(f"ERROR: {JSON_FILE} not found. Make sure the_book.json is in the same folder.")
    sys.exit(1)

with open(JSON_FILE, encoding="utf-8") as f:
    CFG = json.load(f)

C  = CFG["colors"]
T  = CFG["typography"]
P  = CFG["page"]
CO = CFG["components"]
META = CFG["meta"]

# ── Font detection ────────────────────────────────────────────────────
# Zoom factor: wkhtmltopdf renders at 96dpi, PDF is 72dpi → ratio 1.333
# All CSS pt sizes divided by this factor so they look correct after zoom.
ZOOM = 1.33
Z    = ZOOM  # shorthand

def scaled(pt):
    """Scale a font size down so after zoom=1.33 it renders at intended size."""
    return round(pt / Z, 1)

def find_font(name):
    """Look for a font file in the fonts/ directory."""
    for ext in ["ttf", "TTF", "otf", "OTF"]:
        p = FONTS_DIR / f"{name}.{ext}"
        if p.exists():
            return str(p)
    return None

AMIRI_REG  = find_font("Amiri-Regular")
AMIRI_BOLD = find_font("Amiri-Bold")

# System fallbacks
FREESERIF_REG  = "/usr/share/fonts/truetype/freefont/FreeSerif.ttf"
FREESERIF_BOLD = "/usr/share/fonts/truetype/freefont/FreeSerifBold.ttf"

if AMIRI_REG and AMIRI_BOLD:
    FONT_REG  = AMIRI_REG
    FONT_BOLD = AMIRI_BOLD
    FONT_NAME = "Amiri"
    print("✓ Using Amiri font (best quality)")
elif os.path.exists(FREESERIF_REG):
    FONT_REG  = FREESERIF_REG
    FONT_BOLD = FREESERIF_BOLD
    FONT_NAME = "FreeSerif"
    print("⚠ Amiri not found — using FreeSerif (run install_env.sh for better quality)")
else:
    FONT_REG  = None
    FONT_BOLD = None
    FONT_NAME = "serif"
    print("⚠ No Arabic TTF found — using system serif font")

# ═══════════════════════════════════════════════════════════════════════
# CSS
# ═══════════════════════════════════════════════════════════════════════
def build_css():
    # @font-face block
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

/* ── Reset ── */
* {{ box-sizing: border-box; margin: 0; padding: 0; }}

/* ── Page ── */
@page {{
  size: A4;
  margin: {P['margin_top_mm']}mm {P['margin_outer_mm']}mm {P['margin_bottom_mm']}mm {P['margin_inner_mm']}mm;
}}

/* ── Body ── */
body {{
  font-family: {fam};
  font-size: {scaled(T['size_body'])}pt;
  line-height: {T['line_height']};
  color: {C['text_primary']};
  background: {C['page_bg']};
  direction: rtl;
  unicode-bidi: embed;
  word-spacing: 0.05em;
}}

/* ── LTR isolation for Latin codes inside RTL text ── */
.ltr, code, pre, .ltr-block {{
  direction: ltr !important;
  unicode-bidi: isolate !important;
}}
.ltr {{ display: inline; }}
.ltr-block {{ display: block; }}

/* ── Page breaks ── */
.page-break  {{ page-break-after: always; height: 0; }}
.no-break    {{ page-break-inside: avoid; }}
.break-before {{ page-break-before: always; }}

/* ── Section divider page ── */
.section-page {{
  page-break-before: always;
  page-break-after:  always;
  min-height: 96vh;
  display: flex; flex-direction: column;
  justify-content: center; align-items: center;
  text-align: center;
  background: {C['page_bg']};
}}
.section-page .sp-label {{
  font-size: {scaled(11)}pt;
  color: {C['text_muted']};
  letter-spacing: .18em;
  margin-bottom: 16px;
  text-transform: uppercase;
}}
.section-page .sp-title {{
  font-size: {scaled(30)}pt;
  font-weight: bold;
  color: {C['text_primary']};
  margin-bottom: 22px;
  line-height: 1.3;
}}
.section-page .sp-bar {{
  width: 55px; height: 4px;
  border-radius: 2px; margin: 0 auto;
}}

/* ── Chapter header ── */
.chapter-header {{
  page-break-before: always;
  padding: 32px 28px 26px;
  margin-bottom: 26px;
  position: relative;
  overflow: hidden;
  border-radius: 0 0 10px 10px;
  min-height: 95px;
}}
.chapter-header .ch-bgnum {{
  position: absolute;
  left: 12px; top: -8px;
  font-size: {scaled(90)}pt;
  font-weight: bold;
  color: rgba(255,255,255,0.12);
  line-height: 1;
  direction: ltr;
  unicode-bidi: isolate;
  z-index: 0;
  pointer-events: none;
}}
.chapter-header .ch-inner {{
  position: relative; z-index: 1;
}}
.chapter-header .ch-label {{
  font-size: {scaled(9)}pt;
  letter-spacing: .22em;
  color: rgba(255,255,255,0.72);
  margin-bottom: 9px;
  text-transform: uppercase;
  direction: rtl;
}}
.chapter-header .ch-title {{
  font-size: {scaled(22)}pt;
  font-weight: bold;
  color: #FFFFFF;
  line-height: 1.35;
}}

/* ── Visual placeholder ── */
.visual-placeholder {{
  width: 100%;
  height: {CO['visual_placeholder']['height_px']}px;
  border: 1.5px dashed {C['placeholder_border']};
  border-radius: 8px;
  background: {C['placeholder_bg']};
  display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  margin: 16px 0 22px;
  color: {C['placeholder_text']};
  page-break-inside: avoid;
  text-align: center;
}}
.visual-placeholder .vp-label {{
  font-size: {scaled(11)}pt;
  font-weight: bold;
  margin-bottom: 4px;
}}
.visual-placeholder .vp-sub {{
  font-size: {scaled(9)}pt;
  opacity: 0.65;
}}

/* ── Headings ── */
h1 {{
  font-size: {scaled(T['size_h1'])}pt; font-weight: bold;
  color: {C['text_primary']};
  line-height: {T['h_line_height']};
  margin: 20px 0 10px;
  padding-bottom: 7px;
  border-bottom: 2px solid {C['border_light']};
  direction: rtl;
}}
h2 {{
  font-size: {scaled(T['size_h2'])}pt; font-weight: bold;
  color: {C['text_primary']};
  margin: 18px 0 9px;
  padding-right: 13px;
  border-right: 4px solid {C['accent']};
  direction: rtl;
}}
h2.prereq {{ border-right-color: {C['prereq_accent']}; }}
h2.extra   {{ border-right-color: {C['section_accent']}; }}
h3 {{
  font-size: {scaled(T['size_h3'])}pt; font-weight: bold;
  color: {C['text_secondary']};
  margin: 14px 0 7px;
  direction: rtl;
}}
h4 {{
  font-size: {scaled(T['size_h4'])}pt; font-weight: bold;
  color: {C['text_secondary']};
  margin: 10px 0 5px;
  direction: rtl;
}}

/* ── Body text ── */
p  {{ margin-bottom: 8px; direction: rtl; }}
strong {{ font-weight: bold; color: {C['text_primary']}; }}
em {{ font-style: italic; }}
code {{
  font-family: 'Courier New', 'DejaVu Sans Mono', monospace;
  background: {C['accent_light']};
  padding: 1px 5px; border-radius: 3px;
  font-size: {scaled(9)}pt;
  direction: ltr; unicode-bidi: isolate;
  display: inline;
}}

/* ── Lists ── */
ul, ol {{ padding-right: 20px; margin: 7px 0 10px; direction: rtl; }}
li {{ margin-bottom: 4px; line-height: {T['line_height']}; direction: rtl; }}

/* ── Topic divider (📌 line) ── */
.topic-divider {{
  display: flex; align-items: center; gap: 10px;
  margin: 20px 0 12px;
  page-break-inside: avoid;
  direction: rtl;
}}
.topic-divider .td-label {{
  font-size: {scaled(T['size_h2'])}pt; font-weight: bold;
  color: {C['text_primary']}; flex: 1;
}}
.topic-divider .td-line {{
  flex: 1; height: 1px; background: {C['border_light']};
}}

/* ── Scenario card ── */
.scenario-card {{
  border: 1px solid {C['scenario_border']};
  border-radius: 8px; margin: 12px 0 18px;
  overflow: hidden; page-break-inside: avoid;
  background: {C['white']};
  box-shadow: 0 1px 4px rgba(0,0,0,0.06);
}}
.scenario-card .sc-head {{
  background: {C['scenario_header_bg']};
  padding: 9px 16px;
  border-bottom: 1px solid {C['border_light']};
  direction: rtl;
}}
.scenario-card .sc-title {{
  font-size: {scaled(11.5)}pt; font-weight: bold;
  color: {C['text_primary']};
}}
.scenario-card .sc-body {{ padding: 16px; direction: rtl; }}

/* ── Patient quote ── */
.patient-quote {{
  background: {C['scenario_header_bg']};
  border-right: 3px solid {C['accent']};
  border-radius: 0 6px 6px 0;
  padding: 9px 13px; margin: 7px 0 12px;
  font-style: italic; color: {C['text_primary']};
  direction: rtl;
}}

/* ── Colored boxes ── */
.box {{
  border-radius: 7px; padding: 12px 15px; margin: 9px 0;
  page-break-inside: avoid; direction: rtl;
}}
.box .box-head {{
  font-size: {scaled(10)}pt; font-weight: bold;
  margin-bottom: 6px; direction: rtl;
}}
.box-warning  {{ background:{C['warning_bg']};  border:1px solid {C['warning_border']};  border-right:4px solid {C['warning_border']};  color:{C['warning_text']}; }}
.box-tip      {{ background:{C['tip_bg']};      border:1px solid {C['tip_border']};      border-right:4px solid {C['tip_border']};      color:{C['tip_text']}; }}
.box-question {{ background:{C['question_bg']}; border:1px solid {C['question_border']}; border-right:4px solid {C['question_border']}; }}
.box-dont     {{ background:{C['dont_bg']};     border:1px solid {C['dont_border']};     border-right:4px solid {C['dont_border']};     color:{C['dont_text']}; }}
.box-diag     {{ background:{C['diagnosis_bg']}; border:1px solid {C['diagnosis_border']}; border-right:4px solid {C['diagnosis_border']}; }}
.box-rec      {{ background:#EFF8FF; border:1px solid #4A9CBF; border-right:4px solid #4A9CBF; }}
.box-summary  {{ background:{C['accent_light']}; border:1px solid {C['accent']}; border-right:4px solid {C['accent']}; }}

/* ── Tables ── */
table {{
  width: 100%; border-collapse: collapse;
  margin: 10px 0 14px; font-size: {scaled(9.5)}pt;
  page-break-inside: avoid; direction: rtl;
}}
thead tr {{ background: {C['table_header_bg']}; }}
thead th {{
  padding: 8px 10px; font-weight: bold;
  font-size: {scaled(9.5)}pt; text-align: right;
  border: 1px solid {C['border_medium']};
  color: {C['text_primary']}; direction: rtl;
}}
tbody tr {{ background: {C['white']}; }}
tbody tr:nth-child(even) {{ background: {C['table_row_alt']}; }}
tbody td {{
  padding: 7px 10px; border: 1px solid {C['border_light']};
  vertical-align: top; text-align: right; direction: rtl;
}}

/* ── Blockquote ── */
blockquote {{
  border-right: 4px solid {C['accent']};
  background: {C['accent_light']};
  border-radius: 0 8px 8px 0;
  padding: 10px 14px; margin: 10px 0;
  color: {C['accent_dark']}; font-style: italic;
  direction: rtl;
}}

/* ── Pre / code block ── */
pre {{
  background: #F5F2ED; border: 1px solid {C['border_light']};
  border-radius: 6px; padding: 10px;
  direction: ltr; unicode-bidi: isolate;
  font-size: {scaled(8.5)}pt;
  overflow-x: auto; margin: 10px 0;
  white-space: pre-wrap; word-break: break-all;
}}

/* ── Chapter footer ── */
.ch-footer {{
  margin-top: 22px; padding-top: 10px;
  border-top: 1px solid {C['border_light']};
  font-size: {scaled(8)}pt; color: {C['text_muted']};
  text-align: center;
}}

/* ── HR ── */
hr {{ border: none; border-top: 1px solid {C['border_light']}; margin: 12px 0; }}
"""

# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════
def esc(t):
    return t.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

# Wrap Latin sequences (codes, drug names, abbreviations) in LTR spans
_LATIN_PAT = re.compile(
    r'([A-Za-z][A-Za-z0-9\-\._%+/]{1,}(?:\s*[A-Za-z0-9\-]+)*)'
)
def isolate_ltr(text):
    """Wrap Latin-dominant substrings in LTR isolation spans."""
    def replace(m):
        s = m.group(1)
        return f'<span class="ltr">{esc(s)}</span>'
    return _LATIN_PAT.sub(replace, text)

def inline_md(t):
    # Bold
    t = re.sub(r'\*\*(.+?)\*\*', lambda m: f'<strong>{inline_md(m.group(1))}</strong>', t)
    # Italic
    t = re.sub(r'\*(.+?)\*',     lambda m: f'<em>{m.group(1)}</em>', t)
    # Inline code
    t = re.sub(r'`([^`]+)`',     lambda m: f'<code class="ltr">{esc(m.group(1))}</code>', t)
    # After bold/italic, isolate Latin
    t = isolate_ltr(t)
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
    html = '<table class="no-break">\n  <thead><tr>'
    for c in rows[0]:
        html += f'<th>{inline_md(esc(c))}</th>'
    html += '</tr></thead>\n  <tbody>\n'
    for row in rows[1:]:
        html += '    <tr>'
        for c in row:
            html += f'<td>{inline_md(esc(c))}</td>'
        html += '</tr>\n'
    html += '  </tbody>\n</table>\n'
    return html

def visual_placeholder(label="مساحة للصورة التوضيحية", sub="تُضاف لاحقاً"):
    return (f'<div class="visual-placeholder">'
            f'<div class="vp-label">[ {esc(label)} ]</div>'
            f'<div class="vp-sub">{esc(sub)}</div>'
            f'</div>\n')

BOX_MAP = {
    '⚡': ('box-question', '[ اسأل أولاً ]'),
    '🔍': ('box-diag',     '[ التشخيص ]'),
    '💊': ('box-rec',      '[ التوصية ]'),
    '🚨': ('box-warning',  '[ تحذير — أحوّله فوراً ]'),
    '❌': ('box-dont',     '[ لا تعطي ]'),
    '💡': ('box-tip',      '[ ملاحظة مهمة ]'),
    '📋': ('box-summary',  '[ ملخص ]'),
}

def flush_box(emoji, items):
    if not emoji or not items:
        return ""
    cls, label = BOX_MAP.get(emoji, ('box-tip', ''))
    li = ''.join(f'<li>{inline_md(esc(x))}</li>' for x in items)
    inner = f'<ul>{li}</ul>' if li else ''
    return f'<div class="box {cls} no-break"><div class="box-head">{label}</div>{inner}</div>\n'

# ═══════════════════════════════════════════════════════════════════════
# MARKDOWN → HTML  (fixed parser)
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
    in_sc   = False   # inside scenario card
    sc_head = ""
    sc_buf  = []      # scenario body lines

    def push(el, force_main=False):
        if in_sc and not force_main:
            sc_buf.append(el)
        else:
            out.append(el)

    def do_flush_list():
        nonlocal lst_buf, lst_tag
        if not lst_buf:
            return
        tag = 'ol' if lst_tag == 'ol' else 'ul'
        items = ''.join(f'<li>{inline_md(esc(x))}</li>' for x in lst_buf)
        push(f'<{tag}>{items}</{tag}>\n')
        lst_buf = []; lst_tag = None

    def do_flush_box():
        nonlocal box_em, box_buf
        push(flush_box(box_em, box_buf))
        box_em = None; box_buf = []

    def do_flush_sc():
        nonlocal in_sc, sc_buf, sc_head
        if not in_sc:
            return
        body = '\n'.join(sc_buf)
        out.append(
            f'<div class="scenario-card no-break">'
            f'<div class="sc-head"><div class="sc-title">{sc_head}</div></div>'
            f'<div class="sc-body">{body}</div></div>\n'
        )
        in_sc = False; sc_buf = []; sc_head = ""

    while i < len(lines):
        raw = lines[i]; line = raw.rstrip()

        # ── Code block toggle ──────────────────────────────────────────
        if line.strip().startswith('```'):
            if in_code:
                in_code = False
                code_text = esc('\n'.join(code_buf))
                push(f'<pre class="ltr-block"><code>{code_text}</code></pre>\n')
                code_buf = []
            else:
                do_flush_list(); do_flush_box()
                in_code = True
            i += 1; continue

        if in_code:
            code_buf.append(raw)
            i += 1; continue

        # ── Blank line ─────────────────────────────────────────────────
        if not line.strip():
            do_flush_list()
            i += 1; continue

        # ── H1: SKIP entirely — chapter header from JSON is used ───────
        if line.startswith('# '):
            # Close any open scenario but do NOT render H1
            do_flush_list(); do_flush_box(); do_flush_sc()
            # Only add visual placeholder (for chapter illustration)
            out.append(visual_placeholder("صورة توضيحية للفصل"))
            i += 1; continue

        # ── Topic divider (## 📌 ...) ──────────────────────────────────
        if re.match(r'^##\s*📌', line):
            do_flush_list(); do_flush_box(); do_flush_sc()
            txt = re.sub(r'^##\s*📌\s*', '', line).strip()
            push(f'<div class="topic-divider">'
                 f'<span class="td-label">{inline_md(esc(txt))}</span>'
                 f'<span class="td-line"></span></div>\n', force_main=True)
            i += 1; continue

        # ── H2 ─────────────────────────────────────────────────────────
        if line.startswith('## '):
            do_flush_list(); do_flush_box(); do_flush_sc()
            txt = line[3:].strip()
            push(f'<h2 class="{h2_class}">{inline_md(esc(txt))}</h2>\n', force_main=True)
            i += 1; continue

        # ── Scenario card header (### 🗣️ ...) ─────────────────────────
        if re.match(r'^###\s*🗣', line):
            do_flush_list(); do_flush_box(); do_flush_sc()
            txt = re.sub(r'^###\s*🗣️?\s*', '', line).strip()
            in_sc   = True
            sc_head = inline_md(esc(txt))
            i += 1; continue

        # ── H3 ─────────────────────────────────────────────────────────
        if line.startswith('### '):
            do_flush_list(); do_flush_box()
            do_flush_sc()
            txt = line[4:].strip()
            push(f'<h3>{inline_md(esc(txt))}</h3>\n')
            i += 1; continue

        # ── H4 ─────────────────────────────────────────────────────────
        if line.startswith('#### '):
            do_flush_list(); do_flush_box()
            txt = line[5:].strip()
            push(f'<h4>{inline_md(esc(txt))}</h4>\n')
            i += 1; continue

        # ── Table ──────────────────────────────────────────────────────
        if line.strip().startswith('|'):
            do_flush_list(); do_flush_box()
            tbl_lines = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                tbl_lines.append(lines[i])
                i += 1
            push(make_table(tbl_lines))
            continue

        # ── Horizontal rule ────────────────────────────────────────────
        if re.match(r'^[-*_]{3,}$', line.strip()):
            do_flush_list(); do_flush_box()
            push('<hr/>\n')
            i += 1; continue

        # ── Blockquote ─────────────────────────────────────────────────
        if line.startswith('>'):
            do_flush_list(); do_flush_box()
            txt = line.lstrip('> ').strip()
            push(f'<blockquote>{inline_md(esc(txt))}</blockquote>\n')
            i += 1; continue

        # ── Emoji box header (bold line with known emoji) ──────────────
        m = re.match(r'^\*\*(⚡|🔍|💊|🚨|❌|💡|📋)[^*]*\*\*\s*:?\s*$', line.strip())
        if m:
            do_flush_list()
            if box_em:
                do_flush_box()
            box_em  = m.group(1)
            box_buf = []
            i += 1; continue

        # ── Patient dialogue (**المريض:** "...") ─────────────────────
        pm = re.match(r'^\*\*(المريض[^:]*|المريضة[^:]*|الأم[^:]*)\*\*\s*:\s*[\*\"\'"\u201c\u201d](.+?)[\*\"\'"\u201c\u201d]?\s*$', line.strip())
        if pm:
            do_flush_list(); do_flush_box()
            who   = pm.group(1)
            quote = pm.group(2).strip().strip('*"\'')
            el = (f'<p><strong>{esc(who)}:</strong></p>'
                  f'<div class="patient-quote">&quot;{inline_md(esc(quote))}&quot;</div>\n')
            push(el)
            i += 1; continue

        # ── Bullet / numbered list ─────────────────────────────────────
        bm = re.match(r'^(\s*)[-*]\s+(.+)', line)
        nm = re.match(r'^(\s*)\d+\.\s+(.+)', line)
        if bm or nm:
            txt  = (bm or nm).group(2)
            kind = 'ol' if nm else 'ul'
            if box_em:
                box_buf.append(txt)
            else:
                if lst_tag != kind:
                    do_flush_list()
                    lst_tag = kind
                lst_buf.append(txt)
            i += 1; continue

        # ── Regular paragraph ──────────────────────────────────────────
        do_flush_list()
        if box_em:
            box_buf.append(line.strip())
        else:
            push(f'<p>{inline_md(esc(line.strip()))}</p>\n')
        i += 1

    do_flush_list(); do_flush_box(); do_flush_sc()
    return ''.join(out)

# ═══════════════════════════════════════════════════════════════════════
# PAGE BUILDERS
# ═══════════════════════════════════════════════════════════════════════
def section_page(sec):
    color = sec["accent"]
    return (f'<div class="section-page">'
            f'<div class="sp-label">{esc(sec["label"])}</div>'
            f'<div class="sp-title">{esc(sec["title_ar"])}</div>'
            f'<div class="sp-bar" style="background:{color}"></div>'
            f'</div>\n')

def chapter_header(item, sec):
    color = sec["accent"]
    lbl   = f'{esc(sec["label"])} — الفصل {esc(item["num"])}'
    num   = item["num"]
    return (f'<div class="chapter-header" style="background:{color}">'
            f'<div class="ch-bgnum ltr">{num}</div>'
            f'<div class="ch-inner">'
            f'<div class="ch-label">{lbl}</div>'
            f'<div class="ch-title">{esc(item["title_ar"])}</div>'
            f'</div></div>\n')

def title_page():
    return f"""
<div class="section-page">
  <div style="font-family:'{FONT_NAME}',serif;font-size:{scaled(40)}pt;font-weight:bold;
              color:{C['accent']};letter-spacing:-.01em;margin-bottom:4px;direction:ltr">
    BetterDiagnosis
  </div>
  <div style="font-size:{scaled(26)}pt;font-weight:bold;color:{C['text_primary']};
              margin-bottom:12px;direction:rtl">
    {esc(META['title_ar'])}
  </div>
  <div style="width:50px;height:3px;background:{C['accent']};
              border-radius:2px;margin:0 auto 18px"></div>
  <div style="font-size:{scaled(12)}pt;color:{C['text_secondary']};
              margin-bottom:36px;direction:rtl">
    {esc(META['tagline_ar'])}
  </div>
  <div style="font-size:{scaled(8.5)}pt;color:{C['text_muted']};direction:rtl">
    {esc(META['edition'])} &nbsp;&middot;&nbsp; {esc(META['copyright'])}
  </div>
</div>
"""

# ═══════════════════════════════════════════════════════════════════════
# RESOLVE FILE PATH
# ═══════════════════════════════════════════════════════════════════════
def resolve(filename, sec_id):
    if sec_id == "prereqs":
        return BOOK_ROOT / filename
    return MAIN_DIR / filename

# ═══════════════════════════════════════════════════════════════════════
# BUILD HTML
# ═══════════════════════════════════════════════════════════════════════
def build():
    css   = build_css()
    parts = [f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8"/>
<title>BetterDiagnosis</title>
<style>{css}</style>
</head>
<body>
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
                f'<div class="ch-footer">'
                f'{esc(sec["label"])} — {esc(item["title_ar"])}'
                f' &nbsp;&middot;&nbsp; BetterDiagnosis {esc(META["edition"])}'
                f'</div>\n'
                f'<div class="page-break"></div>\n'
            )

    parts.append("</body></html>")
    return ''.join(parts)

# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("\nBetterDiagnosis Book Builder v2")
    print("─" * 40)
    print(f"Book root : {BOOK_ROOT}")
    print(f"Font      : {FONT_NAME}")
    print(f"Zoom      : {ZOOM}x (corrects 96-DPI → 72-DPI)")
    print(f"Output    : {OUT_PDF}")
    print("─" * 40)

    print("\nBuilding HTML...")
    html = build()
    OUT_HTML.write_text(html, encoding="utf-8")
    size_kb = len(html) // 1024
    print(f"HTML done: {size_kb} KB")

    print("\nConverting to PDF...")
    cmd = [
        "wkhtmltopdf",
        "--enable-local-file-access",
        "--background",
        "--print-media-type",
        "--encoding", "utf-8",
        "--page-size", "A4",
        # ── Zoom fix: corrects 96dpi screen rendering → 72dpi PDF ──
        "--zoom", str(ZOOM),
        "--disable-smart-shrinking",
        "--dpi", "300",
        # ── Margins ──
        "--margin-top",    f"{P['margin_top_mm']}mm",
        "--margin-bottom", f"{P['margin_bottom_mm']}mm",
        "--margin-right",  f"{P['margin_inner_mm']}mm",
        "--margin-left",   f"{P['margin_outer_mm']}mm",
        # ── Footer ──
        "--footer-center", f"BetterDiagnosis — {META['title_ar']}",
        "--footer-right",  "[page]",
        "--footer-font-size", "7",
        "--footer-spacing", "5",
        "--quiet",
        str(OUT_HTML),
        str(OUT_PDF),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        mb = OUT_PDF.stat().st_size / 1_000_000
        print(f"\nDone! PDF: {OUT_PDF}")
        print(f"Size: {mb:.1f} MB")
        print("\nClean up temp HTML? (y/n): ", end="", flush=True)
        try:
            ans = input().strip().lower()
            if ans == 'y':
                OUT_HTML.unlink()
                print("Temp HTML removed.")
        except EOFError:
            OUT_HTML.unlink()
    else:
        print(f"\nwkhtmltopdf error:\n{result.stderr[:800]}")
        sys.exit(1)