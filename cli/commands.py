#!/usr/bin/env python3
# =============================================================================
# MODSTAN - CLI Management Tool
# Manage devices, services, database, and exports from the command line
# =============================================================================

import sys
import os
import argparse
import subprocess
import datetime
import csv

# ROOT_DIR is resolved via MODSTAN_ROOT env var (set by install.sh),
# falling back to the grandparent of this file for local development use.
ROOT_DIR = os.environ.get(
    'MODSTAN_ROOT',
    os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
)
sys.path.insert(0, ROOT_DIR)

CONFIG_DIR  = os.path.join(ROOT_DIR, 'config')
EXPORTS_DIR = os.path.join(ROOT_DIR, 'exports')
VERSION     = '2.0.1'

# ANSI color codes
GREEN  = '\033[92m'
YELLOW = '\033[93m'
RED    = '\033[91m'
CYAN   = '\033[96m'
BOLD   = '\033[1m'
RESET  = '\033[0m'

def ok(msg):     print(f"  {GREEN}[✓]{RESET} {msg}")
def warn(msg):   print(f"  {YELLOW}[!]{RESET} {msg}")
def fail(msg):   print(f"  {RED}[✗]{RESET} {msg}")
def info(msg):   print(f"  {CYAN}[i]{RESET} {msg}")
def header(msg): print(f"\n{BOLD}{msg}{RESET}")


# =============================================================================
# Helpers
# =============================================================================

def systemctl(action: str, device: str) -> tuple[int, str]:
    """Run a systemctl command for a modstan@<device> service."""
    result = subprocess.run(
        ['sudo', 'systemctl', action, f"modstan@{device}.service"],
        capture_output=True, text=True
    )
    return result.returncode, result.stdout + result.stderr


def get_service_status(device: str) -> dict:
    """Return the systemd service status for a given device."""
    service = f"modstan@{device}.service"
    r1 = subprocess.run(
        ['systemctl', 'is-active', service],
        capture_output=True, text=True
    )
    r2 = subprocess.run(
        ['systemctl', 'show', service, '--property=ActiveEnterTimestamp'],
        capture_output=True, text=True
    )
    uptime = r2.stdout.strip().replace('ActiveEnterTimestamp=', '')
    return {
        'service': service,
        'active' : r1.stdout.strip(),
        'uptime' : uptime,
    }


def list_configs() -> list[str]:
    """Return a sorted list of device names from .conf files in the config directory."""
    if not os.path.isdir(CONFIG_DIR):
        return []
    return [
        f.replace('.conf', '')
        for f in sorted(os.listdir(CONFIG_DIR))
        if f.endswith('.conf') and f != 'example.conf'
    ]


def load_device_config(device: str):
    """Load and return the DeviceConfig for a given device name."""
    from core.config_manager import load_config, ConfigError
    conf_path = os.path.join(CONFIG_DIR, f"{device}.conf")
    if not os.path.exists(conf_path):
        fail(f"Config file not found: {conf_path}")
        return None
    try:
        return load_config(conf_path)
    except ConfigError as e:
        fail(str(e))
        return None


def get_storage_for(cfg):
    """Open and return a connected storage adapter for the given config."""
    from core.storage.factory import get_storage
    return get_storage(cfg)


# =============================================================================
# Commands
# =============================================================================

def cmd_list(args):
    """List all registered devices with their current service status."""
    header("MODSTAN — Device List")
    devices = list_configs()
    if not devices:
        warn(f"No .conf files found in {CONFIG_DIR}")
        info("Copy and adjust: config/example.conf")
        return

    print(f"\n  {'DEVICE':<20} {'HOST':<20} {'PORT':<7} {'STORAGE':<10} {'STATUS'}")
    print(f"  {'-'*68}")
    for d in devices:
        cfg = load_device_config(d)
        if cfg:
            st      = get_service_status(d)
            active  = st['active']
            color   = GREEN if active == 'active' else RED
            storage = cfg.storage_type if cfg.storage_enabled else 'disabled'
            print(
                f"  {cfg.name:<20} {cfg.modbus_host:<20} {cfg.modbus_port:<7} "
                f"{storage:<10} {color}{active}{RESET}"
            )
    print()


