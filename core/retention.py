# =============================================================================
# MODSTAN - Retention Manager
# Periodically deletes records older than the configured retention period
# =============================================================================

import threading
import time
import logging
import datetime

logger = logging.getLogger(__name__)

RETENTION_CHECK_INTERVAL = 86400  # Run once every 24 hours


class RetentionManager:
    """
    Runs scheduled data cleanup in a background thread.
    Registered storage adapters are cleaned up based on their retention_days setting.
    """

    def __init__(self):
        self._tasks  : list[dict] = []  # [{storage, retention_days, device_name}]
        self._thread  = None
        self._running = False

    def register(self, storage, retention_days: int, device_name: str):
        """Register a storage adapter with its retention policy."""
        if retention_days <= 0:
            logger.info(
                f"[Retention] Device '{device_name}': retention=0, data kept forever."
            )
            return
        self._tasks.append({
            'storage'        : storage,
            'retention_days' : retention_days,
            'device_name'    : device_name,
        })
        logger.info(
            f"[Retention] Device '{device_name}': "
            f"data retained for {retention_days} day(s)."
        )

    def _run_all(self):
        """Execute retention cleanup for all registered tasks."""
        for task in self._tasks:
            try:
                deleted = task['storage'].delete_old_records(task['retention_days'])
                if deleted > 0:
                    logger.info(
                        f"[Retention] '{task['device_name']}': "
                        f"{deleted} record(s) deleted "
                        f"(older than {task['retention_days']} day(s))."
                    )
            except Exception as e:
                logger.error(
                    f"[Retention] Error for '{task['device_name']}': {e}"
                )

    def _loop(self):
        logger.info("[Retention] Background thread started.")

        # Run immediately on startup
        self._run_all()

        while self._running:
            # Wait 24 hours with 1-second resolution so the thread can be stopped cleanly
            for _ in range(RETENTION_CHECK_INTERVAL):
                if not self._running:
                    break
                time.sleep(1)

            if self._running:
                logger.info(
                    f"[Retention] Running scheduled cleanup... "
                    f"({datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')})"
                )
                self._run_all()

        logger.info("[Retention] Background thread stopped.")

    def run_now(self):
        """Trigger a manual retention cleanup immediately."""
        logger.info("[Retention] Manual cleanup triggered.")
        self._run_all()

    def start(self):
        if not self._tasks:
            return
        self._running = True
        self._thread  = threading.Thread(
            target=self._loop,
            name="modstan-retention",
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
