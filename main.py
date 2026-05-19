import os
import json
import re
import argparse
from collections import Counter, defaultdict
from datetime import datetime
import subprocess
import threading
import queue
import time
import shlex
from typing import List, Dict, Optional
import posixpath

# =====================================================================
# 第一部分：持久化 Rish Shell 及文件读取器 (你的代码，略加增强)
# =====================================================================

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
            if not line: break
            self.queue.put(line)

    def run(self, command: str, timeout: float = 15.0) -> str:
        marker = "__RISH_CMD_END__"
        full_command = f"{command}\necho {marker}\n"
        
        self.proc.stdin.write(full_command)
        self.proc.stdin.flush()
        
        lines = []
        start = time.time()
        while True:
            if time.time() - start > timeout: break
            try:
                line = self.queue.get(timeout=0.1)
                if line.strip().endswith("$") or line.strip().endswith("#"):
                    continue
                if marker in line:
                    cleaned = line.replace(marker, "")
                    if cleaned: lines.append(cleaned)
                    break
                lines.append(line)
            except queue.Empty:
                pass
        return "".join(lines).strip()

    def close(self):
        try:
            self.proc.terminate()
        except:
            pass

class RishFileReader:
    def __init__(self, shell: PersistentRish, base_path: str):
        self.shell = shell
        self.base_path = base_path.rstrip("/")

    def _full_path(self, path: str = "") -> str:
        if not path: return self.base_path
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
            if len(parts) < 8: continue
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
        """获取修改时间的时间戳 (增加 %Y 参数)"""
        full = self._quote(self._full_path(path))
        # %Y 返回 unix timestamp
        output = self.shell.run(f"stat -c '%Y' {full}")
        try:
            return float(output.strip())
        except ValueError:
            return 0.0

# =====================================================================
# 第二部分：试题内容提取及解析逻辑 (原逻辑)
# =====================================================================

def strip_html(text):
    text = re.sub(r"</p>\s*<p>", " ", str(text))
    text = re.sub(r"<[^>]+>", "", text)
    return text

def clean(text):
    return re.sub(r"^ets_th\d+\s*", "", strip_html(text)).strip()

def qnum(nr):
    return nr.strip().rstrip(".")

_EXPECTED_TYPES = [
    "collector.choose", "collector.choose", "collector.choose", "collector.choose", "collector.choose",
    "collector.word", "collector.word", "collector.read", "collector.dialogue", "collector.picture",
    "collector.dialogue", "collector.dialogue"
]
_EXAM_SECTION_NAMES = [
    "Section A", "Section A", "Section B", "Section B", "Section B",
    "朗读句子", "朗读句子", "朗读段落", "情景提问", "图片描述", "快速应答", "简述和回答"
]
_TYPE_NAMES = {
    "collector.choose": "听力选择", "collector.word": "朗读句子",
    "collector.read": "朗读段落", "collector.dialogue": "情景对话",
    "collector.picture": "图片描述"
}
_TYPE_ORDER = {t: i for i, t in enumerate(_EXPECTED_TYPES)}

def do_choose(content, info, passage_num=0):
    data = content["info"]
    q_parts, a_parts = [], []
    passage = strip_html(data.get("st_nr", "")).strip()
    if passage:
        q_parts.extend([f"【听力原文{passage_num}】", passage, ""])

    for xt in data.get("xtlist", []):
        nr = xt.get("xt_nr", "?")
        val = strip_html(xt.get("xt_value", "")).strip()
        ans = xt.get("answer", "").strip()

        if re.match(r"^\d+\.?$", nr):
            n = qnum(nr)
            q_text = re.sub(rf"^{re.escape(n)}\.\s*", "", val)
            label = f"{n}. {q_text}"
            show_context = False
        else:
            label, show_context = nr, True

        q_parts.append(label)
        if show_context and val.strip(): q_parts.append(f"    {val}")
        q_parts.append("")
        for xx in xt.get("xxlist", []):
            mc, xtext = xx.get("xx_mc", ""), strip_html(xx.get("xx_nr", ""))
            q_parts.append(f"    {mc}. {xtext}")
        q_parts.append("")
        a_parts.append(f"{label}  →  {ans}")

    return "\n".join(q_parts), "\n".join(a_parts)

