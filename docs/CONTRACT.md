# 契约

命令行参数、退出码与 JSON 字段是对外契约。改这些要同步改 `tests/test_scissors.py`。

## 通用约定

- 输入文件按 UTF-8 读取，`\r\n` 与 `\r` 归一为 `\n` 后再比较。除此之外不做任何归一化：空格、缩进、全角半角、编号都算字符，差异即新增。
- 输出为 UTF-8。`--json` 打一行对象；加 `--out` 时同时把全量报告写成文件（屏幕输出受 `--report-limit` 截断，文件不截断）。
- `text` 字段为截断预览，截断处以 `…` 结尾。判定不受截断影响。
- 工具不写输入文件，不产生任何中间文本。

## verify

```
python tools/scissors.py verify --original A --edited B
    [--keep "词1,词2"] [--allow-partial-unit] [--ignore-eof-newline]
    [--json] [--out report.json] [--report-limit 12]
```

判据：`B` 的字符序列是 `A` 的字符序列的子序列。不成立即为新增、改写、替换或重排。

| 码 | 条件 |
| --- | --- |
| 0 | 是子序列，且没有阻断项 |
| 1 | 不是子序列 |
| 2 | 是子序列，但删除片段命中保护内容或未落在完整单元边界 |

```json
{
  "ok": true,
  "subsequence": true,
  "original": {"path": "a.md", "chars": 1200},
  "edited":   {"path": "b.md", "chars": 980},
  "deleted":  {"spans": 3, "chars": 220, "ratio": 0.1833},
  "spans": [
    {"start": 120, "end": 180, "chars": 60, "unit": "block+sentence",
     "text": "…", "context_before": "…", "blocked": []}
  ],
  "blocked": [
    {"kind": "protection", "names": ["数字", "单位"], "start": 300, "end": 340, "text": "…"},
    {"kind": "partial_unit", "start": 500, "end": 505, "text": "…"}
  ],
  "added_chars": null
}
```

`unit` 取值：

| 值 | 含义 |
| --- | --- |
| `block+sentence` | 整行删除，且末字符是句末标点或换行 |
| `block` | 整行删除（标题、列表项、表格行） |
| `sentence` | 落在句末标点之间 |
| `partial` | 两端至少有一端不在单元边界上 |

`blocked[].kind` 取值 `protection` 或 `partial_unit`。`protection` 的 `names` 为保护类别，取值固定为：链接、代码、数字、单位、引用、警告、定义、出处、指定保留。

`spans[].start` 与 `end` 是原文字符偏移，左闭右开。

`deleted.ratio` 保留四位小数。`added_chars` 在通过时为 `null`，不通过时为现文比原文多出的字符数下限，仅作提示。

## scan

```
python tools/scissors.py scan --file D [--min-overlap 0.45]
    [--json] [--out report.json] [--report-limit 20]
```

| 码 | 条件 |
| --- | --- |
| 0 | 没有可删候选 |
| 3 | 至少一条可删候选 |
| 5 | 文件读不到 |

```json
{
  "file": "d.md",
  "chars": 257,
  "candidates": [
    {"line": 13, "cat": "收尾", "name": "祈求式收尾", "text": "…",
     "signals": ["套话命中"], "action": "删整句", "blocked_by": []}
  ],
  "summary": {"chars": 257, "paragraphs": 7, "candidates": 8,
              "deletable_candidates": 7, "estimated_deletable_chars": 183,
              "estimated_ratio": 0.7121}
}
```

`action` 取值固定为：`删整句`、`删整段`、`整句保留（按单元完整性不得只删前缀）`、`改正文陈述后删引用块`、`只保留关键结论的加粗`。

`blocked_by` 非空表示该条不可删，其内容与 `names` 同义。`estimated_deletable_chars` 只统计可删条目的预览文本长度，是量级估计，不是精确字数。

工具不输出改写文本，`candidates` 的字段集合是封闭的：出现任何"建议改为"类字段都属于契约破坏。

## code

```
python tools/scissors.py code --repo . [--base HEAD] [--test-cmd "命令"]
    [--json] [--report-limit 15]
```

| 码 | 条件 |
| --- | --- |
| 0 | 没有新增行，且测试（若给出）退出码为 0 |
| 1 | 有新增行，或测试失败 |
| 5 | 不是 git 仓库，或 git 命令失败 |

```json
{
  "repo": ".", "base": "HEAD",
  "added_lines": 0, "deleted_lines": 42,
  "files": [{"path": "src/a.py", "added": 0, "deleted": 42}],
  "added_samples": [], "test_cmd": "pytest -q", "test_exit": 0,
  "only_deletions": true
}
```

`added_samples` 最多 `--report-limit` 行。`test_exit` 在未给 `--test-cmd` 时为 `null`。

## 误报漏报的边界

- `verify` 的判定是精确的：通过就意味着没有新增。它的漏报只有一个方向——删得对不归它管。
- `verify` 的单元边界是启发式，偏差只会多阻断，不会少阻断。
- `scan` 是词典法，会有假阳性（标出作者写的正常过渡）与假阴性（新式套话不入词典）。所以它只给候选，不给结论。
- 三者的共同前提：输入都在本地、可重复读。工具不联网，不调用模型，同一输入永远给同一输出。
