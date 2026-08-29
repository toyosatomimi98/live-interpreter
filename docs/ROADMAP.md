# Roadmap / TODO

Planned improvements (ideas only — not all implemented). Feedback and PRs welcome.

- [x] **Courseware glossary (Phase 1)** — parse a course Markdown, extract key terms /
  acronyms, and generate an ASR term list + translation glossary.
- [x] **Context retrieval (Phase 2)** — index each slide's text and feed the most
  relevant slide as translation context (keyword overlap with stay-put smoothing).
- [x] **Slide mapping (Phase 3)** — tag each translated line with the likely
  section/page (`页:X` in console, `§ …` in GUI/transcript).
- [x] **Lower live latency** — parallel translation workers (ordered output), lower
  default segment length (6 s), and a concise ASR prompt.
- [ ] **More robust system-audio (loopback) capture** — better device auto-selection
  and a clearer on-screen hint when no speech is detected.
- [ ] **Instant model switch** — preload the selected model in the background so
  changing the ASR model is seamless.