def do_word(content, info, sentence_num=0):
    val = re.sub(r'^\d+\.\s*', '', clean(content["info"].get("value", "")))
    return f"{sentence_num}. {val}\n", ""

def do_read(content, info):
    return clean(content["info"].get("value", "")) + "\n", ""

def do_dialogue(content, info):
    cinfo = content["info"]
    info_map = {it["code_id"]: it["code_value"] for it in info}
    q_parts, a_parts = [], []
    passage = clean(cinfo.get("value", ""))
    
    if passage: q_parts.extend(["【阅读短文】", passage, ""])

    askall = info_map.get("askall", "")
    if askall:
        q_parts.append("【题目】")
        for part in askall.split("</br>"):
            if clean(part): q_parts.append(clean(part))
        q_parts.append("")

    ask_ids = sorted([k for k in info_map if re.match(r"^ask\d+$", k)], key=lambda x: int(re.search(r"\d+", x).group()))
    
    if not askall:
        for aid in ask_ids:
            if clean(info_map[aid]): q_parts.extend([f"  {clean(info_map[aid])}", ""])

    questions = cinfo.get("question", [])
    for i, aid in enumerate(ask_ids):
        prompt = clean(info_map[aid])
        if i < len(questions):
            short = prompt[:36] + "..." if len(prompt) > 36 else prompt
            a_parts.append(f"【{short}】")
            for s in questions[i].get("std", [])[:3]:
                ans = clean(s.get("value", "") or s.get("ai", ""))
                if ans: a_parts.append(f"  · {ans}")
            a_parts.append("")

    return "\n".join(q_parts), "\n".join(a_parts)

def do_picture(content, info):
    data = content["info"]
    q_parts, a_parts = [], []
    topic = data.get("topic", "")
    q_parts.extend([f"话题：{topic}", ""])

    kp = data.get("keypoint", "")
    if kp:
        q_parts.append("关键词要点：")
        for line in kp.split("</br>"):
            if strip_html(line).strip(): q_parts.append(f"  {strip_html(line).strip()}")
        q_parts.append("")

    std_list = data.get("std", [])
    if std_list:
        a_parts.extend([f"【{topic} — 参考范文】", ""])
        for i, s in enumerate(std_list, 1):
            val = clean(s.get("value", "") or s.get("ai", ""))
            if val: a_parts.extend([f"  版本{i}：{val}", ""])

    return "\n".join(q_parts), "\n".join(a_parts)

HANDLERS = {
    "collector.choose": do_choose, "collector.word": do_word,
    "collector.read": do_read, "collector.dialogue": do_dialogue,
    "collector.picture": do_picture,
}

# =====================================================================
# 第三部分：连接 Rish 与 试卷发现逻辑
# =====================================================================