def cmd_status(args):
    """Show detailed status for one or all devices."""
    header("MODSTAN — Status")
    devices = [args.device] if args.device else list_configs()
    if not devices:
        warn("No devices registered.")
        return

    for d in devices:
        cfg = load_device_config(d)
        if not cfg:
            continue
        st    = get_service_status(d)
        color = GREEN if st['active'] == 'active' else RED

        print(f"\n  {BOLD}{cfg.name}{RESET}")
        print(f"    Service    : {color}{st['service']}{RESET} ({st['active']})")
        print(f"    Since      : {st['uptime'] or 'N/A'}")
        print(f"    Host       : {cfg.modbus_host}:{cfg.modbus_port}")
        print(f"    Interval   : {cfg.interval}s (default)")
        print(f"    Registers  : {len(cfg.registers)}")
        for r in cfg.registers:
            print(
                f"      - {r.name:<15} addr={r.address:<6} "
                f"fc={r.function_code}  interval={r.interval}s  "
                f"{r.data_type}/{r.byte_format}"
            )
        print(f"    Storage    : {'enabled' if cfg.storage_enabled else 'disabled'}")
        if cfg.storage_enabled:
            print(f"      Type     : {cfg.storage_type}")
            print(f"      Host     : {cfg.storage_host}:{cfg.storage_port}")
            print(f"      Database : {cfg.storage_database}")
            print(f"      Table    : {cfg.storage_table}")
            ret = f"{cfg.storage_retention} day(s)" if cfg.storage_retention > 0 else "forever"
            print(f"      Retention: {ret}")
    print()


def cmd_start(args):
    """Start the systemd service for a device."""
    header(f"MODSTAN — Start: {args.device}")
    code, out = systemctl('start', args.device)
    if code == 0:
        ok(f"modstan@{args.device} started successfully.")
    else:
        fail(f"Failed to start service: {out.strip()}")


def cmd_stop(args):
    """Stop the systemd service for a device."""
    header(f"MODSTAN — Stop: {args.device}")
    code, out = systemctl('stop', args.device)
    if code == 0:
        ok(f"modstan@{args.device} stopped successfully.")
    else:
        fail(f"Failed to stop service: {out.strip()}")


def cmd_restart(args):
    """Restart the systemd service for a device."""
    header(f"MODSTAN — Restart: {args.device}")
    code, out = systemctl('restart', args.device)
    if code == 0:
        ok(f"modstan@{args.device} restarted successfully.")
    else:
        fail(f"Failed to restart service: {out.strip()}")


def cmd_read(args):
    """
    Read all registers once and print the values to the terminal.
    No data is written to the database.
    Useful for quick spot-checks of current register values.
    """
    header(f"MODSTAN — Read: {args.device}")
    cfg = load_device_config(args.device)
    if not cfg:
        return

    from pyModbusTCP.client import ModbusClient
    from core.data_converter import process_register
    import time

    print(f"\n  Connecting to {cfg.modbus_host}:{cfg.modbus_port}...\n")
    client = ModbusClient(
        host=cfg.modbus_host, port=cfg.modbus_port, timeout=cfg.modbus_timeout
    )
    if not client.open():
        fail(f"Cannot connect to {cfg.modbus_host}:{cfg.modbus_port}")
        return

    ok(f"Connected. Reading {len(cfg.registers)} register(s)...\n")
    print(f"  {'REGISTER':<18} {'VALUE':>12}  {'HEX':<25} {'PING':>8}")
    print(f"  {'-'*68}")

    for reg in cfg.registers:
        start = time.time()
        raw   = (
            client.read_holding_registers(reg.address, reg.quantity)
            if reg.function_code == 3
            else client.read_input_registers(reg.address, reg.quantity)
        )
        ping = (time.time() - start) * 1000

        if raw is None:
            fail(f"  {reg.name:<18} No response (addr={reg.address})")
            continue
        try:
            result = process_register(raw, reg.data_type, reg.byte_format, reg.scale)
            print(
                f"  {reg.name:<18} {result['scaled']:>12.4f}  "
                f"{result['hex']:<25} {ping:>6.1f}ms"
            )
        except Exception as e:
            fail(f"  {reg.name:<18} Conversion error: {e}")

    client.close()
    print()


