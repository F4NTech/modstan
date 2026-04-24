# =============================================================================
# MODSTAN - MariaDB / MySQL Storage Adapter
# Compatible with all MariaDB versions; supports auto-reconnect
# =============================================================================

import logging
import datetime

logger = logging.getLogger(__name__)

try:
    import mysql.connector
    from mysql.connector import Error as MySQLError
    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False

from core.storage.base import BaseStorage


class MariaDBStorage(BaseStorage):

    def __init__(self, config):
        super().__init__(config)
        self._conn = None
        if not MYSQL_AVAILABLE:
            raise ImportError(
                "Package 'mysql-connector-python' is not installed. "
                "Run: pip install mysql-connector-python"
            )

    # ------------------------------------------------------------------
    # Connection & Auto-Reconnect
    # ------------------------------------------------------------------
    def connect(self) -> bool:
        try:
            self._conn = mysql.connector.connect(
                host               = self.config.storage_host,
                port               = self.config.storage_port,
                database           = self.config.storage_database,
                user               = self.config.storage_username,
                password           = self.config.storage_password,
                connection_timeout = 10,
                autocommit         = False,
            )
            logger.info(
                f"[MariaDB] Connected to {self.config.storage_host}:"
                f"{self.config.storage_port}/{self.config.storage_database}"
            )
            return True
        except Exception as e:
            logger.error(f"[MariaDB] Connection failed: {e}")
            return False

    def _ensure_connected(self) -> bool:
        """Automatically reconnect if the database connection has been lost."""
        try:
            if self._conn and self._conn.is_connected():
                return True
        except Exception:
            pass
        logger.warning("[MariaDB] Connection lost, attempting to reconnect...")
        return self.connect()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------
    def _index_exists(self, cur, table: str, index_name: str) -> bool:
        """
        Check whether an index exists.
        Uses information_schema for full compatibility across MariaDB versions.
        """
        cur.execute(
            "SELECT COUNT(*) FROM information_schema.statistics "
            "WHERE table_schema = DATABASE() "
            "AND table_name = %s AND index_name = %s",
            (table, index_name)
        )
        return cur.fetchone()[0] > 0

    def ensure_schema(self, register_names: list[str]) -> bool:
        """Create the table if it does not exist, and add any new register columns."""
        if not self._ensure_connected():
            return False

        table = self.config.storage_table
        try:
            cur = self._conn.cursor()

            # Create base table
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS `{table}` (
                    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
                    timestamp   DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
                    device_name VARCHAR(100) NOT NULL,
                    ping_ms     DOUBLE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)

            # Get existing columns
            cur.execute(f"SHOW COLUMNS FROM `{table}`")
            existing = {row[0] for row in cur.fetchall()}

            # Add missing register columns
            for reg_name in register_names:
                if reg_name not in existing:
                    cur.execute(
                        f"ALTER TABLE `{table}` ADD COLUMN `{reg_name}` DOUBLE NULL;"
                    )
                    logger.info(f"[MariaDB] New column added: {reg_name}")

            # Create indexes only if they don't already exist
            idx_ts = f"idx_{table}_timestamp"
            if not self._index_exists(cur, table, idx_ts):
                cur.execute(f"CREATE INDEX `{idx_ts}` ON `{table}` (timestamp);")

            idx_dev = f"idx_{table}_device"
            if not self._index_exists(cur, table, idx_dev):
                cur.execute(
                    f"CREATE INDEX `{idx_dev}` ON `{table}` (device_name, timestamp);"
                )

            self._conn.commit()
            cur.close()
            return True

        except Exception as e:
            try:
                self._conn.rollback()
            except Exception:
                pass
            logger.error(f"[MariaDB] Schema setup failed: {e}")
            return False

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------
    def save(self, data: dict) -> bool:
        if not self._ensure_connected():
            logger.error("[MariaDB] Cannot save data: connection unavailable.")
            return False

        table = self.config.storage_table
        try:
            fixed = {
                'device_name': data.get('device_name'),
                'timestamp'  : data.get('timestamp', datetime.datetime.now()),
                'ping_ms'    : data.get('ping_ms'),
            }
            dynamic  = {
                k: v for k, v in data.items()
                if k not in ('device_name', 'timestamp', 'ping_ms')
            }
            all_data     = {**fixed, **dynamic}
            columns      = ', '.join(f'`{k}`' for k in all_data.keys())
            placeholders = ', '.join(['%s'] * len(all_data))
            values       = list(all_data.values())

            cur = self._conn.cursor()
            cur.execute(
                f'INSERT INTO `{table}` ({columns}) VALUES ({placeholders})',
                values
            )
            self._conn.commit()
            cur.close()
            return True

        except Exception as e:
            try:
                self._conn.rollback()
            except Exception:
                pass
            logger.error(f"[MariaDB] Failed to save data: {e}")
            self._conn = None
            return False

    # ------------------------------------------------------------------
    # Retention
    # ------------------------------------------------------------------
    def delete_old_records(self, retention_days: int) -> int:
        if retention_days <= 0:
            return 0
        if not self._ensure_connected():
            return 0

        table = self.config.storage_table
        try:
            cur = self._conn.cursor()
            cur.execute(
                f"DELETE FROM `{table}` WHERE timestamp < NOW() - INTERVAL %s DAY",
                (retention_days,)
            )
            deleted = cur.rowcount
            self._conn.commit()
            cur.close()
            if deleted > 0:
                logger.info(
                    f"[MariaDB] Retention: {deleted} record(s) deleted "
                    f"(older than {retention_days} day(s))."
                )
            return deleted
        except Exception as e:
            try:
                self._conn.rollback()
            except Exception:
                pass
            logger.error(f"[MariaDB] Failed to delete old records: {e}")
            return 0

    # ------------------------------------------------------------------
    # Test & Close
    # ------------------------------------------------------------------
    def test_connection(self) -> tuple[bool, str]:
        try:
            conn = mysql.connector.connect(
                host               = self.config.storage_host,
                port               = self.config.storage_port,
                database           = self.config.storage_database,
                user               = self.config.storage_username,
                password           = self.config.storage_password,
                connection_timeout = 5,
            )
            conn.close()
            return (
                True,
                f"OK - {self.config.storage_host}:"
                f"{self.config.storage_port}/{self.config.storage_database}"
            )
        except Exception as e:
            return False, str(e)

    def close(self):
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
        self._conn = None