def discover_exams(reader: RishFileReader):
    """终极极限版：利用通配符 O(1) 进程读取，拒绝任何 Shell 循环"""
    entries = []
    
    print("正在拉取底层数据快照，准备秒速解析...")
    start_time = time.time()

    base_dir = shlex.quote(reader.base_path)
    
    # 真正的 0 循环脚本：
    # 1. stat -c '%Y %n' */ ：一次性读取所有目录的修改时间
    # 2. grep -H -a "^" */*.json ：利用正则瞬间读取所有目录下所有 JSON 文件的内容并自动打上文件名前缀
    shell_script = f"""cd {base_dir} || exit
echo "__TIMES__"
stat -c '%Y %n' */ 2>/dev/null
echo "__JSON__"
grep -H -a "^" */*.json 2>/dev/null
"""

    raw_output = reader.shell.run(shell_script, timeout=15.0)
    fetch_time = time.time() - start_time
    
    if "__JSON__" not in raw_output:
        return []

    raw_times_str, raw_jsons_str = raw_output.split("__JSON__", 1)

    # 1. 瞬间解析时间
    mtime_map = {}
    for line in raw_times_str.splitlines():
        line = line.strip()
        if not line or line == "__TIMES__": continue
        parts = line.split(maxsplit=1)
        if len(parts) == 2:
            # 去掉文件夹末尾的斜杠 /
            mtime_map[parts[1].rstrip("/")] = float(parts[0])

    # 2. 瞬间重组 JSON 文件内容
    # grep 的输出格式为:  ets_168001/content.json:{"info": {"stid": "123"}}
    temp_lines = defaultdict(list)
    for line in raw_jsons_str.splitlines():
        if ":" not in line: 
            continue
        # 只在第一个冒号处切分，保留正常的 JSON 冒号
        filepath, text = line.split(":", 1)
        temp_lines[filepath].append(text)
        
    temp_db = defaultdict(dict)
    for filepath, lines in temp_lines.items():
        folder = posixpath.dirname(filepath)
        filename = posixpath.basename(filepath)
        
        # 过滤掉无关文件
        if filename not in ("content.json", "content2.json", "info.json"):
            continue
            
        full_text = "\n".join(lines)
        try:
            temp_db[folder][filename] = json.loads(full_text)
        except json.JSONDecodeError:
            pass

    # 3. 组装试卷条目
    for folder, files in temp_db.items():
        # 优先读取 content2.json，如果不存在则使用 content.json
        content = files.get("content2.json") or files.get("content.json")
        info = files.get("info.json", {})
        
        if not content or "info" not in content:
            continue
            
        stid = content["info"].get("stid", "0")
        mtime = mtime_map.get(folder, 0.0)
        
        entries.append((stid, folder, content, info, mtime))

    print(f"数据快照拉取耗时: {fetch_time:.2f}秒 (纯提取)，成功提取 {len(entries)} 道题目！\n")

    if not entries: 
        return []
        
    entries.sort(key=lambda x: int(x[0]))

    # --- 以下组合试卷的业务逻辑保持不变 ---
    groups = []
    current = [entries[0]]
    has_non_choose = (entries[0][2].get("structure_type", "") != "collector.choose")

    for i in range(1, len(entries)):
        prev_stid = int(entries[i - 1][0])
        curr_stid = int(entries[i][0])
        stype = entries[i][2].get("structure_type", "")

        if curr_stid - prev_stid > 1:
            groups.append(current)
            current = [entries[i]]
            has_non_choose = (stype != "collector.choose")
        elif stype == "collector.choose" and has_non_choose:
            groups.append(current)
            current = [entries[i]]
            has_non_choose = False
        else:
            current.append(entries[i])
            if stype != "collector.choose": has_non_choose = True

    groups.append(current)

    exams = []
    for g in groups:
        items = sorted(g, key=lambda x: int(x[0]))
        exams.append(items)

    exams.sort(key=lambda e: min(item[4] for item in e))

    merged = []
    i = 0
    while i < len(exams):
        if _is_valid_exam(exams[i]):
            merged.append(exams[i])
            i += 1
            continue

        combined = list(exams[i])
        j = i + 1
        while j < len(exams) and not _is_valid_exam(exams[j]):
            combined.extend(exams[j])
            j += 1

        if _is_valid_exam(combined):
            _sort_exam_order(combined)
            merged.append(combined)
        else:
            for k in range(i, j): merged.append(exams[k])
        i = j

    return merged

def _is_valid_exam(items):
    return len(items) == 12 and Counter([item[2].get("structure_type", "") for item in items]) == Counter(_EXPECTED_TYPES)

def _sort_exam_order(items):
    def sort_key(item):
        content = item[2]
        stype = content.get("structure_type", "")
        type_pos = _TYPE_ORDER.get(stype, 99)
        info = content.get("info", {})
        has_passage = bool((info.get("st_nr") or info.get("value") or "").strip())
        return (type_pos, has_passage, int(item[0]))
    items.sort(key=sort_key)

