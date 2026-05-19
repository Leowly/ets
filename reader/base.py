from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple


class FileReader(ABC):
    """Abstract base for reading ETS exam data from different platforms."""

    @abstractmethod
    def exists(self, path: str) -> bool:
        ...

    @abstractmethod
    def read_file(self, path: str) -> Optional[str]:
        ...

    @abstractmethod
    def list_details(self, path: str = "") -> List[Dict[str, Any]]:
        ...

    @abstractmethod
    def stat_mtime(self, path: str) -> float:
        ...

    @abstractmethod
    def get_base_path(self) -> str:
        ...

    @abstractmethod
    def discover_raw_entries(self) -> List[Tuple]:
        """Scan data directory and return [(stid, folder, content, info, mtime), ...]."""
        ...
