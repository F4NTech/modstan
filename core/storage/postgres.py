# =============================================================================
# MODSTAN - PostgreSQL Storage Adapter
# Supports auto-reconnect when the database connection is lost
# =============================================================================

import logging
import datetime

logger = logging.getLogger(__name__)

try:
    import psycopg2
    import psycopg2.extras
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False

from core.storage.base import BaseStorage


class PostgresStorage(BaseStorage):

    def __init__(self, config):
        super().__init__(config)
        self._conn = None
        if not PSYCOPG2_AVAILABLE:
            raise ImportError(
                "Package 'psycopg2-binary' is not installed. "
                "Run: pip install psycopg2-binary"
            )

    # ------------------------------------------------------------------
    # Connection & Auto-Reconnect
    # ------------------------------------------------------------------
    def connect(self) -> bool:
        try:
            self._conn = psycopg2.connect(
                host            = self.config.storage_host,
                port            = self.config.storage_port,
                dbname          = self.config.storage_database,
                user            = self.config.storage_username,
                password        = self.config.storage_password,
                connect_timeout = 10,
            )
            self._conn.autocommit = False
            logger.info(
                f"[PostgreSQL] Connected to {self.config.storage_host}:"
                f"{self.config.storage_port}/{self.config.storage_database}"
            )
            return True
        except Exception as e:
            logger.error(f"[PostgreSQL] Connection failed: {e}")
            return False

    def _ensure_connected(self) -> bool:
        """Automatically reconnect if the database connection has been lost."""
        try:
            if self._conn and self._conn.closed == 0:
                cur = self._conn.cursor()
                cur.execute("SELECT 1")
                cur.close()
                return True
        except Exception:
            pass
        logger.warning("[PostgreSQL] Connection lost, attempting to reconnect...")
        return self.connect()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------
    def ensure_schema(self, register_names: list[str]) -> bool:
        """Create the table if it does not exist, and add any new register columns."""
        if not self._ensure_connected():
            return False

        table = self.config.storage_table
        try:
            with self._conn.cursor() as cur:
                # Create base table
                cur.execute(f"""
                    CREATE TABLE IF NOT EXISTS {table} (
                        id          BIGSERIAL PRIMARY KEY,
                        timestamp   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        device_name VARCHAR(100) NOT NULL,
                        ping_ms     FLOAT
                    );
                """)

                # Get existing columns
                cur.execute("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_name = %s
                """, (table,))
                existing = {row[0] for row in cur.fetchall()}

                # Add missing register columns
                for reg_name in register_names:
                    if reg_name not in existing:
                        cur.execute(
                            f'ALTER TABLE {table} '
                            f'ADD COLUMN IF NOT EXISTS "{reg_name}" FLOAT;'
                        )
                        logger.info(f"[PostgreSQL] New column added: {reg_name}")

                # Create indexes (IF NOT EXISTS supported since PostgreSQL 9.5)
                cur.execute(f"""
                    CREATE INDEX IF NOT EXISTS idx_{table}_timestamp
                    ON {table} (timestamp DESC);
                """)
                cur.execute(f"""
                    CREATE INDEX IF NOT EXISTS idx_{table}_device
                    ON {table} (device_name, timestamp DESC);
                """)

                self._conn.commit()
                return True

        except Exception as e:
            try:
                self._conn.rollback()
            except Exception:
                pass
            logger.error(f"[PostgreSQL] Schema setup failed: {e}")
            return False

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------
    def save(self, data: dict) -> bool:
        """
        Insert one row into the register_logs table.
        All register values are stored as FLOAT columns.
        """
        if not self._ensure_connected():
            logger.error("[PostgreSQL] Cannot save data: connection unavailable.")
            return False

        table = self.config.storage_table
        try:
            fixed = {
                'device_name': data.get('device_name'),
                'timestamp'  : data.get('timestamp', datetime.datetime.now(datetime.timezone.utc)),
                'ping_ms'    : data.get('ping_ms'),
            }
            dynamic = {
                k: v for k, v in data.items()
                if k not in ('device_name', 'timestamp', 'ping_ms')
            }
            all_data     = {**fixed, **dynamic}
            columns      = ', '.join(f'"{k}"' for k in all_data.keys())
            placeholders = ', '.join(['%s'] * len(all_data))
            values       = list(all_data.values())

            with self._conn.cursor() as cur:
                cur.execute(
                    f'INSERT INTO {table} ({columns}) VALUES ({placeholders})',
                    values
                )
            self._conn.commit()
            return True

        except Exception as e:
            try:
                self._conn.rollback()
            except Exception:
                pass
            logger.error(f"[PostgreSQL] Failed to save data: {e}")
            try:
                self._conn.close()
            except Exception:
                pass
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
            with self._conn.cursor() as cur:
                cur.execute(
                    f"DELETE FROM {table} WHERE timestamp < NOW() - INTERVAL %s",
                    (f"{retention_days} days",)
                )
                deleted = cur.rowcount
            self._conn.commit()
            if deleted > 0:
                logger.info(
                    f"[PostgreSQL] Retention: {deleted} record(s) deleted "
                    f"(older than {retention_days} day(s))."
                )
            return deleted
        except Exception as e:
            try:
                self._conn.rollback()
            except Exception:
                pass
            logger.error(f"[PostgreSQL] Failed to delete old records: {e}")
            return 0

    # ------------------------------------------------------------------
    # Test & Close
    # ------------------------------------------------------------------
    def test_connection(self) -> tuple[bool, str]:
        try:
            conn = psycopg2.connect(
                host            = self.config.storage_host,
                port            = self.config.storage_port,
                dbname          = self.config.storage_database,
                user            = self.config.storage_username,
                password        = self.config.storage_password,
                connect_timeout = 5,
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