def build_section_map(items):
    items.sort(key=lambda x: int(x[0]))
    if _is_valid_exam(items):
        _sort_exam_order(items)
        return {item[0]: name for item, name in zip(items, _EXAM_SECTION_NAMES)}

    section_map, type_blocks, i = {}, [], 0
    while i < len(items):
        stid, stype = items[i][0], items[i][2].get("structure_type", "")
        j = i + 1
        while j < len(items) and items[j][2].get("structure_type", "") == stype and int(items[j][0]) == int(stid) + (j - i):
            j += 1
        type_blocks.append((stype, i, j))
        i = j

    type_counters = defaultdict(int)
    for stype, start, end in type_blocks:
        type_counters[stype] += 1
        total = sum(1 for t, _, _ in type_blocks if t == stype)
        section_name = f"{_TYPE_NAMES.get(stype, stype)} {type_counters[stype]}" if total > 1 else _TYPE_NAMES.get(stype, stype)
        for idx in range(start, end):
            section_map[items[idx][0]] = section_name
    return section_map

def exam_summary(items):
    dates = set()
    for item in items:
        mtime = item[4]
        if mtime > 0:
            dates.add(datetime.fromtimestamp(mtime).strftime("%Y-%m-%d"))
    
    date_str = "/".join(sorted(dates)) if dates else "未知日期"
    type_question_counts = defaultdict(int)
    total = 0
    for item in items:
        content = item[2]
        stype = content.get("structure_type", "?")
        n = len(content["info"].get("xtlist", [])) if stype == "collector.choose" else 1
        type_question_counts[_TYPE_NAMES.get(stype, stype)] += n
        total += n

    summary = "、".join(f"{k}×{v}" for k, v in type_question_counts.items())
    status = "" if _is_valid_exam(items) else " [非标准]"
    return f"{date_str} — {total} 题（{summary}）{status}"


def extract_exam(items, section_map, q_path, a_path):
    q_all, a_all = [], []
    last_section, last_a_section = None, None
    counters = {}
    q_count = 0

    for item in items:
        # 解包 5 个元素
        stid, name, content, infodata, mtime = item
        stype = content.get("structure_type", "")
        section = section_map.get(stid, _TYPE_NAMES.get(stype, stype))
        topic = content["info"].get("topic", "")
        handler = HANDLERS.get(stype)

        if section != last_section:
            counters[section] = {"passage": 0, "sentence": 0}
            q_all.extend(["", "─" * 20, f"  {section}" + (f"  ·  {topic}" if topic else ""), "─" * 20, ""])
            last_section = section

        if handler:
            kwargs = {}
            if stype == "collector.choose":
                counters[section]["passage"] += 1
                kwargs["passage_num"] = counters[section]["passage"]
            elif stype == "collector.word":
                counters[section]["sentence"] += 1
                kwargs["sentence_num"] = counters[section]["sentence"]

            q_text, a_text = handler(content, infodata, **kwargs)
            q_all.append(q_text.rstrip())

            if a_text.strip():
                if section != last_a_section:
                    a_all.extend(["", "─" * 20, f"  {section}" + (f"  话题: {topic}" if topic else ""), "─" * 20, ""])
                    last_a_section = section
                a_all.append(a_text.rstrip())
        else:
            q_all.append(f"[未支持题型: {stype}]")

        q_count += len(content["info"].get("xtlist", [])) if stype == "collector.choose" else 1

    # 本地文件操作 (os) 保持不变，写入到手机普通存储中
    os.makedirs(os.path.dirname(q_path) or ".", exist_ok=True)
    with open(q_path, "w", encoding="utf-8") as f:
        f.write("\n".join(q_all).strip() + "\n")
    with open(a_path, "w", encoding="utf-8") as f:
        f.write("\n".join(a_all).strip() + "\n")

    return q_count


