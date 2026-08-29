# Architecture

The app is a multi-threaded pipeline: capture → segment → transcribe → translate →
present.

```mermaid
flowchart LR
    subgraph SRC[输入 / 来源]
        MIC["麦克风 · sounddevice · 16kHz"]
        SYS["系统声音内录 · soundcard · 48kHz"]
        FILE["音频/视频文件 · --file"]
    end

    SEG["切句 Segmenter · silero VAD（能量兜底）"]
    ASR["识别 faster-whisper<br>模型 + prompt.txt<br>（内录音频先重采样到 16kHz）"]
    TR["翻译 DeepSeek → Google → 仅原文<br>（并行 worker）"]

    subgraph OUT[输出]
        GUI["界面字幕 EN/ZH + 延迟 + 页"]
        MD["Markdown 记录 transcripts"]
        LOG["控制台日志 事件/延迟/积压"]
        TTS["中文语音 edge-tts"]
        REC["可选录音 recordings/*.wav"]
    end

    MIC --> SEG
    SYS --> SEG
    FILE --> SEG
    SEG -->|"音频段 out_q"| ASR
    ASR -->|"识别文本 _asr_q"| TR
    TR -->|"结果 result_q"| GUI
    TR --> MD
    TR --> LOG
    TR --> TTS
    SYS --> REC
    MIC --> REC
```

## Threading & queues

- **GUI thread** owns the tkinter window and drains `result_q` (every 120 ms).
- **Capture** feeds the Segmenter via a background thread (system loopback) or the
  sounddevice callback (microphone).
- **Segmenter thread** runs silero VAD and emits audio segments (`out_q`).
- **ASR thread** transcribes segments (`_asr_q`) with the courseware prompt.
- **Translation** runs on a small worker pool (default 2) with **ordered output** into
  `result_q`; the coordinator also prints a periodic backlog heartbeat.
- **TTS thread** synthesizes + plays the latest translation (drops stale audio).

Add-on tasks: WAV recording (from capture), Markdown/console logging, courseware
glossary and context retrieval (see [COURSEWARE.md](COURSEWARE.md)).
