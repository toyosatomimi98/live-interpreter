"""课程 Markdown -> 术语表（用于识别热词 + 翻译译法）。

支持格式：
  - front-matter：  --- 里的 course / model
  - `## 术语表`（或 `## Glossary`）段落内的 Markdown 表格 `| EN | 中文 |`
    或 `EN = 中文` 行
  - 正文 / 标题：用于补充识别热词（大写缩写、加粗/代码术语）

生成的词表会：
  1) 进入 Whisper 的 initial_prompt -> 减少术语听错
  2) 注入翻译系统提示词 -> 让中文和课件用词一致
"""

from __future__ import annotations

import re
import os
from dataclasses import dataclass, field


@dataclass
class Course:
    name: str = ""
    model: str = ""
    glossary: list[tuple[str, str]] = field(default_factory=list)  # (en, zh)
    terms: list[str] = field(default_factory=list)  # 去重后的英文术语/缩写


def _front_matter(text: str) -> dict:
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    out = {}
    if m:
        for line in m.group(1).splitlines():
            if ":" in line or "=" in line:
                sep = ":" if ":" in line else "="
                k, v = line.split(sep, 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _strip_md(s: str) -> str:
    s = re.sub(r"`([^`]+)`", r"\1", s)
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", s)
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"[*_~>#]+", "", s)
    return s.strip()


def _parse_glossary_section(text: str) -> list[tuple[str, str]]:
    res: list[tuple[str, str]] = []
    m = re.search(r"^#{2,3}\s*(?:术语表|Glossary)\s*$.*?(?=^#{2,3}\s|\Z)", text, re.M | re.S)
    section = m.group(0) if m else ""
    for line in section.splitlines():
        line = line.strip()
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) >= 2 and "--" not in cells[0]:
                en = _strip_md(cells[0])
                zh = _strip_md(cells[1])
                if en and en.lower() != "english":
                    res.append((en, zh))
        elif "=" in line and not line.startswith("#"):
            en, zh = line.split("=", 1)
            en, zh = _strip_md(en), _strip_md(zh)
            if en:
                res.append((en, zh))
    return res


def _collect_terms(text: str) -> list[str]:
    terms = set()
    for t in re.findall(r"\b[A-Z][A-Z0-9]{1,9}\b", text):
        if t.lower() not in {"the", "and", "for", "not", "this", "that"}:
            terms.add(t)
    for t in re.findall(r"`([^`\n]{2,40})`", text):
        terms.add(t.strip())
    for t in re.findall(r"\*\*([^*\n]{2,40})\*\*", text):
        terms.add(t.strip())
    # 连字符复合词：write-combining / non-temporal / out-of-order
    for t in re.findall(r"\b[A-Za-z]+(?:-[A-Za-z]+)+\b", text):
        terms.add(t)
    # 后缀启发：XXX buffer / cache / ordering / coherence / conflict / barrier / protocol ...
    SUFFIXES = ("buffer", "cache", "coherence", "ordering", "conflict", "barrier",
                "protocol", "hierarchy", "prefetch", "prediction", "throughput",
                "bandwidth", "storage", "thread", "memory", "latency")
    STOP = {"the", "a", "an", "to", "of", "in", "and", "is", "are", "for", "on",
            "with", "as", "this", "that", "it", "by", "from"}
    pat = re.compile(r"([A-Za-z][A-Za-z0-9\-]*(?:\s+[A-Za-z][A-Za-z0-9\-]*){0,2})\s+("
                     + "|".join(SUFFIXES) + r")\b", re.I)
    for m in pat.finditer(text):
        phrase = m.group(0).strip()
        first = phrase.split()[0].lower()
        if first not in STOP and len(phrase.split()) >= 1:
            terms.add(phrase)
    return sorted(terms)


def load_course(path: str) -> Course:
    with open(path, encoding="utf-8") as f:
        text = f.read()
    course = Course()
    fm = _front_matter(text)
    course.name = fm.get("course", os.path.splitext(os.path.basename(path))[0])
    course.model = fm.get("model", "")
    course.glossary = _parse_glossary_section(text)
    seen = set()
    for en, _ in course.glossary:
        if en and en.lower() not in seen:
            course.terms.append(en)
            seen.add(en.lower())
    for t in _collect_terms(text):
        if t.lower() not in seen:
            course.terms.append(t)
            seen.add(t.lower())
    return course


def asr_prompt(course: Course) -> str:
    return ", ".join(course.terms)


def glossary_text(course: Course) -> str:
    pairs = [f"{en} = {zh}" for en, zh in course.glossary if en and zh]
    return "; ".join(pairs)


def load_sections(path: str) -> list[tuple[str, str]]:
    """把课程 Markdown 按 `## 标题` 切成 (标题, 正文) 段落，用于上下文检索。"""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    # 去掉 front-matter
    text = re.sub(r"^---\n.*?\n---\n", "", text, flags=re.S)
    parts = re.split(r"^##\s+(.+)$", text, flags=re.M)
    out = []
    # parts = [pre, title1, body1, title2, body2, ...]
    for i in range(1, len(parts) - 1, 2):
        title = parts[i].strip()
        body = parts[i + 1].strip()
        if body and not re.search(r"术语表|Glossary|词汇表", title, re.I):
            out.append((title, body))
    return out


if __name__ == "__main__":
    import sys
    c = load_course(sys.argv[1])
    print("course:", c.name, "| model:", c.model)
    print("terms:", len(c.terms), "->", c.terms[:40])
    print("glossary:", len(c.glossary), "->", c.glossary[:20])
    print("asr_prompt(前200):", asr_prompt(c)[:200])
    print("glossary_text:", glossary_text(c)[:200])
