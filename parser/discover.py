from collections import Counter, defaultdict
from datetime import datetime

from reader.base import FileReader
from .types import _EXPECTED_TYPES, _EXAM_SECTION_NAMES, _TYPE_NAMES, _TYPE_ORDER


def _safe_int(v, default=-1):
    try:
        return int(v)
    except (ValueError, TypeError):
        return default


def _stid(entry):
    """Safely parse stid from an entry tuple; returns -1 on failure."""
    try:
        return int(entry[0])
    except (ValueError, TypeError, IndexError):
        return -1


def discover_exams(reader: FileReader):
    """Discover and organize exams from reader data.

    Calls the reader's platform-specific raw data discovery, then applies
    cross-platform grouping, validation, and merging logic.
    """
    entries = reader.discover_raw_entries()
    if not entries:
        return []

    entries.sort(key=_stid)

    # --- Group entries by stid continuity and type transitions ---
    groups = []
    current = [entries[0]]
    has_non_choose = (entries[0][2].get("structure_type", "") != "collector.choose")

    for i in range(1, len(entries)):
        prev_stid = _stid(entries[i - 1])
        curr_stid = _stid(entries[i])
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
            if stype != "collector.choose":
                has_non_choose = True

    groups.append(current)

    exams = []
    for g in groups:
        items = sorted(g, key=_stid)
        exams.append(items)

    exams.sort(key=lambda e: min(item[4] for item in e))

    # --- Merge adjacent non-standard groups if they form a valid exam ---
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
            for k in range(i, j):
                merged.append(exams[k])
        i = j

    return merged


def _is_valid_exam(items):
    return (
        len(items) == 12
        and Counter(item[2].get("structure_type", "") for item in items)
        == Counter(_EXPECTED_TYPES)
    )


def _sort_exam_order(items):
    def sort_key(item):
        content = item[2]
        stype = content.get("structure_type", "")
        type_pos = _TYPE_ORDER.get(stype, 99)
        info = content.get("info", {})
        has_passage = bool((info.get("st_nr") or info.get("value") or "").strip())
        return (type_pos, has_passage, _stid(item))

    items.sort(key=sort_key)


def build_section_map(items):
    _sort_exam_order(items) if _is_valid_exam(items) else items.sort(key=_stid)
    if _is_valid_exam(items):
        return {item[0]: name for item, name in zip(items, _EXAM_SECTION_NAMES)}

    section_map, type_blocks, i = {}, [], 0
    while i < len(items):
        stid_str, stype = items[i][0], items[i][2].get("structure_type", "")
        stid_num = _safe_int(stid_str)
        j = i + 1
        while j < len(items) and items[j][2].get("structure_type", "") == stype and _stid(items[j]) == stid_num + (j - i):
            j += 1
        type_blocks.append((stype, i, j))
        i = j

    type_counters = defaultdict(int)
    for stype, start, end in type_blocks:
        type_counters[stype] += 1
        total = sum(1 for t, _, _ in type_blocks if t == stype)
        section_name = (
            f"{_TYPE_NAMES.get(stype, stype)} {type_counters[stype]}"
            if total > 1
            else _TYPE_NAMES.get(stype, stype)
        )
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
