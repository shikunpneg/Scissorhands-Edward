# 运行与排错

## 跑测试

```
python tests/test_scissors.py
```

不装依赖。26 个用例，约 4 秒。退出码 0 即全绿。

## 跑门禁

```
python tools/scissors.py verify --original 原文.md --edited 现文.md
python tools/scissors.py verify --original 原文.md --edited 现文.md --json --out report.json
python tools/scissors.py scan --file 文档.md
python tools/scissors.py code --repo . --test-cmd "pytest -q"
```

交付前必须看到退出码 0。看到 1 或 2 就不交付。

## 安装与更新

```
pwsh -File install.ps1                 # 装到 ~/.dsh/skills
pwsh -File install.ps1 -Scope Project  # 装到 <当前目录>/.dsh/skills
pwsh -File install.ps1 -Force          # 覆盖已装版本
```

安装做三件事：校验每个 SKILL.md 的 frontmatter、跑一遍测试、把 `skills/*` 复制到目标根目录；`User` 作用域还会把整个仓库复制到 `~/.dsh/scissorhands/`，让 skill 里引用的 `tools/scissors.py` 有稳定路径。

更新：改完仓库里的文件，重跑 `install.ps1 -Force`。skill 正文每次加载都会重读磁盘，frontmatter 变化才需要重装。

卸载：删掉 `~/.dsh/skills/scissorhands*` 与 `~/.dsh/scissorhands`；项目作用域删掉 `<项目>/.dsh/skills/scissorhands*`。

安装后 skill 出现在下一次会话的目录里；当前会话如果没显示，开新会话。

## 控制台乱码

`scissors.py` 固定按 UTF-8 输出，便于进 CI 和进 JSON。中文 Windows 控制台可能显示乱码，两种解法：

```
chcp 65001                          # 换代码页
$env:PYTHONUTF8 = "1"               # 让 Python 全链路 UTF-8
```

这只是显示问题，不影响判定和退出码。

## 接 CI

```
python tools/scissors.py verify --original base/doc.md --edited doc.md
if ($LASTEXITCODE -ne 0) { exit 1 }
```

`verify` 的退出码可以直接当守门条件：1 表示有人在删的同时加了东西，2 表示删到了数据或删破了单元边界。

对代码删减类提交：

```
python tools/scissors.py code --base origin/main --test-cmd "pytest -q"
```

## 常见错误

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 退出码 1，但"我只是删了" | 删除时顺手动过标点、空格、缩进，或把两段接起来补了过渡 | 撤回，只保留删除动作 |
| 退出码 2，`names` 含"数字" | 被删句子带数据 | 整句补回；需要删前缀时属于改写，不走这条路 |
| 退出码 2，`unit` 为 `partial` | 删除切在句子中间 | 扩到句末标点，或缩回整句 |
| 退出码 3 但都是"整句保留" | 候选全部含保护内容 | 正常，说明文档没有可删废话，退出码按 0 处理 |
| 退出码 5 | 不是 git 仓库，或路径写错 | 修命令，不要当成通过 |
| `scan` 把正常过渡标成候选 | 词典法的假阳性 | 人工复核；`blocked_by` 非空的条目一律不删 |
| 装完 skill 没出现 | 会话目录是启动时快照 | 开新会话 |

## 维护词典

废话语料在 `tools/scissors.py` 的 `FAT` 表里，每条形如 `(类别, 名称, 正则, 强度)`。

新增前先想清楚强度：`strong` 表示单信号即可删，只给四类零信息的套话；其余一律 `weak`，要第二个信号才成为候选。

加完必须跑测试，特别是 `test_clean_doc_has_no_deletable_candidate` 这条假阳性控制：新词把干净文档标出候选，说明收得太宽，测试会失败。

保护清单在 `PROTECTIONS` 里，同样是正则表。往里加比往外拿安全：多加一条最多让工具少删，少加一条会让数据被删掉。
