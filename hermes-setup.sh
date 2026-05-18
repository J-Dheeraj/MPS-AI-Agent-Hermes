#!/usr/bin/env bash
# hermes-setup.sh — MPS AI Agent setup on Hermes
# =================================================
# Run this script inside WSL2 Ubuntu after cloning the repo.
# It installs Hermes Agent, creates the three MPS profiles, copies
# all SOUL.md and SKILL files into place, wires the CRM bridge,
# and starts all three gateways as background daemons.
#
# Usage:
#   cd ~/mps-hermes
#   bash hermes-setup.sh
#
# Prerequisites:
#   - WSL2 Ubuntu 22.04 running
#   - Internet connection
#   - Anthropic API key ready (sk-ant-...)
#   - Three Telegram bot tokens from @BotFather

set -e

# Colours for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC} $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo "=================================================="
echo "  MPS AI Agent — Hermes Setup"
echo "=================================================="
echo ""

# ---------------------------------------------------------------------------
# Phase 0 — System check
# ---------------------------------------------------------------------------

info "Checking WSL2 and system requirements..."

if ! command -v python3 &>/dev/null; then
    info "Installing Python 3..."
    sudo apt-get update -qq && sudo apt-get install -y python3 python3-pip
fi
success "Python3 found: $(python3 --version)"

if ! command -v pip3 &>/dev/null; then
    sudo apt-get install -y python3-pip
fi

# ---------------------------------------------------------------------------
# Phase 1 — Install Hermes Agent
# ---------------------------------------------------------------------------

if command -v hermes &>/dev/null; then
    success "Hermes already installed: $(hermes --version)"
else
    info "Installing Hermes Agent..."
    curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash
    # Re-source shell to get hermes in PATH
    export PATH="$HOME/.hermes/bin:$PATH"
    if ! command -v hermes &>/dev/null; then
        error "Hermes installation failed. Check https://hermes-agent.nousresearch.com/docs"
    fi
    success "Hermes installed: $(hermes --version)"
fi

# ---------------------------------------------------------------------------
# Phase 2 — Configure model (prompt for API key)
# ---------------------------------------------------------------------------

info "Configuring Hermes with Anthropic API..."
echo ""
echo "You need your Anthropic API key (starts with sk-ant-)."
echo "Get one at: https://console.anthropic.com/settings/api-keys"
echo ""
read -p "Enter your Anthropic API key: " ANTHROPIC_KEY
if [[ ! "$ANTHROPIC_KEY" == sk-ant-* ]]; then
    warn "Key does not start with sk-ant- — double-check before proceeding."
fi

hermes setup --provider anthropic --api-key "$ANTHROPIC_KEY" --model claude-sonnet-4-5 --non-interactive 2>/dev/null || \
    hermes setup --provider anthropic --api-key "$ANTHROPIC_KEY" --model claude-sonnet-4-5
success "Model configured."

# ---------------------------------------------------------------------------
# Phase 3 — Create three MPS profiles
# ---------------------------------------------------------------------------

info "Creating MPS profiles..."

for profile in mps-main mps-volunteers mps-vetters; do
    if hermes profile list 2>/dev/null | grep -q "$profile"; then
        warn "Profile $profile already exists — skipping creation."
    else
        hermes profile create "$profile"
        success "Created profile: $profile"
    fi
done

# ---------------------------------------------------------------------------
# Phase 4 — Copy SOUL.md files
# ---------------------------------------------------------------------------

info "Copying SOUL.md identity files to profiles..."

cp "$REPO_DIR/profiles/mps-main/SOUL.md"       "$HOME/.hermes/profiles/mps-main/SOUL.md"
cp "$REPO_DIR/profiles/mps-volunteers/SOUL.md" "$HOME/.hermes/profiles/mps-volunteers/SOUL.md"
cp "$REPO_DIR/profiles/mps-vetters/SOUL.md"    "$HOME/.hermes/profiles/mps-vetters/SOUL.md"
success "SOUL.md files copied."

# ---------------------------------------------------------------------------
# Phase 5 — Copy config.yaml templates
# ---------------------------------------------------------------------------

info "Copying config.yaml templates..."

