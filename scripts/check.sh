#!/usr/bin/env bash
# =============================================================================
# MODSTAN - System Health Check
# Verifies Python, packages, config files, database connections, and services
# =============================================================================

MODSTAN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$MODSTAN_DIR/venv"
CONFIG_DIR="$MODSTAN_DIR/config"
LOG_DIR="$MODSTAN_DIR/logs"
EXPORTS_DIR="$MODSTAN_DIR/exports"

GREEN='\033[92m'; YELLOW='\033[93m'; RED='\033[91m'; CYAN='\033[96m'; BOLD='\033[1m'; RESET='\033[0m'
ok()      { echo -e "  ${GREEN}[✓]${RESET} $1"; }
warn()    { echo -e "  ${YELLOW}[!]${RESET} $1"; }
fail()    { echo -e "  ${RED}[✗]${RESET} $1"; }
info()    { echo -e "  ${CYAN}[i]${RESET} $1"; }
section() { echo -e "\n${BOLD}  $1${RESET}"; echo -e "  $(printf '─%.0s' {1..50})"; }

echo -e "\n${BOLD}======================================================${RESET}"
echo -e "${BOLD}  MODSTAN — Health Check${RESET}"
echo -e "${BOLD}  $(date '+%Y-%m-%d %H:%M:%S')${RESET}"
echo -e "${BOLD}======================================================${RESET}"

# -----------------------------------------------------------------------------
# 1. Python
# -----------------------------------------------------------------------------
section "Python"
PYTHON_OK=false
for cmd in python3.12 python3.11 python3.10 python3; do
    if command -v "$cmd" &>/dev/null; then
        VER=$($cmd --version 2>&1)
        MINOR=$($cmd -c "import sys; print(sys.version_info.minor)")
        if [ "$MINOR" -ge 10 ]; then
            ok "$VER  ($(which $cmd))"
            PYTHON_OK=true
            break
        fi
    fi
done
$PYTHON_OK || fail "Python 3.10+ not found. Install with: sudo apt install python3.11"

# -----------------------------------------------------------------------------
# 2. Virtual Environment
# -----------------------------------------------------------------------------
section "Virtual Environment"
if [ -d "$VENV_DIR" ] && [ -f "$VENV_DIR/bin/activate" ]; then
    ok "venv found: $VENV_DIR"
    source "$VENV_DIR/bin/activate"
    ok "venv activated  ($(python --version))"
else
    fail "venv not found. Run: bash scripts/install.sh"
fi

# -----------------------------------------------------------------------------
# 3. Python Packages
# -----------------------------------------------------------------------------
section "Python Packages"

check_package() {
    local IMPORT="$1"
    local PIP_NAME="$2"
    local REQUIRED="$3"
    if python -c "import $IMPORT" 2>/dev/null; then
        VER=$(python -c "import $IMPORT; print(getattr($IMPORT, '__version__', '?'))" 2>/dev/null || echo "?")
        ok "$PIP_NAME  (v$VER)"
    else
        if [ "$REQUIRED" = "required" ]; then
            fail "$PIP_NAME — NOT INSTALLED (required!)"
        else
            warn "$PIP_NAME — not installed (optional)"
        fi
    fi
}

check_package "pyModbusTCP"     "pyModbusTCP"            "required"
check_package "psycopg2"        "psycopg2-binary"        "optional"
check_package "mysql.connector" "mysql-connector-python" "optional"

# -----------------------------------------------------------------------------
# 4. Project Structure
# -----------------------------------------------------------------------------
section "Project Structure"

for DIR in "$MODSTAN_DIR/core" "$MODSTAN_DIR/cli" "$MODSTAN_DIR/config" \
           "$MODSTAN_DIR/scripts" "$MODSTAN_DIR/logs" "$MODSTAN_DIR/exports"; do
    if [ -d "$DIR" ]; then
        ok "$(basename $DIR)/"
    else
        warn "$(basename $DIR)/ — directory not found"
    fi
