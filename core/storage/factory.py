# =============================================================================
# MODSTAN - Storage Factory
# Selects and returns the appropriate storage adapter based on configuration
# =============================================================================

import logging
from core.storage.base import BaseStorage

logger = logging.getLogger(__name__)


def get_storage(config) -> BaseStorage:
    """
    Factory function — return a connected storage adapter instance based on config.

    Args:
        config: DeviceConfig with parsed storage settings.

    Returns:
        A connected BaseStorage instance.

    Raises:
        ValueError  : If the storage type is not recognized.
        ImportError : If the required database driver is not installed.
        RuntimeError: If the connection attempt fails.
    """
    storage_type = config.storage_type.lower()

    match storage_type:
        case 'postgres':
            from core.storage.postgres import PostgresStorage
            adapter = PostgresStorage(config)

        case 'mariadb' | 'mysql':
            from core.storage.mariadb import MariaDBStorage
            adapter = MariaDBStorage(config)

        case 'sqlite':
            from core.storage.sqlite import SQLiteStorage
            adapter = SQLiteStorage(config)

        case 'csv':
            from core.storage.csv_adapter import CSVStorage
            adapter = CSVStorage(config)

        case _:
            raise ValueError(
                f"Unknown storage type '{storage_type}'. "
                f"Valid options: postgres, mariadb, sqlite, csv"
            )

    if not adapter.connect():
        raise RuntimeError(
            f"Failed to connect to '{storage_type}' storage "
            f"for device '{config.name}'"
        )

    logger.info(
        f"[Storage] '{storage_type}' adapter ready for device '{config.name}'"
    )
    return adapter
