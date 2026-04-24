# =============================================================================
# MODSTAN - Config Manager
# Loads, validates, and provides access to device configuration (.conf files)
# =============================================================================

import configparser
import os
import logging

logger = logging.getLogger(__name__)

REQUIRED_SECTIONS  = ['DEVICE', 'MODBUS', 'REGISTERS']
VALID_DATA_TYPES   = {'uint16', 'int16', 'uint32', 'int32', 'uint64', 'int64', 'float32', 'float64'}
VALID_BYTE_FORMATS = {'ABCD', 'CDAB', 'BADC', 'DCBA', 'AB', 'BA'}
VALID_STORAGE_TYPES = {'postgres', 'mariadb', 'sqlite', 'csv'}
VALID_FUNC_CODES   = {3, 4}

DEFAULT_INTERVAL    = 1
DEFAULT_TIMEOUT     = 10
DEFAULT_RETRY_DELAY = 5
DEFAULT_MAX_RETRIES = 0
DEFAULT_PORT_MODBUS = 502
DEFAULT_TABLE       = 'register_logs'
DEFAULT_RETENTION   = 0


class ConfigError(Exception):
    """Raised when a configuration file contains invalid or missing values."""
    pass


class RegisterConfig:
    """Represents a single register entry from the [REGISTERS] section."""

    def __init__(self, name: str, function_code: int, address: int, quantity: int,
                 data_type: str, scale: float, byte_format: str, interval: int):
        self.name          = name
        self.function_code = function_code
        self.address       = address
        self.quantity      = quantity
        self.data_type     = data_type
        self.scale         = scale
        self.byte_format   = byte_format
        self.interval      = interval

    def __repr__(self):
        return (
            f"RegisterConfig(name={self.name}, fc={self.function_code}, "
            f"addr={self.address}, type={self.data_type}, interval={self.interval}s)"
        )


