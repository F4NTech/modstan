# =============================================================================
# MODSTAN - Logger Setup
# Configures file and console logging with daily rotation
# =============================================================================

import logging
import os
import sys
from logging.handlers import TimedRotatingFileHandler

LOG_DIR    = 'logs'
LOG_FORMAT = '%(asctime)s | %(levelname)-8s | %(name)-25s | %(message)s'
DATE_FMT   = '%Y-%m-%d %H:%M:%S'


def setup_logger(device_name: str = 'modstan', log_dir: str = LOG_DIR, verbose: bool = False):
    """
    Set up logging to both file and console.

    - Log file : logs/{device_name}.log, rotated daily, kept for 7 days
    - Console  : WARNING and above only (unless verbose mode is enabled)
    """
    os.makedirs(log_dir, exist_ok=True)

    log_level = logging.DEBUG if verbose else logging.INFO
    log_path  = os.path.join(log_dir, f"{device_name}.log")

    root = logging.getLogger()
    root.setLevel(log_level)

    # Avoid duplicate handlers on re-initialization
    if root.handlers:
        root.handlers.clear()

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FMT)

    # File handler — daily rotation, keep last 7 files
    fh = TimedRotatingFileHandler(
        log_path,
        when='midnight',
        backupCount=7,
        encoding='utf-8',
    )
    fh.setLevel(log_level)
    fh.setFormatter(formatter)
    root.addHandler(fh)

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.WARNING if not verbose else logging.DEBUG)
    ch.setFormatter(formatter)
    root.addHandler(ch)

    return root