done

for FILE in \
    "$MODSTAN_DIR/main.py" \
    "$MODSTAN_DIR/requirements.txt" \
    "/etc/systemd/system/modstan@.service" \
    "/usr/local/bin/modstan"; do
    if [ -f "$FILE" ]; then
        ok "$FILE"
    else
        warn "$FILE — not found"
    fi
done

# -----------------------------------------------------------------------------
# 5. Config Files
# -----------------------------------------------------------------------------
section "Config Files"
CONF_COUNT=0
for conf in "$CONFIG_DIR"/*.conf; do
    fname="$(basename "$conf")"
    [ "$fname" = "example.conf" ] && continue
    PERM=$(stat -c "%a" "$conf")
    if [ "$PERM" = "600" ]; then
        ok "$fname  (permission: $PERM)"
    else
        warn "$fname  (permission: $PERM — recommend: chmod 600 $conf)"
    fi
    CONF_COUNT=$((CONF_COUNT + 1))
done
[ "$CONF_COUNT" -eq 0 ] && warn "No device config files found. Copy from config/example.conf"

# -----------------------------------------------------------------------------
# 6. Systemd Services
# -----------------------------------------------------------------------------
section "Systemd Services"
SERVICES=$(systemctl list-units --type=service --all 2>/dev/null \
    | grep 'modstan@' | awk '{print $1}' || true)

if [ -z "$SERVICES" ]; then
    info "No modstan services registered yet."
    info "Enable one with: sudo systemctl enable --now modstan@METER01"
else
    for svc in $SERVICES; do
        STATUS=$(systemctl is-active "$svc" 2>/dev/null || echo "unknown")
        SINCE=$(systemctl show "$svc" --property=ActiveEnterTimestamp \
            | sed 's/ActiveEnterTimestamp=//' || echo "")
        if [ "$STATUS" = "active" ]; then
            ok "$svc — $STATUS  (since: $SINCE)"
        else
            fail "$svc — $STATUS"
        fi
    done
fi

# -----------------------------------------------------------------------------
# 7. Disk Space
# -----------------------------------------------------------------------------
section "Disk Space"
DISK_AVAIL=$(df -h "$MODSTAN_DIR" | awk 'NR==2{print $4}')
DISK_USE=$(df -h   "$MODSTAN_DIR" | awk 'NR==2{print $5}')
LOG_SIZE=$(du -sh  "$LOG_DIR"     2>/dev/null | cut -f1 || echo "0")
EXP_SIZE=$(du -sh  "$EXPORTS_DIR" 2>/dev/null | cut -f1 || echo "0")

ok  "Disk available : $DISK_AVAIL  (used: $DISK_USE)"
info "logs/          : $LOG_SIZE"
info "exports/       : $EXP_SIZE"

# -----------------------------------------------------------------------------
# 8. Modbus Host Reachability
# -----------------------------------------------------------------------------
section "Modbus Host Reachability"
for conf in "$CONFIG_DIR"/*.conf; do
    fname="$(basename "$conf")"
    [ "$fname" = "example.conf" ] && continue
    HOST=$(grep -i "^host" "$conf" | head -1 | awk -F'=' '{print $2}' | tr -d ' ')
    PORT=$(grep -i "^port" "$conf" | head -1 | awk -F'=' '{print $2}' | tr -d ' ')
    PORT="${PORT:-502}"
    DEVICE="${fname%.conf}"
    if timeout 2 bash -c "cat < /dev/null > /dev/tcp/$HOST/$PORT" 2>/dev/null; then
        ok "$DEVICE — $HOST:$PORT reachable"
    else
        fail "$DEVICE — $HOST:$PORT unreachable"
    fi
done

echo -e "\n${BOLD}======================================================${RESET}"
echo -e "  Done. Use ${BOLD}modstan check${RESET} for a concise summary."
echo -e "${BOLD}======================================================${RESET}\n"
