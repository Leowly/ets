# ETS 试卷提取工具

从 ETS 原始数据目录中自动发现并提取试卷，生成纯文本格式的试题文件及答案文件。

Android 通过 Shizuku rish 远程读取，其他平台（Windows / Linux / macOS）直接读取本地文件系统。

## 快速开始

```bash
# 确保 resource/ 在脚本同目录下，然后运行
python main.py

# 仅列出可用试卷
python main.py --list

# 提取所有试卷
python main.py --all
```

## 使用方式

```bash
# 提取指定编号（支持 1,3,5 / 1-5 / all）
python main.py --exam 1
python main.py --exam 1,3,5
python main.py --exam 1-5

# 指定输出目录（默认 ./result）
python main.py --all --output my_results

# 指定数据目录（覆盖默认路径）
python main.py --dir path/to/resource
```

## 平台检测与数据源

脚本启动时按以下逻辑选择读取方式：

```
Android?
├── rish 可用 → 通过 rish 读取 Android data 目录
├── rish 不可用，但 resource/ 存在 → 提示后回退到本地读取
└── 都没有 → 报错，给出两条解决路径

非 Android（Windows / Linux / macOS）?
├── resource/ 存在 → 本地读取
└── 不存在 → 报错，给出两条解决路径
```

### 默认路径

| 场景 | 默认数据目录 | 读取方式 |
|---|---|---|
| Android + rish | `/storage/.../ETS_secondary/resource` | Shizuku rish |
| 本地回退 / 非 Android | `main.py 同目录下的 resource/` | 本地文件系统 |

`--dir` 参数始终可以覆盖默认值。

### 配置 DEFAULT_LOCAL_DIR

默认本地路径由 `main.py` 顶部的 `DEFAULT_LOCAL_DIR` 变量决定：

```python
DEFAULT_LOCAL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resource")
```

如果你的 resource 目录不在脚本同目录下，可以先尝试 `--dir` 参数。如果希望持久化更改，修改 `DEFAULT_LOCAL_DIR` 的值。需要注意 `DEFAULT_LOCAL_DIR` 仅在非 rish 模式下生效，Android 上 rish 可用时仍会走 `DEFAULT_RISH_DIR`。

### CLI 参数

| 参数 | 说明 |
|---|---|
| `--dir DIR` | 数据源目录 |
| `--list` | 仅列出试卷，不提取 |
| `--exam N` | 提取指定编号（逗号分隔、范围、all） |
| `--all` | 提取全部试卷 |
| `--output DIR` | 输出目录（默认: `./result`） |

## 找不到数据目录怎么办

脚本会在启动时检查数据源是否可用，如果不可用会打印具体提示。对应各种场景的解决方法：

| 场景 | 方案 A | 方案 B |
|---|---|---|
| Android 无 rish 也无本地 resource | 下载配置 Shizuku + rish | 将 resource 目录复制到脚本同目录 |
| 非 Android 无本地 resource | 修改 `DEFAULT_LOCAL_DIR` 指向正确路径 | 复制 resource 目录到脚本同目录 |

## 项目结构

```
ets/
├── main.py                 # 入口脚本
├── reader/                 # 文件读取层
│   ├── base.py             #   FileReader 抽象基类
│   ├── rish.py             #   PersistentRish + RishFileReader (Android)
│   └── local.py            #   LocalFileReader (本地)
├── parser/                 # 内容解析层（平台无关）
│   ├── cleaners.py         #   HTML 清洗 / 文本清理
│   ├── types.py            #   题型常量定义
│   ├── handlers.py         #   各题型处理器
│   ├── discover.py         #   试卷发现、分组、校验、合并
│   └── extractor.py        #   提取输出
└── utils/
    └── selector.py         #   用户选择解析
```

### 原始数据格式

每个题目是一个子目录（hash 命名），包含：

| 文件 | 说明 |
|---|---|
| `content.json` / `content2.json` | 题目内容（stid、structure_type、选项、答案） |
| `info.json` | 辅助元数据 |
| `material/` | 音频、图片等素材 |

## 试卷发现机制

1. 扫描数据目录下所有子目录
2. 读取每个题目的 stid 和 structure_type，按 stid 升序排列
3. stid 不连续（gap > 1）→ 新试卷边界
4. 出现 `collector.choose` 且前面已有非 choose 题型 → 新 12 题试卷边界
5. 每组 12 题且题型序列匹配标准模式 → 标准试卷，否则标注 [非标准]
6. 按最早修改时间排序展示

## 标准试卷 Section 结构

每套标准试卷共 12 题，题型序列固定：

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
