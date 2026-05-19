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
    "collector.choose": "听力选择",
    "collector.word": "朗读句子",
    "collector.read": "朗读段落",
    "collector.dialogue": "情景对话",
    "collector.picture": "图片描述",
}

_TYPE_ORDER = {t: i for i, t in enumerate(_EXPECTED_TYPES)}
