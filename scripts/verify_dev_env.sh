#!/bin/bash
# ============================================================================
# Birkin Development Environment Verification Script
# ============================================================================
# Checks whether your development environment meets all requirements
# for Birkin development and testing.
#
# Usage:
#   ./scripts/verify_dev_env.sh [--fix]
#
# Options:
#   --fix    Try to auto-fix issues (requires manual input for some)
# ============================================================================

set +e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ISSUES=0
WARNINGS=0
FIXES_APPLIED=0
FIX_MODE="${1:-}"

echo ""
echo -e "${CYAN}🔍 Birkin Development Environment Verification${NC}"
echo ""

# ============================================================================
# Utility Functions
# ============================================================================

check_version() {
    local cmd=$1
    local min_version=$2
    local installed_version=$($cmd 2>/dev/null)

    if [ -z "$installed_version" ]; then
        return 1
    fi

    # Simple version comparison (assumes X.Y.Z format)
    installed_major=$(echo "$installed_version" | grep -oE '^[0-9]+' | head -1)
    min_major=$(echo "$min_version" | grep -oE '^[0-9]+' | head -1)

    if [ -z "$installed_major" ] || [ -z "$min_major" ]; then
        return 0  # Can't parse, assume it's OK
    fi

    if [ "$installed_major" -ge "$min_major" ]; then
        return 0
    else
        return 1
    fi
}

check_success() {
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓${NC} $1"
    else
        echo -e "${RED}✗${NC} $1"
        ((ISSUES++))
    fi
}

check_warning() {
    if [ $? -ne 0 ]; then
        echo -e "${YELLOW}⚠${NC} $1"
        ((WARNINGS++))
    fi
}

# ============================================================================
# Required Tools
# ============================================================================

echo -e "${CYAN}→${NC} Required Tools"
echo ""

# Python 3.11+
echo -n "  Python 3.11+: "
if command -v python3.11 &> /dev/null; then
    PY_VERSION=$(python3.11 --version 2>&1 | awk '{print $2}')
    echo -e "${GREEN}✓${NC} $PY_VERSION"
    PYTHON_BIN="python3.11"
elif command -v python3 &> /dev/null; then
    PY_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
    PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
    PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)
    if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 11 ]; then
        echo -e "${GREEN}✓${NC} $PY_VERSION"
        PYTHON_BIN="python3"
    else
        echo -e "${RED}✗${NC} $PY_VERSION (required 3.11+)"
        ((ISSUES++))
        PYTHON_BIN="python3"
    fi
else
    echo -e "${RED}✗${NC} Not found (required 3.11+)"
    ((ISSUES++))
    PYTHON_BIN="python3"
fi

# Node.js 18+
echo -n "  Node.js 18+: "
if command -v node &> /dev/null; then
    NODE_VERSION=$(node --version 2>&1 | sed 's/v//')
    NODE_MAJOR=$(echo "$NODE_VERSION" | cut -d. -f1)
    if [ "$NODE_MAJOR" -ge 18 ]; then
        echo -e "${GREEN}✓${NC} v$NODE_VERSION"
    else
        echo -e "${YELLOW}⚠${NC} v$NODE_VERSION (18+ recommended)"
        ((WARNINGS++))
    fi
else
    echo -e "${YELLOW}⚠${NC} Not found (optional, needed for browser tools)"
    ((WARNINGS++))
fi

# Git
echo -n "  Git: "
if command -v git &> /dev/null; then
    GIT_VERSION=$(git --version | awk '{print $3}')
    echo -e "${GREEN}✓${NC} $GIT_VERSION"
else
    echo -e "${RED}✗${NC} Not found"
    ((ISSUES++))
fi

echo ""

# ============================================================================
# Optional Tools
# ============================================================================

echo -e "${CYAN}→${NC} Optional Tools (Recommended)"
echo ""

# uv
echo -n "  uv (Python manager): "
if command -v uv &> /dev/null; then
    UV_VERSION=$(uv --version 2>&1 | awk '{print $2}')
    echo -e "${GREEN}✓${NC} $UV_VERSION"
else
    echo -e "${YELLOW}⚠${NC} Not installed (recommended: https://docs.astral.sh/uv/)"
    ((WARNINGS++))
fi

# direnv
echo -n "  direnv (env auto-loader): "
if command -v direnv &> /dev/null; then
    echo -e "${GREEN}✓${NC} Installed"
else
    echo -e "${YELLOW}⚠${NC} Not installed (optional: https://direnv.net/)"
    ((WARNINGS++))
fi

# Docker
echo -n "  Docker: "
if command -v docker &> /dev/null; then
    DOCKER_VERSION=$(docker --version 2>&1 | awk '{print $3}' | sed 's/,//')
    echo -e "${GREEN}✓${NC} $DOCKER_VERSION"
else
    echo -e "${YELLOW}⚠${NC} Not installed (optional, for containerized testing)"
    ((WARNINGS++))
fi

echo ""

# ============================================================================
# Repository State
# ============================================================================

echo -e "${CYAN}→${NC} Repository State"
echo ""

# Git submodules
echo -n "  Git submodules: "
cd "$REPO_ROOT"
if git submodule status 2>/dev/null | grep -q "^-"; then
    echo -e "${RED}✗${NC} Not initialized"
    ((ISSUES++))
