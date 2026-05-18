"""从 ETS 原始数据中提取试卷 — 题目和答案严格分开"""
import os
import json
import re

BASE_DIR = os.path.join(os.path.dirname(__file__), "ets原始数据")


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def strip_html(text):
    text = re.sub(r"</p>\s*<p>", " ", str(text))
    text = re.sub(r"<[^>]+>", "", text)
    return text


def clean(text):
    """去除 ets_th 前缀和多余空白"""
    text = re.sub(r"^ets_th\d+\s*", "", strip_html(text)).strip()
    return text


def qnum(nr):
    """提取纯数字题号"""
    return nr.strip().rstrip(".")


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

        # 生成题目文本
        if re.match(r"^\d+\.?$", nr):
            # nr 只是数字，题目在 val 里
            n = qnum(nr)
            q_text = re.sub(rf"^{re.escape(n)}\.\s*", "", val)
            label = f"{n}. {q_text}"
            show_context = False  # val 就是题目本身，不用重复
        else:
            # nr 就是完整题目文本，val 是对话/题干
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
    # 去掉原始数据中自带的题号
    val = re.sub(r'^\d+\.\s*', '', val)
    return f"{sentence_num}. {val}\n", ""


def do_read(content, info):
    """短文朗读"""
    val = clean(content["info"].get("value", ""))
    return val + "\n", ""


def do_dialogue(content, info):
    """情景问答 — 题目只放题干，答案只放参考回答"""
    cinfo = content["info"]
    info_map = {it["code_id"]: it["code_value"] for it in info}

    q_parts = []
    a_parts = []

    # 阅读短文
    passage = clean(cinfo.get("value", ""))
    if passage:
        q_parts.append("【阅读短文】")
        q_parts.append(passage)
        q_parts.append("")

    # 题干（askall）
    askall = info_map.get("askall", "")
    if askall:
        q_parts.append("【题目】")
        for part in askall.split("</br>"):
            part = clean(part)
            if part:
                q_parts.append(part)
        q_parts.append("")

    # 小题
    ask_ids = sorted(
        [k for k in info_map if re.match(r"^ask\d+$", k)],
        key=lambda x: int(re.search(r"\d+", x).group())
    )

    # 只在没有 askall 时才逐个输出到题目（有 askall 时信息已包含）
    if not askall:
        for i, aid in enumerate(ask_ids):
            prompt = clean(info_map[aid])
            if prompt:
                q_parts.append(f"  {prompt}")
                q_parts.append("")

    # 答案：每个小题的参考回答
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
    """看图说话 — 题目放话题+要点，答案放范文"""
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

    # 范文 → 答案
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


# ═══════════════════════════════════════════════════

# stid → 题型名称（同一名称的连续 stid 会合并）
SECTION_MAP = {
    "353672": "Section A",
    "353673": "Section A",
    "353674": "Section B",
    "353675": "Section B",
    "353676": "Section B",
    "353677": "朗读句子",
    "353678": "朗读句子",
    "353679": "朗读段落",
    "353680": "情景提问",
    "353681": "图片描述",
    "353682": "快速应答",
    "353683": "简述和回答",
}

HANDLERS = {
    "collector.choose":   do_choose,
    "collector.word":     do_word,
    "collector.read":     do_read,
    "collector.dialogue": do_dialogue,
    "collector.picture":  do_picture,
}


def main():
    items = []
    for name in os.listdir(BASE_DIR):
        d = os.path.join(BASE_DIR, name)
        if not os.path.isdir(d):
            continue
        c2 = os.path.join(d, "content2.json")
        if not os.path.exists(c2):
            c2 = os.path.join(d, "content.json")
        info = os.path.join(d, "info.json")
        try:
            content = load_json(c2)
            infodata = load_json(info)
            stid = content["info"].get("stid", "999999")
            items.append((stid, name, content, infodata))
        except Exception as e:
            print(f"[跳过] {name}: {e}")

    items.sort(key=lambda x: x[0])

    # 按 section 名合并：连续同名 stid 归入一个 section，只输出一个标题
    q_all = []
    a_all = []
    last_section = None
    last_a_section = None
    counters = {}  # section -> {"passage": 0, "sentence": 0}

    for stid, name, content, infodata in items:
        stype = content.get("structure_type", "")
        section = SECTION_MAP.get(stid, stype)
        handler = HANDLERS.get(stype)
        topic = content["info"].get("topic", "")

        # 新 section 初始化计数器
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
            # 传递序号给 handler
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
                # 答案也按 section 合并标题
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

    # 写入
    out = os.path.dirname(__file__)
    q_path = os.path.join(out, "试题.txt")
    a_path = os.path.join(out, "答案.txt")

    with open(q_path, "w", encoding="utf-8") as f:
        f.write("\n".join(q_all).strip() + "\n")

    with open(a_path, "w", encoding="utf-8") as f:
        f.write("\n".join(a_all).strip() + "\n")

    print(f"完成！共处理 {len(items)} 个题目")
    print(f"  试题 → {q_path}")
    print(f"  答案 → {a_path}")


if __name__ == "__main__":
    main()
