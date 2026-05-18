"""从 ETS 原始数据中提取试卷"""
import os
import sys
import json
import re
import argparse
from collections import Counter, defaultdict
from datetime import datetime


# ═══════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def strip_html(text):
    text = re.sub(r"</p>\s*<p>", " ", str(text))
    text = re.sub(r"<[^>]+>", "", text)
    return text


def clean(text):
    text = re.sub(r"^ets_th\d+\s*", "", strip_html(text)).strip()
    return text


def qnum(nr):
    return nr.strip().rstrip(".")


# ═══════════════════════════════════════════════════
# 题型名（原卷格式：Section A / Section B / 朗读句子 / 朗读段落 / 情景提问 /
#            图片描述 / 快速应答 / 简述和回答）
# ═══════════════════════════════════════════════════

# 标准 12 题试卷的题型序列
_EXPECTED_TYPES = [
    "collector.choose",
    "collector.choose",
    "collector.choose",
    "collector.choose",
    "collector.choose",
    "collector.word",
    "collector.word",
    "collector.read",
    "collector.dialogue",
    "collector.picture",
    "collector.dialogue",
    "collector.dialogue",
]

# 标准 12 题试卷每道题对应的 section 名
_EXAM_SECTION_NAMES = [
    "Section A",
    "Section A",
    "Section B",
    "Section B",
    "Section B",
    "朗读句子",
    "朗读句子",
    "朗读段落",
    "情景提问",
    "图片描述",
    "快速应答",
    "简述和回答",
]

# 非常规试卷的 fallback：structure_type → section 名
_TYPE_NAMES = {
    "collector.choose":   "听力选择",
    "collector.word":     "朗读句子",
    "collector.read":     "朗读段落",
    "collector.dialogue": "情景对话",
    "collector.picture":  "图片描述",
}


# ═══════════════════════════════════════════════════
# 各题型提取：返回 (题目, 答案)
# ═══════════════════════════════════════════════════

def do_choose(content, info, passage_num=0):
    """听力选择题"""
    data = content["info"]
    q_parts = []
    a_parts = []

    passage = strip_html(data.get("st_nr", "")).strip()
    if passage:
        label = f"【听力原文{passage_num}】"
        q_parts.append(label)
        q_parts.append(passage)
        q_parts.append("")

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
            label = nr
            show_context = True

        q_parts.append(label)
        if show_context and val.strip():
            q_parts.append(f"    {val}")
        q_parts.append("")

        for xx in xt.get("xxlist", []):
            mc = xx.get("xx_mc", "")
            xtext = strip_html(xx.get("xx_nr", ""))
            q_parts.append(f"    {mc}. {xtext}")
        q_parts.append("")

        a_parts.append(f"{label}  →  {ans}")

    return "\n".join(q_parts), "\n".join(a_parts)


def do_word(content, info, sentence_num=0):
    """句子朗读"""
    val = clean(content["info"].get("value", ""))
    val = re.sub(r'^\d+\.\s*', '', val)
    return f"{sentence_num}. {val}\n", ""


def do_read(content, info):
    """短文朗读"""
    val = clean(content["info"].get("value", ""))
    return val + "\n", ""


def do_dialogue(content, info):
    """情景问答"""
    cinfo = content["info"]
    info_map = {it["code_id"]: it["code_value"] for it in info}

    q_parts = []
    a_parts = []

    passage = clean(cinfo.get("value", ""))
    if passage:
        q_parts.append("【阅读短文】")
        q_parts.append(passage)
        q_parts.append("")

    askall = info_map.get("askall", "")
    if askall:
        q_parts.append("【题目】")
        for part in askall.split("</br>"):
            part = clean(part)
            if part:
                q_parts.append(part)
        q_parts.append("")

    ask_ids = sorted(
        [k for k in info_map if re.match(r"^ask\d+$", k)],
        key=lambda x: int(re.search(r"\d+", x).group())
    )

    if not askall:
        for i, aid in enumerate(ask_ids):
            prompt = clean(info_map[aid])
            if prompt:
                q_parts.append(f"  {prompt}")
                q_parts.append("")

    questions = cinfo.get("question", [])
    for i, aid in enumerate(ask_ids):
        prompt = clean(info_map[aid])
        if i < len(questions):
            short = prompt[:36] + "..." if len(prompt) > 36 else prompt
            a_parts.append(f"【{short}】")
            std_list = questions[i].get("std", [])
            for s in std_list[:3]:
                ans = clean(s.get("value", "") or s.get("ai", ""))
                if ans:
                    a_parts.append(f"  · {ans}")
            a_parts.append("")

    return "\n".join(q_parts), "\n".join(a_parts)


