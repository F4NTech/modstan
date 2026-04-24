#!/usr/bin/env bash
# =============================================================================
# MODSTAN - Upgrade Script
# Stops active services, pulls latest code, upgrades packages, restarts services
# =============================================================================
set -e

MODSTAN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$MODSTAN_DIR/venv"

GREEN='\033[92m'; YELLOW='\033[93m'; RED='\033[91m'; BOLD='\033[1m'; RESET='\033[0m'
ok()   { echo -e "  ${GREEN}[✓]${RESET} $1"; }
warn() { echo -e "  ${YELLOW}[!]${RESET} $1"; }
fail() { echo -e "  ${RED}[✗]${RESET} $1"; exit 1; }
info() { echo -e "  [i] $1"; }

echo -e "\n${BOLD}======================================================${RESET}"
echo -e "${BOLD}  MODSTAN — Upgrade${RESET}"
echo -e "${BOLD}======================================================${RESET}\n"

# -----------------------------------------------------------------------------
# 1. Stop any active modstan services
# -----------------------------------------------------------------------------
info "Looking for active modstan services..."
ACTIVE_SERVICES=$(systemctl list-units --type=service --state=active \
    | grep 'modstan@' | awk '{print $1}' || true)

if [ -n "$ACTIVE_SERVICES" ]; then
    warn "Active services found — stopping temporarily:"
    for svc in $ACTIVE_SERVICES; do
        sudo systemctl stop "$svc"
        warn "  Stopped: $svc"
    done
else
    info "No active modstan services found."
fi

# -----------------------------------------------------------------------------
# 2. Pull latest code from Git (if inside a Git repository)
# -----------------------------------------------------------------------------
if [ -d "$MODSTAN_DIR/.git" ]; then
    info "Pulling latest code from Git..."
    cd "$MODSTAN_DIR"
    git fetch origin
    LOCAL=$(git rev-parse HEAD)
    REMOTE=$(git rev-parse @{u})
    if [ "$LOCAL" = "$REMOTE" ]; then
        ok "Already up to date."
    else
        git pull origin main
        ok "Code updated from Git."
    fi
else
    warn "Not a Git repository — skipping code pull."
fi

# -----------------------------------------------------------------------------
# 3. Upgrade Python dependencies
# -----------------------------------------------------------------------------
info "Upgrading Python dependencies..."
source "$VENV_DIR/bin/activate"
pip install --upgrade pip --quiet
pip install --upgrade -r "$MODSTAN_DIR/requirements.txt" --quiet
ok "Dependencies upgraded."

# -----------------------------------------------------------------------------
# 4. Reload systemd and restart previously active services
# -----------------------------------------------------------------------------
info "Reloading systemd daemon..."
sudo systemctl daemon-reload
ok "systemd daemon reloaded."

if [ -n "$ACTIVE_SERVICES" ]; then
    info "Restarting services..."
    for svc in $ACTIVE_SERVICES; do
        sudo systemctl start "$svc"
        ok "  Started: $svc"
    done
fi

echo -e "\n${GREEN}${BOLD}Upgrade complete!${RESET}\n"
echo -e "  Check status with: ${BOLD}modstan status${RESET}\n"
