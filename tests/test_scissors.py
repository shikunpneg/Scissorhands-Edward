#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""剪刀手门禁的端到端冒烟用例。

运行：python tests/test_scissors.py
只依赖标准库与 git。
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TOOL = os.path.join(ROOT, "tools", "scissors.py")
SKILLS = os.path.join(ROOT, "skills")
FIXTURES = os.path.join(ROOT, "tests", "fixtures")

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def run_tool(*args, cwd=None):
    return subprocess.run(
        [sys.executable, TOOL, *args],
        cwd=cwd or ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


class Pair:
    """把原文与现文写进临时目录，跑 verify。"""

    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="scissors-")
        self.orig = os.path.join(self.dir, "orig.md")
        self.edited = os.path.join(self.dir, "edited.md")

    def write(self, original, edited):
        for path, text in ((self.orig, original), (self.edited, edited)):
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(text)
        return self

    def verify(self, *extra):
        return run_tool("verify", "--original", self.orig, "--edited", self.edited, *extra)

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


ORIG = (
    "# 标题\n"
    "\n"
    "第一段含结论，保持不变。\n"
    "\n"
    "- 列表项一\n"
    "- 列表项二\n"
    "\n"
    "第三段有数据 42% 与链接 https://example.com/a 。\n"
    "\n"
    "## 附录\n"
    "\n"
    "附录正文。\n"
)


class VerifyPass(unittest.TestCase):
    def setUp(self):
        self.p = Pair()

    def tearDown(self):
        self.p.close()

    def test_delete_whole_paragraph(self):
        self.p.write(ORIG, ORIG.replace("- 列表项一\n- 列表项二\n\n", ""))
        r = self.p.verify()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_delete_single_sentence(self):
        self.p.write(ORIG, ORIG.replace("第一段含结论，保持不变。\n", ""))
        r = self.p.verify()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_delete_heading_block(self):
        self.p.write(ORIG, ORIG.replace("## 附录\n\n附录正文。\n", ""))
        r = self.p.verify()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_delete_whole_section_keeps_rest(self):
        self.p.write(ORIG, ORIG.split("\n## 附录")[0] + "\n")
        r = self.p.verify("--ignore-eof-newline")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_identical_is_passthrough(self):
        self.p.write(ORIG, ORIG)
        r = self.p.verify("--json")
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertEqual(data["deleted"]["chars"], 0)
        self.assertEqual(data["deleted"]["spans"], 0)

    def test_empty_edited_passes_only_without_protected_content(self):
        self.p.write("纯套话一段。\n\n另一段套话。\n", "")
        r = self.p.verify()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_delete_everything_with_data_is_blocked(self):
        self.p.write(ORIG, "")
        r = self.p.verify("--json")
        self.assertEqual(r.returncode, 2, r.stdout)


class VerifyFail(unittest.TestCase):
    def setUp(self):
        self.p = Pair()

    def tearDown(self):
        self.p.close()

    def test_rewrite_punctuation_fails(self):
        self.p.write(ORIG, ORIG.replace("第一段含结论，保持不变。", "第一段含结论、保持不变。"))
        r = self.p.verify()
        self.assertEqual(r.returncode, 1, r.stdout)

    def test_addition_fails(self):
        self.p.write(ORIG, ORIG + "\n补充一句本轮新写的。\n")
        r = self.p.verify()
        self.assertEqual(r.returncode, 1, r.stdout)

    def test_reorder_fails(self):
        edited = ORIG.replace("- 列表项一\n- 列表项二\n", "- 列表项二\n- 列表项一\n")
        self.p.write(ORIG, edited)
        r = self.p.verify()
        self.assertEqual(r.returncode, 1, r.stdout)

    def test_reflow_fails(self):
        self.p.write(ORIG, ORIG.replace("第一段含结论，保持不变。", "第一段含结论，\n保持不变。"))
        r = self.p.verify()
        self.assertEqual(r.returncode, 1, r.stdout)


