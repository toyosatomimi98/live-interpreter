# Courseware alignment

Feed a course's Markdown and the app aligns recognition + translation with it.

## What it does

1. Adds the course's terms to the ASR prompt (`prompt.txt`), so technical terms are
   more likely recognized — and homophones get corrected (e.g. `MESI`, not `messy`).
2. Injects a **translation glossary** (`term = 标准中文`) so the Chinese output uses
   the same wording as your handout.
3. Retrieves the most relevant courseware page for each recognized sentence and feeds
   it as translation context (keyword-overlap retrieval with stay-put smoothing), and
   **tags each translated line with that section** (`页:X` in console, `§ …` in GUI and
   Markdown transcript) for easy review.

## Format

See [sample-courseware.md](sample-courseware.md). Expected structure:

```markdown
---
course: 硬件优化与内存访问
model: small.en       # optional per-course default model
---

## 术语表
| English | 中文 |
| --- | --- |
| MESI | 缓存一致性协议(MESI) |
| store buffer | 存储缓冲 |
| row buffer | 行缓冲 |

## 1 存储层次与缓存
本节正文……（术语、讲解）
## 2 缓存一致性
……
```

Key points:
- The **`## 术语表`** table is the highest-priority source (your manual `term = 中文`).
- Split body into `##` sections per lecture/topic/slide — this powers Phase 2 retrieval
  and Phase 3 page tagging.
- The glossary extractor also auto-detects multi-word technical phrases (e.g.
  `store buffer`, `cache coherence`) and hyphenated terms.

Put your own courses in `courseware\` (gitignored). Use it from the GUI **课程课件**
dropdown or:

```bat
.venv\Scripts\python.exe tongchuan.py --course courseware\xxx.md
```

## Convert PDF/PPT to courseware Markdown

```bat
.venv\Scripts\python.exe convert_courseware.py "slides.pdf" --course "计算机组成原理"
```

It writes `courseware\<课程名>.md`, split into per-page sections, and (with a DeepSeek
key) auto-fills a `## 术语表` for acronyms. Edit it to add lowercase technical phrases
(e.g. `store buffer`) that auto-extract misses.

## Measured effect (base.en, sample hardware/memory sentence)

| | Without courseware | With courseware |
|---|---|---|
| ASR key terms | 10/11 (`MESI`→`messy`) | 11/11 (`MESI`) |
| Translation terms | 存储缓冲区 / 内存排序 / MESI | 存储缓冲 / 内存序 / 缓存一致性协议(MESI) |

The ASR gain is modest on clean audio but larger on real/noisy/accented lectures; the
translation glossary reliably aligns wording with your handout.