def do_picture(content, info):
    """看图说话"""
    data = content["info"]
    q_parts = []
    a_parts = []

    topic = data.get("topic", "")
    q_parts.append(f"话题：{topic}")
    q_parts.append("")

    kp = data.get("keypoint", "")
    if kp:
        q_parts.append("关键词要点：")
        for line in kp.split("</br>"):
            line = strip_html(line).strip()
            if line:
                q_parts.append(f"  {line}")
        q_parts.append("")

    std_list = data.get("std", [])
    if std_list:
        a_parts.append(f"【{topic} — 参考范文】")
        a_parts.append("")
        for i, s in enumerate(std_list, 1):
            val = clean(s.get("value", "") or s.get("ai", ""))
            if val:
                a_parts.append(f"  版本{i}：{val}")
                a_parts.append("")

    return "\n".join(q_parts), "\n".join(a_parts)


HANDLERS = {
    "collector.choose":   do_choose,
    "collector.word":     do_word,
    "collector.read":     do_read,
    "collector.dialogue": do_dialogue,
    "collector.picture":  do_picture,
}


# ═══════════════════════════════════════════════════
# 试卷发现 —— stid 连续 + 题型序列检测
# ═══════════════════════════════════════════════════

def _is_exam_item(dirpath):
    name = os.path.basename(dirpath.rstrip("/").rstrip("\\"))
    if name in ("common",):
        return False
    c2 = os.path.join(dirpath, "content2.json")
    c1 = os.path.join(dirpath, "content.json")
    return os.path.exists(c2) or os.path.exists(c1)


def discover_exams(root_dir):
    """扫描 root_dir，按 stid 连续性与题型序列分组。

    规则：
    1. stid 不连续（gap > 1）→ 新试卷
    2. 出现 collector.choose 且前面已有非 choose 题型 → 新一个 12 题试卷
    """
    entries = []
    for name in os.listdir(root_dir):
        d = os.path.join(root_dir, name)
        if not os.path.isdir(d):
            continue
        if not _is_exam_item(d):
            continue

        c2 = os.path.join(d, "content2.json")
        if not os.path.exists(c2):
            c2 = os.path.join(d, "content.json")
        info = os.path.join(d, "info.json")
        try:
            content = load_json(c2)
            infodata = load_json(info)
            stid = content["info"].get("stid", "0")
            entries.append((stid, name, content, infodata))
        except Exception:
            continue

    if not entries:
        return []

    entries.sort(key=lambda x: int(x[0]))

    groups = []
    current = [entries[0]]
    has_non_choose = (
        entries[0][2].get("structure_type", "") != "collector.choose"
    )

    for i in range(1, len(entries)):
        prev_stid = int(entries[i - 1][0])
        curr_stid = int(entries[i][0])
        stype = entries[i][2].get("structure_type", "")

        if curr_stid - prev_stid > 1:
            # stid 断档 → 新试卷
            groups.append(current)
            current = [entries[i]]
            has_non_choose = (stype != "collector.choose")
        elif stype == "collector.choose" and has_non_choose:
            # 又出现 choose 且前面已有非 choose → 12 题试卷边界
            groups.append(current)
            current = [entries[i]]
            has_non_choose = False
        else:
            current.append(entries[i])
            if stype != "collector.choose":
                has_non_choose = True

    groups.append(current)

    exams = []
    for g in groups:
        items = [(stid, name, content, infodata)
                 for stid, name, content, infodata in g]
        items.sort(key=lambda x: int(x[0]))
        exams.append(items)

    # 按最早修改时间排序
    exams.sort(key=lambda e: min(
        os.path.getmtime(os.path.join(root_dir, name))
        for _, name, _, _ in e
    ))

    # ── 合并通道 ──
    # 连续的非标准试卷若合并后满足标准 12 题模式，则合并为同一套。
    merged = []
    i = 0
    while i < len(exams):
        if _is_valid_exam(exams[i]):
            merged.append(exams[i])
            i += 1
            continue

        # 收集连续非标准组
        combined = list(exams[i])
        j = i + 1
        while j < len(exams) and not _is_valid_exam(exams[j]):
            combined.extend(exams[j])
            j += 1

        if _is_valid_exam(combined):
            _sort_exam_order(combined)
            merged.append(combined)
        else:
            for k in range(i, j):
                merged.append(exams[k])

        i = j

    return merged


