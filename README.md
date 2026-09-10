# live-interpreter

A lightweight, real-time **English → Chinese** interpreter that runs on your own
computer's microphone. It transcribes speech locally, translates it into Chinese,
can read it aloud, and saves the whole session to Markdown.

> **Status: actively maintained & under development.** Features, behavior, and the
> CLI may change between versions.

## Preview

![Live English→Chinese simultaneous interpretation demo](docs/demo.png)

## What it does

```
Microphone / system audio / file
  → English transcription (faster-whisper, offline)
  → Chinese translation (DeepSeek, or free fallback)
  → captions + optional spoken Chinese (edge-tts) → Markdown transcript
```

## Quick start (Windows)

```bat
install.bat   :: one-time setup: venv + dependencies + speech models (needs internet)
run.bat       :: start the app
```

Double-clicking the Chinese-named twins (`安装同声传译.bat` / `启动同声传译.bat`) does
exactly the same thing — pick whichever you prefer.

**Handing this to someone else?** Give them
[docs/新手上手指南.md](docs/新手上手指南.md) — a Chinese, step-by-step guide that
assumes no Python and no command line. If anything looks wrong, `诊断.bat` (or
`doctor.bat`) prints a full health report to copy back to you.

Pick a source (microphone / system sound / a file), choose a courseware Markdown for
term alignment if you have it, and press **开始**.

## Features

- **Live modes** — microphone, system-audio (loopback), or an offline **file**.
- **Local offline ASR** (faster-whisper) + DeepSeek translation + `edge-tts` voice.
- **Auto Markdown transcript**, optional **audio recording** (for platforms you can't
  download from).
- **Live model switching**, **console diagnostics** (latency / backlog), and low
  latency by default.
- **Courseware-aligned** recognition & translation (PDF/PPT → Markdown).
- **Privacy** — audio is processed locally; only the recognized English text is sent
  to DeepSeek.

## Recommended workflow

For the best results, split into **live** and **offline**:

1. **Live (class):** use a fast model so it keeps up in real time (`base.en` or
   `tiny.en`), and tick **录制音频存文件** to save the audio while it plays.
2. **Afterwards (offline):** at a suitable time, translate the saved recording with
   the **best model** (`large-v3-turbo`) in **file mode** for the most accurate
   transcript:

   ```bat
   .venv\Scripts\python.exe tongchuan.py --file "recordings\同传录音_....wav" --save --model large-v3-turbo
   ```

This way you get **live captions** (a fast model) *and* an **accurate full transcript**
(the best model), which is the recommended way to use the tool.

## Pluggable translation backend (DeepSeek / local)

By default translation uses **DeepSeek** (cloud). The translator is now pluggable so
you can point it at a **local OpenAI-compatible server** (e.g. Ollama, llama.cpp, or
vLLM) for offline / private / bulk use — useful when you want to process lots of audio
without paying per call.

- Pick a backend via `--translate-backend {auto,deepseek,local,google}`, or the
  `TRANSLATE_BACKEND` env var. `auto` keeps today's behavior (DeepSeek if a key is
  present, otherwise the free Google fallback).
- For a local backend, set `--local-base-url` / `--local-model` (or
  `LOCAL_LLM_BASE_URL` / `LOCAL_LLM_MODEL`). Defaults are
  `http://localhost:11434/v1` and model `qwen2.5:14b`.
- This is a **work-in-progress hook**: the pluggable backend + factory are in place,
  but a friendly in-UI backend picker and a GPU / offline-batch workflow still come
  next.

## Documentation

- [新手操作指南 / beginner's guide](docs/新手上手指南.md) — 中文，从零装到出字幕（发给同学看这份）
- [Usage guide](docs/GUIDE.md) — sources, options, latency, accuracy tips, troubleshooting
- [Courseware alignment](docs/COURSEWARE.md) — glossary/context/page tagging + converter
- [Architecture](docs/ARCHITECTURE.md) — pipeline diagram, threads & queues
- [Roadmap / TODO](docs/ROADMAP.md)

## Requirements

- Windows, Python 3.10+ (3.11/3.12 recommended; 3.13 tested) — python.org installer or Anaconda both work
- Internet for translation & voice (ASR works offline)
- A microphone, and internet if you want the spoken Chinese output

Run `install.bat` once: it creates `.venv`, installs the dependencies and pre-downloads
the two default speech models (~600 MB), so the first run needs no extra waiting. A
DeepSeek API key is optional (`设置API密钥.bat` writes it to `.env`); without one the
app falls back to the free Google translator. `诊断.bat` / `doctor.bat` checks the whole
environment (Python, packages, models, network, audio devices, write permissions).

## License

MIT — see [LICENSE](LICENSE).
