#!/usr/bin/env bash
# =============================================================================
# MODSTAN - Install Script
# Idempotent: safe to run multiple times without side effects
# =============================================================================
set -e

MODSTAN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$MODSTAN_DIR/venv"
SERVICE_TEMPLATE="/etc/systemd/system/modstan@.service"
CLI_LINK="/usr/local/bin/modstan"
PROFILE_FILE="/etc/profile.d/modstan.sh"
MIN_PYTHON_MAJOR=3
MIN_PYTHON_MINOR=10

GREEN='\033[92m'; YELLOW='\033[93m'; RED='\033[91m'; BOLD='\033[1m'; RESET='\033[0m'
ok()   { echo -e "  ${GREEN}[✓]${RESET} $1"; }
warn() { echo -e "  ${YELLOW}[!]${RESET} $1"; }
fail() { echo -e "  ${RED}[✗]${RESET} $1"; exit 1; }
info() { echo -e "  [i] $1"; }
skip() { echo -e "  ${YELLOW}[→]${RESET} $1 (skipped — already exists)"; }

echo -e "\n${BOLD}======================================================${RESET}"
echo -e "${BOLD}  MODSTAN — Installation${RESET}"
echo -e "${BOLD}  Root: $MODSTAN_DIR${RESET}"
echo -e "${BOLD}======================================================${RESET}\n"

# -----------------------------------------------------------------------------
# 1. Check Python version
# -----------------------------------------------------------------------------
info "Checking Python..."
PYTHON_BIN=""
for cmd in python3.12 python3.11 python3.10 python3; do
    if command -v "$cmd" &>/dev/null; then
        MAJOR=$($cmd -c "import sys; print(sys.version_info.major)")
        MINOR=$($cmd -c "import sys; print(sys.version_info.minor)")
        if [ "$MAJOR" -ge "$MIN_PYTHON_MAJOR" ] && [ "$MINOR" -ge "$MIN_PYTHON_MINOR" ]; then
            PYTHON_BIN="$cmd"
            break
        fi
    fi
done
[ -z "$PYTHON_BIN" ] && fail "Python $MIN_PYTHON_MAJOR.$MIN_PYTHON_MINOR+ not found. Install with: sudo apt install python3.11"
ok "Python $($PYTHON_BIN --version)"

# -----------------------------------------------------------------------------
# 2. Virtual environment (idempotent: skip if already present)
# -----------------------------------------------------------------------------
info "Setting up virtual environment..."
if [ -d "$VENV_DIR" ] && [ -f "$VENV_DIR/bin/activate" ]; then
    skip "venv already exists at $VENV_DIR"
else
    $PYTHON_BIN -m venv "$VENV_DIR"
    ok "venv created at $VENV_DIR"
fi
source "$VENV_DIR/bin/activate"
ok "venv activated ($(python --version))"

# -----------------------------------------------------------------------------
# 3. Install / update dependencies
# -----------------------------------------------------------------------------
info "Installing dependencies..."
pip install --upgrade pip --quiet
pip install -r "$MODSTAN_DIR/requirements.txt" --quiet
ok "Dependencies installed."

# -----------------------------------------------------------------------------
# 4. Required directories
# -----------------------------------------------------------------------------
info "Ensuring required directories exist..."
mkdir -p "$MODSTAN_DIR/logs" "$MODSTAN_DIR/exports"
ok "logs/ and exports/ are ready."

# -----------------------------------------------------------------------------
# 5. MODSTAN_ROOT environment variable (used by CLI to locate the project)
# -----------------------------------------------------------------------------
info "Setting up MODSTAN_ROOT environment variable..."
if [ -f "$PROFILE_FILE" ] && grep -q "MODSTAN_ROOT" "$PROFILE_FILE"; then
    skip "MODSTAN_ROOT already set in $PROFILE_FILE"
else
    sudo tee "$PROFILE_FILE" > /dev/null <<EOF
# MODSTAN environment variable
export MODSTAN_ROOT="$MODSTAN_DIR"
EOF
    ok "MODSTAN_ROOT written to $PROFILE_FILE"
