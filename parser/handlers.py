import re
from .cleaners import strip_html, clean, qnum


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
        if show_context and val.strip():
            q_parts.append(f"    {val}")
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

    if passage:
        q_parts.extend(["【阅读短文】", passage, ""])

    askall = info_map.get("askall", "")
    if askall:
        q_parts.append("【题目】")
        for part in askall.split("</br>"):
            if clean(part):
                q_parts.append(clean(part))
        q_parts.append("")

    ask_ids = sorted(
        [k for k in info_map if re.match(r"^ask\d+$", k)],
        key=lambda x: int(re.search(r"\d+", x).group())
    )

    if not askall:
        for aid in ask_ids:
            if clean(info_map[aid]):
                q_parts.extend([f"  {clean(info_map[aid])}", ""])

    questions = cinfo.get("question", [])
    for i, aid in enumerate(ask_ids):
        prompt = clean(info_map[aid])
        if i < len(questions):
            short = prompt[:36] + "..." if len(prompt) > 36 else prompt
            a_parts.append(f"【{short}】")
            for s in questions[i].get("std", [])[:3]:
                ans = clean(s.get("value", "") or s.get("ai", ""))
                if ans:
                    a_parts.append(f"  · {ans}")
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
            if strip_html(line).strip():
                q_parts.append(f"  {strip_html(line).strip()}")
        q_parts.append("")

    std_list = data.get("std", [])
    if std_list:
        a_parts.extend([f"【{topic} — 参考范文】", ""])
        for i, s in enumerate(std_list, 1):
            val = clean(s.get("value", "") or s.get("ai", ""))
            if val:
                a_parts.extend([f"  版本{i}：{val}", ""])

    return "\n".join(q_parts), "\n".join(a_parts)


HANDLERS = {
    "collector.choose": do_choose,
    "collector.word": do_word,
    "collector.read": do_read,
    "collector.dialogue": do_dialogue,
    "collector.picture": do_picture,
}
