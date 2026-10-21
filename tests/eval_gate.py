#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在真实文档上验一遍门禁：该拦的拦不拦，该放的放不放。

    python tests/eval_gate.py                  # 默认拿 README.md 当靶子
    python tests/eval_gate.py --doc docs/DESIGN.md

七种改法都是程序生成的，不靠手写例子：删干净整节、原样返回、改一个标点、
末尾补一句、对调两节、删带数字的句子、删半句。每种都有预期退出码，
跑完对一遍，给出符合与不符的条数。
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(ROOT, "tools", "scissors.py")

sys.path.insert(0, os.path.join(ROOT, "tools"))
import scissors  # noqa: E402  只用来挑"干净"的删除位置，判定仍走命令行

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def sections(text):
    """按二级标题切节，返回 [(start, end)]。"""
    marks = [m.start() for m in __import__("re").finditer(r"(?m)^## ", text)]
    if not marks:
        return []
    out = []
    for i, start in enumerate(marks):
        end = marks[i + 1] if i + 1 < len(marks) else len(text)
        out.append((start, end))
    return out


def clean(text):
    """只有硬阻断才算脏；行内代码是提示级，不参与挑位置。"""
    return not any(sev == "block" for _n, _t, sev in scissors.find_protections(text))


def find_clean_section(text):
    for start, end in reversed(sections(text)):
        if clean(text[start:end]):
            return start, end
    return None


def find_dirty_sentence(text):
    for start, end in scissors.paragraphs(text):
        for s, e in scissors.sentences(text, start, end):
            frag = text[s:e]
            if scissors.find_protections(frag) and len(frag.strip()) > 6:
                return s, e
    return None


def find_cuttable_clause(text):
    """找一句前半段可以单独删掉、且不含保护内容的子句。"""
    for start, end in scissors.paragraphs(text):
        for s, e in scissors.sentences(text, start, end):
            frag = text[s:e]
            pos = frag.find("，")
            if 4 < pos < len(frag) - 4 and clean(frag[:pos]):
                return s, s + pos + 1
    return None


def cases(text):
    out = []

    sec = find_clean_section(text)
    if sec:
        s, e = sec
        out.append(("删掉一整节（干净，应放行）", text[:s] + text[e:], 0))
    out.append(("原样返回", text, 0))

    pos = text.find("，")
    if pos > 0:
        out.append(("改一个标点（，→、）", text[:pos] + "、" + text[pos + 1:], 1))
    out.append(("末尾补一句", text + "以上。\n", 1))

    secs = sections(text)
    if len(secs) >= 2:
        a, b = secs[-2], secs[-1]
        swapped = text[:a[0]] + text[b[0]:] + text[a[0]:b[0]]
        out.append(("对调最后两节（重排）", swapped, 1))

    dirty = find_dirty_sentence(text)
    if dirty:
        s, e = dirty
        out.append(("删掉带数字的句子（应阻断）", text[:s] + text[e:], 2))

    clause = find_cuttable_clause(text)
    if clause:
        s, e = clause
        out.append(("只删半句（应阻断）", text[:s] + text[e:], 2))

    return out


def run_tool(orig_path, edited_path):
    r = subprocess.run(
        [sys.executable, TOOL, "verify", "--original", orig_path, "--edited", edited_path,
         "--json"],
        capture_output=True, text=True, encoding="utf-8")
    return r.returncode, (json.loads(r.stdout) if r.stdout.strip() else {})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc", default=os.path.join(ROOT, "README.md"))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    with open(args.doc, encoding="utf-8", newline="") as f:
        text = f.read().replace("\r\n", "\n")

    tmp = tempfile.mkdtemp(prefix="scissors-eval-")
    orig = os.path.join(tmp, "orig.md")
    with open(orig, "w", encoding="utf-8", newline="") as f:
        f.write(text)

    rows = []
    for name, edited, expect in cases(text):
        path = os.path.join(tmp, "edited.md")
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(edited)
        code, rep = run_tool(orig, path)
        rows.append({
            "case": name,
            "expect": expect,
            "actual": code,
            "pass": code == expect,
            "deleted_ratio": rep.get("deleted", {}).get("ratio"),
            "blocked_names": sorted({n for b in rep.get("blocked", []) for n in b.get("names", [])}),
        })

    ok = sum(1 for r in rows if r["pass"])
    if args.json:
        print(json.dumps({"doc": args.doc, "rows": rows, "passed": ok, "total": len(rows)},
                         ensure_ascii=False, indent=2))
    else:
        print("靶子：{}".format(os.path.relpath(args.doc, ROOT)))
        print("{:<26} {:>4} {:>4}  {}".format("用例", "预期", "实际", "结果"))
        for r in rows:
            print("{:<26} {:>4} {:>4}  {}".format(
                r["case"], r["expect"], r["actual"], "符合" if r["pass"] else "不符"))
        print("符合 {}/{}".format(ok, len(rows)))
    return 0 if ok == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