class DeviceConfig:
    """Full configuration for a single device loaded from a .conf file."""

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.file_name = os.path.basename(file_path)
        self._raw      = configparser.ConfigParser()
        self._raw.read(file_path)
        self._validate()
        self._parse()

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    def _validate(self):
        for section in REQUIRED_SECTIONS:
            if not self._raw.has_section(section):
                raise ConfigError(
                    f"[{self.file_name}] Required section [{section}] is missing."
                )

        if not self._raw.get('DEVICE', 'name', fallback='').strip():
            raise ConfigError(f"[{self.file_name}] DEVICE.name must not be empty.")

        if not self._raw.get('MODBUS', 'host', fallback='').strip():
            raise ConfigError(f"[{self.file_name}] MODBUS.host must not be empty.")

        if not self._raw.items('REGISTERS'):
            raise ConfigError(f"[{self.file_name}] Section [REGISTERS] must not be empty.")

        # Validate storage section only if enabled
        if self._raw.get('STORAGE', 'enabled', fallback='false').strip().lower() == 'true':
            storage_type = self._raw.get('STORAGE', 'type', fallback='').strip().lower()
            if storage_type not in VALID_STORAGE_TYPES:
                raise ConfigError(
                    f"[{self.file_name}] STORAGE.type '{storage_type}' is not valid. "
                    f"Options: {', '.join(VALID_STORAGE_TYPES)}"
                )
            if storage_type not in ('sqlite', 'csv'):
                for key in ['host', 'database', 'username', 'password']:
                    if not self._raw.get('STORAGE', key, fallback='').strip():
                        raise ConfigError(
                            f"[{self.file_name}] STORAGE.{key} is required "
                            f"for storage type '{storage_type}'."
                        )

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------
    def _parse(self):
        d = self._raw

        # [DEVICE]
        self.name     = d.get('DEVICE', 'name').strip()
        self.interval = int(d.get('DEVICE', 'interval', fallback=str(DEFAULT_INTERVAL)))

        # [MODBUS]
        self.modbus_host        = d.get('MODBUS', 'host').strip()
        self.modbus_port        = int(d.get('MODBUS', 'port',        fallback=str(DEFAULT_PORT_MODBUS)))
        self.modbus_timeout     = int(d.get('MODBUS', 'timeout',     fallback=str(DEFAULT_TIMEOUT)))
        self.modbus_max_retries = int(d.get('MODBUS', 'max_retries', fallback=str(DEFAULT_MAX_RETRIES)))
        self.modbus_retry_delay = int(d.get('MODBUS', 'retry_delay', fallback=str(DEFAULT_RETRY_DELAY)))

        # [STORAGE]
        self.storage_enabled  = d.get('STORAGE', 'enabled',  fallback='false').strip().lower() == 'true'
        self.storage_type     = d.get('STORAGE', 'type',     fallback='sqlite').strip().lower()
        self.storage_host     = d.get('STORAGE', 'host',     fallback='localhost').strip()
        self.storage_port     = int(d.get('STORAGE', 'port', fallback='5432'))
        self.storage_database = d.get('STORAGE', 'database', fallback='modstan.db').strip()
        self.storage_username = d.get('STORAGE', 'username', fallback='').strip()
        self.storage_password = d.get('STORAGE', 'password', fallback='').strip()
        self.storage_table    = d.get('STORAGE', 'table',    fallback=DEFAULT_TABLE).strip()
        self.storage_retention = int(d.get('STORAGE', 'retention', fallback=str(DEFAULT_RETENTION)))

        # [OWNER]
        self.customer_id = d.get('OWNER', 'customer_id', fallback='').strip()
        self.tag_host    = d.get('OWNER', 'tag_host',    fallback='').strip()
        self.tag_name    = d.get('OWNER', 'tag_name',    fallback='').strip()

        # [REGISTERS]
        self.registers = self._parse_registers()

    def _parse_registers(self) -> list[RegisterConfig]:
        registers = []
        for reg_name, reg_value in self._raw.items('REGISTERS'):
            parts = [p.strip() for p in reg_value.split(',')]
            if len(parts) < 6:
                raise ConfigError(
                    f"[{self.file_name}] Register '{reg_name}' has invalid format. "
                    f"Expected: function_code, address, quantity, data_type, scale, byte_format"
                )

            function_code = int(parts[0])
            address       = int(parts[1])
            quantity      = int(parts[2])
            data_type     = parts[3].lower()
            scale         = float(parts[4])
            byte_format   = parts[5].upper()
            interval      = int(parts[6]) if len(parts) > 6 and parts[6] else self.interval

            if function_code not in VALID_FUNC_CODES:
                raise ConfigError(
                    f"[{self.file_name}] Register '{reg_name}': "
                    f"function_code {function_code} is not valid. Use 3 or 4."
                )
            if data_type not in VALID_DATA_TYPES:
                raise ConfigError(
                    f"[{self.file_name}] Register '{reg_name}': "
                    f"data_type '{data_type}' is not valid."
                )
            if byte_format not in VALID_BYTE_FORMATS:
                raise ConfigError(
                    f"[{self.file_name}] Register '{reg_name}': "
                    f"byte_format '{byte_format}' is not valid."
                )
            if interval < 1:
                raise ConfigError(
                    f"[{self.file_name}] Register '{reg_name}': "
                    f"interval must be at least 1 second."
                )

            registers.append(RegisterConfig(
                name=reg_name,
                function_code=function_code,
                address=address,
                quantity=quantity,
                data_type=data_type,
                scale=scale,
                byte_format=byte_format,
                interval=interval,
            ))

        return registers

    def get_register_names(self) -> list[str]:
        return [r.name for r in self.registers]

    def __repr__(self):
        return (
            f"DeviceConfig(name={self.name}, "
            f"host={self.modbus_host}, registers={len(self.registers)})"
        )


def load_config(file_path: str) -> DeviceConfig:
    """Load a single device configuration file."""
    if not os.path.exists(file_path):
        raise ConfigError(f"Configuration file not found: {file_path}")
    return DeviceConfig(file_path)


def load_all_configs(config_dir: str) -> list[DeviceConfig]:
    """Load all .conf files from a directory, skipping example.conf."""
    if not os.path.isdir(config_dir):
        raise ConfigError(f"Configuration directory not found: {config_dir}")

    configs = []
    for fname in sorted(os.listdir(config_dir)):
        if fname.endswith('.conf') and fname != 'example.conf':
            fpath = os.path.join(config_dir, fname)
            try:
                cfg = DeviceConfig(fpath)
                configs.append(cfg)
                logger.info(f"Config loaded: {fname} → device={cfg.name}")
            except ConfigError as e:
                logger.error(f"Failed to load config {fname}: {e}")

    return configs
