# =============================================================================
# MODSTAN - SQLite Storage Adapter
# Local file-based storage; supports auto-reconnect and CSV export
# =============================================================================

import sqlite3
import logging
import datetime
import os

logger = logging.getLogger(__name__)

from core.storage.base import BaseStorage


class SQLiteStorage(BaseStorage):

    def __init__(self, config):
        super().__init__(config)
        self._conn    = None
        # The 'database' config field is used as the SQLite file path
        self._db_path = config.storage_database if config.storage_database else 'modstan.db'

    # ------------------------------------------------------------------
    # Connection & Auto-Reconnect
    # ------------------------------------------------------------------
    def connect(self) -> bool:
        try:
            db_dir = os.path.dirname(self._db_path)
            if db_dir:
                os.makedirs(db_dir, exist_ok=True)
            self._conn = sqlite3.connect(
                self._db_path,
                check_same_thread=False,
            )
            self._conn.row_factory = sqlite3.Row
            logger.info(f"[SQLite] Connected to {self._db_path}")
            return True
        except Exception as e:
            logger.error(f"[SQLite] Connection failed: {e}")
            return False

    def _ensure_connected(self) -> bool:
        """Automatically reconnect if the database connection is invalid."""
        try:
            if self._conn:
                self._conn.execute("SELECT 1")
                return True
        except Exception:
            pass
        logger.warning("[SQLite] Connection invalid, attempting to reconnect...")
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
            cur = self._conn.cursor()
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS "{table}" (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp   TEXT NOT NULL DEFAULT (datetime('now')),
                    device_name TEXT NOT NULL,
                    ping_ms     REAL
                );
            """)
            cur.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{table}_timestamp
                ON "{table}" (timestamp);
            """)
            cur.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{table}_device
                ON "{table}" (device_name, timestamp);
            """)

            # Get existing columns
            cur.execute(f'PRAGMA table_info("{table}")')
            existing = {row[1] for row in cur.fetchall()}

            # Add missing register columns
            for reg_name in register_names:
                if reg_name not in existing:
                    cur.execute(
                        f'ALTER TABLE "{table}" ADD COLUMN "{reg_name}" REAL;'
                    )
                    logger.info(f"[SQLite] New column added: {reg_name}")

            self._conn.commit()
            return True
        except Exception as e:
            try:
                self._conn.rollback()
            except Exception:
                pass
            logger.error(f"[SQLite] Schema setup failed: {e}")
            return False

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------
    def save(self, data: dict) -> bool:
        if not self._ensure_connected():
            logger.error("[SQLite] Cannot save data: connection unavailable.")
            return False

        table = self.config.storage_table
        try:
            ts = data.get('timestamp', datetime.datetime.now())
            if hasattr(ts, 'isoformat'):
                ts = ts.isoformat()

            fixed = {
                'device_name': data.get('device_name'),
                'timestamp'  : ts,
                'ping_ms'    : data.get('ping_ms'),
            }
            dynamic  = {
                k: v for k, v in data.items()
                if k not in ('device_name', 'timestamp', 'ping_ms')
            }
            all_data     = {**fixed, **dynamic}
            columns      = ', '.join(f'"{k}"' for k in all_data.keys())
            placeholders = ', '.join(['?'] * len(all_data))
            values       = list(all_data.values())

            cur = self._conn.cursor()
            cur.execute(
                f'INSERT INTO "{table}" ({columns}) VALUES ({placeholders})',
                values
            )
            self._conn.commit()
            return True
        except Exception as e:
            try:
                self._conn.rollback()
            except Exception:
                pass
            logger.error(f"[SQLite] Failed to save data: {e}")
            self._conn = None
            return False

    # ------------------------------------------------------------------
    # Export helper
    # ------------------------------------------------------------------
    def get_rows(self, device_name: str,
                 from_date: str = None,
                 to_date: str   = None) -> tuple[list, list]:
        """
        Return all rows for a given device as (headers, rows).
        Used by the CLI export command.
        """
        if not self._ensure_connected():
            return [], []

        table  = self.config.storage_table
        wheres = ["device_name = ?"]
        params = [device_name]

        if from_date:
            wheres.append("timestamp >= ?")
            params.append(from_date)
        if to_date:
            wheres.append("timestamp <= ?")
            params.append(to_date)

        where = ' AND '.join(wheres)
        cur   = self._conn.cursor()
        cur.execute(
            f'SELECT * FROM "{table}" WHERE {where} ORDER BY timestamp',
            params
        )
        rows    = cur.fetchall()
        headers = [desc[0] for desc in cur.description]
        cur.close()
        return headers, [list(r) for r in rows]

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
                f"""DELETE FROM "{table}" WHERE timestamp < datetime('now', ?)""",
                (f"-{retention_days} days",)
            )
            deleted = cur.rowcount
            self._conn.commit()
            if deleted > 0:
                logger.info(
                    f"[SQLite] Retention: {deleted} record(s) deleted "
                    f"(older than {retention_days} day(s))."
                )
            return deleted
        except Exception as e:
            try:
                self._conn.rollback()
            except Exception:
                pass
            logger.error(f"[SQLite] Failed to delete old records: {e}")
            return 0

    # ------------------------------------------------------------------
    # Test & Close
    # ------------------------------------------------------------------
    def test_connection(self) -> tuple[bool, str]:
        try:
            conn = sqlite3.connect(self._db_path)
            conn.close()
            return True, f"OK - {self._db_path}"
        except Exception as e:
            return False, str(e)

    def close(self):
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
        self._conn = None
