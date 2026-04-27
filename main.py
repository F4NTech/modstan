#!/usr/bin/env python3
# =============================================================================
# MODSTAN v2.0.1 - Main Entry Point
# Modbus TCP Data Logger — multi-device, multi-threaded, storage-agnostic
# © github.com/F4NTech - @linkedin.com/in/muhammad-farhan-013455141
# =============================================================================

import sys
import os
import signal
import logging
import threading
import datetime
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.logger          import setup_logger
from core.config_manager  import load_config, load_all_configs, ConfigError
from core.modbus_handler  import ModbusHandler
from core.storage.factory import get_storage
from core.retention       import RetentionManager

logger = logging.getLogger(__name__)

MODSTAN_VERSION = '2.0.1'
CONFIG_DIR      = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config')


# =============================================================================
# Device Runner
# =============================================================================

class DeviceRunner:
    """
    Manages a single device: Modbus handler + storage adapter + row buffer.

    The row buffer accumulates all register values within one flush window,
    then writes them as ONE ROW to the database — not one row per register.

    Example row in the database:
    | timestamp  | device_name | ping_ms | voltage | current | power | temperature |
    |------------|-------------|---------|---------|---------|-------|-------------|
    | 10:00:05   | METER01     |  12.3   | 220.5   |  10.2   | 2241  |    45.2     |
    """

    def __init__(self, config):
        self.config  = config
        self.storage = None
        self.handler = None

        # Row buffer — accumulates register values between flushes
        self._buffer      : dict[str, float]         = {}
        self._buffer_ping : list[float]              = []
        self._buffer_ts   : datetime.datetime | None = None
        self._buffer_lock = threading.Lock()

        # Flush to DB every N seconds (N = shortest register interval)
        self._flush_interval = min(r.interval for r in config.registers)
        self._flush_thread   = None
        self._running        = False

    # ------------------------------------------------------------------
    # Storage Setup
    # ------------------------------------------------------------------
    def setup_storage(self) -> bool:
        if not self.config.storage_enabled:
            logger.info(
                f"[{self.config.name}] Storage disabled — running in testing mode."
            )
            return True
        try:
            self.storage = get_storage(self.config)
            self.storage.ensure_schema(self.config.get_register_names())
            return True
        except Exception as e:
            logger.error(f"[{self.config.name}] Storage setup failed: {e}")
            return False

    # ------------------------------------------------------------------
    # Data Callback — invoked by ModbusHandler on each successful register read
    # ------------------------------------------------------------------
    def on_data(self, result: dict):
        register_name = result['register_name']
        scaled_value  = result['scaled']
        ping_ms       = result['ping_ms']
        timestamp     = result['timestamp']

        # Log each register reading
        logger.info(
            f"[{self.config.name}] {register_name:<15} = {scaled_value:<15.4f} "
            f"| hex={result['hex']:<20} | ping={ping_ms:.1f}ms"
        )
        print(
            f"  [{timestamp.strftime('%H:%M:%S')}] "
            f"{self.config.name:<12} | {register_name:<15} = {scaled_value:<12.4f} "
            f"| {result['hex']:<20} | {ping_ms:.1f}ms"
        )

        # Accumulate into the row buffer
        with self._buffer_lock:
            if self._buffer_ts is None:
                self._buffer_ts = timestamp
            self._buffer[register_name] = scaled_value
            self._buffer_ping.append(ping_ms)

    # ------------------------------------------------------------------
    # Flush Buffer → Database
    # ------------------------------------------------------------------
    def _flush_loop(self):
        logger.info(
            f"[{self.config.name}] Flush thread started "
            f"(interval={self._flush_interval}s)."
        )
        while self._running:
            time.sleep(self._flush_interval)
            self._flush_buffer()
        logger.info(f"[{self.config.name}] Flush thread stopped.")

    def _flush_buffer(self):
        """
        Take a snapshot of the current buffer and write it as ONE ROW
        to the database. Resets the buffer afterwards.
        """
        with self._buffer_lock:
            if not self._buffer:
                return  # Nothing to write

            row_data  = dict(self._buffer)
            avg_ping  = (
                sum(self._buffer_ping) / len(self._buffer_ping)
                if self._buffer_ping else 0.0
            )
            timestamp = self._buffer_ts or datetime.datetime.now(datetime.timezone.utc)

            # Reset buffer
            self._buffer      = {}
            self._buffer_ping = []
            self._buffer_ts   = None

        # Build the final row (all registers in one dict)
        row = {
            'device_name': self.config.name,
            'timestamp'  : timestamp,
            'ping_ms'    : round(avg_ping, 3),
            **row_data,
        }

        if self.storage and self.config.storage_enabled:
            success = self.storage.save(row)
            if success:
                summary = ', '.join(f"{k}={v:.3f}" for k, v in row_data.items())
                logger.info(f"[{self.config.name}] Row saved → {summary}")
            else:
                logger.error(f"[{self.config.name}] Failed to save row to database.")

    # ------------------------------------------------------------------
    # Start / Stop
    # ------------------------------------------------------------------
    def start(self):
        self._running = True

        self._flush_thread = threading.Thread(
            target=self._flush_loop,
            name=f"flush-{self.config.name}",
            daemon=True,
        )
        self._flush_thread.start()

        self.handler = ModbusHandler(self.config, on_data=self.on_data)
        self.handler.start()

        logger.info(f"[{self.config.name}] DeviceRunner started.")

    def stop(self):
        self._running = False

        if self.handler:
            self.handler.stop()

        # Flush any remaining buffer before closing
        self._flush_buffer()

        if self._flush_thread and self._flush_thread.is_alive():
            self._flush_thread.join(timeout=5)

        if self.storage:
            self.storage.close()

        logger.info(f"[{self.config.name}] DeviceRunner stopped.")

    def is_running(self) -> bool:
        return self._running and self.handler is not None and self.handler.is_running()

    def get_status(self) -> dict:
        status = self.handler.get_status() if self.handler else {}
        status['storage_enabled'] = self.config.storage_enabled
        status['storage_type']    = (
            self.config.storage_type if self.config.storage_enabled else 'disabled'
        )
        status['buffer_pending']  = len(self._buffer)
        return status


