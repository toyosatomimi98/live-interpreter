# live-interpreter

A lightweight, real-time **English → Chinese** interpreter that runs on your own
computer's microphone. It listens to speech, transcribes it locally, translates
it into Chinese, and can read the translation aloud — while saving the whole
session to a Markdown file so you can review it later.

> **Status: actively maintained & under development.**
> This project is being improved continuously. Features, behavior, and the CLI
> may change between versions. Feedback and bug reports are welcome.

## Why this project

The original motivation was being unable to follow an English-language lecture in
real time. This tool is designed to **help you study English course materials —
recorded lectures, audio, or video files — instead of relying only on a live
classroom where you either miss the flow or fall behind.**

Give it a recording or a lecture audio, and it produces **bilingual
English/Chinese subtitles** you can read and keep. For live use, you can also
point it at your microphone to get near-real-time captions and (optionally)
spoken Chinese.

## Pipeline

```
Microphone / audio file
  → English transcription (faster-whisper, offline)
  → Chinese translation (DeepSeek, or a free fallback)
  → on-screen captions + optional spoken Chinese (edge-tts)
  → Markdown transcript
```

## Features

- **Local, offline speech recognition** — the Whisper model is cached on your
  machine, so the ASR step works without internet.
- **Reliable speech segmentation with silero VAD** — ignores background noise
  and only splits on real speech (this was key to making it work with a hot mic).
- **Live microphone mode** — a GUI with on-screen bilingual captions, a live
  input level meter, and an optional Chinese voice.
- **Offline file mode** — transcribe and translate an audio/video file, then save
  a full Markdown transcript.
- **Pluggable translation** — DeepSeek by default (auto-read from your local
  config or `.env`), with a Google Translate free fallback, and "original only"
  as a last resort.
- **Automatic Markdown logs** — every live session appends timestamped
  EN/ZH lines to `transcripts/tongchuan_YYYYMMDD_HHMMSS.md`.
- **Easy setup** — a one-click installer and a launcher for Windows.

## Requirements

- Windows (developed on Windows 10/11, Chinese locale)
- Python 3.10+ (3.13 tested)
- Internet for the translation and voice steps (ASR itself works offline)
- A working microphone, and **internet** if you want the spoken Chinese output

## Quick start (Windows)

1. **Install once:**

   ```bat
   安装同声传译.bat
   ```

2. **Run the app:**

   ```bat
   启动同声传译.bat
   ```

3. Pick your microphone, press **Start**, and speak. The English and Chinese
   captions appear on screen, and a Markdown file is written to `transcripts\`.

> The first start downloads the Whisper model (about 10–20 seconds); it is cached
> afterwards.

## Usage

### GUI (default)

```bat
.venv\Scripts\python.exe tongchuan.py
```

### Console mode

```bat
.venv\Scripts\python.exe tongchuan.py --console
```

### Translate an audio/video file

This is the recommended way to study English learning materials:

```bat
.venv\Scripts\python.exe tongchuan.py --file "lecture.mp3" --save
```

The results are printed to the console and, with `--save`, written to
`transcripts\` as a Markdown file.

### Useful options

```text
--model base.en|small.en|medium.en   Whisper model size (default: base.en)
--voice / --no-voice                 Enable / disable spoken Chinese
--sensitivity N                      Mic sensitivity (1–8, default 3)
--list-devices                       List available microphones
--test-mic                           Self-test each microphone's level
--save                               (with --file) save a Markdown transcript
```

For more accurate technical terminology, use `--model small.en`:

```bat
.venv\Scripts\python.exe tongchuan.py --model small.en
```

## Translation backend & API key

Translation uses **DeepSeek** (an OpenAI-compatible endpoint) by default. The API
key is **never stored in this repository**. It is read in this order:

1. Environment variable `DEEPSEEK_API_KEY` or `OPENAI_API_KEY`
2. The local `~/.codex/config.toml` file's `experimental_bearer_token` (a
   convenience for this author's machine)
3. A `.env` file in the project directory (`DEEPSEEK_API_KEY=sk-xxxx`) — this is
   the portable, documented way

If no key is available (or DeepSeek is unreachable), it falls back to a free
Google Translate endpoint, and finally shows the original English only.

To change the model or endpoint, edit `translation.py`.

## Privacy

- Microphone/audio is processed **locally** for recognition and is never
  uploaded.
- Only the **recognized English text** is sent to DeepSeek for translation, under
  your own account.
- Spoken output uses Microsoft's `edge-tts` service.

## Troubleshooting

- **"Cannot open microphone":** check Windows **Settings → Privacy → Microphone**,
  or try a different device from the dropdown.
- **Captions never appear:** the level meter near the top is the first thing to
  check. If it barely moves, the microphone isn't capturing audio. If it is high
  but nothing is transcribed, the background noise is being mistaken for speech —
  raise **Sensitivity**, or run `--test-mic` and pick a device with a sane level.
- **No spoken Chinese:** confirm the system output device works and that voice is
  enabled.
- **Reinstall / move to another machine:** run `安装同声传译.bat` (needs internet;
  it creates the environment, installs dependencies, and downloads the model).

## License

MIT — see [LICENSE](LICENSE).

---

## 中文简介

一个在你电脑上跑的**实时英→中同声传译**小工具：用麦克风听写英文，本地离线识别，
翻译为中文，可中文语音朗读，并自动保存为 Markdown。**最适合拿英语学习资料（录音、
视频、音频）来做双语字幕学习**，而不是只能靠现场课堂硬跟。核心依赖：`faster-whisper`
（离线识别）、`DeepSeek`（翻译，key 不写进仓库）、`edge-tts`（中文语音）。

> 本项目**仍在维护和改进中**，功能与命令可能随版本变化，欢迎反馈。

```
双击 安装同声传译.bat   # 首次安装（需联网）
双击 启动同声传译.bat   # 启动界面
```

更详细的中文使用说明可查看历史版本或提交 issue。
