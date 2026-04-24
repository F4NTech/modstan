# =============================================================================
# MODSTAN - CSV Storage Adapter
# Appends readings to a per-device CSV file
# =============================================================================

import csv
import logging
import datetime
import os
import threading

logger = logging.getLogger(__name__)

from core.storage.base import BaseStorage


class CSVStorage(BaseStorage):
    """
    Writes data to CSV files, one file per device.
    Output path: {csv_dir}/{device_name}.csv

    The 'database' field in [STORAGE] is used as the output directory path.
    """

    def __init__(self, config):
        super().__init__(config)
        self._lock    = threading.Lock()
        # Use the 'database' config field as the output directory
        self._csv_dir = config.storage_database if config.storage_database else 'exports'

    def connect(self) -> bool:
        try:
            os.makedirs(self._csv_dir, exist_ok=True)
            logger.info(f"[CSV] Output directory: {self._csv_dir}")
            return True
        except Exception as e:
            logger.error(f"[CSV] Failed to create output directory: {e}")
            return False

    def _get_csv_path(self, device_name: str) -> str:
        return os.path.join(self._csv_dir, f"{device_name}.csv")

    def ensure_schema(self, register_names: list[str]) -> bool:
        # CSV schema is created automatically on first write
        return True

    def save(self, data: dict) -> bool:
        device_name = data.get('device_name', 'unknown')
        csv_path    = self._get_csv_path(device_name)

        row = {
            'timestamp'  : data.get('timestamp', datetime.datetime.now()).isoformat(),
            'device_name': device_name,
            'ping_ms'    : data.get('ping_ms', ''),
        }
        row.update({
            k: v for k, v in data.items()
            if k not in ('timestamp', 'device_name', 'ping_ms')
        })

        with self._lock:
            file_exists = os.path.exists(csv_path)
            try:
                with open(csv_path, 'a', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=row.keys())
                    if not file_exists:
                        writer.writeheader()
                    writer.writerow(row)
                return True
            except Exception as e:
                logger.error(f"[CSV] Failed to write to {csv_path}: {e}")
                return False

    def delete_old_records(self, retention_days: int) -> int:
        # Row-level deletion is not efficiently supported for CSV files.
        if retention_days <= 0:
            return 0
        logger.info("[CSV] Automatic retention is not supported for CSV adapter.")
        return 0

    def test_connection(self) -> tuple[bool, str]:
        try:
            os.makedirs(self._csv_dir, exist_ok=True)
            return True, f"OK - {self._csv_dir}"
        except Exception as e:
            return False, str(e)

    def close(self):
        pass  # No persistent connection to close
