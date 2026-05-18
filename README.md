# ETS 试卷提取工具

从 ETS 原始数据目录中自动发现并提取试卷，生成纯文本格式的试题文件和答案文件。

## 功能

- **自动发现试卷** — 按 stid 连续性与题型序列自动分组，非标准试卷标注提示
- **多种题型支持** — 标准试卷输出 Section A / Section B / 朗读句子 / 朗读段落 / 情景提问 / 图片描述 / 快速应答 / 简述和回答
- **自动 Section 命名** — 标准 12 题试卷位置对应固定 section 名；非常规试卷按 structure_type + 序号自动命名
- **批量 / 交互提取** — 支持单套、多套、全部提取，交互式或命令行模式

## 目录结构

```
ets/
├── extract_exam.py        # 主脚本
├── main.py                # 入口占位
├── pyproject.toml
├── README.md
├── resource/               # 试卷原始数据目录（约 140 个 hash 子目录）
└── result/                 # 提取结果输出目录
    ├── 试卷1.txt
    ├── 答案1.txt
    ├── 试卷2.txt
    └── 答案2.txt
```

### 原始数据格式

每个题目是一个子目录，包含：

| 文件 | 说明 |
|---|---|
| `content.json` / `content2.json` | 题目内容（含 stid、structure_type、选项、答案） |
| `info.json` | 辅助元数据 |
| `material/` | 音频、图片等素材文件 |

## 使用方法

```bash
# 交互式选择提取（默认使用 resource/ 目录）
python extract_exam.py

# 指定数据目录
python extract_exam.py --dir path/to/data

# 仅列出可用试卷
python extract_exam.py --list

# 提取指定试卷（支持 1,3,5 / 1-5 / all）
python extract_exam.py --exam 1
python extract_exam.py --exam 1,3,5
python extract_exam.py --exam 1-5
python extract_exam.py --all

# 指定输出目录
python extract_exam.py --all --output my_results
```

### CLI 参数

| 参数 | 说明 |
|---|---|
| `--dir DIR` | 输入目录（默认: `resource/`） |
| `--list` | 仅列出试卷，不提取 |
| `--exam N` | 提取指定编号试卷（支持逗号分隔、范围、all） |
| `--all` | 提取全部试卷 |
| `--output DIR` | 输出目录（默认: `result/`） |

## 试卷发现机制

1. 扫描输入目录下所有子目录，跳过 `common` 等辅助目录
2. 读取每个题目的 stid 和 structure_type，按 stid 升序排列
3. stid 不连续（gap > 1）→ 新试卷边界
4. 出现 `collector.choose` 且前面已有非 choose 题型 → 新一个 12 题试卷边界
5. 每组 12 题且题型序列匹配标准模式的为标准试卷，其他为 [非标准]
6. 按最早修改时间排序展示

## 标准试卷 Section 结构

每套标准试卷共 12 题，题型序列固定，section 名对应如下：

| 位置 | structure_type | Section 名 | 说明 |
|---|---|---|---|
| 1–2 | `collector.choose` | Section A | 短对话单选 |
| 3–5 | `collector.choose` | Section B | 长对话 / 短文单选 |
| 6–7 | `collector.word` | 朗读句子 | 跟读句子 |
| 8 | `collector.read` | 朗读段落 | 朗读段落 |
| 9 | `collector.dialogue` | 情景提问 | 阅读短文 + 提问 |
| 10 | `collector.picture` | 图片描述 | 看图说话 + 参考范文 |
| 11 | `collector.dialogue` | 快速应答 | 情景应答 |
| 12 | `collector.dialogue` | 简述和回答 | 阅读短文 + 简述 |