for profile in mps-main mps-volunteers mps-vetters; do
    dest="$HOME/.hermes/profiles/$profile/config.yaml"
    if [ -f "$dest" ]; then
        warn "config.yaml already exists for $profile — backing up to config.yaml.bak"
        cp "$dest" "${dest}.bak"
    fi
    cp "$REPO_DIR/profiles/$profile/config.yaml" "$dest"
done
success "Config templates copied."
echo ""
warn "IMPORTANT: Edit each config.yaml to add your Telegram bot tokens and user IDs."
warn "  ~/.hermes/profiles/mps-main/config.yaml       (MP bot)"
warn "  ~/.hermes/profiles/mps-volunteers/config.yaml  (volunteer bot)"
warn "  ~/.hermes/profiles/mps-vetters/config.yaml     (vetter bot)"
echo ""

# ---------------------------------------------------------------------------
# Phase 5 — Install MPS policy skills
# ---------------------------------------------------------------------------

info "Creating skills directories and copying SKILL files..."

for profile in mps-main mps-volunteers mps-vetters; do
    mkdir -p "$HOME/.hermes/profiles/$profile/skills/mps-policy"
    cp "$REPO_DIR/skills/"*.md "$HOME/.hermes/profiles/$profile/skills/mps-policy/"
done
success "SKILL files installed in all three profiles."

# Verify
for profile in mps-main mps-volunteers mps-vetters; do
    count=$(ls "$HOME/.hermes/profiles/$profile/skills/mps-policy/" 2>/dev/null | wc -l)
    info "  $profile: $count skill files"
done

# ---------------------------------------------------------------------------
# Phase 6 — Set up working folder and CRM bridge
# ---------------------------------------------------------------------------

info "Setting up CRM bridge..."

HERMES_DIR="$HOME/mps-hermes"
mkdir -p "$HERMES_DIR/crm-data"

cp "$REPO_DIR/mcp-crm-server.py" "$HERMES_DIR/mcp-crm-server.py"
cp "$REPO_DIR/requirements-crm.txt" "$HERMES_DIR/requirements-crm.txt"

if [ -f "$REPO_DIR/.env.example" ] && [ ! -f "$HERMES_DIR/.env" ]; then
    cp "$REPO_DIR/.env.example" "$HERMES_DIR/.env"
    info "Created $HERMES_DIR/.env from template. Edit if using a non-SQLite backend."
fi

info "Installing CRM Python dependencies..."
pip3 install fastmcp python-dotenv --quiet --break-system-packages 2>/dev/null || \
    pip3 install fastmcp python-dotenv --quiet
success "Core CRM dependencies installed."

# Optional deps (for non-SQLite backends)
pip3 install requests gspread oauth2client Office365-REST-Python-Client \
    --quiet --break-system-packages 2>/dev/null || \
    pip3 install requests gspread oauth2client Office365-REST-Python-Client --quiet
success "CRM bridge ready at $HERMES_DIR/mcp-crm-server.py"

# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

echo ""
echo "=================================================="
echo "  Setup complete — verification"
echo "=================================================="
echo ""

info "Checking profiles..."
hermes profile list

echo ""
info "Checking skills for mps-main..."
hermes --profile mps-main skills list 2>/dev/null || warn "Skills check skipped (run manually: hermes --profile mps-main skills list)"

echo ""
echo "=================================================="
echo "  Next steps"
echo "=================================================="
echo ""
echo "1. Edit the three config.yaml files to add your Telegram bot tokens and"
echo "   allowed user IDs. See Hermes-MPS-Setup-Guide.md for details."
echo ""
echo "2. Start the gateways (after editing config files):"
echo "   hermes --profile mps-main gateway start --daemon"
echo "   hermes --profile mps-volunteers gateway start --daemon"
echo "   hermes --profile mps-vetters gateway start --daemon"
echo ""
echo "3. Send a test message to each Telegram bot:"
echo "   MP bot:        'hello, brief me on tonight'"
echo "   Volunteer bot: 'constituent 70F widow HDB rental, husband passed away, draft letter'"
echo "   Vetter bot:    'what are the CHAS Blue card income thresholds?'"
echo ""
echo "4. Run the verification checklist in Hermes-MPS-Setup-Guide.md"
echo ""
echo "Repo: https://github.com/J-Dheeraj/MPS-AI-Agent-Hermes"
echo "Docs: https://hermes-agent.nousresearch.com/docs"
echo ""
