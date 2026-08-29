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
安装同声传译.bat   :: install once (needs internet)
启动同声传译.bat   :: run the app
```

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

## Documentation

- [Usage guide](docs/GUIDE.md) — sources, options, latency, accuracy tips, troubleshooting
- [Courseware alignment](docs/COURSEWARE.md) — glossary/context/page tagging + converter
- [Architecture](docs/ARCHITECTURE.md) — pipeline diagram, threads & queues
- [Roadmap / TODO](docs/ROADMAP.md)

## Requirements

- Windows, Python 3.10+ (3.13 tested)
- Internet for translation & voice (ASR works offline)
- A microphone, and internet if you want the spoken Chinese output

## License

MIT — see [LICENSE](LICENSE).
