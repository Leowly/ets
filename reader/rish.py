import io
import json
import os
import posixpath
import queue
import shlex
import subprocess
import tarfile
import threading
import time
from collections import defaultdict
from typing import Dict, List, Optional

from .base import FileReader


class PersistentRish:
    """
    Persistent rish shell connection.

    IMPORTANT DESIGN NOTES
    ----------------------

    This implementation intentionally avoids:

    - readline()
    - text mode
    - base64 transport
    - queue draining
    - line-based protocols

    because they are unreliable for large/binary streams over PTY.

    Instead this implementation uses:

    - binary mode
    - explicit byte marker framing
    - exact byte accumulation
    - session restart on timeout/desync

    This makes the protocol stable even when:
    - output is large
    - shell buffering changes
    - PTY inserts CRLF
    - output arrives fragmented
    """

    MARKER_PREFIX = b"\n__RISH_END__"
    READ_SIZE = 65536

    def __init__(self):
        self._start_proc()

    def _start_proc(self):
        self.proc = subprocess.Popen(
            ["rish"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,  # unbuffered binary
        )

        self.queue = queue.Queue()

        self.reader_thread = threading.Thread(
            target=self._reader_loop,
            daemon=True,
        )
        self.reader_thread.start()

    def _reader_loop(self):
        """
        Continuously read raw bytes from stdout.

        IMPORTANT:
        - No readline()
        - No text decoding
        - No line assumptions
        """

        while True:
            try:
                chunk = os.read(self.proc.stdout.fileno(), self.READ_SIZE)

                if not chunk:
                    break

                self.queue.put(chunk)

            except Exception:
                break

    def _restart_proc(self):
        try:
            self.proc.kill()
        except Exception:
            pass

        try:
            self.proc.wait(timeout=1)
        except Exception:
            pass

        self._start_proc()

    def _ensure_alive(self):
        if self.proc.poll() is not None:
            self._restart_proc()

    def run(self, command: str, timeout: float = 30.0) -> bytes:
        """
        Execute command and return raw bytes.

        Protocol:
            command
            printf '\n__RISH_END__<random>\n'

        We then read bytes until exact marker appears.
        """

        self._ensure_alive()

        marker_token = os.urandom(16).hex().encode()
        marker = self.MARKER_PREFIX + marker_token + b"\n"

        full_command = (
            command.encode()
            + b"\n"
            + b"printf '\\n__RISH_END__"
            + marker_token
            + b"\\n'\n"
        )

        try:
            self.proc.stdin.write(full_command)
            self.proc.stdin.flush()

        except (BrokenPipeError, OSError):
            self._restart_proc()

            self.proc.stdin.write(full_command)
            self.proc.stdin.flush()

        buffer = bytearray()

        start_time = time.time()

        while True:
            # HARD DESYNC PROTECTION
            #
            # If timeout happens we MUST restart shell.
            # Otherwise leftover output corrupts next command.
            #
            if time.time() - start_time > timeout:
                self._restart_proc()

                raise TimeoutError(
                    f"PersistentRish command timed out after {timeout:.1f}s"
                )

            try:
                chunk = self.queue.get(timeout=0.1)

                buffer.extend(chunk)

                marker_pos = buffer.find(marker)

                if marker_pos != -1:
                    return bytes(buffer[:marker_pos])

            except queue.Empty:
                continue

    def close(self):
        try:
            self.proc.kill()
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

        output = self.shell.run(
            f"test -e {full} && printf 'ok'"
        )

        return output.strip() == b"ok"

    def read_file(self, path: str) -> Optional[str]:
        full = self._quote(self._full_path(path))

        output = self.shell.run(f"cat {full}")

        try:
            return output.decode("utf-8", errors="replace")
        except Exception:
            return None

    def list_details(self, path: str = "") -> List[Dict]:
        full = self._quote(self._full_path(path))

        output = self.shell.run(f"ls -l {full}")

        try:
            text = output.decode("utf-8", errors="replace")
        except Exception:
            return []

        items = []

        for line in text.splitlines():
            line = line.strip()

            if (
                not line
                or line.startswith("total")
                or "No such file" in line
            ):
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

        output = self.shell.run(
            f"stat -c '%Y' {full}"
        )

        try:
            return float(output.decode().strip())
        except Exception:
            return 0.0

    def get_base_path(self) -> str:
        return self.base_path

    def discover_raw_entries(self):
        """Read all exam data via rish in a single shell session.

        Uses raw tar.gz binary transport directly.

        IMPORTANT:
        - no base64
        - no text parsing
        - no regex
        - no readline
        - no line protocol

        tar preserves:
        - exact file boundaries
        - exact bytes
        - exact filenames
        """

        print("正在通过rish连接到Shizuku获取E听说数据")

        start_time = time.time()

        base_dir = shlex.quote(self.base_path)

        #
        # IMPORTANT:
        #
        # We separate metadata and binary payload using a fixed marker.
        #
        # Layout:
        #
        #   __TIMES__
        #   ...
        #   __TAR_BEGIN__
        #   <raw tar.gz binary>
        #
        # The tar.gz continues until PersistentRish marker appears.
        #

        shell_script = f"""
cd {base_dir} || exit 1

printf '__TIMES__\\n'

stat -c '%Y %n' */ 2>/dev/null

printf '__TAR_BEGIN__\\n'

find . -type f \\( \\
    -name 'content.json' -o \\
    -name 'content2.json' -o \\
    -name 'info.json' \\
\\) -print0 |
tar --null -T - -czf - 2>/dev/null
"""

        try:
            raw_output = self.shell.run(
                shell_script,
                timeout=15.0,
            )

        except TimeoutError:
            print("获取数据超时\n")
            return []

        fetch_time = time.time() - start_time

        marker = b"__TAR_BEGIN__\n"

        marker_pos = raw_output.find(marker)

        if marker_pos == -1:
            print(f"耗时: {fetch_time:.2f}秒 — 未获取到数据\n")
            return []

        raw_times = raw_output[:marker_pos]

        tar_data = raw_output[marker_pos + len(marker):]

        try:
            raw_times_str = raw_times.decode(
                "utf-8",
                errors="replace",
            )
        except Exception:
            print(f"耗时: {fetch_time:.2f}秒 — 时间数据解码失败\n")
            return []

        mtime_map = {}

        for line in raw_times_str.splitlines():
            line = line.strip()

            if (
                not line
                or line == "__TIMES__"
            ):
                continue

            parts = line.split(maxsplit=1)

            if len(parts) != 2:
                continue

            try:
                mtime_map[parts[1].rstrip("/")] = float(parts[0])
            except Exception:
                continue

        temp_db = defaultdict(dict)

        #
        # IMPORTANT:
        #
        # tar_data is already raw gzip bytes.
        #
        # No base64 decoding needed.
        #

        try:
            with tarfile.open(
                fileobj=io.BytesIO(tar_data),
                mode="r:gz",
            ) as tar:

                for member in tar.getmembers():

                    if not member.isfile():
                        continue

                    folder = posixpath.dirname(
                        member.name
                    ).lstrip("./")

                    filename = posixpath.basename(
                        member.name
                    )

                    if filename not in (
                        "content.json",
                        "content2.json",
                        "info.json",
                    ):
                        continue

                    f = tar.extractfile(member)

                    if not f:
                        continue

                    try:
                        temp_db[folder][filename] = json.loads(
                            f.read().decode("utf-8")
                        )

                    except json.JSONDecodeError:
                        continue

        except tarfile.ReadError as e:
            print(
                f"耗时: {fetch_time:.2f}秒 — tar解包失败: {e}\n"
            )
            return []

        entries = []

        for folder, files in temp_db.items():

            content = (
                files.get("content2.json")
                or files.get("content.json")
            )

            info = files.get("info.json", {})

            if not content:
                continue

            try:
                info_obj = content.get("info", {})

                if not info_obj:
                    continue

                stid = str(info_obj.get("stid", "0"))

                mtime = mtime_map.get(folder, 0.0)

                entries.append((
                    stid,
                    folder,
                    content,
                    info,
                    mtime,
                ))

            except Exception:
                continue

        elapsed = time.time() - start_time

        print(
            f"耗时: {elapsed:.2f}秒，成功提取 "
            f"{len(entries)} 道题目！\n"
        )

        return entries