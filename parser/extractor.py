import os

from .types import _TYPE_NAMES
from .handlers import HANDLERS


def extract_exam(items, section_map, q_path, a_path):
    q_all, a_all = [], []
    last_section, last_a_section = None, None
    counters = {}
    q_count = 0

    for item in items:
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

    os.makedirs(os.path.dirname(q_path) or ".", exist_ok=True)
    with open(q_path, "w", encoding="utf-8") as f:
        f.write("\n".join(q_all).strip() + "\n")
    with open(a_path, "w", encoding="utf-8") as f:
        f.write("\n".join(a_all).strip() + "\n")

    return q_count
