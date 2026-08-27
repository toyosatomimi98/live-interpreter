#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
同声传译：麦克风 → 英文识别 (faster-whisper) → 中文翻译 (DeepSeek) → 可选中文语音 (edge-tts)

用法：
    .venv\\Scripts\\python tongchuan.py            # 图形界面（默认）
    .venv\\Scripts\\python tongchuan.py --console   # 控制台模式
    .venv\\Scripts\\python tongchuan.py --file xx.mp3  # 识别单个音频文件（不连麦克风）
"""

from __future__ import annotations

import argparse
import asyncio
import math
import os
import queue
import sys
import threading
import time
from datetime import datetime

import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from faster_whisper import WhisperModel

try:
    from faster_whisper.vad import get_speech_timestamps as _get_speech_timestamps
except Exception:
    _get_speech_timestamps = None

try:
    from scipy.signal import resample_poly as _resample_poly
except Exception:
    _resample_poly = None


def _to_16k(x: np.ndarray, sr: int) -> np.ndarray:
    """把 x（采样率 sr）重采样到 16kHz，交给 Whisper。sr==16000 时原样返回。"""
    x = np.ascontiguousarray(x, dtype=np.float32)
    if _resample_poly is None or sr == SAMPLE_RATE:
        return x
    import math
    g = math.gcd(SAMPLE_RATE, sr)
    return np.ascontiguousarray(_resample_poly(x, SAMPLE_RATE // g, sr // g), dtype=np.float32)

try:
    import sounddevice as sd
except Exception:  # 没有音频库时 GUI 也能显示
    sd = None

try:
    import av
except Exception:
    av = None

try:
    import edge_tts
except Exception:
    edge_tts = None

from translation import Translator, load_api_key

SAMPLE_RATE = 16000
CHANNELS = 1

# 针对“电子与计算机工程”类英文讲课的专业词表，用作用户可覆盖的默认值。
# 作用：作为 Whisper 的 initial_prompt，显著提升技术术语的识别准确率。
DEFAULT_ASR_PROMPT = (
    "Signal processing, Fourier transform, convolution, filter, sampling theorem, "
    "frequency response, Laplace transform, Z-transform, transfer function, "
    "circuit analysis, Kirchhoff's laws, operational amplifier, transistor, CMOS, "
    "digital logic, Boolean algebra, finite state machine, microprocessor, "
    "embedded systems, microcontroller, real-time operating system, "
    "computer architecture, instruction set, pipeline, cache, memory hierarchy, "
    "digital signal processor, ADC, DAC, PWM, "
    "control systems, feedback, PID controller, state-space, "
    "machine learning, neural network, deep learning, gradient descent, "
    "convolutional neural network, reinforcement learning, "
    "robotics, actuator, kinematics, impedance, "
    "wireless communication, modulation, OFDM, channel coding, "
    "electromagnetics, antenna, "
    "probability, random variable, expectation, Gaussian distribution, "
    "optimization, gradient, convergence, equation, derivative, integral, "
    "matrix, eigenvalue, eigenvector, "
    "stability, linear time-invariant, discrete time, continuous time, "
    "processor, register, firmware, compiler, operating system, "
    "digital filter, low-pass filter, sampling rate, Nyquist, "
    "circuit, current, voltage, resistance, capacitance, inductance"
)


def load_asr_prompt() -> str:
    """优先读取项目目录下的 prompt.txt（用户可按课程定制），否则用内置专业词表。"""
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompt.txt")
    if os.path.exists(p):
        try:
            content = open(p, encoding="utf-8").read().strip()
            if content:
                return content
        except OSError:
            pass
    return DEFAULT_ASR_PROMPT

# tkinter 在无图形环境可能不可用，做可选导入
try:
    import tkinter as tk
    from tkinter import ttk
except Exception:
    tk = None
    ttk = None


# ----------------------------------------------------------------------------
# 音频切句（基于能量/VAD 的简易分句器）
# ----------------------------------------------------------------------------
class Segmenter:
    """把连续音频切成人声段落。

    优先用 silero VAD（能区分“人声”和“底噪”），VAD 不可用时退回能量判断。
    """

    def __init__(self, sample_rate=SAMPLE_RATE, min_silence=0.45, max_seg=10.0,
                 sensitivity=3.0, min_threshold=0.003):
        self.sample_rate = sample_rate
        self.min_silence = min_silence
        self.max_seg = max_seg
        self.sensitivity = sensitivity
        self.min_threshold = min_threshold
        self.noise = 0.015
        self.max_noise = 0.06
        self.last_rms = 0.0
        self.speaking = False
        self.in_q: "queue.Queue[np.ndarray]" = queue.Queue()
        self.out_q: "queue.Queue[tuple[np.ndarray, float]]" = queue.Queue()
        self._stop = False
        self._thread = None
        self._vad = None
        self._vad_options = None

    def feed(self, block: np.ndarray):
        self.in_q.put(block)

    def set_sensitivity(self, value: float):
        self.sensitivity = max(1.0, float(value))

    def start(self):
        if self._thread is None:
            self._load_vad()
            self._stop = False
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def _load_vad(self):
        try:
            from faster_whisper.vad import get_vad_model, VadOptions
            self._vad = get_vad_model()
            self._vad_options = VadOptions(
                threshold=0.5,
                neg_threshold=0.35,
                min_speech_duration_ms=250,
                min_silence_duration_ms=180,
                speech_pad_ms=60,
            )
        except Exception as e:
            self._vad = None
            try:
                import sys
                sys.stderr.write(f"[vad] 不可用，退回能量分段：{type(e).__name__}: {e}\n")
            except Exception:
                pass

    def stop(self):
        self._stop = True
        self.in_q.put(None)

    def _rms(self, block: np.ndarray) -> float:
        if block.size == 0:
            return 0.0
        v = float(np.sqrt(np.mean(np.square(block))))
        return v if v > 0 else 1e-9

    def _run(self):
        if self._vad is not None:
            self._run_vad()
        else:
            self._run_energy()

    # ---------------- VAD 分段 ----------------
    def _run_vad(self):
        buf = np.zeros(0, dtype=np.float32)
        in_segment = False
        last_vad = 0.0
        while not self._stop:
            try:
                block = self.in_q.get(timeout=0.3)
            except queue.Empty:
                continue
            if block is None:
                break
            block = np.ascontiguousarray(block, dtype=np.float32)
            buf = np.concatenate((buf, block))
            self.last_rms = self._rms(block)
            now = time.time()
            if now - last_vad < 0.35:
                continue
            last_vad = now
            has_speech, first_start, speech_end = self._vad_stats(buf)
            self.speaking = bool(has_speech)

            if has_speech and not in_segment:
                in_segment = True
                cut = max(0, first_start - int(0.3 * self.sample_rate))
                buf = buf[cut:]

            if in_segment:
                dur = len(buf) / self.sample_rate
                silence_after = (len(buf) - speech_end) / self.sample_rate if has_speech else 1e9
                if dur >= self.max_seg or (has_speech and silence_after >= self.min_silence):
                    emit_len = min(len(buf), speech_end + int(0.35 * self.sample_rate)) if has_speech else len(buf)
                    if emit_len >= int(self.sample_rate * 0.3):
                        self.out_q.put((buf[:emit_len].copy(), emit_len / self.sample_rate))
                    buf = np.zeros(0, dtype=np.float32)
                    in_segment = False
            else:
                keep = int(self.sample_rate * 0.6)
                if buf.size > keep:
                    buf = buf[-keep:]

    def _vad_stats(self, buf):
        try:
            ts = _get_speech_timestamps(buf, self._vad_options)
        except Exception:
            has = self._energy_speaking(buf)
            return has, 0, (len(buf) if has else 0)
        if not ts:
            return False, 0, 0
        return True, int(ts[0]["start"]), int(ts[-1]["end"])

    def _energy_speaking(self, buf):
        thr = max(self.min_threshold, self.noise * self.sensitivity)
        return self._rms(buf) > thr

    # ---------------- 能量分段（VAD 不可用时的兜底） ----------------
    def _run_energy(self):
        buf = np.zeros(0, dtype=np.float32)
        in_speech = False
        speech_len = 0.0
        silence_len = 0.0
        while not self._stop:
            try:
                block = self.in_q.get(timeout=0.3)
            except queue.Empty:
                continue
            if block is None:
                break
            block = np.ascontiguousarray(block, dtype=np.float32)
            buf = np.concatenate((buf, block))
            rms = self._rms(block)
            self.last_rms = rms
            blockdur = len(block) / self.sample_rate
            thr = max(self.min_threshold, self.noise * self.sensitivity)
            if rms < self.noise * 1.6:
                self.noise = 0.95 * self.noise + 0.05 * rms
                if self.noise > self.max_noise:
                    self.noise = self.max_noise
                thr = max(self.min_threshold, self.noise * self.sensitivity)
            if not in_speech:
                if rms > thr:
                    in_speech = True
                    self.speaking = True
                    speech_len = 0.0
                    silence_len = 0.0
                else:
                    self.speaking = False
                    keep = int(self.sample_rate * 0.4)
                    if buf.size > keep:
                        buf = buf[-keep:]
            else:
                speech_len += blockdur
                self.speaking = True
                if rms < thr:
                    silence_len += blockdur
                else:
                    silence_len = 0.0
                if silence_len >= self.min_silence or speech_len >= self.max_seg:
                    if buf.size >= int(self.sample_rate * 0.35):
                        self.out_q.put((buf, speech_len))
                    buf = np.zeros(0, dtype=np.float32)
                    in_speech = False
                    self.speaking = False


# ----------------------------------------------------------------------------
# 识别 + 翻译 + 语音合成
# ----------------------------------------------------------------------------
class Pipeline:
    def __init__(self, model_size="base.en", voice_enabled=True,
                 voice="zh-CN-XiaoxiaoNeural", device=None, sensitivity=3.0,
                 source="mic",
                 status_cb=None, segment_cb=None, error_cb=None, log_cb=None):
        self.model_size = model_size
        self.voice_enabled = voice_enabled
        self.voice = voice
        self.device = device
        self.sensitivity = sensitivity
        self.source = source
        self.capture_rate = 48000 if source == "system" else SAMPLE_RATE
        self.status_cb = status_cb or (lambda *a, **k: None)
        self.segment_cb = segment_cb or (lambda *a, **k: None)
        self.error_cb = error_cb or (lambda *a, **k: None)
        self.log_cb = log_cb or (lambda *a, **k: None)

        self.translator = Translator()
        self.segmenter = Segmenter(sample_rate=self.capture_rate, sensitivity=sensitivity)
        self.asr_prompt = load_asr_prompt()
        self.result_q: "queue.Queue[tuple]" = queue.Queue()
        self._asr_q: "queue.Queue[tuple]" = queue.Queue()
        self._threads = []
        self._stream = None
        self._system_thread = None
        self.running = False
        self.model = None
        self.tts = TtsPlayer(voice, enabled=voice_enabled)
        self.current_level = 0.0
        self.segments_count = 0

    # ---------------- 生命周期 ----------------
    def start(self):
        if self.running:
            return
        self.running = True
        self.segmenter.set_sensitivity(self.sensitivity)

        # 识别线程
        t_asr = threading.Thread(target=self._asr_loop, daemon=True)
        # 翻译线程
        t_tr = threading.Thread(target=self._translate_loop, daemon=True)
        # 语音线程
        t_tts = threading.Thread(target=self.tts.run, daemon=True)
        self._threads = [t_asr, t_tr, t_tts]
        for t in self._threads:
            t.start()

        self.segmenter.start()
        self.tts.enabled = self.voice_enabled
        if self.source == "system":
            self.status_cb("正在准备系统内录…")
            self._system_thread = threading.Thread(target=self._system_capture_loop, daemon=True)
            self._system_thread.start()
        else:
            self.status_cb("正在准备麦克风…")
            self._open_stream()

    def stop(self):
        if not self.running:
            return
        self.running = False
        try:
            if self._stream is not None:
                self._stream.stop()
                self._stream.close()
        except Exception:
            pass
        self._stream = None
        if self._system_thread is not None:
            self._system_thread = None
        self.segmenter.stop()
        for q in (self._asr_q, self.result_q):
            try:
                q.put(None)
            except Exception:
                pass
        self.tts.stop()
        self.status_cb("已停止")

    def _open_stream(self):
        if sd is None:
            self.error_cb("未找到音频库 sounddevice，无法采集麦克风。")
            return
        for device in self._candidate_devices():
            try:
                stream = sd.InputStream(
                    samplerate=SAMPLE_RATE,
                    channels=CHANNELS,
                    dtype="float32",
                    device=device,
                    callback=self._audio_cb,
                )
                stream.start()
            except Exception as e:
                last_err = f"{type(e).__name__}: {e}"
                continue
            self._stream = stream
            name = self._device_name(device)
            self.status_cb(f"正在听…（麦克风：{name}）")
            return
        self.running = False
        self.error_cb(f"无法打开麦克风：{last_err}")

    def _candidate_devices(self):
        cands = []
        if self.device is not None:
            cands.append(self.device)
        try:
            cands.append(sd.default.device[0])
        except Exception:
            pass
        try:
            for i, d in enumerate(sd.query_devices()):
                if d["max_input_channels"] > 0 and i not in cands:
                    cands.append(i)
        except Exception:
            pass
        return cands

    def _device_name(self, idx):
        try:
            return sd.query_devices(idx)["name"]
        except Exception:
            return "未知设备"

    def _audio_cb(self, indata, frames, time_info, status):
        mono = indata.mean(axis=1) if indata.ndim > 1 else indata
        mono = np.clip(mono, -0.98, 0.98)
        self.current_level = float(np.sqrt(np.mean(np.square(mono))))
        self.segmenter.feed(np.ascontiguousarray(mono, dtype=np.float32))

    def _system_capture_loop(self):
        """用 soundcard 内录系统输出声音（WASAPI loopback）。"""
        try:
            import soundcard as sc
        except Exception as e:
            self.error_cb(f"未安装 soundcard，无法内录：{type(e).__name__}: {e}")
            self.running = False
            return
        try:
            mics = sc.all_microphones(include_loopback=True)
        except Exception as e:
            self.error_cb(f"无法列出内录设备：{type(e).__name__}: {e}")
            self.running = False
            return
        loopbacks = [m for m in mics if getattr(m, "isloopback", False)] or list(mics)
        chosen = None
        if self.device is not None:
            for m in loopbacks:
                if self.device in (m.name, m.id):
                    chosen = m
                    break
        if chosen is None:
            chosen = loopbacks[0]

        rec = None
        for sr in (48000, 44100):
            try:
                rec = chosen.recorder(samplerate=sr, channels=2)
                rec.__enter__()
                self.capture_rate = sr
                self.segmenter.sample_rate = sr
                break
            except Exception:
                rec = None
        if rec is None:
            self.error_cb("无法打开系统内录（试过 48000 / 44100 Hz）。")
            self.running = False
            return

        self.status_cb(f"正在听系统声音…（{chosen.name}）")
        block = int(self.capture_rate * 0.1)
        try:
            while self.running:
                try:
                    data = rec.record(numframes=block)
                except Exception as e:
                    self.error_cb(f"内录读取失败：{type(e).__name__}: {e}")
                    break
                if data is None:
                    continue
                arr = np.asarray(data, dtype=np.float32)
                mono = arr[:, 0] if arr.ndim == 2 else arr
                mono = np.clip(mono, -0.98, 0.98)
                self.current_level = float(np.sqrt(np.mean(np.square(mono))))
                self.segmenter.feed(np.ascontiguousarray(mono, dtype=np.float32))
        finally:
            try:
                rec.__exit__(None, None, None)
            except Exception:
                pass

    # ---------------- 识别 ----------------
    def _asr_loop(self):
        self.status_cb("正在加载语音模型（首次约 10~20 秒）…")
        try:
            self.model = WhisperModel(self.model_size, device="cpu", compute_type="int8")
        except Exception as e:
            self.error_cb(f"语音模型加载失败：{e}")
            self.running = False
            return
        self.status_cb("模型就绪，正在听…")

        while self.running:
            try:
                seg, dur = self.segmenter.out_q.get(timeout=0.5)
            except queue.Empty:
                continue
            if seg is None:
                break
            try:
                seg = _to_16k(np.ascontiguousarray(seg, dtype=np.float32), self.capture_rate)
                seg_iters, info = self.model.transcribe(
                    seg, beam_size=1, language="en", vad_filter=True,
                    condition_on_previous_text=False,
                    initial_prompt=self.asr_prompt,
                )
                text = "".join(s.text for s in seg_iters).strip()
                self.segments_count += 1
                if text:
                    t0 = time.time()
                    self._asr_q.put((text, t0))
                    self.log_cb("EN", text)
            except Exception as e:
                self.error_cb(f"识别出错：{type(e).__name__}: {e}")

    # ---------------- 翻译 ----------------
    def _translate_loop(self):
        while True:
            try:
                item = self._asr_q.get(timeout=0.5)
            except queue.Empty:
                if not self.running:
                    break
                continue
            if item is None:
                break
            en_text, t0 = item
            try:
                zh = self.translator.translate(en_text)
                backend = self.translator.last_backend
                err = ""
            except Exception as e:
                zh = ""
                backend = "error"
                err = str(e)[:200]
            self.result_q.put({
                "en": en_text, "zh": zh, "backend": backend,
                "err": err, "t0": t0,
                "latency": time.time() - t0,
            })


# ----------------------------------------------------------------------------
# 中文语音合成 + 播放
# ----------------------------------------------------------------------------
class TtsPlayer:
    def __init__(self, voice="zh-CN-XiaoxiaoNeural", enabled=False):
        self.voice = voice
        self.enabled = enabled
        self._cond = threading.Condition()
        self._pending: str | None = None
        self._stop = False

    def speak(self, text: str):
        if not self.enabled or not text:
            return
        # 只保留最新一条待播文本，避免积压导致越念越慢
        with self._cond:
            self._pending = text
            self._cond.notify()

    def run(self):
        while True:
            with self._cond:
                while self._pending is None:
                    if self._stop:
                        return
                    self._cond.wait(timeout=0.5)
                text = self._pending
                self._pending = None
            if self.enabled:
                self._play(text)

    def stop(self):
        self._stop = True
        self.enabled = False
        with self._cond:
            self._cond.notify()

    def _play(self, text: str):
        if not self.enabled:
            return
        if edge_tts is None or av is None or sd is None:
            return
        try:
            mp3 = os.path.join(tempfile_dir(), f"tiche_{datetime.now():%H%M%S%f}.mp3")
            asyncio.run(edge_tts.Communicate(text, self.voice).save(mp3))
            samples = _decode_mp3(mp3)
            try:
                os.remove(mp3)
            except OSError:
                pass
            if samples.size == 0:
                return
            sd.stop()
            sd.play(samples, 44100, blocking=True)
        except Exception as e:
            try:
                sys.stderr.write(f"[tts] {type(e).__name__}: {e}\n")
            except Exception:
                pass


def _decode_mp3(path: str) -> np.ndarray:
    """用 PyAV 把 mp3 解码成 float32 单声道 44100。"""
    container = av.open(path)
    stream = container.streams.audio[0]
    resampler = av.AudioResampler(format="flt", layout="mono", rate=44100)
    chunks = []
    for frame in container.decode(stream):
        for rf in resampler.resample(frame):
            chunks.append(rf.to_ndarray().reshape(-1))
    return np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)


def tempfile_dir() -> str:
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
    os.makedirs(d, exist_ok=True)
    return d


def transcripts_dir() -> str:
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "transcripts")
    os.makedirs(d, exist_ok=True)
    return d


class MarkdownLogger:
    """把实时识别+翻译结果持续追加写入 markdown 文件（每个会话一个文件）。"""

    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"# 同声传译记录\n\n> 开始时间：{datetime.now():%Y-%m-%d %H:%M:%S}\n\n")

    @classmethod
    def auto(cls, directory: str | None = None) -> "MarkdownLogger":
        d = directory or transcripts_dir()
        name = f"同声传译_{datetime.now():%Y%m%d_%H%M%S}.md"
        return cls(os.path.join(d, name))

    def append(self, en: str, zh: str, backend: str = ""):
        ts = datetime.now().strftime("%H:%M:%S")
        note = f"（{backend}）" if backend else ""
        with self._lock:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(f"**{ts}** EN: {en}\n\nZH: {zh}{note}\n\n---\n\n")


# ----------------------------------------------------------------------------
# 图形界面
# ----------------------------------------------------------------------------
class GUI:
    def __init__(self, root, opts):
        self.root = root
        self.opts = opts
        root.title("同声传译 · 麦克风实时翻译")
        root.geometry("860x640")
        root.configure(bg="#f4f6fb")

        self.en_var = tk.StringVar(value="等待说话…")
        self.zh_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="就绪")
        self.voice_var = tk.BooleanVar(value=opts.voice_enabled)
        self.source_var = tk.StringVar(value="麦克风")
        self.device_var = tk.StringVar()
        self.skip_tts = threading.Lock()
        self.ui_q: "queue.Queue[tuple]" = queue.Queue()
        self.logger: "MarkdownLogger | None" = None
        self._start_time = 0.0
        self._no_seg_warned = False
        self._last_count = 0

        self.pipeline = None

        self._build_widgets()
        self._refresh_devices()
        self._poll()

    def _build_widgets(self):
        top = tk.Frame(self.root, bg="#f4f6fb")
        top.pack(fill="x", padx=12, pady=(10, 4))
        tk.Label(top, textvariable=self.status_var, bg="#f4f6fb",
                 fg="#1f6feb", font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w")

        # 音量条 + 说话状态
        meter_row = tk.Frame(self.root, bg="#f4f6fb")
        meter_row.pack(fill="x", padx=12, pady=(0, 4))
        self.meter = ttk.Progressbar(meter_row, orient="horizontal", maximum=1.0, value=0.0)
        self.meter.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.meter_label = tk.Label(meter_row, text="待机", bg="#f4f6fb", fg="#9ca3af",
                                    font=("Microsoft YaHei UI", 10), width=16, anchor="e")
        self.meter_label.pack(side="left")

        en_card = tk.Frame(self.root, bg="#ffffff", highlightbackground="#e1e6f0",
                           highlightthickness=1)
        en_card.pack(fill="x", padx=12, pady=6)
        tk.Label(en_card, text="英文原文", bg="#ffffff", fg="#6b7280",
                 font=("Microsoft YaHei UI", 10)).pack(anchor="w", padx=10, pady=(8, 0))
        en_lbl = tk.Label(en_card, textvariable=self.en_var, bg="#ffffff", fg="#111827",
                          font=("Microsoft YaHei UI", 15), wraplength=820, justify="left",
                          anchor="w")
        en_lbl.pack(fill="x", padx=10, pady=(2, 10))

        zh_card = tk.Frame(self.root, bg="#ffffff", highlightbackground="#e1e6f0",
                           highlightthickness=1)
        zh_card.pack(fill="x", padx=12, pady=6)
        tk.Label(zh_card, text="中文翻译", bg="#ffffff", fg="#6b7280",
                 font=("Microsoft YaHei UI", 10)).pack(anchor="w", padx=10, pady=(8, 0))
        zh_lbl = tk.Label(zh_card, textvariable=self.zh_var, bg="#ffffff", fg="#0b7a3b",
                          font=("Microsoft YaHei UI", 17, "bold"), wraplength=820,
                          justify="left", anchor="w")
        zh_lbl.pack(fill="x", padx=10, pady=(2, 10))

        # 控制区
        ctrl = tk.Frame(self.root, bg="#f4f6fb")
        ctrl.pack(fill="x", padx=12, pady=6)
        self.start_btn = tk.Button(ctrl, text="▶ 开始", command=self.toggle,
                                   bg="#1f6feb", fg="white", font=("Microsoft YaHei UI", 11),
                                   padx=18, pady=6, bd=0, cursor="hand2")
        self.start_btn.pack(side="left", padx=(0, 8))
        self.save_btn = tk.Button(ctrl, text="清屏", command=self.clear,
                                  bg="#e5e7eb", fg="#374151", font=("Microsoft YaHei UI", 10),
                                  padx=12, pady=6, bd=0, cursor="hand2")
        self.save_btn.pack(side="left", padx=4)

        tk.Checkbutton(ctrl, text="中文语音播报", variable=self.voice_var,
                       command=self._on_voice, bg="#f4f6fb", font=("Microsoft YaHei UI", 10),
                       activebackground="#f4f6fb").pack(side="left", padx=12)

        tk.Label(ctrl, text="声音来源：", bg="#f4f6fb", font=("Microsoft YaHei UI", 10)).pack(side="left", padx=(12, 2))
        self.source_box = ttk.Combobox(ctrl, values=["麦克风", "系统声音"],
                                       textvariable=self.source_var, width=8, state="readonly")
        self.source_box.pack(side="left", padx=(0, 6))
        self.source_box.bind("<<ComboboxSelected>>", self._on_source)
        tk.Label(ctrl, text="设备：", bg="#f4f6fb", font=("Microsoft YaHei UI", 10)).pack(side="left")
        self.device_box = ttk.Combobox(ctrl, textvariable=self.device_var, width=30,
                                       state="readonly")
        self.device_box.pack(side="left", padx=(0, 4))
        tk.Button(ctrl, text="刷新", command=self._refresh_devices,
                  bg="#e5e7eb", fg="#374151", font=("Microsoft YaHei UI", 9),
                  padx=8, pady=2, bd=0, cursor="hand2").pack(side="left", padx=2)

        # 灵敏度
        sens_row = tk.Frame(self.root, bg="#f4f6fb")
        sens_row.pack(fill="x", padx=12, pady=2)
        tk.Label(sens_row, text="灵敏度", bg="#f4f6fb", font=("Microsoft YaHei UI", 10)).pack(side="left", padx=(0, 8))
        self.sens_scale = ttk.Scale(sens_row, from_=1.0, to=8.0, value=3.0,
                                    command=self._on_sens)
        self.sens_scale.pack(side="left", fill="x", expand=True, padx=(0, 12))
        self.sens_val = tk.Label(sens_row, text="3.0", bg="#f4f6fb", font=("Microsoft YaHei UI", 10))
        self.sens_val.pack(side="left")

        # 记录
        tk.Label(self.root, text="记录", bg="#f4f6fb", fg="#6b7280",
                 font=("Microsoft YaHei UI", 10)).pack(anchor="w", padx=12, pady=(10, 0))
        log_frame = tk.Frame(self.root, bg="#ffffff", highlightbackground="#e1e6f0",
                             highlightthickness=1)
        log_frame.pack(fill="both", expand=True, padx=12, pady=(2, 12))
        self.log = tk.Text(log_frame, bg="#ffffff", fg="#374151", wrap="word",
                           font=("Microsoft YaHei UI", 10), bd=0, state="disabled")
        self.log.pack(fill="both", expand=True, padx=6, pady=6)

    # ---------------- 设备 ----------------
    def _refresh_devices(self):
        if self.source_var.get() == "系统声音":
            self._devices = {}
            items = []
            try:
                import soundcard as sc
                for m in sc.all_microphones(include_loopback=True):
                    if not getattr(m, "isloopback", False):
                        continue
                    label = m.name
                    self._devices[label] = m.id
                    items.append(label)
            except Exception as e:
                self._show_error(f"内录设备列表失败：{type(e).__name__}: {e}")
            self.device_box["values"] = items
            if items:
                self.device_var.set(items[0])
                self.device_box.current(0)
            return

        if sd is None:
            self.device_box["values"] = []
            return
        self._devices = {}
        try:
            default_in = sd.default.device[0]
            # default.device[0] 可能为负数表示“默认主机”的默认输入
            if default_in < 0:
                default_in = sd.default.hostapi
        except Exception:
            default_in = -1
        items = []
        devs = sd.query_devices()
        for i, d in enumerate(devs):
            if d["max_input_channels"] > 0:
                label = f"{i} - {d['name']}"
                self._devices[label] = i
                items.append(label)
        self.device_box["values"] = items
        # 优先选中系统默认输入设备
        sel_label = None
        for label, idx in self._devices.items():
            if idx == default_in:
                sel_label = label
                break
        if sel_label is None and items:
            sel_label = items[0]
        if sel_label:
            self.device_var.set(sel_label)
            self.device_box.current(items.index(sel_label))

    def _on_source(self, event=None):
        self._refresh_devices()

    def _selected_device(self):
        try:
            label = self.device_var.get()
            return self._devices.get(label)
        except Exception:
            return None

    # ---------------- 控制 ----------------
    def toggle(self):
        try:
            if self.pipeline and getattr(self.pipeline, "running", False):
                self.pipeline.stop()
                self.start_btn.configure(text="▶ 开始")
            else:
                self._build_pipeline()
                self.start_btn.configure(text="■ 停止")
                self.logger = MarkdownLogger.auto()
                self._show_hint(f"记录将保存到：{self.logger.path}")
                self._start_time = time.time()
                self._no_seg_warned = False
                self._last_count = 0
                self.pipeline.start()
        except Exception as e:
            self.status_var.set("⚠ 启动出错：" + str(e))
            self._append_log("ERR", f"启动出错: {type(e).__name__}: {e}")

    def _show_hint(self, line: str):
        self._append_log("INFO", line)

    def _build_pipeline(self):
        source = "system" if self.source_var.get() == "系统声音" else "mic"
        self.pipeline = Pipeline(
            model_size=self.opts.model,
            voice_enabled=self.voice_var.get(),
            source=source,
            device=self._selected_device(),
            sensitivity=float(self.sens_scale.get()),
            status_cb=lambda s: self.ui_q.put(("status", s)),
            segment_cb=None,
            error_cb=lambda e: self.ui_q.put(("error", e)),
            log_cb=lambda kind, text: self.ui_q.put(("log", kind, text)),
        )

    def clear(self):
        self.en_var.set("等待说话…")
        self.zh_var.set("")
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _on_voice(self):
        on = self.voice_var.get()
        if self.pipeline:
            self.pipeline.voice_enabled = on
            if self.pipeline.tts:
                self.pipeline.tts.enabled = on
        self.status_var.set("中文语音播报：开" if on else "中文语音播报：关")

    def _on_sens(self, val):
        self.sens_val.configure(text=f"{float(val):.1f}")
        if self.pipeline:
            self.pipeline.sensitivity = float(val)
            self.pipeline.segmenter.set_sensitivity(float(val))

    def _show_error(self, msg):
        self.status_var.set("⚠ " + msg)
        self._append_log("ERR", msg)

    def _append_log(self, kind: str, text: str):
        ts = datetime.now().strftime("%H:%M:%S")
        if kind == "ERR":
            line = f"[{ts}] ⚠ {text}\n"
        elif kind == "EN":
            line = f"[{ts}] EN: {text}\n"
        elif kind == "ZH":
            line = f"    ZH: {text}\n"
        else:
            line = text + "\n"
        self._log_line(line)

    def _log_line(self, line: str):
        self.log.configure(state="normal")
        self.log.insert("end", line)
        self.log.see("end")
        self.log.configure(state="disabled")

    # ---------------- 轮询结果 ----------------
    def _poll(self):
        # 音量条 / 说话状态 / 引导提示
        if self.pipeline:
            lvl = float(getattr(self.pipeline, "current_level", 0.0))
            self.meter["value"] = min(1.0, lvl * 2.5)
            speaking = bool(getattr(getattr(self.pipeline, "segmenter", None), "speaking", False))
            if speaking:
                self.meter_label.configure(text="▉ 检测到声音", fg="#16a34a")
            else:
                self.meter_label.configure(text="待机", fg="#9ca3af")

            cnt = int(getattr(self.pipeline, "segments_count", 0))
            if cnt != self._last_count:
                self._last_count = cnt
            # 模型已就绪但一时没识别到话 → 提示
            if (getattr(self.pipeline, "running", False)
                    and self.pipeline.model is not None
                    and cnt == 0
                    and not self._no_seg_warned
                    and self._start_time
                    and (time.time() - self._start_time) > 25):
                self._no_seg_warned = True
                self.status_var.set("暂时没检测到说话。请确认麦克风音量正常、人离麦克风够近，或调低“灵敏度”。")

        # 工作线程的 UI 消息都经由队列，在这里（主线程）刷新，避免跨线程调用 tkinter
        while True:
            try:
                msg = self.ui_q.get_nowait()
            except queue.Empty:
                break
            kind = msg[0]
            if kind == "status":
                self.status_var.set(msg[1])
            elif kind == "error":
                self._show_error(msg[1])
            elif kind == "log":
                self._append_log(msg[1], msg[2])

        if self.pipeline:
            q = getattr(self.pipeline, "result_q", None)
            if q:
                while True:
                    try:
                        item = q.get_nowait()
                    except queue.Empty:
                        break
                    self._show_result(item)
        self.root.after(120, self._poll)

    def _show_result(self, item):
        en = item.get("en", "")
        zh = item.get("zh", "")
        backend = item.get("backend", "")
        self.en_var.set(en)
        if zh:
            self.zh_var.set(zh)
            self._append_log("ZH", zh)
        elif item.get("err"):
            self.zh_var.set("(翻译失败，仅显示原文)")
            self._append_log("ERR", item.get("err"))
        if self.logger and en:
            self.logger.append(en, zh, backend)
        if self.pipeline and self.voice_var.get() and zh:
            self.pipeline.tts.speak(zh)

    def on_close(self):
        if self.pipeline:
            self.pipeline.stop()
        self.root.destroy()


# ----------------------------------------------------------------------------
# 控制台模式
# ----------------------------------------------------------------------------
def run_console(opts):
    trans = Translator()
    print("已使用 API key：", trans.key_summary())
    src_txt = "系统声音" if opts.source == "system" else "麦克风"
    print(f"正在从{src_txt}实时识别并翻译… Ctrl+C 退出。\n")
    pipe = Pipeline(model_size=opts.model, voice_enabled=opts.voice_enabled,
                    source=opts.source, device=None, sensitivity=opts.sensitivity,
                    status_cb=lambda s: print("[状态]", s),
                    segment_cb=None,
                    error_cb=lambda e: print("[出错]", e),
                    log_cb=_console_log)
    # 存好 translator 引用
    print("按 Enter 开始采集…")
    input()
    logger = MarkdownLogger.auto()
    print("记录将保存到：", logger.path)
    pipe.start()
    t0 = time.time()
    try:
        while True:
            try:
                item = pipe.result_q.get(timeout=0.5)
            except queue.Empty:
                continue
            en = item["en"]; zh = item["zh"]
            print("─" * 60)
            print("EN:", en)
            if zh:
                print("ZH:", zh)
            if item.get("err"):
                print("   (翻译失败:", item["err"], ")")
            print(f"   延迟: {item['latency']:.1f}s | {item['backend']}")
            logger.append(en, zh, item.get("backend", ""))
    except KeyboardInterrupt:
        pass
    finally:
        pipe.stop()


def _console_log(kind, text):
    pass  # 控制台模式下不重复打印，避免刷屏


# ----------------------------------------------------------------------------
# 文件模式：识别单个音频文件
# ----------------------------------------------------------------------------
def run_file(path, opts):
    trans = Translator()
    print("翻译后端 api_key：", trans.key_summary())
    print("识别文件：", path)
    model = WhisperModel(opts.model, device="cpu", compute_type="int8")
    print("识别中…")
    segments, info = model.transcribe(path, beam_size=1, language="en", vad_filter=True)
    lines = []
    for s in segments:
        text = s.text.strip()
        if not text:
            continue
        try:
            zh = trans.translate(text)
        except Exception as e:
            zh = f"(翻译失败 {e})"
        lines.append((text, zh))
        print("EN:", text)
        print("ZH:", zh)
        print("-" * 60)
    if opts.save:
        out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "transcripts")
        os.makedirs(out, exist_ok=True)
        fn = os.path.join(out, f"录音稿_{datetime.now():%Y%m%d_%H%M%S}.md")
        with open(fn, "w", encoding="utf-8") as f:
            f.write(f"# 同声传译记录 {datetime.now():%Y-%m-%d %H:%M}\n\n")
            for en, zh in lines:
                f.write(f"**EN:** {en}\n\n**ZH:** {zh}\n\n---\n\n")
        print("已保存：", fn)


def list_devices():
    if sd is None:
        print("无音频库")
        return
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            print(i, d["name"], d["default_samplerate"])


def mic_test():
    """自检：逐个输入设备短录，报告电平，推荐最佳麦克风。"""
    if sd is None:
        print("未安装 sounddevice，无法测试麦克风。")
        return
    print("正在测试麦克风（每次约 1.2 秒，不回放不保存）…")
    results = []
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] <= 0:
            continue
        try:
            rec = sd.rec(int(SAMPLE_RATE * 1.2), samplerate=SAMPLE_RATE,
                         channels=1, dtype="float32", device=i)
            sd.wait()
            x = np.asarray(rec).reshape(-1)
            peak = float(np.abs(x).max()) if x.size else 0.0
            results.append((peak, i, d["name"]))
        except Exception as e:
            results.append((0.0, i, f"{d['name']} (open fail: {type(e).__name__})"))
    results.sort(key=lambda r: r[0], reverse=True)
    for rank, (peak, i, name) in enumerate(results[:8]):
        db = 20 * (np.log10(peak + 1e-12)) if peak > 0 else -120
        flag = "  <-- 电平最高" if rank == 0 else ""
        print(f"device {i:2d}: peak={peak:.3f} ({db:6.1f} dBFS)  {name}{flag}")


def main():
    ap = argparse.ArgumentParser(description="麦克风实时英语→中语同声传译")
    ap.add_argument("--model", default="base.en", help="whisper 模型大小（base.en/small.en/medium.en）")
    ap.add_argument("--console", action="store_true", help="控制台模式")
    ap.add_argument("--file", default=None, help="识别单个音频文件（mp3/wav 等）")
    ap.add_argument("--save", action="store_true", help="文件模式保存 markdown 记录")
    ap.add_argument("--voice", dest="voice_enabled", action="store_true", default=True,
                    help="开启中文语音（默认开）")
    ap.add_argument("--no-voice", dest="voice_enabled", action="store_false", help="关闭中文语音")
    ap.add_argument("--sensitivity", type=float, default=3.0)
    ap.add_argument("--list-devices", action="store_true", help="列出麦克风设备")
    ap.add_argument("--test-mic", action="store_true", help="自检麦克风电平")
    ap.add_argument("--source", choices=["mic", "system"], default="mic",
                    help="声音来源：mic=麦克风，system=电脑内部声音(内录)")
    opts = ap.parse_args()

    if opts.list_devices:
        list_devices()
        return
    if opts.test_mic:
        mic_test()
        return
    if opts.file:
        run_file(opts.file, opts)
        return
    if opts.console:
        run_console(opts)
        return

    if tk is None:
        print("此环境不支持图形界面，请直接运行 启动同声传译.bat 或在有桌面的环境下运行。")
        return
    root = tk.Tk()
    app = GUI(root, opts)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
