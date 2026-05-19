import json
import os
import posixpath
import queue
import re
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
            print(f"[DEBUG run] write failed, restarting proc")
            self._start_proc()
            self.proc.stdin.write(full_command)
            self.proc.stdin.flush()

        lines = []
        line_count = 0
        prompt_skipped = 0
        start = time.time()
        while True:
            if time.time() - start > timeout:
                print(f"[DEBUG run] TIMEOUT after {timeout}s, collected {line_count} lines ({prompt_skipped} prompts skipped)")
                self._drain_queue()
                break
            try:
                line = self.queue.get(timeout=0.1)
                stripped = line.strip()
                if stripped in ("$", "#", ""):
                    prompt_skipped += 1
                    continue
                if marker in stripped:
                    cleaned = stripped.replace(marker, "").strip()
                    if cleaned:
                        lines.append(cleaned)
                    print(f"[DEBUG run] marker found at line {line_count} (after {prompt_skipped} prompts), total chars={sum(len(l) for l in lines)}")
                    break
                lines.append(line)
                line_count += 1
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
        """Read all exam data via rish in a single shell session.

        Uses shell globs (not ``find -maxdepth``, which toybox lacks) with
        per-file delimiters so every JSON file arrives intact regardless of
        formatting or line endings.
        """
        print("正在通过rish连接到Shizuku获取E听说数据")
        start_time = time.time()

        base_dir = shlex.quote(self.base_path)
        print(f"[DEBUG] base_dir = {base_dir}")

        # Shell globs work on every Android shell (mksh, toybox sh, bash).
        shell_script = f"""cd {base_dir} || exit
echo "__TIMES__"
stat -c '%Y %n' */ 2>/dev/null
echo "__JSON__"
for f in ./*/*.json; do
    [ -f "$f" ] || continue
    echo "==== $f ===="
    cat "$f" 2>/dev/null
done
"""

        print(f"[DEBUG] shell_script ({len(shell_script)} chars):")
        for line in shell_script.splitlines():
            print(f"  | {line}")

        raw_output = self.shell.run(shell_script, timeout=30.0)
        fetch_time = time.time() - start_time

        print(f"[DEBUG] raw_output length = {len(raw_output)} chars")
        print(f"[DEBUG] raw_output first 500 chars:")
        print(raw_output[:500])
        print("[DEBUG] ---")
        print(f"[DEBUG] raw_output last 300 chars:")
        print(raw_output[-300:])
        print("[DEBUG] ---")

        # Check for key markers
        has_times = "__TIMES__" in raw_output
        has_json = "__JSON__" in raw_output
        has_rish_end = "__RISH_END_" in raw_output
        print(f"[DEBUG] __TIMES__ in output: {has_times}")
        print(f"[DEBUG] __JSON__ in output: {has_json}")
        print(f"[DEBUG] __RISH_END_ in output: {has_rish_end}")

        if not has_json:
            print(f"[DEBUG] Exiting: __JSON__ marker not found")
            print(f"耗时: {fetch_time:.2f}秒 — 未获取到数据\n")
            return []

        raw_times_str, raw_jsons_str = raw_output.split("__JSON__", 1)
        print(f"[DEBUG] raw_times_str length = {len(raw_times_str)}")
        print(f"[DEBUG] raw_jsons_str length = {len(raw_jsons_str)}")

        mtime_map = {}
        for line in raw_times_str.splitlines():
            line = line.strip()
            if not line or line == "__TIMES__":
                continue
            parts = line.split(maxsplit=1)
            if len(parts) == 2:
                mtime_map[parts[1].rstrip("/")] = float(parts[0])
        print(f"[DEBUG] mtime_map has {len(mtime_map)} entries")
        if mtime_map:
            print(f"[DEBUG] mtime_map sample: {list(mtime_map.items())[:3]}")

        temp_db = defaultdict(dict)

        file_blocks = re.split(
            r'^====\s+(\./.+?)\s+====$',
            raw_jsons_str,
            flags=re.MULTILINE,
        )
        print(f"[DEBUG] file_blocks count = {len(file_blocks)}")
        print(f"[DEBUG] file_blocks[0] (preamble) = {repr(file_blocks[0][:200] if file_blocks else 'EMPTY')}")
        for idx in range(1, min(len(file_blocks), 8), 2):
            path = file_blocks[idx].strip() if idx < len(file_blocks) else "N/A"
            content_len = len(file_blocks[idx + 1]) if idx + 1 < len(file_blocks) else 0
            print(f"[DEBUG]   block[{idx}] path={path}, content_len={content_len}")

        for i in range(1, len(file_blocks), 2):
            if i + 1 >= len(file_blocks):
                break
            raw_path = file_blocks[i].strip()
            content_text = file_blocks[i + 1]

            folder = posixpath.dirname(raw_path).lstrip("./")
            filename = posixpath.basename(raw_path)

            if filename in ("content.json", "content2.json", "info.json"):
                try:
                    temp_db[folder][filename] = json.loads(content_text)
                except json.JSONDecodeError:
                    print(f"[DEBUG] JSON parse failed: {raw_path}")
                    pass

        print(f"[DEBUG] temp_db has {len(temp_db)} folders")
        if temp_db:
            sample = list(temp_db.items())[:2]
            for folder, files in sample:
                print(f"[DEBUG]   folder={folder}, files={list(files.keys())}")

        entries = []
        for folder, files in temp_db.items():
            content = files.get("content2.json") or files.get("content.json")
            info = files.get("info.json", {})
            if not content:
                print(f"[DEBUG]   skip {folder}: no content")
                continue
            try:
                info_obj = content.get("info", {})
                if not info_obj:
                    print(f"[DEBUG]   skip {folder}: no info in content")
                    continue
                stid = str(info_obj.get("stid", "0"))
                mtime = mtime_map.get(folder, 0.0)
                entries.append((stid, folder, content, info, mtime))
            except Exception as e:
                print(f"[DEBUG]   skip {folder}: exception {e}")
                continue

        elapsed = time.time() - start_time
        print(f"耗时: {elapsed:.2f}秒，成功提取 {len(entries)} 道题目！\n")
        return entries
