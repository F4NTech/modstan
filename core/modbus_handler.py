# =============================================================================
# MODSTAN - Modbus Handler
# Manages a Modbus TCP connection with auto-reconnect and per-register scheduling
# =============================================================================

import time
import logging
import threading
import datetime
from pyModbusTCP.client import ModbusClient

from core.config_manager import DeviceConfig, RegisterConfig
from core.data_converter  import process_register

logger = logging.getLogger(__name__)


class ModbusHandler:
    """
    Manages a Modbus TCP connection to a single device.
    Supports auto-reconnect and independent polling interval per register.
    """

    def __init__(self, config: DeviceConfig, on_data=None):
        """
        Args:
            config  : DeviceConfig parsed from a .conf file
            on_data : Callback invoked whenever new data is available.
                      Signature: on_data(result: dict)
        """
        self.config   = config
        self.on_data  = on_data
        self._client  = ModbusClient(
            host      = config.modbus_host,
            port      = config.modbus_port,
            timeout   = config.modbus_timeout,
            auto_open = False,
        )
        self._running   = False
        self._connected = False
        self._thread    = None
        self._lock      = threading.Lock()

        # Track the last time each register was polled
        self._last_read: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------
    def _connect(self) -> bool:
        """Attempt to open a connection to the Modbus device."""
        try:
            result = self._client.open()
            if result:
                self._connected = True
                logger.info(
                    f"[{self.config.name}] Connected to "
                    f"{self.config.modbus_host}:{self.config.modbus_port}"
                )
            else:
                self._connected = False
                logger.warning(
                    f"[{self.config.name}] Failed to connect to "
                    f"{self.config.modbus_host}:{self.config.modbus_port}"
                )
            return result
        except Exception as e:
            self._connected = False
            logger.error(f"[{self.config.name}] Connection error: {e}")
            return False

    def _disconnect(self):
        """Close the Modbus connection."""
        try:
            self._client.close()
        except Exception:
            pass
        self._connected = False

    def _ensure_connected(self) -> bool:
        """
        Ensure the connection is active.
        If not, retry according to max_retries and retry_delay config values.
        """
        if self._client.is_open:
            return True

        self._connected = False
        attempt = 0
        max_r   = self.config.modbus_max_retries

        while self._running:
            attempt += 1
            logger.info(
                f"[{self.config.name}] Reconnect attempt #{attempt}"
                + (f" of {max_r}" if max_r > 0 else " (unlimited)")
            )
            if self._connect():
                return True

            if max_r > 0 and attempt >= max_r:
                logger.error(
                    f"[{self.config.name}] Gave up after {max_r} reconnect attempts."
                )
                return False

            # Wait before next attempt, checking _running every second
            for _ in range(self.config.modbus_retry_delay):
                if not self._running:
                    return False
                time.sleep(1)

        return False

    # ------------------------------------------------------------------
    # Register Reading
    # ------------------------------------------------------------------
    def _read_register(self, reg: RegisterConfig) -> dict | None:
        """
        Read a single register from the device.
        Returns a result dict or None on failure.
        """
        with self._lock:
            if not self._ensure_connected():
                return None

            start = time.time()
            try:
                if reg.function_code == 3:
                    raw = self._client.read_holding_registers(reg.address, reg.quantity)
                elif reg.function_code == 4:
                    raw = self._client.read_input_registers(reg.address, reg.quantity)
                else:
                    logger.error(
                        f"[{self.config.name}] Unsupported function code: {reg.function_code}"
                    )
                    return None
            except Exception as e:
                logger.error(
                    f"[{self.config.name}] Error reading register '{reg.name}': {e}"
                )
                self._connected = False
                return None

            ping_ms = (time.time() - start) * 1000

            if raw is None:
                logger.error(
                    f"[{self.config.name}] No response for register '{reg.name}' "
                    f"(addr={reg.address})"
                )
                return None

            try:
                result = process_register(raw, reg.data_type, reg.byte_format, reg.scale)
            except ValueError as e:
                logger.error(
                    f"[{self.config.name}] Conversion failed for '{reg.name}': {e}"
                )
                return None

            return {
                'device_name'   : self.config.name,
                'register_name' : reg.name,
                'timestamp'     : datetime.datetime.now(datetime.timezone.utc),
                'ping_ms'       : round(ping_ms, 3),
                'hex'           : result['hex'],
                'raw'           : result['raw'],
                'scaled'        : result['scaled'],
                'address'       : reg.address,
                'function_code' : reg.function_code,
                'data_type'     : reg.data_type,
                'byte_format'   : reg.byte_format,
                'scale'         : reg.scale,
            }

    # ------------------------------------------------------------------
    # Main Loop
    # ------------------------------------------------------------------
    def _run_loop(self):
        """Main polling loop running in a dedicated thread."""
        logger.info(f"[{self.config.name}] Polling thread started.")

        # Initial connection attempt
        self._connect()

        while self._running:
            now = time.time()

            for reg in self.config.registers:
                if not self._running:
                    break

                last = self._last_read.get(reg.name, 0)
                if now - last >= reg.interval:
                    self._last_read[reg.name] = now
                    result = self._read_register(reg)

                    if result and self.on_data:
                        try:
                            self.on_data(result)
                        except Exception as e:
                            logger.error(
                                f"[{self.config.name}] Error in on_data callback "
                                f"for '{reg.name}': {e}"
                            )

            time.sleep(0.1)  # Loop resolution: 100ms

        self._disconnect()
        logger.info(f"[{self.config.name}] Polling thread stopped.")

    # ------------------------------------------------------------------
    # Start / Stop
    # ------------------------------------------------------------------
    def start(self):
        """Start the Modbus polling thread."""
        if self._running:
            logger.warning(f"[{self.config.name}] Handler is already running.")
            return
        self._running = True
        self._thread  = threading.Thread(
            target=self._run_loop,
            name=f"modstan-{self.config.name}",
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        """Stop the Modbus polling thread."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)

    def is_running(self) -> bool:
        return self._running and (self._thread is not None) and self._thread.is_alive()

    def is_connected(self) -> bool:
        return self._client.is_open

    def get_status(self) -> dict:
        return {
            'device'    : self.config.name,
            'host'      : self.config.modbus_host,
            'port'      : self.config.modbus_port,
            'running'   : self.is_running(),
            'connected' : self.is_connected(),
            'registers' : len(self.config.registers),
        }
