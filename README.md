# MODSTAN v2.0.1
**Modbus TCP Data Logger — Instant, Modular, Production-Ready**

---

## Features

- **Multi-device** — run multiple devices simultaneously, each in its own thread
- **Auto-reconnect** — automatically reconnects to both Modbus devices and databases if connections drop
- **Per-register interval** — each register can have its own independent polling interval
- **Storage adapters** — supports PostgreSQL, MariaDB, SQLite, and CSV out of the box
- **Dynamic schema** — database tables are created and updated automatically from `.conf` files
- **Row buffering** — all register values within one poll cycle are written as a single database row
- **Data retention** — automatically deletes old records based on a configurable number of days
- **Testing mode** — read registers without writing to the database (`enabled = false`)
- **CLI tool** — full device management from the terminal using the `modstan` command
- **systemd service** — runs as a managed background service with automatic restart on failure

---

## Requirements

- Linux (Ubuntu 20.04+ / Debian 11+ / RHEL 8+)
- Python 3.10 or newer

---

## Installation

```bash
# Clone or extract the project
git clone https://github.com/F4NTech/modstan.git
cd modstan

# Run the installer
bash scripts/install.sh
```

The installer will automatically:
1. Create a Python virtual environment
2. Install all required dependencies
3. Register the systemd service template
4. Create the `modstan` CLI command
5. Set the `MODSTAN_ROOT` environment variable

---

## Configuration

Copy the example file and adjust it for your device:

```bash
cp config/example.conf config/METER01.conf
nano config/METER01.conf
chmod 600 config/METER01.conf   # restrict access to credentials
```

### Configuration file structure

```ini
[DEVICE]
name     = METER01      # unique device name — used as device_name in the database
interval = 5            # default polling interval for all registers (seconds)

[MODBUS]
host        = 192.168.1.100
port        = 502
slave_id    = 1         # default 1
timeout     = 10
max_retries = 0         # 0 = retry indefinitely
retry_delay = 5

[STORAGE]
enabled   = false       # true = write to DB | false = testing mode (print only)
type      = postgres    # postgres | mariadb | sqlite | csv
host      = 192.168.1.10
port      = 5432
database  = modbus_data
username  = admin
password  = secret123
table     = register_logs
retention = 30          # keep data for 30 days; 0 = keep forever

[OWNER]
customer_id = 001
tag_host    = PANEL-A
tag_name    = MAIN-METER

[REGISTERS]
# Format: function_code, address, quantity, data_type, scale, byte_format[, interval]
#
# function_code : 3 = Holding Register, 4 = Input Register
# data_type     : uint16 | int16 | uint32 | int32 | uint64 | int64 | float32 | float64
# byte_format   : ABCD | CDAB | BADC | DCBA | AB | BA
# interval      : (optional) per-register override in seconds

voltage      = 3, 100, 2, float32, 0.1,  ABCD
current      = 3, 102, 2, float32, 0.01, ABCD
power        = 3, 104, 2, float32, 1.0,  ABCD
temperature  = 3, 200, 2, float32, 0.1,  ABCD, 30
energy_total = 3, 300, 4, float32, 1.0,  ABCD, 60
```

### Interval priority

```
Per-register interval  (if defined in [REGISTERS])
        ↓ not set?
Device interval        ([DEVICE] interval)
        ↓ not set?
Default: 1 second
```

---

## CLI Reference

```bash
# Device overview
modstan list

# Detailed status
modstan status
modstan status METER01

# Read registers once — no data written to DB
modstan read METER01

# Same as read, explicitly labelled as test mode
modstan test DEVICE01

# Show active configuration
modstan config METER01

# Service control
sudo systemctl enable --now modstan@METER01
modstan start   METER01
modstan stop    METER01
modstan restart METER01

# Live log stream
modstan logs METER01

# Full system health check
modstan check

# Database
modstan db init          # create tables
modstan db status        # check connectivity

# Data management
modstan retention run                              # run cleanup now
modstan flush METER01                              # delete all data for a device
modstan export METER01                             # export all data to CSV
modstan export METER01 --from 2024-01-01 --to 2024-01-31

# Version
modstan version
```

---

## Running Directly (without systemd)

```bash
# Single device
python main.py --config config/METER01.conf

# All devices in the config/ directory
python main.py --config-dir config/

# Verbose / debug mode
python main.py --config config/METER01.conf --verbose
```

---

## Database Schema

All devices share a single table with dynamic columns:

```sql
CREATE TABLE register_logs (
    id          BIGSERIAL PRIMARY KEY,
    timestamp   TIMESTAMPTZ NOT NULL,
    device_name VARCHAR(100) NOT NULL,
    ping_ms     FLOAT,

    -- Columns below are created automatically from register names in .conf files
    voltage      FLOAT,
    current      FLOAT,
    power        FLOAT,
    temperature  FLOAT,
    energy_total FLOAT
    -- additional columns added as new registers are configured
);
```

New columns are added automatically (`ALTER TABLE`) when new registers are added to a config file. Existing data is never affected.

---

## Maintenance

```bash
# Upgrade code and dependencies
bash scripts/upgrade.sh

# Full system check
bash scripts/check.sh

# Uninstall
bash scripts/uninstall.sh
```

---

## Project Structure

```
modstan/
├── main.py                    # Application entry point
├── requirements.txt           # Python dependencies
├── setup.py                   # Package setup
├── core/
│   ├── config_manager.py      # Load and validate .conf files
│   ├── data_converter.py      # Modbus register conversion
│   ├── modbus_handler.py      # Polling loop, auto-reconnect, per-register interval
│   ├── retention.py           # Scheduled deletion of old records
│   ├── logger.py              # Logging setup (file + console)
│   └── storage/
│       ├── base.py            # Abstract storage interface
│       ├── factory.py         # Adapter selector
│       ├── postgres.py        # PostgreSQL adapter
│       ├── mariadb.py         # MariaDB / MySQL adapter
│       ├── sqlite.py          # SQLite adapter
│       └── csv_adapter.py     # CSV adapter
├── cli/
│   └── commands.py            # CLI management tool
├── config/
│   └── example.conf           # Example device configuration
├── scripts/
│   ├── install.sh             # Installer
│   ├── upgrade.sh             # Upgrade script
│   ├── uninstall.sh           # Uninstaller
│   └── check.sh               # System health check
├── logs/                      # Log files (auto-created)
└── exports/                   # CSV exports (auto-created)
```

---

## License

MIT License — F4NTech
