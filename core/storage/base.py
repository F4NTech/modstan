# =============================================================================
# MODSTAN - Base Storage
# Abstract interface that all storage adapters must implement
# =============================================================================

from abc import ABC, abstractmethod
import logging

logger = logging.getLogger(__name__)


class BaseStorage(ABC):
    """
    Contract that every storage adapter must fulfill.
    New adapters should inherit from this class and implement all abstract methods.
    """

    def __init__(self, config):
        self.config = config

    @abstractmethod
    def connect(self) -> bool:
        """Open a connection to the storage backend. Returns True on success."""
        ...

    @abstractmethod
    def ensure_schema(self, register_names: list[str]) -> bool:
        """
        Ensure the table and all required columns exist.
        Creates the table if missing; adds new columns (ALTER TABLE) as needed.

        Args:
            register_names: List of register names from all active config files.
        """
        ...

    @abstractmethod
    def save(self, data: dict) -> bool:
        """
        Persist one row of register readings.

        The data dict contains:
            device_name : str
            timestamp   : datetime
            ping_ms     : float
            <register>  : float  (one key per register in the flush batch)

        Returns True on success.
        """
        ...

    @abstractmethod
    def delete_old_records(self, retention_days: int) -> int:
        """
        Delete records older than retention_days days.
        Returns the number of records deleted.
        """
        ...

    @abstractmethod
    def close(self):
        """Close the connection to the storage backend."""
        ...

    @abstractmethod
    def test_connection(self) -> tuple[bool, str]:
        """
        Test connectivity without writing any data.
        Returns (success: bool, message: str).
        """
        ...
