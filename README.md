# ETS 试卷提取工具

从 ETS 原始数据目录中自动发现并提取试卷，生成纯文本格式的试题文件和答案文件。

## 功能

- **自动发现试卷** — 扫描目录下的题目数据目录，按修改时间聚类分组，自动识别多套试卷
- **多种题型支持** — 听力选择、朗读句子、朗读段落、情景对话、图片描述
- **自动 Section 命名** — 根据题型和 stid 连续性自动生成中文 section 标题，同一题型非连续块自动加序号
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
2. 按目录修改时间排序
3. 相邻目录修改时间差 < 2 小时的归为同一套试卷（同套试卷同时下载）
4. 每套试卷内部按 stid 排序
5. 按日期 + 题型分布展示摘要

## 支持题型

| structure_type | 题型 | 说明 |
|---|---|---|
| `collector.choose` | 听力选择 | 阅读理解 + 单选题 |
| `collector.word` | 朗读句子 | 跟读句子 |
| `collector.read` | 朗读段落 | 跟读段落 |
| `collector.dialogue` | 情景对话 | 阅读短文 + 问答 |
| `collector.picture` | 图片描述 | 看图说话 + 参考范文 |