class VerifyProtection(unittest.TestCase):
    def setUp(self):
        self.p = Pair()

    def tearDown(self):
        self.p.close()

    def test_delete_sentence_with_number_blocked(self):
        self.p.write(ORIG, ORIG.replace("第三段有数据 42% 与链接 https://example.com/a 。\n", ""))
        r = self.p.verify("--json")
        self.assertEqual(r.returncode, 2, r.stdout)
        data = json.loads(r.stdout)
        names = {n for b in data["blocked"] for n in b.get("names", [])}
        self.assertIn("数字", names)

    def test_delete_url_blocked(self):
        self.p.write(ORIG, ORIG.replace("\n\n第三段有数据 42% 与链接 https://example.com/a 。", ""))
        r = self.p.verify("--json")
        self.assertEqual(r.returncode, 2)

    def test_delete_code_block_blocked(self):
        orig = "前言句子。\n\n```python\nprint(1)\n```\n\n后记句子。\n"
        self.p.write(orig, "前言句子。\n\n后记句子。\n")
        r = self.p.verify("--json")
        self.assertEqual(r.returncode, 2, r.stdout)
        data = json.loads(r.stdout)
        names = {n for b in data["blocked"] for n in b.get("names", [])}
        self.assertIn("代码", names)

    def test_partial_sentence_blocked(self):
        orig = "虽然如此，整体进度正常，风险可控。\n"
        self.p.write(orig, "整体进度正常，风险可控。\n")
        r = self.p.verify("--json")
        self.assertEqual(r.returncode, 2, r.stdout)
        kinds = {b["kind"] for b in json.loads(r.stdout)["blocked"]}
        self.assertIn("partial_unit", kinds)

    def test_partial_sentence_escape_hatch(self):
        orig = "虽然如此，整体进度正常，风险可控。\n"
        self.p.write(orig, "整体进度正常，风险可控。\n")
        r = self.p.verify("--allow-partial-unit")
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_keep_term_blocked(self):
        self.p.write(ORIG, ORIG.replace("- 列表项一\n- 列表项二\n", "- 列表项二\n"))
        r = self.p.verify("--keep", "列表项一", "--json")
        self.assertEqual(r.returncode, 2, r.stdout)
        data = json.loads(r.stdout)
        self.assertEqual(data["blocked"][0]["names"], ["指定保留"])

    def test_report_schema(self):
        self.p.write(ORIG, ORIG.replace("- 列表项一\n", ""))
        r = self.p.verify("--json")
        data = json.loads(r.stdout)
        for key in ("ok", "subsequence", "deleted", "spans", "blocked"):
            self.assertIn(key, data)
        self.assertEqual(set(data["deleted"]), {"spans", "chars", "ratio"})
        self.assertTrue(all("text" in s and "unit" in s for s in data["spans"]))


class Scan(unittest.TestCase):
    def scan(self, path, *extra):
        r = run_tool("scan", "--file", path, "--json", *extra)
        return r, (json.loads(r.stdout) if r.stdout.strip() else None)

    def test_clean_doc_has_no_deletable_candidate(self):
        r, data = self.scan(os.path.join(FIXTURES, "report_clean.md"))
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(data["summary"]["deletable_candidates"], 0)
        # 含数据的套话句必须标成「保留」，不得建议删
        kept = [c for c in data["candidates"] if c["blocked_by"]]
        self.assertTrue(kept, "含数据的弱套话应被标为保留")
        self.assertTrue(all("整句保留" in c["action"] for c in kept))

    def test_dirty_doc_finds_candidates(self):
        r, data = self.scan(os.path.join(FIXTURES, "report_dirty.md"))
        self.assertEqual(r.returncode, 3, r.stdout)
        self.assertGreater(data["summary"]["deletable_candidates"], 3)
        cats = {c["cat"] for c in data["candidates"]}
        for expected in ("收尾", "开场", "重复总结"):
            self.assertIn(expected, cats)
        self.assertGreater(data["summary"]["estimated_ratio"], 0.05)

    def test_scan_never_proposes_rewrite(self):
        r, data = self.scan(os.path.join(FIXTURES, "report_dirty.md"))
        allowed = {"line", "cat", "name", "text", "signals", "action", "blocked_by"}
        for c in data["candidates"]:
            self.assertEqual(set(c), allowed)
            self.assertIn(c["action"], {"删整句", "删整段", "整句保留（按单元完整性不得只删前缀）",
                                        "改正文陈述后删引用块", "只保留关键结论的加粗"})

    def test_out_file_written(self):
        out = os.path.join(tempfile.mkdtemp(prefix="scissors-out-"), "report.json")
        r = run_tool("scan", "--file", os.path.join(FIXTURES, "report_dirty.md"),
                     "--json", "--out", out)
        self.assertTrue(os.path.exists(out))
        with open(out, encoding="utf-8") as f:
            self.assertGreater(len(json.load(f)["candidates"]), 0)