def exam_summary(items, root_dir):
    dates = set()
    for _, name, _, _ in items:
        d = os.path.join(root_dir, name)
        dates.add(datetime.fromtimestamp(os.path.getmtime(d)).strftime("%Y-%m-%d"))

    date_str = "/".join(sorted(dates))
    type_question_counts = defaultdict(int)
    total_questions = 0
    for _, _, content, _ in items:
        stype = content.get("structure_type", "?")
        label = _TYPE_NAMES.get(stype, stype)
        if stype == "collector.choose":
            n = len(content["info"].get("xtlist", []))
        else:
            n = 1
        type_question_counts[label] += n
        total_questions += n

    type_summary = "、".join(
        f"{k}×{v}" for k, v in type_question_counts.items())
    status = "" if _is_valid_exam(items) else " [非标准]"
    return f"{date_str} — {total_questions} 题（{type_summary}）{status}"


# ═══════════════════════════════════════════════════
# Section 命名
# ═══════════════════════════════════════════════════

def _is_valid_exam(items):
    """检查是否为标准的 12 题试卷（按题型计数匹配，不要求顺序）"""
    if len(items) != 12:
        return False
    item_types = [item[2].get("structure_type", "") for item in items]
    return Counter(item_types) == Counter(_EXPECTED_TYPES)


# structure_type → 标准试卷中的位置序号（用于排序）
_TYPE_ORDER = {t: i for i, t in enumerate(_EXPECTED_TYPES)}


def _sort_exam_order(items):
    """按标准试卷题型顺序排列（choose×5 → word×2 → read×1 →
       dialogue×1 → picture×1 → dialogue×2），同题型先按无 passage 优先、
      再按 stid 升序。"""
    def sort_key(item):
        content = item[2]
        stype = content.get("structure_type", "")
        type_pos = _TYPE_ORDER.get(stype, 99)
        # 无 st_nr / value 的排在前面（Section A 短对话、快速应答等）
        info = content.get("info", {})
        has_passage = bool(
            (info.get("st_nr") or info.get("value") or "").strip())
        return (type_pos, has_passage, int(item[0]))
    items.sort(key=sort_key)


def build_section_map(items):
    """生成 section 名称映射。

    标准 12 题试卷使用固定 section 名（Section A/B、朗读句子、
    情景提问、图片描述、快速应答、简述和回答）。
    非常规试卷按 structure_type + 序号自动命名。
    """
    items.sort(key=lambda x: int(x[0]))

    if _is_valid_exam(items):
        _sort_exam_order(items)
        return {item[0]: name for item, name in zip(items, _EXAM_SECTION_NAMES)}

    # 非常规试卷：按 structure_type 块自动命名
    section_map = {}
    type_blocks = []

    i = 0
    while i < len(items):
        stid = items[i][0]
        stype = items[i][2].get("structure_type", "")
        j = i + 1
        while j < len(items):
            next_stid = items[j][0]
            next_stype = items[j][2].get("structure_type", "")
            if next_stype != stype or int(next_stid) != int(stid) + (j - i):
                break
            j += 1
        type_blocks.append((stype, i, j))
        i = j

    type_counters = defaultdict(int)
    for stype, start, end in type_blocks:
        type_counters[stype] += 1
        total = sum(1 for t, _, _ in type_blocks if t == stype)
        if total > 1:
            section_name = f"{_TYPE_NAMES.get(stype, stype)} {type_counters[stype]}"
        else:
            section_name = _TYPE_NAMES.get(stype, stype)

        for idx in range(start, end):
            stid = items[idx][0]
            section_map[stid] = section_name

    return section_map


# ═══════════════════════════════════════════════════
# 提取逻辑
# ═══════════════════════════════════════════════════

def extract_exam(items, section_map, q_path, a_path):
    """将一套试卷的题目写入试题文件和答案文件"""
    q_all = []
    a_all = []
    last_section = None
    last_a_section = None
    counters = {}

    q_count = 0
    for stid, name, content, infodata in items:
        stype = content.get("structure_type", "")
        section = section_map.get(stid, _TYPE_NAMES.get(stype, stype))
        topic = content["info"].get("topic", "")
        handler = HANDLERS.get(stype)

        if section != last_section:
            counters[section] = {"passage": 0, "sentence": 0}
            q_all.append("")
            q_all.append("─" * 56)
            header = f"  {section}"
            if topic:
                header += f"  ·  {topic}"
            q_all.append(header)
            q_all.append("─" * 56)
            q_all.append("")
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
                    a_all.append("")
                    a_all.append("─" * 50)
                    a_all.append(f"  {section}")
                    if topic:
                        a_all.append(f"  话题: {topic}")
                    a_all.append("─" * 50)
                    a_all.append("")
                    last_a_section = section
                a_all.append(a_text.rstrip())
        else:
            q_all.append(f"[未支持题型: {stype}]")

        # 统计本题的小题数
        if stype == "collector.choose":
            q_count += len(content["info"].get("xtlist", []))
        else:
            q_count += 1

    os.makedirs(os.path.dirname(q_path) or ".", exist_ok=True)

    with open(q_path, "w", encoding="utf-8") as f:
        f.write("\n".join(q_all).strip() + "\n")

    with open(a_path, "w", encoding="utf-8") as f:
        f.write("\n".join(a_all).strip() + "\n")

    return q_count


