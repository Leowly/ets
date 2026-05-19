import json
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
        self.proc = subprocess.Popen(
            ["rish"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
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

    def run(self, command: str, timeout: float = 15.0) -> str:
        marker = "__RISH_CMD_END__"
        full_command = f"{command}\necho {marker}\n"

        self.proc.stdin.write(full_command)
        self.proc.stdin.flush()

        lines = []
        start = time.time()
        while True:
            if time.time() - start > timeout:
                break
            try:
                line = self.queue.get(timeout=0.1)
                if line.strip().endswith("$") or line.strip().endswith("#"):
                    continue
                if marker in line:
                    cleaned = line.replace(marker, "")
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

    def discover_raw_entries(self):
        """Optimized: read all exam data in a single shell script (O(1) processes)."""
        print("正在通过rish连接到Shizuku获取E听说数据")
        start_time = time.time()

        base_dir = shlex.quote(self.base_path)

        shell_script = f"""cd {base_dir} || exit
echo "__TIMES__"
stat -c '%Y %n' */ 2>/dev/null
echo "__JSON__"
grep -H -a "^" */*.json 2>/dev/null
"""

        raw_output = self.shell.run(shell_script, timeout=15.0)
        fetch_time = time.time() - start_time

        if "__JSON__" not in raw_output:
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

        temp_lines = defaultdict(list)
        for line in raw_jsons_str.splitlines():
            if ":" not in line:
                continue
            filepath, text = line.split(":", 1)
            temp_lines[filepath].append(text)

        temp_db = defaultdict(dict)
        for filepath, lines in temp_lines.items():
            folder = posixpath.dirname(filepath)
            filename = posixpath.basename(filepath)
            if filename not in ("content.json", "content2.json", "info.json"):
                continue
            full_text = "\n".join(lines)
            try:
                temp_db[folder][filename] = json.loads(full_text)
            except json.JSONDecodeError:
                pass

        entries = []
        for folder, files in temp_db.items():
            content = files.get("content2.json") or files.get("content.json")
            info = files.get("info.json", {})
            if not content or "info" not in content:
                continue
            stid = content["info"].get("stid", "0")
            mtime = mtime_map.get(folder, 0.0)
            entries.append((stid, folder, content, info, mtime))

        print(f"耗时: {fetch_time:.2f}秒 (纯提取)，成功提取 {len(entries)} 道题目！\n")
        return entries