@unittest.skipUnless(shutil.which("git"), "需要 git")
class CodeGate(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="scissors-git-")
        self.git("init", "-q")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "t")
        self.write("a.py", "def f():\n    return 1\n\n\ndef g():\n    return 2\n")
        self.git("add", "a.py")
        self.git("commit", "-q", "-m", "init")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.dir, capture_output=True, text=True)

    def write(self, name, text):
        with open(os.path.join(self.dir, name), "w", encoding="utf-8") as f:
            f.write(text)

    def gate(self, *extra):
        return run_tool("code", "--repo", self.dir, *extra)

    def test_deletion_only_passes(self):
        self.write("a.py", "def f():\n    return 1\n")
        r = self.gate("--json")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        data = json.loads(r.stdout)
        self.assertTrue(data["only_deletions"])
        self.assertGreater(data["deleted_lines"], 0)
        self.assertEqual(data["added_lines"], 0)

    def test_addition_fails(self):
        self.write("a.py", "def f():\n    return 1\n\n\ndef g():\n    return 2\n\n\ndef h():\n    return 3\n")
        r = self.gate("--json")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertFalse(json.loads(r.stdout)["only_deletions"])

    def test_no_diff_passes(self):
        r = self.gate()
        self.assertEqual(r.returncode, 0, r.stdout)


class SkillManifest(unittest.TestCase):
    def test_every_skill_has_valid_frontmatter(self):
        self.assertTrue(os.path.isdir(SKILLS), "缺少 skills/ 目录")
        dirs = sorted(d for d in os.listdir(SKILLS) if os.path.isdir(os.path.join(SKILLS, d)))
        self.assertGreaterEqual(len(dirs), 5, "减法 skill 应成系列")
        for d in dirs:
            path = os.path.join(SKILLS, d, "SKILL.md")
            self.assertTrue(os.path.exists(path), "缺 " + path)
            with open(path, encoding="utf-8") as f:
                text = f.read()
            self.assertTrue(text.startswith("---\n"), path + " 缺 frontmatter")
            head = text.split("---", 2)[1]
            name = re.search(r"^name:\s*(\S+)\s*$", head, re.M)
            desc = re.search(r"^description:\s*(.+)$", head, re.M)
            self.assertIsNotNone(name, path + " 缺 name")
            self.assertIsNotNone(desc, path + " 缺 description")
            self.assertEqual(name.group(1), d, path + " 的 name 必须等于目录名")
            self.assertRegex(d, r"^[a-z0-9]+(-[a-z0-9]+)*$")
            self.assertGreater(len(desc.group(1)), 20, path + " 的 description 太短")
            body = text.split("---", 2)[2]
            self.assertGreater(len(body), 400, path + " 正文过短")
            self.assertIsNone(re.search(r"^\s*(TODO|FIXME|待补|XXX)\b", body, re.M),
                              path + " 还有待补占位")
            # 全局规则：中文产出不写 AI 味儿
            self.assertFalse(re.search(r"[\u2705\u274c\u2714\u2716\u26a0\ufe0f]", body), path + " 含表情符号")
            self.assertFalse(re.search(r"[┌┐└┘├┤┬┴┼│─]", body), path + " 含方框画图")


class DocHygiene(unittest.TestCase):
    """仓库里的中文文档也要过同一套自查：没有装饰符号，没有方框画图。"""

    def docs(self):
        paths = [os.path.join(ROOT, "README.md")]
        docdir = os.path.join(ROOT, "docs")
        if os.path.isdir(docdir):
            paths += [os.path.join(docdir, n) for n in sorted(os.listdir(docdir)) if n.endswith(".md")]
        return paths

    def test_no_decoration_in_docs(self):
        for path in self.docs():
            with open(path, encoding="utf-8") as f:
                text = f.read()
            self.assertFalse(re.search(r"[\u2705\u274c\u2714\u2716\u26a0\ufe0f\u2b50\u2728]", text),
                             path + " 含表情符号")
            self.assertFalse(re.search(r"[┌┐└┘├┤┬┴┼│─╔╗╚╝║═]", text), path + " 含方框画图")
            self.assertNotIn("！！！", text, path + " 含堆叠感叹号")

    def test_install_script_keeps_bom(self):
        path = os.path.join(ROOT, "install.ps1")
        with open(path, "rb") as f:
            head = f.read(3)
        self.assertEqual(head, b"\xef\xbb\xbf",
                         "install.ps1 必须以 UTF-8 BOM 保存，否则 Windows PowerShell 5.1 解析中文会报错")


if __name__ == "__main__":
    unittest.main(verbosity=2)