# ═══════════════════════════════════════════════════
# 交互式选择
# ═══════════════════════════════════════════════════

def _parse_selection(choice, max_n):
    choice = choice.strip().lower()
    if choice in ("all", "a"):
        return list(range(max_n))

    indices = []
    for part in re.split(r"[,\s]+", choice):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            try:
                a, b = part.split("-", 1)
                indices.extend(range(int(a) - 1, int(b)))
            except ValueError:
                print(f"  忽略无效范围: {part}")
        else:
            try:
                indices.append(int(part) - 1)
            except ValueError:
                print(f"  忽略无效编号: {part}")

    return sorted(set(i for i in indices if 0 <= i < max_n))


# ═══════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="从 ETS 原始数据提取试卷")
    parser.add_argument("--dir", default=None,
                        help="输入目录（默认: resource/）")
    parser.add_argument("--list", action="store_true",
                        help="仅列出可提取的试卷")
    parser.add_argument("--exam", type=str, default=None,
                        help="提取指定试卷编号（支持逗号分隔、范围、all）")
    parser.add_argument("--all", action="store_true",
                        help="提取全部试卷")
    parser.add_argument("--output", default=None,
                        help="输出目录（默认: result/）")

    args = parser.parse_args()

    # 确定输入目录
    if args.dir:
        root_dir = os.path.abspath(args.dir)
    else:
        root_dir = os.path.join(os.path.dirname(__file__), "resource")
        if not os.path.isdir(root_dir):
            print(f"错误：未找到默认目录 {root_dir}，请用 --dir 指定")
            sys.exit(1)

    if not os.path.isdir(root_dir):
        print(f"错误：目录不存在 — {root_dir}")
        sys.exit(1)

    # 发现试卷
    exams = discover_exams(root_dir)
    if not exams:
        print(f"在 {root_dir} 中未发现试卷数据")
        sys.exit(1)

    # 确定输出目录
    if args.output:
        out_dir = os.path.abspath(args.output)
    else:
        out_dir = os.path.join(os.path.dirname(__file__), "result")

    # --list 模式
    if args.list:
        print(f"目录: {root_dir}")
        print(f"共发现 {len(exams)} 套试卷：")
        for i, items in enumerate(exams, 1):
            print(f"  {i:>2}. {exam_summary(items, root_dir)}")
        return

    # --all 或 --exam 模式
    if args.all:
        selected = list(range(len(exams)))
    elif args.exam:
        selected = _parse_selection(args.exam, len(exams))
        if not selected:
            print("错误：未选中任何试卷")
            sys.exit(1)
    elif len(exams) == 1:
        selected = [0]
    else:
        # 交互模式
        print(f"目录: {root_dir}")
        print(f"共发现 {len(exams)} 套试卷：")
        for i, items in enumerate(exams, 1):
            print(f"  {i:>2}. {exam_summary(items, root_dir)}")
        print()
        choice = input("请选择要提取的试卷编号（支持多选，如 1,3,5 或 all）：").strip()
        selected = _parse_selection(choice, len(exams))
        if not selected:
            print("未选中任何试卷，退出")
            return

    # 多试卷时输出到独立子文件
    multi = len(selected) > 1 or (len(exams) > 1 and len(selected) == 1)

    total = 0
    for idx in selected:
        items = exams[idx]
        section_map = build_section_map(items)

        if multi:
            label = f"试卷{idx + 1}"
            q_path = os.path.join(out_dir, f"{label}.txt")
            a_path = os.path.join(out_dir, f"答案{idx + 1}.txt")
        else:
            q_path = os.path.join(out_dir, "试题.txt")
            a_path = os.path.join(out_dir, "答案.txt")

        n = extract_exam(items, section_map, q_path, a_path)
        total += n
        print(f"  [{idx + 1}] {exam_summary(items, root_dir)}")
        print(f"       试题 → {q_path}")
        print(f"       答案 → {a_path}")

    print(f"\n完成！共提取 {total} 题（{len(selected)} 套试卷）")


if __name__ == "__main__":
    main()