def cmd_test(args):
    """
    Same as 'read' but explicitly labelled as testing mode.
    Useful when storage is enabled — confirms no data is written.
    """
    header(f"MODSTAN — Test: {args.device}")
    cmd_read(args)
    warn("TEST mode — no data written to database.")
    print()


def cmd_config(args):
    """Display the active configuration for a device in a readable format."""
    header(f"MODSTAN — Config: {args.device}")
    cfg = load_device_config(args.device)
    if not cfg:
        return

    print(f"\n  {BOLD}[DEVICE]{RESET}")
    print(f"    name     = {cfg.name}")
    print(f"    interval = {cfg.interval}s")

    print(f"\n  {BOLD}[MODBUS]{RESET}")
    print(f"    host        = {cfg.modbus_host}")
    print(f"    port        = {cfg.modbus_port}")
    print(f"    timeout     = {cfg.modbus_timeout}s")
    print(f"    max_retries = {cfg.modbus_max_retries}  (0 = unlimited)")
    print(f"    retry_delay = {cfg.modbus_retry_delay}s")

    print(f"\n  {BOLD}[STORAGE]{RESET}")
    print(f"    enabled   = {cfg.storage_enabled}")
    print(f"    type      = {cfg.storage_type}")
    if cfg.storage_enabled:
        print(f"    host      = {cfg.storage_host}:{cfg.storage_port}")
        print(f"    database  = {cfg.storage_database}")
        print(f"    table     = {cfg.storage_table}")
        ret = f"{cfg.storage_retention} day(s)" if cfg.storage_retention > 0 else "forever"
        print(f"    retention = {ret}")

    print(f"\n  {BOLD}[REGISTERS]{RESET}")
    print(
        f"  {'NAME':<18} {'FC':<4} {'ADDR':<7} {'QTY':<5} "
        f"{'TYPE':<9} {'SCALE':<8} {'FORMAT':<7} {'INTERVAL'}"
    )
    print(f"  {'-'*72}")
    for r in cfg.registers:
        print(
            f"  {r.name:<18} {r.function_code:<4} {r.address:<7} {r.quantity:<5} "
            f"{r.data_type:<9} {r.scale:<8} {r.byte_format:<7} {r.interval}s"
        )
    print()


