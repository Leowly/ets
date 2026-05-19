import json
import os
import posixpath
import queue
import shlex
import subprocess
import threading
import time
from collections import defaultdict
from typing import Dict, List, Optional

from .base import FileReader


class PersistentRish:
    def __init__(self):
        self._start_proc()

    def _start_proc(self):
        self.proc = subprocess.Popen(
            ["rish"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self.queue = queue.Queue()
        self.reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self.reader_thread.start()

    def _reader_loop(self):
        while True:
            line = self.proc.stdout.readline()
            if not line:
                break
            self.queue.put(line)

    def _drain_queue(self):
        while True:
            try:
                self.queue.get_nowait()
            except queue.Empty:
                break

    def _ensure_alive(self):
        if self.proc.poll() is not None:
            self._drain_queue()
            try:
                self.proc.terminate()
            except Exception:
                pass
            self._start_proc()

    def run(self, command: str, timeout: float = 30.0) -> str:
        self._ensure_alive()
        self._drain_queue()

        marker = f"__RISH_END_{os.urandom(8).hex()}__"
        full_command = f"{command}\necho '{marker}'\n"

        try:
            self.proc.stdin.write(full_command)
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError):
            self._start_proc()
            self.proc.stdin.write(full_command)
            self.proc.stdin.flush()

        lines = []
        start = time.time()
        while True:
            if time.time() - start > timeout:
                self._drain_queue()
                break
            try:
                line = self.queue.get(timeout=0.1)
                stripped = line.strip()
                if stripped in ("$", "#", ""):
                    continue
                if marker in stripped:
                    cleaned = stripped.replace(marker, "").strip()
                    if cleaned:
                        lines.append(cleaned)
                    break
                lines.append(line)
            except queue.Empty:
                pass
        return "".join(lines).strip()

    def close(self):
        try:
            self.proc.terminate()
        except Exception:
            pass


class RishFileReader(FileReader):
    """File reader that accesses Android data via Shizuku rish shell."""

    def __init__(self, shell: PersistentRish, base_path: str):
        self.shell = shell
        self.base_path = base_path.rstrip("/")

    def _full_path(self, path: str = "") -> str:
        if not path:
            return self.base_path
        return f"{self.base_path}/{path}".replace("//", "/")

    def _quote(self, path: str) -> str:
        return shlex.quote(path)

    def exists(self, path: str) -> bool:
        full = self._quote(self._full_path(path))
        return self.shell.run(f"test -e {full} && echo ok").strip() == "ok"

    def read_file(self, path: str) -> Optional[str]:
        full = self._quote(self._full_path(path))
        return self.shell.run(f"cat {full}")

    def list_details(self, path: str = "") -> List[Dict]:
        full = self._quote(self._full_path(path))
        output = self.shell.run(f"ls -l {full}")
        items = []
        for line in output.splitlines():
            line = line.strip()
            if not line or line.startswith("total") or "No such file" in line:
                continue
            parts = line.split(maxsplit=7)
            if len(parts) < 8:
                continue
            perms, _, owner, group, size, _, _, raw_name = parts[:8]
            target = None
            if " -> " in raw_name:
                name, target = raw_name.split(" -> ", 1)
            else:
                name = raw_name
            items.append({
                "name": name,
                "is_directory": perms.startswith("d"),
            })
        return items

    def stat_mtime(self, path: str) -> float:
        full = self._quote(self._full_path(path))
        output = self.shell.run(f"stat -c '%Y' {full}")
        try:
            return float(output.strip())
        except ValueError:
            return 0.0

    def get_base_path(self) -> str:
        return self.base_path

    @staticmethod
    def _store_json(temp_db, raw_path, content_text):
        folder = posixpath.dirname(raw_path).lstrip("./")
        filename = posixpath.basename(raw_path)
        if filename in ("content.json", "content2.json", "info.json"):
            try:
                temp_db[folder][filename] = json.loads(content_text)
            except json.JSONDecodeError:
                pass

    def discover_raw_entries(self):
        """Read all exam data via rish in a single shell session.

        Uses ``head -n 999999`` which is a single POSIX process that
        prints each file preceded by a ``==> filename <==`` header.
        This gives single-process speed with reliable per-file boundaries
        (the header format is POSIX-mandated for multi-file output).
        """
        print("正在通过rish连接到Shizuku获取E听说数据")
        start_time = time.time()

        base_dir = shlex.quote(self.base_path)

        shell_script = f"""cd {base_dir} || exit
echo "__TIMES__"
stat -c '%Y %n' */ 2>/dev/null
echo "__JSON__"
head -n 999999 ./*/*.json 2>/dev/null
"""

        raw_output = self.shell.run(shell_script, timeout=30.0)
        fetch_time = time.time() - start_time

        if "__JSON__" not in raw_output:
            print(f"耗时: {fetch_time:.2f}秒 — 未获取到数据\n")
            return []

        raw_times_str, raw_jsons_str = raw_output.split("__JSON__", 1)

        mtime_map = {}
        for line in raw_times_str.splitlines():
            line = line.strip()
            if not line or line == "__TIMES__":
                continue
            parts = line.split(maxsplit=1)
            if len(parts) == 2:
                mtime_map[parts[1].rstrip("/")] = float(parts[0])

        temp_db = defaultdict(dict)

        current_path = None
        current_lines = []
        for line in raw_jsons_str.splitlines():
            stripped = line.strip()
            if stripped.startswith("==> ") and stripped.endswith(" <=="):
                if current_path:
                    self._store_json(temp_db, current_path, "\n".join(current_lines))
                current_path = stripped[4:-4].strip()
                current_lines = []
            elif current_path:
                current_lines.append(line)
        if current_path:
            self._store_json(temp_db, current_path, "\n".join(current_lines))

        entries = []
        for folder, files in temp_db.items():
            content = files.get("content2.json") or files.get("content.json")
            info = files.get("info.json", {})
            if not content:
                continue
            try:
                info_obj = content.get("info", {})
                if not info_obj:
                    continue
                stid = str(info_obj.get("stid", "0"))
                mtime = mtime_map.get(folder, 0.0)
                entries.append((stid, folder, content, info, mtime))
            except Exception:
                continue

        elapsed = time.time() - start_time
        print(f"耗时: {elapsed:.2f}秒，成功提取 {len(entries)} 道题目！\n")
        return entries
