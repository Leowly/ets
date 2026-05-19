import json
import os
from typing import Any, Dict, List, Optional, Tuple

from .base import FileReader


class LocalFileReader(FileReader):
    """File reader that accesses data directly from the local filesystem."""

    def __init__(self, base_path: str):
        self.base_path = base_path.rstrip("/\\")

    def exists(self, path: str) -> bool:
        return os.path.exists(os.path.join(self.base_path, path))

    def read_file(self, path: str) -> Optional[str]:
        full = os.path.join(self.base_path, path)
        try:
            with open(full, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return None

    def list_details(self, path: str = "") -> List[Dict[str, Any]]:
        full = os.path.join(self.base_path, path)
        items = []
        try:
            for name in os.listdir(full):
                p = os.path.join(full, name)
                items.append({
                    "name": name,
                    "is_directory": os.path.isdir(p),
                })
        except OSError:
            pass
        return items

    def stat_mtime(self, path: str) -> float:
        full = os.path.join(self.base_path, path)
        try:
            return os.path.getmtime(full)
        except OSError:
            return 0.0

    def get_base_path(self) -> str:
        return self.base_path

    def discover_raw_entries(self) -> List[Tuple]:
        """Scan local data directory and return raw exam entries."""
        entries = []
        for name in os.listdir(self.base_path):
            d = os.path.join(self.base_path, name)
            if not os.path.isdir(d):
                continue

            c2 = os.path.join(d, "content2.json")
            c1 = os.path.join(d, "content.json")
            if not os.path.exists(c2) and not os.path.exists(c1):
                continue

            try:
                content_path = c2 if os.path.exists(c2) else c1
                with open(content_path, "r", encoding="utf-8") as f:
                    content = json.load(f)
                with open(os.path.join(d, "info.json"), "r", encoding="utf-8") as f:
                    info = json.load(f)
                stid = content["info"].get("stid", "0")
                mtime = os.path.getmtime(d)
                entries.append((stid, name, content, info, mtime))
            except Exception:
                continue

        return entries
