#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""剪刀手 · 减法门禁。

只判定与报告，不改写任何文本。三个子命令：

  verify  校验 edited 是否 original 的严格子序列（只删不改），并检查
          删除单元完整性、保护内容是否被删。
  scan    标出套话 / 空洞评价 / 重复总结 的候选单元；含数据、引用、代码的
          句子直接判为不可删，并说明原因。
  code    校验一次代码改动是否「只有删除行」。

退出码：
  0 通过（scan：无候选）
  1 出现新增（verify：非子序列；code：有新增行或测试失败）
  2 删除越界（动了保护内容，或删除没落在完整单元边界上）
  3 scan 找到候选（仅 scan）
  5 环境或用法错误
"""

import argparse
import difflib
import json
import re
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ---------------------------------------------------------------- 常量

TERMINATORS = set("。！？!?；;…\n")

# 删除片段必须落在「句子边界」或「块边界」上，否则判为非完整单元。
# 块边界 = 行首到行尾（覆盖标题、列表项、表格行、代码块内的整行）。
#
# severity：block = 直接阻断（不可复现的数据、可执行内容、用户点名项）；
#           warn  = 只提示（行内代码这种"术语提法"，抹掉通常还能从别处找回）。

PROTECTIONS = [
    ("链接", r"https?://\S+|www\.\S+|\b\S+@\S+\.\S+\b|\[[^\]]+\]\([^)]+\)", "block"),
    ("围栏", r"```", "block"),
    ("行内代码", r"`[^`\n]+`", "warn"),
    ("数字", r"[0-9]", "block"),
    ("单位", r"[0-9]\s*(%|％|倍|万|亿|ms|s\b|GB|MB|KB|TB|元|人|次|天|年|月|小时|分钟|页|字|行)", "block"),
    ("引用", r"《[^》]+》|「[^」]+」|『[^』]+』|“[^”]+”", "block"),
    ("警告", r"警告|注意：|注意:|风险|禁止|不得|必须|不要|勿|deprecated|WARNING|CAUTION", "block"),
    ("定义", r"是指|指的是|定义为|即\s|means|refers to|is defined as", "block"),
    ("出处", r"\[\d+\]|doi:|arXiv|来源：|来源:|参见|引用自", "block"),
]

FAT = [
    # (类别, 名称, 正则, 强度)  strength: strong=命中即可删, weak=需第二信号
    ("开场", "自问自答或夸问题", r"这是一个(非常)?好的?问题|问得好|好问题|你说得对", "strong"),
    ("开场", "时代背景铺陈", r"在当今(这个)?[^。\n]{0,12}(时代|社会|环境|世界)|随着[^。\n]{0,20}的(不断)?(发展|进步|演进|普及|兴起)", "strong"),
    ("收尾", "祈求式收尾", r"希望(以上|这些|本文|这份)?[^。\n]{0,8}(帮助你|对你有帮助|有所帮助|能帮到你)", "strong"),
    ("收尾", "兜底邀约", r"如需[^。\n]{0,12}(进一步|更多)|如有(任何)?(疑问|问题)[^。\n]{0,10}|欢迎(随时)?(交流|反馈|指正)|随时(联系|找我)", "strong"),
    ("收尾", "免责式结束", r"以上(内容)?(供|仅)供?参考|仅供参考|抛砖引玉", "strong"),
    ("过渡", "提醒式引导", r"值得注意的是|需要(指出|强调|注意)的是|必须指出|值得一提的是", "weak"),
    ("过渡", "推演式引导", r"由此可见|可以看出|不难(发现|看出)|可见", "weak"),
    ("过渡", "复述式转折", r"换句话说|也就是说|换言之|正如(前面|上文|前面提到)[^。\n]{0,6}(所述|提到)", "weak"),
    ("过渡", "下段预告", r"接下来[，,]?\s*(我们|本文|本文中)?|下面(我们)?(来看|介绍|讨论|分)", "weak"),
    ("评价", "空洞分量", r"意义(重大|深远)|具有(重要|深远)意义|至关重要|举足轻重|不容忽视|不可忽视|影响深远", "weak"),
    ("评价", "空洞作用", r"起到了(重要|关键|积极|决定性)?(作用)|发挥了(重要|关键|积极)?(作用)|为[^。\n]{0,12}奠定了[^。\n]{0,8}基础", "weak"),
    ("评价", "空洞优秀", r"非常(出色|优秀|重要|关键)|极其重要|十分必要|大有裨益|具有(很强|较高)的(参考价值|现实意义|指导意义)", "weak"),
    ("元话语", "交代本文结构", r"本(文|回答|节|章|篇)(将|拟|会)(从|围绕|分)|(下面|以下)(先|将)?(分|从)[^。\n]{0,10}(方面|部分|角度)(展开|介绍|说明)|下面(先|将)?(分|从)[^。\n]{0,10}(方面|部分)", "strong"),
    ("元话语", "过程自述", r"我(们)?(先|来|再)(看|说|讲|梳理)|老实说|说实话|值得注意的是", "weak"),
    ("装饰", "装饰符号", r"[\u2705\u274c\u2714\u2716\u26a0\ufe0f\u2b50\u2728\U0001f300-\U0001faff\u25cf\u25c6\u25b6]", "strong"),
    ("装饰", "方框画图", r"[┌┐└┘├┤┬┴┼│─╔╗╚╝║═╠╣╦╩╬]", "strong"),
    ("免责", "条件免责", r"因人而异|视(具体|实际)情况而定|取决于(具体|实际)情况|当然[，,][^。\n]{0,10}(情况|视)", "weak"),
    ("英文", "英文套话", r"(?i)\b(it'?s worth noting|in today'?s|delve into|i hope this helps|let'?s dive in|a testament to|navigate the complexities|at the end of the day|in conclusion|that said,)", "strong"),
]

SUMMARY_MARKERS = re.compile(r"^(综上|总之|总的来说|小结|结论|总结|in summary|to sum up|in conclusion|all in all)", re.I)
TRIPLE = re.compile(r"首先|其次|再次|最后|其一|其二|其三")
HAS_FACT = re.compile(r"[0-9]|[A-Za-z]{2,}|「|“|《")
BLOCK_QUOTE = re.compile(r"^\s*>")


# ---------------------------------------------------------------- 工具函数

def read_text(path):
    with open(path, "r", encoding="utf-8", newline="") as f:
        raw = f.read()
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    return text


def clip(s, n=40):
    s = s.replace("\n", "\\n")
    return s if len(s) <= n else s[: n - 1] + "…"


def align(orig, edited):
    """返回 (是否子序列, 删除片段列表[(start, end)])。

    判定用两指针，这是充要判据；片段划分优先用 SequenceMatcher，
    因为它倾向匹配最长公共块，能把「删掉列表里的一条」还原成整行，
    而不是在字符层面切出半个词。SequenceMatcher 的结果必须能重建出
    现文，否则退回两指针对齐的结果。
    """
    ok, spans = greedy_spans(orig, edited)
    if not ok:
        return False, spans
    better = seqmatch_spans(orig, edited)
    return True, (better if better is not None else spans)


def greedy_spans(orig, edited):
    i = j = 0
    start = -1
    spans = []
    while True:
        if j == len(edited):
            if start != -1:
                spans.append((start, len(orig)))
            elif i < len(orig):
                spans.append((i, len(orig)))
            return True, spans
        if i == len(orig):
            return False, spans
        if orig[i] == edited[j]:
            if start != -1:
                spans.append((start, i))
                start = -1
            i += 1
            j += 1
        else:
            if start == -1:
                start = i
            i += 1


def seqmatch_spans(orig, edited):
    """用最长公共块划分删除片段；无法重建现文时返回 None。"""
    sm = difflib.SequenceMatcher(None, orig, edited, autojunk=False)
    spans = []
    for tag, i1, i2, _j1, _j2 in sm.get_opcodes():
        if tag == "insert":
            return None
        if tag in ("delete", "replace"):
            spans.append((i1, i2))
    kept = []
    last = 0
    for start, end in spans:
        kept.append(orig[last:start])
        last = end
    kept.append(orig[last:])
    return spans if "".join(kept) == edited else None


def unit_kind(orig, start, end):
    """删除片段是否落在完整单元边界上。

    句子边界：片段前一字符与最后字符都是句末标点/换行。
    块边界：片段整行整行地删（可以从行首前一个换行开始，也可以把行尾换行吃掉），
    覆盖标题、列表项、表格行、整行代码。允许空行归属的歧义，所以两端的换行
    在内部或外部都算对齐。
    """
    start_block = (start == 0
                   or orig[start - 1] == "\n"
                   or (start < len(orig) and orig[start] == "\n"))
    end_block = (end == len(orig)
                 or orig[end - 1] == "\n"
                 or (end < len(orig) and orig[end] == "\n"))
    block = start_block and end_block
    sentence = start > 0 and orig[start - 1] in TERMINATORS and orig[end - 1] in TERMINATORS
    if block and sentence:
        return "block+sentence"
    if block:
        return "block"
    if sentence:
        return "sentence"
    return "partial"


def find_protections(text, keep_terms=()):
    """返回 [(名称, 命中文本, 级别)]，级别为 block 或 warn。"""
    hits = []
    for name, pattern, severity in PROTECTIONS:
        for m in re.finditer(pattern, text):
            hits.append((name, m.group(0), severity))
    for term in keep_terms:
        if term and term in text:
            hits.append(("指定保留", term, "block"))
    return hits


def paragraphs(text):
    return [(m.start(), m.end()) for m in re.finditer(r"[^\n]+(?:\n(?!\n)[^\n]*)*", text)]


def sentences(text, pstart, pend):
    out = []
    pos = pstart
    buf = ""
    for i in range(pstart, pend):
        buf += text[i]
        if text[i] in "。！？!?；;…":
            out.append((pos, i + 1))
            pos = i + 1
            buf = ""
    if pos < pend:
        out.append((pos, pend))
    return out


def fence_ranges(text):
    """代码围栏的字符区间，围栏内的内容一律不扫描。"""
    ranges = []
    open_at = None
    pos = 0
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            if open_at is None:
                open_at = pos
            else:
                ranges.append((open_at, pos + len(line)))
                open_at = None
        pos += len(line) + 1
    if open_at is not None:
        ranges.append((open_at, len(text)))
    return ranges


def unit_shape(ptext):
    """段落形态。scan 只判行文，不判被列举的术语、表格与标题。"""
    first = ptext.lstrip()
    if first.startswith("#"):
        return "heading"
    if first.startswith("|"):
        return "table"
    if BLOCK_QUOTE.match(first):
        return "quote"
    if re.match(r"^([-*+]|\d+[.)])\s", first):
        return "list"
    return "prose"


MASK = re.compile(r"`[^`\n]*`|「[^」\n]*」|“[^”\n]*”|『[^』\n]*』|《[^》\n]*》"
                  r"|\"[^\"\n]*\"|（[^）\n]*）|\([^)\n]*\)")


def mask_mentions(s):
    """把引号、括号、行内代码里的内容抹成等长占位。

    文档里引用一个套话当例子，和真的写了一句套话，不是一回事。
    变长会让偏移错位，所以逐字符替换成等长的占位符。
    """
    return MASK.sub(lambda m: "·" * len(m.group(0)), s)


def bigrams(s):
    s = re.sub(r"[\s。，、；：！？,.;:!?（）()「」“”\"'《》\[\]{}*`#>|-]", "", s)
    return {s[i: i + 2] for i in range(len(s) - 1)}


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def containment(a, b):
    """a 被 b 覆盖的比例。总结段通常是前文的超集，用包含度而非 Jaccard。"""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def first_divergence(orig, edited):
    """判失败时，指出第一处新增落在现文的哪个位置，免得只拿到一个"不通过"。"""
    sm = difflib.SequenceMatcher(None, orig, edited, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("insert", "replace"):
            return {
                "tag": tag,
                "original_offset": i1,
                "edited_offset": j1,
                "original_text": clip(orig[i1:i2], 60),
                "edited_text": clip(edited[j1:j2], 60),
                "context_before": clip(edited[max(0, j1 - 24):j1], 24),
            }
    return None


# ---------------------------------------------------------------- verify

def cmd_verify(args):
    orig = read_text(args.original)
    edited = read_text(args.edited)
    if args.ignore_eof_newline:
        orig_cmp = orig.rstrip("\n")
        edited_cmp = edited.rstrip("\n")
    else:
        orig_cmp, edited_cmp = orig, edited

    ok, spans = align(orig_cmp, edited_cmp)
    keep_terms = [t.strip() for t in (args.keep or "").split(",") if t.strip()]

    blocked = []
    warnings = []
    span_reports = []
    for start, end in spans:
        deleted = orig_cmp[start:end]
        kind = unit_kind(orig_cmp, start, end)
        hits = find_protections(deleted, keep_terms)
        report = {
            "start": start,
            "end": end,
            "chars": end - start,
            "unit": kind,
            "text": clip(deleted, 80),
            "context_before": clip(orig_cmp[max(0, start - 20): start], 20),
            "blocked": [],
        }
        hard = [h for h in hits if h[2] == "block"]
        soft = [h for h in hits if h[2] == "warn"]
        if hard:
            names = sorted({h[0] for h in hard})
            report["blocked"].extend(names)
            blocked.append({
                "kind": "protection",
                "names": names,
                "start": start,
                "end": end,
                "text": clip(deleted, 80),
            })
        if soft:
            warnings.append({
                "kind": "mention",
                "names": sorted({h[0] for h in soft}),
                "start": start,
                "end": end,
                "text": clip(deleted, 80),
            })
        if kind == "partial":
            report["blocked"].append("非完整单元")
            if not args.allow_partial_unit:
                blocked.append({
                    "kind": "partial_unit",
                    "start": start,
                    "end": end,
                    "text": clip(deleted, 80),
                })
        span_reports.append(report)

    added = max(0, len(edited_cmp) - len(orig_cmp)) if ok else None
    deleted_chars = sum(s["chars"] for s in span_reports)

    result = {
        "ok": bool(ok) and not blocked,
        "subsequence": bool(ok),
        "original": {"path": args.original, "chars": len(orig_cmp)},
        "edited": {"path": args.edited, "chars": len(edited_cmp)},
        "deleted": {
            "spans": len(span_reports),
            "chars": deleted_chars,
            "ratio": round(deleted_chars / len(orig_cmp), 4) if orig_cmp else 0.0,
        },
        "spans": span_reports,
        "blocked": blocked,
        "warnings": warnings,
        "added_chars": added,
        "first_divergence": None if ok else first_divergence(orig_cmp, edited_cmp),
    }

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        render_verify(result, args)

    if not ok:
        return 1
    if blocked:
        return 2
    return 0


def render_verify(r, args):
    print("原文 {} 字符 → 现文 {} 字符".format(r["original"]["chars"], r["edited"]["chars"]))
    if not r["subsequence"]:
        print("判定：不是严格子序列。现文含原文没有的文字（新增/改写/重排）。")
        d = r.get("first_divergence")
        if d:
            print("第一处新增在现文第 {} 字符，前面是「{}」，多出来的是「{}」（原文该处为「{}」）。".format(
                d["edited_offset"], d["context_before"], d["edited_text"], d["original_text"]))
        print("先撤回到原文，再只做删除。")
        return
    print("子序列：通过（现文每一字符都能在原文中按序找到）")
    print("删除 {} 处，共 {} 字符，占原文 {:.1%}".format(
        r["deleted"]["spans"], r["deleted"]["chars"], r["deleted"]["ratio"]))
    limit = args.report_limit
    for s in r["spans"][:limit]:
        flag = "  ×" if s["blocked"] else "   "
        print("{} [{:>6}-{:<6}] {:<14} {}".format(flag, s["start"], s["end"], s["unit"], s["text"]))
    if len(r["spans"]) > limit:
        print("   … 另有 {} 处未列出（用 --report-limit 或 --json --out 查看）".format(
            len(r["spans"]) - limit))
    if r["blocked"]:
        print("阻断项 {} 个：".format(len(r["blocked"])))
        for b in r["blocked"][:limit]:
            if b["kind"] == "protection":
                print("   [{}-{}] 删到了 {}：{}".format(
                    b["start"], b["end"], "/".join(b["names"]), b["text"]))
            else:
                print("   [{}-{}] 删除未落在完整单元边界：{}".format(
                    b["start"], b["end"], b["text"]))
        print("处理：把被删的章节补回原样，或缩小到完整句子/段落/整节；不得改写补全。")
    if r.get("warnings"):
        print("提示项 {} 个（不阻断，确认一下即可）：".format(len(r["warnings"])))
        for w in r["warnings"][:limit]:
            print("   [{}-{}] 删到了{}：{}".format(
                w["start"], w["end"], "/".join(w["names"]), w["text"]))


# ---------------------------------------------------------------- scan

def cmd_scan(args):
    text = read_text(args.file)
    paras = paragraphs(text)
    if not paras:
        data = {"file": args.file, "chars": 0, "candidates": [], "summary": {}}
        if args.json:
            print(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            print("空文件。")
        return 0

    fences = fence_ranges(text)
    seen_bigrams = []
    candidates = []
    total_chars = len(text)

    for pstart, pend in paras:
        if any(a <= pstart < b for a, b in fences):
            continue
        ptext = text[pstart:pend]
        shape = unit_shape(ptext)
        if shape in ("heading", "table", "quote"):
            continue
        if shape == "list" and not args.include_lists:
            continue

        masked = mask_mentions(ptext)
        is_summary = bool(SUMMARY_MARKERS.match(masked.strip()))
        p_bigrams = bigrams(masked)
        overlap = 0.0
        if is_summary and seen_bigrams:
            overlap = max(containment(p_bigrams, b) for b in seen_bigrams[-4:])
        repeat_hit = is_summary and overlap >= args.min_overlap
        seen_bigrams.append(p_bigrams)
        seen_bigrams = seen_bigrams[-8:]

        p_triple = len(set(TRIPLE.findall(masked))) >= 3
        quote_lines = sum(1 for ln in ptext.split("\n") if BLOCK_QUOTE.match(ln))
        bold_count = ptext.count("**")

        if repeat_hit:
            candidates.append({
                "line": text.count("\n", 0, pstart) + 1,
                "cat": "重复总结",
                "name": "总结段重述前文",
                "text": clip(ptext.strip(), 60),
                "signals": ["总结标记", "与前文重合 {:.0%}".format(overlap)],
                "action": "删整段",
                "blocked_by": [],
            })
            continue
        if p_triple and not HAS_FACT.search(masked):
            candidates.append({
                "line": text.count("\n", 0, pstart) + 1,
                "cat": "排比框架",
                "name": "首先/其次/最后 无内容",
                "text": clip(ptext.strip(), 60),
                "signals": ["三段式标记", "无数据"],
                "action": "删整段或降为主体陈述",
                "blocked_by": [],
            })
        if quote_lines >= 3:
            candidates.append({
                "line": text.count("\n", 0, pstart) + 1,
                "cat": "装饰",
                "name": "引用块堆砌",
                "text": clip(ptext.strip(), 60),
                "signals": ["{} 行引用".format(quote_lines)],
                "action": "改正文陈述后删引用块",
                "blocked_by": [],
            })
        if bold_count >= 6:
            candidates.append({
                "line": text.count("\n", 0, pstart) + 1,
                "cat": "装饰",
                "name": "满屏加粗",
                "text": clip(ptext.strip(), 60),
                "signals": ["{} 处加粗".format(bold_count // 2)],
                "action": "只保留关键结论的加粗",
                "blocked_by": [],
            })

        for sstart, send in sentences(text, pstart, pend):
            raw = text[sstart:send]
            if not raw.strip():
                continue
            s = mask_mentions(raw)
            hits = []
            strong = False
            for cat, name, pattern, strength in FAT:
                if re.search(pattern, s):
                    hits.append((cat, name, strength))
                    if strength == "strong":
                        strong = True
            if not hits:
                continue
            has_fact = bool(HAS_FACT.search(s))
            if not strong and has_fact:
                # 弱信号 + 含事实：整句不能删（数据要留），前缀又不是完整单元。
                prot = find_protections(raw)
                if prot:
                    candidates.append({
                        "line": text.count("\n", 0, sstart) + 1,
                        "cat": hits[0][0],
                        "name": hits[0][1],
                        "text": clip(raw.strip(), 60),
                        "signals": ["套话命中", "含" + "/".join(sorted({p[0] for p in prot}))],
                        "action": "整句保留（按单元完整性不得只删前缀）",
                        "blocked_by": sorted({p[0] for p in prot}),
                    })
                continue
            candidates.append({
                "line": text.count("\n", 0, sstart) + 1,
                "cat": hits[0][0],
                "name": "、".join(sorted({h[1] for h in hits})),
                "text": clip(raw.strip(), 60),
                "signals": ["套话命中"] + ([] if has_fact else ["无数据"]),
                "action": "删整句",
                "blocked_by": [],
            })

    # 去重（同一行同一文本只留一条）
    uniq = []
    seen = set()
    for c in candidates:
        key = (c["line"], c["text"], c["action"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(c)

    cand_chars = sum(len(c["text"]) for c in uniq if not c["blocked_by"])
    summary = {
        "chars": total_chars,
        "paragraphs": len(paras),
        "candidates": len(uniq),
        "deletable_candidates": sum(1 for c in uniq if not c["blocked_by"]),
        "estimated_deletable_chars": cand_chars,
        "estimated_ratio": round(cand_chars / total_chars, 4) if total_chars else 0.0,
    }

    data = {"file": args.file, "chars": total_chars, "candidates": uniq, "summary": summary}
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        render_scan(data, args)
    return 3 if any(not c["blocked_by"] for c in uniq) else 0


def render_scan(d, args):
    s = d["summary"]
    print("{}：{} 字符，{} 段，候选 {} 条（其中可删 {} 条，约 {} 字符）".format(
        d["file"], s["chars"], s["paragraphs"], s["candidates"],
        s["deletable_candidates"], s["estimated_deletable_chars"]))
    if not d["candidates"]:
        print("未发现套话候选。不需要剪刀动作。")
        return
    limit = args.report_limit
    for c in d["candidates"][:limit]:
        mark = "保留" if c["blocked_by"] else "可删"
        print("[{}] L{:<5} {} / {}  → {}".format(mark, c["line"], c["cat"], c["name"], c["action"]))
        print("        {}".format(c["text"]))
        if c["blocked_by"]:
            print("        原因：含 {}".format("/".join(c["blocked_by"])))
    if len(d["candidates"]) > limit:
        print("… 另有 {} 条未列出（用 --json --out 导出全量）".format(len(d["candidates"]) - limit))
    print("说明：清单只给候选与单元边界，不含改写。删不删由调用方按完整单元自行决定。")


# ---------------------------------------------------------------- code

def run(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def cmd_code(args):
    cwd = args.repo
    base = args.base or "HEAD"
    r = run("git rev-parse --is-inside-work-tree", cwd)
    if r.returncode != 0:
        print("不是 git 仓库：{}".format(cwd))
        return 5
    r = run('git diff --numstat "{}"'.format(base), cwd)
    if r.returncode != 0:
        print("git diff 失败：{}".format(r.stderr.strip()))
        return 5
    added = deleted = 0
    files = []
    for line in r.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        a, d, path = parts[0], parts[1], parts[2]
        a = 0 if a == "-" else int(a)
        d = 0 if d == "-" else int(d)
        added += a
        deleted += d
        files.append({"path": path, "added": a, "deleted": d})

    sample = []
    if added:
        r2 = run('git diff -U0 "{}"'.format(base), cwd)
        for line in r2.stdout.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                sample.append(line[1:])
                if len(sample) >= args.report_limit:
                    break

    test_rc = None
    test_tail = ""
    if args.test_cmd:
        rt = run(args.test_cmd, cwd)
        test_rc = rt.returncode
        tail = (rt.stdout + "\n" + rt.stderr).strip().splitlines()
        test_tail = "\n".join(tail[-args.report_limit:]) if tail else ""

    result = {
        "repo": cwd,
        "base": base,
        "added_lines": added,
        "deleted_lines": deleted,
        "files": files,
        "added_samples": sample,
        "test_cmd": args.test_cmd,
        "test_exit": test_rc,
        "only_deletions": added == 0,
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("基线 {}：删除 {} 行，新增 {} 行，涉及 {} 个文件".format(
            base, deleted, added, len(files)))
        for f in files[:args.report_limit]:
            print("  {}  -{}  +{}".format(f["path"], f["deleted"], f["added"]))
        if added:
            print("新增行示例（这些不是减法）：")
            for s in sample:
                print("  + {}".format(s))
        if args.test_cmd:
            print("测试：{} → 退出码 {}".format(args.test_cmd, test_rc))
            if test_tail:
                print(test_tail)
    if added:
        return 1
    if test_rc not in (None, 0):
        return 1
    return 0


# ---------------------------------------------------------------- main

def main(argv=None):
    p = argparse.ArgumentParser(prog="scissors", description="剪刀手减法门禁：只判定，不改写。")
    sub = p.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("verify", help="校验现文是否为原文的严格子序列")
    v.add_argument("--original", required=True)
    v.add_argument("--edited", required=True)
    v.add_argument("--keep", default="", help="逗号分隔的必留词")
    v.add_argument("--allow-partial-unit", action="store_true",
                   help="放行非完整单元删除（仅在确认是合法子句时使用）")
    v.add_argument("--ignore-eof-newline", action="store_true",
                   help="忽略文件末尾换行差异")
    v.add_argument("--json", action="store_true")
    v.add_argument("--out", default="", help="把完整 JSON 报告写到文件")
    v.add_argument("--report-limit", type=int, default=12)
    v.set_defaults(func=cmd_verify)

    s = sub.add_parser("scan", help="标出套话候选，不改写")
    s.add_argument("--file", required=True)
    s.add_argument("--min-overlap", type=float, default=0.45)
    s.add_argument("--include-lists", action="store_true",
                   help="列表项也参与判定（默认只判行文，避免把被列举的术语当成套话）")
    s.add_argument("--json", action="store_true")
    s.add_argument("--out", default="")
    s.add_argument("--report-limit", type=int, default=20)
    s.set_defaults(func=cmd_scan)

    c = sub.add_parser("code", help="校验改动是否只有删除行")
    c.add_argument("--repo", default=".")
    c.add_argument("--base", default="HEAD")
    c.add_argument("--test-cmd", default="")
    c.add_argument("--json", action="store_true")
    c.add_argument("--report-limit", type=int, default=15)
    c.set_defaults(func=cmd_code)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