def cmd_check(args):
    """Run a full system health check: Python, packages, configs, DB, services."""
    header("MODSTAN — Health Check")

    # Python version
    v = sys.version_info
    if v >= (3, 10):
        ok(f"Python {v.major}.{v.minor}.{v.micro}")
    else:
        fail(f"Python {v.major}.{v.minor}.{v.micro} — Python 3.10+ is required!")

    # Package check with version comparison against requirements.txt
    print()
    info("Installed packages:")
    req_path     = os.path.join(ROOT_DIR, 'requirements.txt')
    req_versions = {}
    if os.path.exists(req_path):
        with open(req_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    for sep in ('==', '>=', '<='):
                        if sep in line:
                            pkg, ver = line.split(sep, 1)
                            req_versions[pkg.strip().lower()] = ver.strip()
                            break

    def check_pkg(import_name, pip_name, required=False):
        try:
            mod       = __import__(import_name)
            installed = getattr(mod, '__version__', '?')
            req_ver   = req_versions.get(pip_name.lower(), '')
            note      = f"v{installed}"
            if req_ver and installed != '?':
                note += f"  (required: {req_ver})"
            ok(f"  {pip_name:<35} {note}")
        except ImportError:
            if required:
                fail(f"  {pip_name:<35} NOT INSTALLED — required!")
            else:
                warn(f"  {pip_name:<35} not installed (optional)")

    check_pkg('pyModbusTCP',     'pyModbusTCP',            required=True)
    check_pkg('psycopg2',        'psycopg2-binary',        required=False)
    check_pkg('mysql.connector', 'mysql-connector-python', required=False)

    # Config files
    print()
    info("Config files:")
    devices = list_configs()
    if devices:
        for d in devices:
            conf_path = os.path.join(CONFIG_DIR, f"{d}.conf")
            perm      = oct(os.stat(conf_path).st_mode)[-3:]
            sym       = f"{GREEN}✓{RESET}" if perm == '600' else f"{YELLOW}!{RESET}"
            note      = '' if perm == '600' else '  ← recommend: chmod 600'
            print(f"    {sym} {d}.conf  (permission: {perm}{note})")
    else:
        warn(f"No .conf files found in {CONFIG_DIR}")

    # Database connections
    print()
    info("Database connections:")
    for d in devices:
        cfg = load_device_config(d)
        if cfg and cfg.storage_enabled:
            try:
                storage      = get_storage_for(cfg)
                success, msg = storage.test_connection()
                storage.close()
                (ok if success else fail)(f"  [{cfg.name}] {cfg.storage_type} — {msg}")
            except Exception as e:
                fail(f"  [{cfg.name}] {cfg.storage_type} — {e}")
        elif cfg:
            warn(f"  [{cfg.name}] storage disabled")

    # Service status
    print()
    info("Service status:")
    for d in devices:
        st     = get_service_status(d)
        active = st['active']
        (ok if active == 'active' else fail)(f"  modstan@{d} — {active}")

    print()


def cmd_logs(args):
    """Stream live logs for a device service via journalctl."""
    header(f"MODSTAN — Live Logs: {args.device}")
    service = f"modstan@{args.device}.service"
    print(f"  Streaming logs for {service}  (Ctrl+C to exit)\n")
    try:
        subprocess.run(['journalctl', '-u', service, '-f', '--no-pager'])
    except KeyboardInterrupt:
        pass


def cmd_db_init(args):
    """Initialize database tables for all configured devices."""
    header("MODSTAN — DB Init")
    for d in list_configs():
        cfg = load_device_config(d)
        if cfg and cfg.storage_enabled:
            try:
                storage = get_storage_for(cfg)
                storage.ensure_schema(cfg.get_register_names())
                storage.close()
                ok(f"[{cfg.name}] Table '{cfg.storage_table}' ready in {cfg.storage_type}.")
            except Exception as e:
                fail(f"[{cfg.name}] DB init failed: {e}")
        elif cfg:
            warn(f"[{cfg.name}] Storage disabled — skipped.")
    print()


def cmd_db_status(args):
    """Check database connectivity for all configured devices."""
    header("MODSTAN — DB Status")
    for d in list_configs():
        cfg = load_device_config(d)
        if cfg and cfg.storage_enabled:
            try:
                storage      = get_storage_for(cfg)
                success, msg = storage.test_connection()
                storage.close()
                (ok if success else fail)(f"[{cfg.name}] {cfg.storage_type} — {msg}")
            except Exception as e:
                fail(f"[{cfg.name}] Error: {e}")
        elif cfg:
            warn(f"[{cfg.name}] Storage disabled.")
    print()


def cmd_flush(args):
    """
    Delete ALL stored data for a specific device from the database.
    Requires typing the device name to confirm.
    """
    header(f"MODSTAN — Flush: {args.device}")
    cfg = load_device_config(args.device)
    if not cfg or not cfg.storage_enabled:
        fail("Storage is not enabled for this device.")
        return

    warn(f"This will permanently delete ALL data for '{args.device}' from the database!")
    print(f"  Database : {cfg.storage_type} — {cfg.storage_database}")
    print(f"  Table    : {cfg.storage_table}")
    print()
    confirm = input("  Type the device name to confirm: ").strip()
    if confirm != args.device:
        print("\n  Cancelled.\n")
        return

    try:
        storage = get_storage_for(cfg)
        table   = cfg.storage_table

        if cfg.storage_type == 'postgres':
            with storage._conn.cursor() as cur:
                cur.execute(
                    f"DELETE FROM {table} WHERE device_name = %s", (args.device,)
                )
                deleted = cur.rowcount
            storage._conn.commit()

        elif cfg.storage_type in ('mariadb', 'mysql'):
            cur = storage._conn.cursor()
            cur.execute(
                f"DELETE FROM `{table}` WHERE device_name = %s", (args.device,)
            )
            deleted = cur.rowcount
            storage._conn.commit()
            cur.close()

        elif cfg.storage_type == 'sqlite':
            cur = storage._conn.cursor()
            cur.execute(
                f'DELETE FROM "{table}" WHERE device_name = ?', (args.device,)
            )
            deleted = cur.rowcount
            storage._conn.commit()

        else:
            warn("Flush is not supported for the CSV adapter.")
            storage.close()
            return

        storage.close()
        ok(f"{deleted} record(s) for '{args.device}' deleted from the database.")

    except Exception as e:
        fail(f"Flush failed: {e}")
    print()


def cmd_retention_run(args):
    """Manually trigger the data retention cleanup for all devices."""
    header("MODSTAN — Retention Run")
    for d in list_configs():
        cfg = load_device_config(d)
        if cfg and cfg.storage_enabled and cfg.storage_retention > 0:
            try:
                storage = get_storage_for(cfg)
                deleted = storage.delete_old_records(cfg.storage_retention)
                storage.close()
                ok(
                    f"[{cfg.name}] {deleted} record(s) deleted "
                    f"(older than {cfg.storage_retention} day(s))."
                )
            except Exception as e:
                fail(f"[{cfg.name}] Error: {e}")
        elif cfg:
            warn(f"[{cfg.name}] Retention not active (disabled or retention=0).")
    print()


def cmd_export(args):
    """
    Export register data for a device to a CSV file.
    Supports all storage adapters: postgres, mariadb, sqlite, csv.
    Output is saved to the exports/ directory.
    """
    header(f"MODSTAN — Export: {args.device}")
    cfg = load_device_config(args.device)
    if not cfg or not cfg.storage_enabled:
        fail("Storage is not enabled for this device.")
        return

    os.makedirs(EXPORTS_DIR, exist_ok=True)
    ts       = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    out_file = os.path.join(EXPORTS_DIR, f"{args.device}_{ts}.csv")

    try:
        storage = get_storage_for(cfg)
        table   = cfg.storage_table
        headers = []
        rows    = []

        if cfg.storage_type == 'sqlite':
            headers, rows = storage.get_rows(
                args.device,
                from_date=args.from_date,
                to_date=args.to_date,
            )

        elif cfg.storage_type in ('postgres', 'mariadb', 'mysql'):
            query  = f"SELECT * FROM {table} WHERE device_name = %s"
            params = [args.device]
            if args.from_date:
                query  += " AND timestamp >= %s"
                params.append(args.from_date)
            if args.to_date:
                query  += " AND timestamp <= %s"
                params.append(args.to_date)
            query += " ORDER BY timestamp"

            cur = storage._conn.cursor()
            cur.execute(query, params)
            rows    = [list(r) for r in cur.fetchall()]
            headers = [desc[0] for desc in cur.description]
            cur.close()

        elif cfg.storage_type == 'csv':
            src = os.path.join(ROOT_DIR, cfg.storage_database, f"{args.device}.csv")
            if not os.path.exists(src):
                fail(f"CSV source file not found: {src}")
                storage.close()
                return
            with open(src, 'r', encoding='utf-8') as f:
                reader  = csv.reader(f)
                headers = next(reader)
                rows    = list(reader)

        storage.close()

        with open(out_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(rows)

        ok(f"Export complete: {out_file}")
        ok(f"{len(rows)} row(s) exported.")

    except Exception as e:
        fail(f"Export failed: {e}")
    print()


def cmd_version(args):
    print(f"\n  MODSTAN v{VERSION}\n")


# =============================================================================
# CLI Router
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        prog='modstan',
        description='MODSTAN — CLI Management Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  list                        List all registered devices
  status     [device]         Detailed status (all or one device)
  start      <device>         Start the systemd service
  stop       <device>         Stop the systemd service
  restart    <device>         Restart the systemd service
  read       <device>         Read all registers once, print to terminal
  test       <device>         Same as read — explicitly labelled as test mode
  config     <device>         Display the active device configuration
  check                       Full system health check
  logs       <device>         Stream live logs via journalctl
  flush      <device>         Delete all data for a device from the database
  db init                     Initialize database tables
  db status                   Check database connectivity
  retention run               Manually run data retention cleanup
  export     <device>         Export data to CSV
  version                     Print version

Examples:
  modstan list
  modstan status METER01
  modstan read METER01
  modstan config METER01
  modstan start METER01
  modstan test DEVICE01
  modstan flush METER01
  modstan export METER01 --from 2024-01-01 --to 2024-01-31
  modstan check
  modstan db init
  modstan retention run
        """
    )

    sub = parser.add_subparsers(dest='command')

    sub.add_parser('list',    help='List all registered devices')
    sub.add_parser('version', help='Print version')

    p_status = sub.add_parser('status', help='Device status')
    p_status.add_argument('device', nargs='?', metavar='DEVICE')

    p_check = sub.add_parser('check', help='Health check')
    p_check.add_argument('device', nargs='?', metavar='DEVICE')

    for cmd in ('start', 'stop', 'restart', 'read', 'test', 'config', 'logs', 'flush'):
        p = sub.add_parser(cmd)
        p.add_argument('device', metavar='DEVICE')

    p_db  = sub.add_parser('db', help='Database management')
    p_dbs = p_db.add_subparsers(dest='db_command')
    p_dbs.add_parser('init',   help='Initialize tables')
    p_dbs.add_parser('status', help='Check connectivity')

    p_ret  = sub.add_parser('retention', help='Data retention')
    p_rets = p_ret.add_subparsers(dest='retention_command')
    p_rets.add_parser('run', help='Run cleanup now')

    p_exp = sub.add_parser('export', help='Export data to CSV')
    p_exp.add_argument('device', metavar='DEVICE')
    p_exp.add_argument('--from', dest='from_date', default=None, metavar='YYYY-MM-DD')
    p_exp.add_argument('--to',   dest='to_date',   default=None, metavar='YYYY-MM-DD')

    args = parser.parse_args()

    match args.command:
        case 'list'      : cmd_list(args)
        case 'status'    : cmd_status(args)
        case 'start'     : cmd_start(args)
        case 'stop'      : cmd_stop(args)
        case 'restart'   : cmd_restart(args)
        case 'read'      : cmd_read(args)
        case 'test'      : cmd_test(args)
        case 'config'    : cmd_config(args)
        case 'check'     : cmd_check(args)
        case 'logs'      : cmd_logs(args)
        case 'flush'     : cmd_flush(args)
        case 'version'   : cmd_version(args)
        case 'db':
            match getattr(args, 'db_command', None):
                case 'init'   : cmd_db_init(args)
                case 'status' : cmd_db_status(args)
                case _        : p_db.print_help()
        case 'retention':
            match getattr(args, 'retention_command', None):
                case 'run' : cmd_retention_run(args)
                case _     : p_ret.print_help()
        case 'export'    : cmd_export(args)
        case _           : parser.print_help()


if __name__ == '__main__':
    main()
