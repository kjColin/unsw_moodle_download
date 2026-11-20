#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Summarize Moodle PDFs (Lectures/Tutorials) into bilingual Markdown.

Default mode:
- summarize only newly downloaded PDFs from /tmp/moodle_pdf_extract_report.json

Rebuild mode:
- --rebuild-all rewrites all existing summaries from local PDFs

Output:
- /home/colin/Unsw/Summaries/{COURSE}/{Lectures|Tutorials}/*.md
"""

import argparse
import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

REPORT_PATH = "/tmp/moodle_pdf_extract_report.json"
PDF_ROOT = Path("/home/colin/Unsw")
SUMMARY_ROOT = Path("/home/colin/Unsw/Summaries")
FOCUS_RULES_PATH = Path("/home/colin/video_pipeline/moodle_focus_rules.json")

# fallback rules
FOCUS_INCLUDE = [
    "week", "lecture", "tutorial", "lab", "introduction", "overview",
    "machine learning", "neural", "search", "design", "regression", "classification",
]
FOCUS_EXCLUDE = [
    "rubric", "marking", "solution", "sample", "example", "template", "transcript",
    "faq", "outline", "contract", "dataset", "guide", "references", "book",
]


def run_pdftotext(pdf_path: str, pages: int = 12) -> str:
    try:
        cmd = ["pdftotext", "-l", str(pages), pdf_path, "-"]
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
        return out.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def normalize_line(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    s = s.replace("&amp;", "&")
    return s


def clean_lines(text: str):
    lines = []
    seen_norm = set()
    for ln in text.splitlines():
        s = normalize_line(ln)
        if len(s) < 10:
            continue
        if re.fullmatch(r"\d+", s):
            continue
        if s.lower().startswith(("unsw", "page ")) and len(s) < 28:
            continue

        key = re.sub(r"[^a-z0-9]+", "", s.lower())
        if len(key) < 8 or key in seen_norm:
            continue
        seen_norm.add(key)
        lines.append(s)
    return lines


def canonical_stem(name: str) -> str:
    stem = Path(name).stem
    stem = stem.replace("&amp;", "&")
    stem = re.sub(r"[_\-]+", " ", stem)
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem


def sentence_split(paragraph: str):
    parts = re.split(r"(?<=[\.!?])\s+", paragraph)
    return [p.strip() for p in parts if len(p.strip()) >= 20]


def pick_overview(lines):
    if not lines:
        return "No extractable text was found in this PDF.", "该 PDF 暂未提取到可读文本。"

    para = " ".join(lines[:30])
    sents = sentence_split(para)
    if not sents:
        sents = lines[:3]

    en = " ".join(sents[:3])[:900]

    zh = en
    replace = {
        "lecture": "讲义",
        "tutorial": "教程",
        "introduction": "介绍",
        "overview": "概览",
        "algorithm": "算法",
        "model": "模型",
        "evaluation": "评估",
        "example": "示例",
        "design": "设计",
        "search": "搜索",
        "neural network": "神经网络",
        "decision tree": "决策树",
        "classification": "分类",
        "regression": "回归",
    }
    for k, v in replace.items():
        zh = re.sub(rf"\b{k}\b", v, zh, flags=re.I)

    return en, zh


def polish_line(s: str) -> str:
    s = re.sub(r"^\s*\d+[\).:-]?\s*", "", s)
    s = re.sub(r"\s+", " ", s).strip(" -•\t")
    s = s.replace("&amp;", "&")
    # avoid truncated tails that hurt readability
    s = re.sub(r"\b(and|or|to|of|for)$", "", s, flags=re.I).strip()
    return s


def pick_core_concepts(lines, limit=6):
    keywords = [
        "concept", "principle", "method", "algorithm", "model", "framework",
        "feature", "process", "evaluation", "design", "search", "classification",
        "regression", "neural", "tree", "probability", "agent", "optimization",
    ]

    picked = []
    for ln in lines:
        low = ln.lower()
        if any(k in low for k in keywords) and 35 <= len(ln) <= 220:
            picked.append(polish_line(ln))
        if len(picked) >= limit:
            break

    if len(picked) < 4:
        for ln in lines[:80]:
            if 45 <= len(ln) <= 220:
                picked.append(polish_line(ln))
            if len(picked) >= limit:
                break

    out, seen = [], set()
    for p in picked:
        key = re.sub(r"[^a-z0-9]+", "", p.lower())
        if len(key) < 16 or key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out[:limit]


def zh_hint_line(en: str) -> str:
    zh = en
    mapping = {
        "introduction": "介绍",
        "overview": "概览",
        "objective": "目标",
        "algorithm": "算法",
        "model": "模型",
        "evaluation": "评估",
        "method": "方法",
        "example": "示例",
        "exercise": "练习",
        "tutorial": "教程",
        "lecture": "讲义",
        "summary": "总结",
        "important": "重点",
        "classification": "分类",
        "regression": "回归",
        "neural": "神经",
        "search": "搜索",
        "design": "设计",
        "decision tree": "决策树",
        "exam": "考试",
        "assignment": "作业",
        "mistake": "错误",
        "pitfall": "易错点",
    }
    for k, v in mapping.items():
        zh = re.sub(rf"\b{k}\b", v, zh, flags=re.I)
    return zh


def pick_high_freq_points(lines, limit=4):
    keys = ["important", "exam", "assignment", "quiz", "key", "must", "focus", "objective"]
    out, seen = [], set()
    for ln in lines:
        low = ln.lower()
        if any(k in low for k in keys) and 30 <= len(ln) <= 220:
            p = polish_line(ln)
            k = re.sub(r"[^a-z0-9]+", "", p.lower())
            if k in seen:
                continue
            seen.add(k)
            out.append(p)
        if len(out) >= limit:
            break
    return out


def pick_pitfalls(lines, limit=4):
    keys = ["common", "mistake", "warning", "avoid", "note", "attention", "pitfall", "error"]
    out, seen = [], set()
    for ln in lines:
        low = ln.lower()
        if any(k in low for k in keys) and 25 <= len(ln) <= 220:
            p = polish_line(ln)
            k = re.sub(r"[^a-z0-9]+", "", p.lower())
            if k in seen:
                continue
            seen.add(k)
            out.append(p)
        if len(out) >= limit:
            break
    return out


def build_markdown(course: str, category: str, pdf_name: str, source: str, text: str) -> str:
    lines = clean_lines(text)
    title = canonical_stem(pdf_name)
    overview_en, overview_zh = pick_overview(lines)
    concepts_en = pick_core_concepts(lines, limit=6)
    concepts_zh = [zh_hint_line(x) for x in concepts_en]

    high_en = pick_high_freq_points(lines, limit=4)
    if not high_en:
        high_en = concepts_en[:3]
    high_zh = [zh_hint_line(x) for x in high_en]

    pit_en = pick_pitfalls(lines, limit=4)
    if not pit_en:
        pit_en = ["Review lecture examples and tutorial exercises to avoid common implementation mistakes."]
    pit_zh = [zh_hint_line(x) for x in pit_en]

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    md = f"""---
course: {course}
category: {category}
source_pdf: {pdf_name}
source_url: {source}
generated_at: {now}
summary_mode: bilingual_structured_v3
---

# {title}

## English

### 1) Overview
{overview_en}

### 2) Core Concepts
"""

    for i, p in enumerate(concepts_en, 1):
        md += f"{i}. {p}\n"

    md += "\n### 3) High-frequency Tested Points (Exam/Assignment)\n"
    for i, p in enumerate(high_en, 1):
        md += f"{i}. {p}\n"

    md += "\n### 4) Pitfalls & How to Avoid\n"
    for i, p in enumerate(pit_en, 1):
        md += f"{i}. {p}\n"

    md += "\n## 中文\n\n### 1) 这节讲什么（概述）\n"
    md += f"{overview_zh}\n\n### 2) 必会概念（核心要点）\n"
    for i, p in enumerate(concepts_zh, 1):
        md += f"{i}. {p}\n"

    md += "\n### 3) 作业/考试高频点\n"
    for i, p in enumerate(high_zh, 1):
        md += f"{i}. {p}\n"

    md += "\n### 4) 易错点与规避\n"
    for i, p in enumerate(pit_zh, 1):
        md += f"{i}. {p}\n"

    return md


def load_focus_rules():
    if FOCUS_RULES_PATH.exists():
        try:
            return json.loads(FOCUS_RULES_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def is_focus_pdf_name(name: str, course: str = "") -> bool:
    s = canonical_stem(name).lower()
    rules = load_focus_rules()
    default = rules.get("default", {})
    course_rule = rules.get(course, {}) if course else {}

    include = course_rule.get("include") or default.get("include") or FOCUS_INCLUDE
    exclude = course_rule.get("exclude") or default.get("exclude") or FOCUS_EXCLUDE

    if any(x in s for x in exclude):
        return False
    if any(x in s for x in include):
        return True
    return False


def normalize_key(stem: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", stem.lower().replace("amp", "&"))


def dedupe_dir(out_dir: Path):
    groups = {}
    for p in out_dir.glob("*.md"):
        groups.setdefault(normalize_key(p.stem), []).append(p)

    removed = 0
    for _, arr in groups.items():
        if len(arr) <= 1:
            continue
        arr_sorted = sorted(arr, key=lambda x: (x.name.count("_"), len(x.name), x.name.lower()))
        keep = arr_sorted[0]
        for p in arr_sorted[1:]:
            p.unlink(missing_ok=True)
            removed += 1
    return removed


def targets_from_report():
    if not os.path.exists(REPORT_PATH):
        return []
    with open(REPORT_PATH, "r", encoding="utf-8") as f:
        report = json.load(f)
    downloaded = report.get("downloaded", [])
    out = []
    for item in downloaded:
        if item.get("category") not in {"Lectures", "Tutorials"}:
            continue
        pdf_path = item.get("file", "")
        if not pdf_path or not os.path.exists(pdf_path):
            continue
        if not is_focus_pdf_name(os.path.basename(pdf_path), item.get("course", "")):
            continue
        out.append(
            {
                "course": item.get("course", "UNKNOWN"),
                "category": item.get("category", "Lectures"),
                "pdf_path": pdf_path,
                "source": item.get("source", ""),
            }
        )
    return out


def targets_all_pdfs():
    out = []
    for course_dir in PDF_ROOT.iterdir():
        if not course_dir.is_dir() or course_dir.name == "Summaries":
            continue
        course = course_dir.name
        for category in ("Lectures", "Tutorials"):
            cat_dir = course_dir / category
            if not cat_dir.exists():
                continue
            for pdf in cat_dir.glob("*.pdf"):
                if not is_focus_pdf_name(pdf.name, course):
                    continue
                out.append(
                    {
                        "course": course,
                        "category": category,
                        "pdf_path": str(pdf),
                        "source": "",
                    }
                )
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rebuild-all", action="store_true", help="rewrite all summaries from local PDFs")
    args = parser.parse_args()

    targets = targets_all_pdfs() if args.rebuild_all else targets_from_report()

    generated = 0
    rewritten = 0
    skipped = 0
    errors = []
    dedup_removed = 0

    for item in targets:
        course = item["course"]
        category = item["category"]
        pdf_path = item["pdf_path"]
        source = item.get("source", "")
        pdf_name = os.path.basename(pdf_path)

        out_dir = SUMMARY_ROOT / course / category
        out_dir.mkdir(parents=True, exist_ok=True)

        stem = canonical_stem(pdf_name)
        out_md = out_dir / f"{stem}.md"

        text = run_pdftotext(pdf_path)
        md = build_markdown(course, category, pdf_name, source, text)

        try:
            existed = out_md.exists()
            out_md.write_text(md, encoding="utf-8")
            if existed:
                rewritten += 1
            else:
                generated += 1
        except Exception as e:
            errors.append(f"write fail {out_md}: {e}")
            skipped += 1

        dedup_removed += dedupe_dir(out_dir)

    result = {
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "rebuild_all" if args.rebuild_all else "incremental",
        "targets": len(targets),
        "generated": generated,
        "rewritten": rewritten,
        "skipped": skipped,
        "dedup_removed": dedup_removed,
        "errors": errors,
    }

    with open("/tmp/moodle_summary_report.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"TARGETS={len(targets)}")
    print(f"GENERATED={generated}")
    print(f"REWRITTEN={rewritten}")
    print(f"DEDUP_REMOVED={dedup_removed}")
    print(f"SKIPPED={skipped}")
    print(f"ERRORS={len(errors)}")


if __name__ == "__main__":
    main()