# =============================================================================
# Main Application
# =============================================================================

class ModstanApp:
    """
    Orchestrates all DeviceRunners and the RetentionManager.
    Handles graceful startup and shutdown via SIGINT / SIGTERM.
    """

    def __init__(self):
        self.runners   : list[DeviceRunner] = []
        self.retention = RetentionManager()
        self._stop_event = threading.Event()

    def load(self, config_file: str = None, config_dir: str = None):
        """Load device configurations from a single file or an entire directory."""
        configs = []

        if config_file:
            try:
                cfg = load_config(config_file)
                configs.append(cfg)
            except ConfigError as e:
                print(f"[ERROR] {e}")
                sys.exit(1)

        elif config_dir:
            configs = load_all_configs(config_dir)
            if not configs:
                print(f"[ERROR] No valid config files found in: {config_dir}")
                sys.exit(1)

        else:
            configs = load_all_configs(CONFIG_DIR)
            if not configs:
                print(f"[ERROR] No .conf files found in {CONFIG_DIR}")
                print(f"        Copy and adjust: {CONFIG_DIR}/example.conf")
                sys.exit(1)

        for cfg in configs:
            runner = DeviceRunner(cfg)
            if runner.setup_storage():
                self.runners.append(runner)
                if cfg.storage_enabled and cfg.storage_retention > 0:
                    self.retention.register(
                        runner.storage, cfg.storage_retention, cfg.name
                    )

        print(f"\n{'='*65}")
        print(f"  MODSTAN v{MODSTAN_VERSION} — Modbus TCP Data Logger")
        print(f"{'='*65}")
        print(f"  Active devices : {len(self.runners)}")
        for r in self.runners:
            st = r.config.storage_type if r.config.storage_enabled else 'disabled'
            print(
                f"    [{r.config.name:<20}] "
                f"{r.config.modbus_host}:{r.config.modbus_port} | "
                f"storage={st} | "
                f"registers={len(r.config.registers)}"
            )
        print(f"{'='*65}\n")

        self._validate_initial_connections()

    def _validate_initial_connections(self):
        """
        Test Modbus connectivity for all devices before starting the polling loops.
        Unreachable devices will still start — auto-reconnect handles them.
        """
        from pyModbusTCP.client import ModbusClient
        print("  Checking initial Modbus connections...\n")
        for runner in self.runners:
            cfg    = runner.config
            client = ModbusClient(
                host    = cfg.modbus_host,
                port    = cfg.modbus_port,
                unit_id = cfg.modbus_slave_id,   # ← tambah ini
                timeout = 3,
            )
            if client.open():
                client.close()
                print(f"    ✓ {cfg.name:<20} {cfg.modbus_host}:{cfg.modbus_port} — reachable")
            else:
                print(
                    f"    ✗ {cfg.name:<20} {cfg.modbus_host}:{cfg.modbus_port} "
                    f"— UNREACHABLE (auto-reconnect is active)"
                )
        print()

    def start(self):
        """Start all device runners and the retention manager."""
        for runner in self.runners:
            runner.start()

        self.retention.start()

        signal.signal(signal.SIGINT,  self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

        print("  Press Ctrl+C to stop.\n")

        try:
            self._stop_event.wait()
        except Exception:
            pass

    def _handle_signal(self, signum, frame):
        print("\n\n  Stopping MODSTAN...")
        self.stop()

    def stop(self):
        """Gracefully stop all device runners and the retention manager."""
        self.retention.stop()
        for runner in self.runners:
            runner.stop()
        self._stop_event.set()
        logger.info("MODSTAN stopped.")


# =============================================================================
# Entry Point
# =============================================================================

def parse_args():
    import argparse
    parser = argparse.ArgumentParser(
        prog='modstan',
        description='MODSTAN — Modbus TCP Data Logger',
    )
    parser.add_argument('--config',     '-c', help='Path to a specific .conf file')
    parser.add_argument('--config-dir', '-d', help='Path to a directory containing .conf files')
    parser.add_argument('--verbose',    '-v', action='store_true', help='Enable verbose (debug) logging')
    parser.add_argument('--version',          action='store_true', help='Print version and exit')
    return parser.parse_args()


def main():
    args = parse_args()

    if args.version:
        print(f"MODSTAN v{MODSTAN_VERSION}")
        print(f"© github.com/F4NTech")
        sys.exit(0)

    setup_logger(device_name='modstan', verbose=args.verbose)

    app = ModstanApp()
    app.load(config_file=args.config, config_dir=args.config_dir)
    app.start()


if __name__ == '__main__':
    main()