elif git submodule status 2>/dev/null | grep -q "^+"; then
    echo -e "${YELLOW}⚠${NC} Out of sync (run: git submodule update --remote)"
    ((WARNINGS++))
else
    echo -e "${GREEN}✓${NC} Initialized"
fi

# Virtual environment
echo -n "  Virtual environment (venv/): "
if [ -d "$REPO_ROOT/venv" ]; then
    if [ -f "$REPO_ROOT/venv/bin/python" ] || [ -f "$REPO_ROOT/venv/Scripts/python.exe" ]; then
        echo -e "${GREEN}✓${NC} Found"
    else
        echo -e "${YELLOW}⚠${NC} Directory exists but appears broken"
        ((WARNINGS++))
    fi
else
    echo -e "${YELLOW}⚠${NC} Not found (run: $PYTHON_BIN -m venv venv)"
    ((WARNINGS++))
fi

# .env file
echo -n "  .env configuration: "
if [ -f "$REPO_ROOT/.env" ]; then
    if grep -q "ANTHROPIC_API_KEY\|OPENAI_API_KEY\|OPENROUTER_API_KEY" "$REPO_ROOT/.env" 2>/dev/null; then
        echo -e "${GREEN}✓${NC} Found with API keys"
    else
        echo -e "${YELLOW}⚠${NC} Found but no API keys configured"
        ((WARNINGS++))
    fi
else
    echo -e "${YELLOW}⚠${NC} Not found (run: cp .env.example .env)"
    ((WARNINGS++))
fi

echo ""

# ============================================================================
# Dependencies (if venv is active)
# ============================================================================

if [ -f "$REPO_ROOT/venv/bin/activate" ] || [ -f "$REPO_ROOT/venv/Scripts/activate" ]; then
    echo -e "${CYAN}→${NC} Installed Dependencies"
    echo ""

    # Try to activate and check packages
    if [ -f "$REPO_ROOT/venv/bin/activate" ]; then
        source "$REPO_ROOT/venv/bin/activate" 2>/dev/null
        PIP_BIN="pip"
    elif [ -f "$REPO_ROOT/venv/Scripts/activate" ]; then
        source "$REPO_ROOT/venv/Scripts/activate" 2>/dev/null
        PIP_BIN="pip"
    fi

    # Check key packages
    for pkg in pytest ruff anthropic openai; do
        echo -n "  $pkg: "
        if $PIP_BIN show "$pkg" &>/dev/null; then
            VERSION=$($PIP_BIN show "$pkg" 2>/dev/null | grep Version | awk '{print $2}')
            echo -e "${GREEN}✓${NC} $VERSION"
        else
            echo -e "${YELLOW}⚠${NC} Not installed"
            ((WARNINGS++))
        fi
    done

    deactivate 2>/dev/null || true

    echo ""
fi

# ============================================================================
# Tests
# ============================================================================

echo -e "${CYAN}→${NC} Module Import Tests"
echo ""

# Try importing core modules
if [ -f "$REPO_ROOT/venv/bin/python" ]; then
    VENV_PYTHON="$REPO_ROOT/venv/bin/python"
elif [ -f "$REPO_ROOT/venv/Scripts/python.exe" ]; then
    VENV_PYTHON="$REPO_ROOT/venv/Scripts/python.exe"
else
    VENV_PYTHON="$PYTHON_BIN"
fi

echo -n "  agent module: "
$VENV_PYTHON -c "from agent import *" 2>/dev/null && echo -e "${GREEN}✓${NC} Imports OK" || echo -e "${YELLOW}⚠${NC} Import failed (venv not activated?)"

echo -n "  run_agent module: "
cd "$REPO_ROOT"
$VENV_PYTHON -c "import run_agent" 2>/dev/null && echo -e "${GREEN}✓${NC} Imports OK" || echo -e "${YELLOW}⚠${NC} Import failed (dependencies not installed?)"

echo ""

# ============================================================================
# Summary
# ============================================================================

echo -e "${CYAN}═════════════════════════════════════════════════════${NC}"
echo ""

if [ $ISSUES -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo -e "${GREEN}✓ All checks passed! Development environment is ready.${NC}"
    echo ""
    echo "Next steps:"
    echo "  • Activate venv: source venv/bin/activate"
    echo "  • Run agent: birkin-agent -q 'Hello'"
    echo "  • Run tests: pytest"
    echo ""
    exit 0
elif [ $ISSUES -eq 0 ]; then
    echo -e "${YELLOW}⚠ Environment OK but $WARNINGS warnings found.${NC}"
    echo ""
    echo "Your setup works, but consider installing recommended tools:"
    echo "  • uv: https://docs.astral.sh/uv/"
    echo "  • direnv: https://direnv.net/"
    echo ""
    exit 0
else
    echo -e "${RED}✗ Environment setup incomplete ($ISSUES critical issues)${NC}"
    echo ""
    echo "Required fixes:"
    echo "  1. Install Python 3.11+: https://www.python.org/downloads/"
    echo "  2. Create venv: $PYTHON_BIN -m venv venv"
    echo "  3. Activate venv: source venv/bin/activate"
    echo "  4. Install deps: pip install -e '.[dev]'"
    echo "  5. Setup .env: cp .env.example .env && edit .env"
    echo ""
    echo "See DEV_SETUP.md for detailed instructions."
    echo ""
    exit 1
fi