fi

# -----------------------------------------------------------------------------
# 6. systemd service template (idempotent: only update if content changed)
# -----------------------------------------------------------------------------
info "Installing systemd service template..."
WHOAMI=$(whoami)
NEW_SERVICE="$(cat <<EOF
[Unit]
Description=MODSTAN Modbus TCP Logger — %i
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=$WHOAMI
WorkingDirectory=$MODSTAN_DIR
Environment=MODSTAN_ROOT=$MODSTAN_DIR
ExecStart=$VENV_DIR/bin/python $MODSTAN_DIR/main.py --config $MODSTAN_DIR/config/%i.conf
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=modstan@%i

[Install]
WantedBy=multi-user.target
EOF
)"

EXISTING_SERVICE=""
[ -f "$SERVICE_TEMPLATE" ] && EXISTING_SERVICE=$(cat "$SERVICE_TEMPLATE")

if [ "$NEW_SERVICE" = "$EXISTING_SERVICE" ]; then
    skip "systemd service template unchanged"
else
    echo "$NEW_SERVICE" | sudo tee "$SERVICE_TEMPLATE" > /dev/null
    sudo systemctl daemon-reload
    ok "systemd service template installed: $SERVICE_TEMPLATE"
fi

# -----------------------------------------------------------------------------
# 7. CLI command (idempotent: only update if content changed)
# -----------------------------------------------------------------------------
info "Installing 'modstan' CLI command..."
NEW_CLI="#!/usr/bin/env bash
export MODSTAN_ROOT=\"$MODSTAN_DIR\"
source \"$VENV_DIR/bin/activate\"
python \"$MODSTAN_DIR/cli/commands.py\" \"\$@\""

EXISTING_CLI=""
[ -f "$CLI_LINK" ] && EXISTING_CLI=$(cat "$CLI_LINK")

if [ "$NEW_CLI" = "$EXISTING_CLI" ]; then
    skip "CLI command unchanged"
else
    echo "$NEW_CLI" | sudo tee "$CLI_LINK" > /dev/null
    sudo chmod +x "$CLI_LINK"
    ok "CLI command installed: $CLI_LINK"
fi

# -----------------------------------------------------------------------------
# 8. Config file reminder
# -----------------------------------------------------------------------------
CONF_COUNT=$(ls "$MODSTAN_DIR/config/"*.conf 2>/dev/null | grep -v example.conf | wc -l)
if [ "$CONF_COUNT" -eq 0 ]; then
    echo
    warn "No device config files found. Create one before starting any service:"
    echo -e "     ${BOLD}cp $MODSTAN_DIR/config/example.conf $MODSTAN_DIR/config/METER01.conf${RESET}"
    echo -e "     ${BOLD}nano $MODSTAN_DIR/config/METER01.conf${RESET}"
    echo -e "     ${BOLD}chmod 600 $MODSTAN_DIR/config/METER01.conf${RESET}"
fi

# -----------------------------------------------------------------------------
# Done
# -----------------------------------------------------------------------------
echo -e "\n${GREEN}${BOLD}Installation complete!${RESET}\n"
echo -e "  Next steps:"
echo -e "  1. Create and configure a device file (if not done yet):"
echo -e "     ${BOLD}cp config/example.conf config/METER01.conf${RESET}"
echo -e "     ${BOLD}nano config/METER01.conf${RESET}"
echo -e "     ${BOLD}chmod 600 config/METER01.conf${RESET}"
echo
echo -e "  2. Test the connection without writing to the database:"
echo -e "     ${BOLD}modstan test METER01${RESET}"
echo
echo -e "  3. Enable and start as a background service:"
echo -e "     ${BOLD}sudo systemctl enable --now modstan@METER01${RESET}"
echo
echo -e "  4. Check status:"
echo -e "     ${BOLD}modstan status${RESET}"
echo -e "     ${BOLD}modstan check${RESET}"
echo
echo -e "  Note: Run 'source /etc/profile.d/modstan.sh' or log out and back in"
echo -e "        to activate the MODSTAN_ROOT variable in your current session."
echo
