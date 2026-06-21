#!/bin/bash
# ─────────────────────────────────────────────────────────────────
# BetterDiagnosis — Environment Setup Script  (v2 — WeasyPrint engine)
# Supports: macOS (Homebrew) | Ubuntu 20.04+ | Debian
# Run: bash install_env.sh
#
# ENGINE CHANGE: this script now installs WeasyPrint instead of
# wkhtmltopdf. wkhtmltopdf is unmaintained since 2020 and has confirmed
# Arabic/Latin bidi (mixed-direction text) rendering bugs that cannot
# be fixed from the HTML/CSS side — see build_book_local.py's top
# docstring for the full debugging trail. WeasyPrint uses Pango +
# HarfBuzz (the same text-shaping stack as GTK/LibreOffice) and has
# correct, modern Unicode BiDi support out of the box.
# ─────────────────────────────────────────────────────────────────

set -e
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
ok()   { echo -e "${GREEN}  ✓ $1${NC}"; }
warn() { echo -e "${YELLOW}  ⚠ $1${NC}"; }
info() { echo -e "${BLUE}  → $1${NC}"; }
fail() { echo -e "${RED}  ✗ $1${NC}"; exit 1; }

echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}   BetterDiagnosis — Book Builder Environment Setup (v2)${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# ── Detect OS ──────────────────────────────────────────────────────────────
OS="unknown"
if [[ "$OSTYPE" == "darwin"* ]]; then
    OS="macos"
    info "Detected: macOS"
elif [ -f /etc/debian_version ]; then
    OS="debian"
    info "Detected: Debian/Ubuntu"
elif [ -f /etc/redhat-release ]; then
    OS="redhat"
    info "Detected: RedHat/CentOS/Fedora"
else
    warn "Unknown OS — will try Ubuntu-style commands"
    OS="debian"
fi

# ── Python check ──────────────────────────────────────────────────────────
info "Checking Python 3..."
if ! command -v python3 &>/dev/null; then
    fail "Python 3 not found. Install it from https://python.org"
fi
PYVER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
ok "Python $PYVER found"

# ── System libraries WeasyPrint needs (Pango, Cairo, GDK-Pixbuf, HarfBuzz) ──
# These are the text-shaping/rendering libraries WeasyPrint links against.
# On macOS, Homebrew's "pango" formula pulls in cairo+harfbuzz as deps.
# On Linux, the listed packages cover Debian/Ubuntu naming; RedHat/Fedora
# package names are similar but prefixed differently (handled below).
info "Installing system libraries for WeasyPrint (Pango/Cairo/HarfBuzz)..."
if [ "$OS" = "macos" ]; then
    if command -v brew &>/dev/null; then
        brew install pango cairo gdk-pixbuf libffi
        ok "macOS font/rendering libraries installed via Homebrew"
    else
        fail "Homebrew not found. Install from https://brew.sh then re-run."
    fi
elif [ "$OS" = "debian" ]; then
    sudo apt-get update -qq
    sudo apt-get install -y \
        libpango-1.0-0 libpangocairo-1.0-0 libpangoft2-1.0-0 \
        libcairo2 libgdk-pixbuf2.0-0 libffi-dev \
        fonts-freefont-ttf fonts-arabeyes fonts-farsiweb
    ok "Debian/Ubuntu rendering libraries + fallback fonts installed"
elif [ "$OS" = "redhat" ]; then
    sudo yum install -y pango cairo gdk-pixbuf2 libffi-devel 2>/dev/null || \
    sudo dnf install -y pango cairo gdk-pixbuf2 libffi-devel 2>/dev/null || \
    warn "Could not auto-install system libs. WeasyPrint may still work if these are already present."
fi

# ── Remove old wkhtmltopdf note (informational only — harmless if present) ──
if command -v wkhtmltopdf &>/dev/null; then
    info "Note: wkhtmltopdf is still installed but no longer used by the build script."
    info "      Safe to leave it, or uninstall it if you want to reclaim disk space."
fi

# ── Python packages ───────────────────────────────────────────────────────
info "Installing Python packages (weasyprint, arabic-reshaper, python-bidi, pypdf)..."
PIP_PKGS="weasyprint arabic-reshaper python-bidi pypdf"

pip3 install --quiet $PIP_PKGS 2>/dev/null || \
pip3 install --quiet $PIP_PKGS --break-system-packages 2>/dev/null || \
pip  install --quiet $PIP_PKGS 2>/dev/null || \
fail "pip install failed. Try manually: pip install $PIP_PKGS"

# Verify
python3 -c "import weasyprint; print('weasyprint', weasyprint.__version__)" 2>/dev/null && ok "weasyprint installed" || fail "weasyprint import failed — check system libraries above"
python3 -c "import arabic_reshaper" 2>/dev/null && ok "arabic-reshaper" || warn "arabic-reshaper not installed (optional safety net, not required by current parser)"
python3 -c "from bidi.algorithm import get_display" 2>/dev/null && ok "python-bidi" || warn "python-bidi not installed (optional safety net, not required by current parser)"
python3 -c "import pypdf" 2>/dev/null && ok "pypdf" || true

# ── Fonts ─────────────────────────────────────────────────────────────────
FONT_DIR="$(dirname "$0")/fonts"
mkdir -p "$FONT_DIR"

info "Downloading Amiri Arabic fonts..."
AMIRI_REG="$FONT_DIR/Amiri-Regular.ttf"
AMIRI_BOLD="$FONT_DIR/Amiri-Bold.ttf"

if [ -f "$AMIRI_REG" ] && [ -f "$AMIRI_BOLD" ]; then
    ok "Amiri fonts already present"
else
    BASE_URL="https://github.com/aliftype/amiri/releases/download/1.000"
    if curl -fsSL "$BASE_URL/Amiri-1.000.zip" -o /tmp/amiri_fonts.zip 2>/dev/null; then
        cd /tmp && unzip -q amiri_fonts.zip
        cp /tmp/Amiri-1.000/Amiri-Regular.ttf "$AMIRI_REG" 2>/dev/null || true
        cp /tmp/Amiri-1.000/Amiri-Bold.ttf    "$AMIRI_BOLD" 2>/dev/null || true
        cd - > /dev/null
        ok "Amiri fonts downloaded → $FONT_DIR"
    else
        warn "Could not download Amiri fonts (no internet?)."
        warn "Manually download from: https://github.com/aliftype/amiri/releases"
        warn "Place Amiri-Regular.ttf + Amiri-Bold.ttf in: $FONT_DIR"
        warn "Script will fall back to system fonts if not found."
    fi
fi

# ── Summary ───────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}   Setup complete! Now run:${NC}"
echo ""
echo -e "   ${YELLOW}python3 build_book_local.py${NC}"
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