def _parse_selection(choice, max_n):
    choice = choice.strip().lower()
    if choice in ("all", "a"): return list(range(max_n))
    indices = []
    for part in re.split(r"[,\s]+", choice):
        part = part.strip()
        if not part: continue
        if "-" in part:
            try:
                a, b = part.split("-", 1)
                indices.extend(range(int(a) - 1, int(b)))
            except ValueError: pass
        else:
            try: indices.append(int(part) - 1)
            except ValueError: pass
    return sorted(set(i for i in indices if 0 <= i < max_n))

# =====================================================================
# 主函数
# =====================================================================

def main():
    parser = argparse.ArgumentParser(description="通过 Shizuku rish 从 ETS Android 数据目录提取试卷")
    # 默认目录指向 Android 隔离目录
    DEFAULT_RISH_DIR = "/storage/emulated/0/Android/data/com.ets100.secondary/files/Download/ETS_secondary/resource"
    
    parser.add_argument("--dir", default=DEFAULT_RISH_DIR, help=f"Android源目录 (默认: {DEFAULT_RISH_DIR})")
    parser.add_argument("--output", default="./result", help="输出到本地的目录 (默认: 当前目录下的 ./result)")
    parser.add_argument("--exam", type=str, default=None, help="提取指定试卷编号（支持逗号分隔、范围、all）")
    parser.add_argument("--list", action="store_true", help="仅列出可提取的试卷")
    parser.add_argument("--all", action="store_true", help="提取全部试卷")

    args = parser.parse_args()

    # 初始化 Rish shell
    shell = PersistentRish()
    try:
        reader = RishFileReader(shell, base_path=args.dir)
        
        # 测试目录是否可达
        if not reader.exists(""):
            print(f"\n[错误] rish 无法访问该目录: {args.dir}")
            print("请检查包名是否正确，或者是否已授予 Shizuku 权限。")
            return

        exams = discover_exams(reader)
        if not exams:
            print(f"\n在 {args.dir} 中未发现试卷数据。")
            return

        # 仅列出模式
        if args.list:
            print(f"\n发现 {len(exams)} 套试卷：")
            for i, items in enumerate(exams, 1):
                print(f"  {i:>2}. {exam_summary(items)}")
            return

        out_dir = os.path.abspath(args.output)

        if args.all:
            selected = list(range(len(exams)))
        elif args.exam:
            selected = _parse_selection(args.exam, len(exams))
        elif len(exams) == 1:
            selected = [0]
        else:
            print(f"\n发现 {len(exams)} 套试卷：")
            for i, items in enumerate(exams, 1):
                print(f"  {i:>2}. {exam_summary(items)}")
            print()
            choice = input("请选择要提取的试卷编号（支持多选，如 1,3,5 或 all）：").strip()
            selected = _parse_selection(choice, len(exams))
            if not selected:
                print("未选中任何试卷，退出。")
                return

        multi = len(selected) > 1 or (len(exams) > 1 and len(selected) == 1)
        total = 0

        print(f"\n开始提取，结果将保存至本地: {out_dir}\n")
        
        for idx in selected:
            items = exams[idx]
            section_map = build_section_map(items)

            if multi:
                q_path = os.path.join(out_dir, f"试卷{idx + 1}.txt")
                a_path = os.path.join(out_dir, f"答案{idx + 1}.txt")
            else:
                q_path = os.path.join(out_dir, "试题.txt")
                a_path = os.path.join(out_dir, "答案.txt")

            n = extract_exam(items, section_map, q_path, a_path)
            total += n
            print(f"  [{idx + 1}] {exam_summary(items)}")
            print(f"       试题 → {q_path}")
            print(f"       答案 → {a_path}")

        print(f"\n完成！共提取 {total} 题（{len(selected)} 套试卷）")

    finally:
        # 确保安全退出
        shell.close()

if __name__ == "__main__":
    main()