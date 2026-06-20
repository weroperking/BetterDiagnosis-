
#!/bin/bash
# ─────────────────────────────────────────────────────────────────
# BetterDiagnosis — Environment Setup Script
# Supports: macOS (Homebrew) | Ubuntu 20.04+ | Debian
# Run: bash install_env.sh
# ─────────────────────────────────────────────────────────────────

set -e
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
ok()   { echo -e "${GREEN}  ✓ $1${NC}"; }
warn() { echo -e "${YELLOW}  ⚠ $1${NC}"; }
info() { echo -e "${BLUE}  → $1${NC}"; }
fail() { echo -e "${RED}  ✗ $1${NC}"; exit 1; }

echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}   BetterDiagnosis — Book Builder Environment Setup${NC}"
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

# ── wkhtmltopdf ───────────────────────────────────────────────────────────
info "Checking wkhtmltopdf..."
if command -v wkhtmltopdf &>/dev/null; then
    WKVER=$(wkhtmltopdf --version 2>&1 | head -1)
    ok "wkhtmltopdf already installed: $WKVER"
else
    info "Installing wkhtmltopdf..."
    if [ "$OS" = "macos" ]; then
        if command -v brew &>/dev/null; then
            brew install --cask wkhtmltopdf
        else
            fail "Homebrew not found. Install from https://brew.sh then re-run.\nOr manually: https://wkhtmltopdf.org/downloads.html"
        fi
    elif [ "$OS" = "debian" ]; then
        sudo apt-get update -qq
        sudo apt-get install -y wkhtmltopdf
        # On Ubuntu, wkhtmltopdf from apt may lack patched Qt (needed for headers/footers)
        # Check if it works with --footer-right
        if ! wkhtmltopdf --footer-right "[page]" --quiet - /dev/null < /dev/null 2>/dev/null; then
            warn "System wkhtmltopdf may not support headers/footers."
            warn "For full support, download patched version from:"
            warn "https://wkhtmltopdf.org/downloads.html"
        fi
    elif [ "$OS" = "redhat" ]; then
        sudo yum install -y wkhtmltopdf 2>/dev/null || \
        sudo dnf install -y wkhtmltopdf 2>/dev/null || \
        fail "Could not install wkhtmltopdf. Download from: https://wkhtmltopdf.org/downloads.html"
    fi
    ok "wkhtmltopdf installed"
fi

# ── Python packages ───────────────────────────────────────────────────────
info "Installing Python packages..."
pip3 install --quiet arabic-reshaper python-bidi pypdf 2>/dev/null || \
pip3 install --quiet arabic-reshaper python-bidi pypdf --break-system-packages 2>/dev/null || \
pip install  --quiet arabic-reshaper python-bidi pypdf 2>/dev/null || true

# Verify
python3 -c "import arabic_reshaper; print('arabic_reshaper ok')" 2>/dev/null && ok "arabic-reshaper" || warn "arabic-reshaper not installed — Arabic shaping may be basic"
python3 -c "from bidi.algorithm import get_display; print('bidi ok')" 2>/dev/null && ok "python-bidi" || warn "python-bidi not installed"
python3 -c "import pypdf; print('pypdf ok')" 2>/dev/null && ok "pypdf" || true

# ── Fonts ─────────────────────────────────────────────────────────────────
FONT_DIR="$(dirname "$0")/fonts"
mkdir -p "$FONT_DIR"

info "Downloading Amiri Arabic fonts..."
AMIRI_REG="$FONT_DIR/Amiri-Regular.ttf"
AMIRI_BOLD="$FONT_DIR/Amiri-Bold.ttf"

if [ -f "$AMIRI_REG" ] && [ -f "$AMIRI_BOLD" ]; then
    ok "Amiri fonts already present"
else
    # Try downloading from GitHub
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

# ── Install system Arabic fonts (Linux fallback) ──────────────────────────
if [ "$OS" = "debian" ]; then
    info "Installing system Arabic font support..."
    sudo apt-get install -y fonts-freefont-ttf fonts-arabeyes fonts-farsiweb 2>/dev/null || true
    ok "System Arabic fonts installed"
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