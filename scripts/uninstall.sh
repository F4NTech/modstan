#!/usr/bin/env bash
# =============================================================================
# MODSTAN - Uninstall Script
# Removes all installed components cleanly
# =============================================================================

MODSTAN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_TEMPLATE="/etc/systemd/system/modstan@.service"
CLI_LINK="/usr/local/bin/modstan"
PROFILE_FILE="/etc/profile.d/modstan.sh"

GREEN='\033[92m'; YELLOW='\033[93m'; RED='\033[91m'; BOLD='\033[1m'; RESET='\033[0m'
ok()   { echo -e "  ${GREEN}[✓]${RESET} $1"; }
warn() { echo -e "  ${YELLOW}[!]${RESET} $1"; }
fail() { echo -e "  ${RED}[✗]${RESET} $1"; }
info() { echo -e "  [i] $1"; }

echo -e "\n${BOLD}======================================================${RESET}"
echo -e "${BOLD}  MODSTAN — Uninstall${RESET}"
echo -e "${BOLD}======================================================${RESET}\n"

warn "This will remove MODSTAN from the system."
echo -ne "  Continue? (y/N): "
read -r CONFIRM
if [[ "$CONFIRM" != "y" && "$CONFIRM" != "Y" ]]; then
    echo -e "\n  Cancelled.\n"
    exit 0
fi

echo -e "\n  Also remove log and export data?"
echo -ne "  Delete logs/ and exports/? (y/N): "
read -r DEL_DATA
echo

# -----------------------------------------------------------------------------
# 1. Stop and disable all modstan services
# -----------------------------------------------------------------------------
info "Stopping all modstan services..."
SERVICES=$(systemctl list-units --type=service --all \
    | grep 'modstan@' | awk '{print $1}' || true)

if [ -n "$SERVICES" ]; then
    for svc in $SERVICES; do
        sudo systemctl stop    "$svc" 2>/dev/null || true
        sudo systemctl disable "$svc" 2>/dev/null || true
        ok "Stopped and disabled: $svc"
    done
else
    info "No modstan services found."
fi

# -----------------------------------------------------------------------------
# 2. Remove systemd service template
# -----------------------------------------------------------------------------
if [ -f "$SERVICE_TEMPLATE" ]; then
    sudo rm -f "$SERVICE_TEMPLATE"
    sudo systemctl daemon-reload
    ok "Service template removed: $SERVICE_TEMPLATE"
else
    info "Service template not found — skipped."
fi

# -----------------------------------------------------------------------------
# 3. Remove CLI command
# -----------------------------------------------------------------------------
if [ -f "$CLI_LINK" ]; then
    sudo rm -f "$CLI_LINK"
    ok "CLI command removed: $CLI_LINK"
else
    info "CLI command not found — skipped."
fi

# -----------------------------------------------------------------------------
# 4. Remove environment variable profile
# -----------------------------------------------------------------------------
if [ -f "$PROFILE_FILE" ]; then
    sudo rm -f "$PROFILE_FILE"
    ok "Environment profile removed: $PROFILE_FILE"
else
    info "Environment profile not found — skipped."
fi

# -----------------------------------------------------------------------------
# 5. Remove virtual environment
# -----------------------------------------------------------------------------
if [ -d "$MODSTAN_DIR/venv" ]; then
    rm -rf "$MODSTAN_DIR/venv"
    ok "Virtual environment removed."
else
    info "Virtual environment not found — skipped."
fi

# -----------------------------------------------------------------------------
# 6. Optionally remove data directories
# -----------------------------------------------------------------------------
if [[ "$DEL_DATA" == "y" || "$DEL_DATA" == "Y" ]]; then
    rm -rf "$MODSTAN_DIR/logs"
    rm -rf "$MODSTAN_DIR/exports"
    ok "logs/ and exports/ removed."
else
    warn "logs/ and exports/ were kept."
fi

# -----------------------------------------------------------------------------
# Done
# -----------------------------------------------------------------------------
echo -e "\n${GREEN}${BOLD}Uninstall complete!${RESET}"
echo -e "\n  The project folder still exists at: ${BOLD}$MODSTAN_DIR${RESET}"
echo -e "  To remove it entirely, run:"
echo -e "  ${BOLD}rm -rf $MODSTAN_DIR${RESET}\n"
