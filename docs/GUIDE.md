# Usage guide

Full usage for `live-interpreter`.

## Sources

- **Microphone** — live, ambient speech (your own voice, or the room). Reliable.
- **Audio file** — the **recommended** way to study a recorded lecture / video:
  translate the whole file at once with no real-time constraints.
- **System sound (loopback)** — what the PC is playing. Convenient, but the least
  stable; prefer it only when you can't obtain the audio as a file.

> Loopback is the least reliable source: a flood of `data discontinuity in
> recording` warnings (or getting only the **first** sentence, then the meter
> staying on “待机”) means the loopback stream is delivering broken/noisy audio.
> Those benign warnings are suppressed. For accuracy, use the audio-file or
> microphone modes.

## Usage

### GUI (default)

```bat
.venv\Scripts\python.exe tongchuan.py
```

### Console mode

```bat
.venv\Scripts\python.exe tongchuan.py --console
```

### System sound (loopback)

```bat
.venv\Scripts\python.exe tongchuan.py --source system --console
```

Uses Windows **WASAPI loopback** (via `soundcard`) and resamples the captured audio
(typically 48 kHz) down to 16 kHz for Whisper. Choose 声音来源 → 系统声音 in the GUI
and pick the speaker device to monitor.

### File mode

```bat
.venv\Scripts\python.exe tongchuan.py --file "lecture.mp3" --save
```

The results are printed and, with `--save`, written to `transcripts\` as Markdown.

### Can't download the lecture?

For platforms that don't allow downloads (e.g. NUS WebLecture): choose 系统声音, tick
**“录制音频存文件”**, press **开始** and let the lecture play — the app writes the audio
to `recordings\*.wav` while trying live captions. Press **停止**, then translate the
recording reliably:

```bat
.venv\Scripts\python.exe tongchuan.py --file "recordings\同传录音_....wav" --save --model large-v3-turbo
```

Recordings are stored in `recordings\` and are **gitignored**.

## Options

```text
--model base.en|small.en|medium.en|large-v3-turbo|large-v3
                                    Whisper model (default: small.en)
--voice / --no-voice                 Enable / disable spoken Chinese
--source mic|system                  Input source (microphone or system audio)
--sensitivity N                      Mic sensitivity (1–8, default 3)
--list-devices                       List available microphones
--test-mic                           Self-test each microphone's level
--save                               (with --file) save a Markdown transcript
--save-audio                         Record the captured audio to recordings\*.wav
--course <path>                      Courseware Markdown for term alignment
```

## Live model switching & console logs

- **Model switching is live.** Change the **识别模型** dropdown while running and it
  takes effect at the next idle moment (larger models pause briefly to load).
- **Console log:** the launcher window prints timestamped events — model load/switch,
  recognition, translation backend + latency, and every UI action. It also prints a
  **backlog heartbeat** every 5 s (`待翻译`/`待识别`/`结果队列`) and per-utterance
  latency + queue size, so you can tell whether the pipeline is falling behind
  (a growing `待翻译` means translation is the bottleneck).

## Latency & responsiveness

The GUI shows the measured end-to-end latency (`延迟 X.Xs`). Latency =
segment-accumulation (up to the **分段上限**, default 6 s) + recognition + translation.
The **分段上限** dropdown trades speed vs. completeness (smaller = faster but can cut
phrases). Translation runs on **parallel workers** (default 2) with ordered output,
and the ASR prompt is kept **concise** (a huge prompt slows decoding and can drift).

Measured on this machine for a ~9 s utterance:

| Model | Load | ASR time | vs. live |
|---|---|---|---|
| base.en | ~5 s | ~5 s | ≈0.6× (keeps up) |
| small.en | ~5 s | ~17 s | ≈1.9× (lags) |
| medium.en | ~17 s | ~44 s | ≈4.8× (file mode only) |
| large-v3-turbo | ~14 s | ~43 s | ≈4.6× (file mode only) |

Large models are best for **file mode**, not live captions.

## Accuracy tips

- Use a larger model for technical material: `--model small.en` is a big step up,
  `medium.en` even better (slower). For heavily accented English (e.g. Indian),
  prefer `large-v3-turbo` with **file mode**.
- The translator already infers and auto-corrects obvious ASR mis-transcriptions
  (e.g. `messy` → `MESI`, `Barclay` → `Barkley`) from context.
- The **灵敏度** slider only affects how eagerly audio is treated as speech — not
  translation quality.

## Translation backend & API key

Default is **DeepSeek** (OpenAI-compatible). The key is **never stored in the repo**;
read in this order:

1. Env `DEEPSEEK_API_KEY` or `OPENAI_API_KEY`
2. The local `~/.codex/config.toml` `experimental_bearer_token`
3. A `.env` file in the project (`DEEPSEEK_API_KEY=sk-xxxx`)

If no key (or DeepSeek unreachable) it falls back to a free Google endpoint, then
shows the original English only. Change model/endpoint in `translation.py`.

## Privacy

- Audio is processed locally for recognition and never uploaded.
- Only the recognized English text is sent to DeepSeek for translation.
- Spoken output uses Microsoft `edge-tts`.

## Troubleshooting

- **"Cannot open microphone":** check Settings → Privacy → Microphone, or try another
  device.
- **Captions never appear:** check the level meter. Barely moving = no audio; high
  but nothing = noise mistaken for speech → raise **灵敏度**, or use `--test-mic`.
- **No spoken Chinese:** confirm the output device works and voice is enabled.
- **`symlinks` / `unauthenticated HF Hub` warnings:** benign (first model use);
  suppressed in the launchers via `HF_HUB_DISABLE_SYMLINKS_WARNING=1`.
- **Only the first sentence, then “待机”:** usually a *source* problem, not a bug.
  On loopback, the stream may be dropping audio → switch to file or microphone.
- **Reinstall:** run `安装同声传译.bat` (creates env, installs deps, downloads model).

## Testing

```bat
.venv\Scripts\python.exe selftest.py
```
