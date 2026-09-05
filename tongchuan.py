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
import re
import sys
import threading
import time
import warnings
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

import numpy as np

# 系统内录（WASAPI loopback）在空闲/断续时会产生大量良性警告，压掉以免刷屏。
warnings.filterwarnings("ignore", message=".*data discontinuity in recording.*")


# 控制台配色：除中英字幕外，其它日志统一灰色。仅在真实终端启用 ANSI，
# 重定向/管道时关闭，避免把 \033[90m 这类转义序列原样输出。
_ANSI = bool(getattr(sys.stdout, "isatty", lambda: False)())
if os.name == "nt" and _ANSI:
    try:
        import ctypes
        _h = ctypes.windll.kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        _mode = ctypes.c_uint32(0)
        ctypes.windll.kernel32.GetConsoleMode(_h, ctypes.byref(_mode))
        ctypes.windll.kernel32.SetConsoleMode(_h, _mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except Exception:
        pass
_C_GRAY = "\033[90m" if _ANSI else ""
_C_RESET = "\033[0m" if _ANSI else ""


def clog(msg: str):
    """把事件打印到控制台（启动 bat 打开的窗口），供用户实时观察。"""
    try:
        print(f"{_C_GRAY}[{datetime.now():%H:%M:%S}] {msg}{_C_RESET}", flush=True)
    except Exception:
        pass

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


def _com_init() -> bool:
    """初始化当前线程的 COM（WASAPI/声音设备需要）。返回是否需要 CoUninitialize。"""
    try:
        import ctypes
        # COINIT_MULTITHREADED = 0
        hr = ctypes.windll.ole32.CoInitializeEx(None, 0)
        # 只有 S_OK(0) 表示“我们确实第一次初始化了 COM”，需要其在结束时释放；
        # S_FALSE(1)/CHANGED_MODE 表示已由别的代码初始化，无需释放。
        return hr == 0
    except Exception:
        return False


def _com_uninit():
    try:
        import ctypes
        ctypes.windll.ole32.CoUninitialize()
    except Exception:
        pass

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
# 注意：词表过长会拖慢解码、反而容易跑偏，因此保持精简聚焦。
DEFAULT_ASR_PROMPT = (
    "signal processing, Fourier transform, convolution, filter, sampling theorem, "
    "frequency response, Laplace transform, Z-transform, transfer function, "
    "circuit, transistor, CMOS, digital logic, finite state machine, microprocessor, "
    "ADC, DAC, PWM, Nyquist, "
    "control system, feedback, PID controller, state-space, machine learning, "
    "neural network, deep learning, gradient descent, convolutional neural network, "
    "reinforcement learning, robotics, probability, random variable, matrix, "
    "eigenvalue, eigenvector, "
    "computer architecture, instruction set, microarchitecture, pipeline, superscalar, "
    "out-of-order, branch prediction, register, throughput, latency, bandwidth, "
    "clock cycle, "
    "cache, cache coherence, coherence protocol, MESI, cache line, L1 cache, "
    "L2 cache, L3 cache, virtual memory, page table, TLB, "
    "parallelism, concurrency, multithreading, synchronization, deadlock, "
    "race condition, shared memory, distributed memory, message passing, CUDA, "
    "OpenMP, MPI, "
    "computer network, protocol, TCP, IP, UDP, router, gateway, socket, "
    "congestion control, routing, firewall, VPN, Ethernet, Wi-Fi, three-way handshake"
)


def _merge_prompt(a: str, b: str, max_terms: int = 35) -> str:
    """合并两份词表，优先 b（课程词），去重并限量，避免 prompt 过长拖慢识别。"""
    def parts(s: str):
        return [p.strip() for p in s.replace("\n", " ").split(",") if p.strip()]
    seen, uniq = [], set()
    for p in parts(b) + parts(a):
        k = p.lower()
        if k not in uniq:
            uniq.add(k)
            seen.append(p)
        if len(seen) >= max_terms:
            break
    return ", ".join(seen)


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

    def __init__(self, sample_rate=SAMPLE_RATE, min_silence=0.5, max_seg=10.0,
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
        self._apply_vad_threshold()

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
                min_speech_duration_ms=500,
                min_silence_duration_ms=300,
                speech_pad_ms=80,
            )
            self._apply_vad_threshold()
        except Exception as e:
            self._vad = None
            try:
                import sys
                sys.stderr.write(f"[vad] 不可用，退回能量分段：{type(e).__name__}: {e}\n")
            except Exception:
                pass

    def _apply_vad_threshold(self):
        """把“灵敏度”映射到 silero VAD 的说话概率阈值。
        （灵敏度越低→阈值越低→越灵敏；越高→阈值越高→越严格、越抗噪）"""
        if self._vad_options is None:
            return
        thr = 0.40 + (self.sensitivity - 1.0) * 0.05
        self._vad_options.threshold = min(0.75, max(0.35, thr))

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
            ts = _get_speech_timestamps(buf, self._vad_options, sampling_rate=self.sample_rate)
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
                 source="mic", save_audio=False, max_seg=4.0,
                 min_silence=0.5, min_words=3, translation_workers=2,
                 course_file=None,
                 status_cb=None, segment_cb=None, error_cb=None, log_cb=None):
        self.model_size = model_size
        self.voice_enabled = voice_enabled
        self.voice = voice
        self.device = device
        self.sensitivity = sensitivity
        self.source = source
        self.save_audio = save_audio
        self.max_seg = max_seg
        self.min_silence = min_silence
        self.min_words = max(1, int(min_words))
        self.translation_workers = max(1, int(translation_workers))
        self.course_file = course_file
        self.capture_rate = 48000 if source == "system" else SAMPLE_RATE
        self.status_cb = status_cb or (lambda *a, **k: None)
        self.segment_cb = segment_cb or (lambda *a, **k: None)
        self.error_cb = error_cb or (lambda *a, **k: None)
        self.log_cb = log_cb or (lambda *a, **k: None)

        self.translator = Translator()
        # 分段器始终在 16kHz 工作：silero VAD 是 16kHz 模型，采样率不符会严重丢段（尤其内录 48k）。
        self.segmenter = Segmenter(sample_rate=SAMPLE_RATE, sensitivity=sensitivity,
                                   max_seg=max_seg, min_silence=min_silence)
        self.asr_prompt = load_asr_prompt()
        self.course_name = ""
        self.course_sections: "list[tuple[str, str]]" = []
        self._last_section = None
        if course_file:
            try:
                import courseware as _cw
                course = _cw.load_course(course_file)
                self.course_name = course.name
                self.course_sections = _cw.load_sections(course_file)
                # 识别热词 = 内置词表 + 课件术语
                extra = _cw.asr_prompt(course)
                if extra:
                    self.asr_prompt = _merge_prompt(self.asr_prompt, extra)
                # 翻译术语表
                gl = _cw.glossary_text(course)
                if gl:
                    self.translator.glossary = gl
                clog(f"已加载课程课件：{course.name}（术语 {len(course.terms)} 条，"
                     f"译法 {len(course.glossary)} 条，分节 {len(self.course_sections)} 页）")
            except Exception as e:
                clog(f"课程课件加载失败：{type(e).__name__}: {e}")
        self.result_q: "queue.Queue[tuple]" = queue.Queue()
        self._asr_q: "queue.Queue[tuple]" = queue.Queue()
        self._seq = 0
        self._threads = []
        self._stream = None
        self._system_thread = None
        self._translate_pool = None
        self._wav = None
        self._wav_path = None
        self.running = False
        self.model = None
        self.current_model = model_size
        self._model_change_pending: str | None = None
        self.tts = TtsPlayer(voice, enabled=voice_enabled)
        self.current_level = 0.0
        self.segments_count = 0
        self._last_metrics = 0.0
        self._last_lag_warn = 0.0

    def request_model_change(self, model: str):
        """运行中切换识别模型；不在运行时就记下，下次启动生效。"""
        if self.running:
            self._model_change_pending = model
            clog(f"已请求切换识别模型 -> {model}（下一次空闲时生效）")
        else:
            self.model_size = model
            clog(f"识别模型设为 -> {model}（下次启动生效）")

    # ---------------- 生命周期 ----------------
    def start(self):
        if self.running:
            return
        self.running = True
        self.segmenter.set_sensitivity(self.sensitivity)

        if self.save_audio:
            try:
                import wave
                d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recordings")
                os.makedirs(d, exist_ok=True)
                self._wav_path = os.path.join(d, f"同传录音_{datetime.now():%Y%m%d_%H%M%S}.wav")
                self._wav = wave.open(self._wav_path, "wb")
                self._wav.setnchannels(1)
                self._wav.setsampwidth(2)
                self._wav.setframerate(SAMPLE_RATE)
                clog(f"正在录制音频 -> {self._wav_path}")
            except Exception as e:
                self._wav = None
                clog(f"无法创建录音文件：{type(e).__name__}: {e}")

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
        if self._wav is not None:
            try:
                self._wav.close()
            except Exception:
                pass
            clog(f"音频已保存 -> {self._wav_path}")
            self._wav = None
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
        self._record(mono, SAMPLE_RATE)
        self.segmenter.feed(np.ascontiguousarray(mono, dtype=np.float32))

    def _record(self, mono, sr):
        """把采集到的声音（可选）写入 16kHz 单声道 WAV，供离线文件模式使用。"""
        if self._wav is None:
            return
        try:
            a16 = _to_16k(np.ascontiguousarray(mono, dtype=np.float32), sr)
            self._wav.writeframes((np.clip(a16, -1.0, 1.0) * 32767).astype("<i2").tobytes())
        except Exception:
            pass

    def _system_capture_loop(self):
        """用 soundcard 内录系统输出声音（WASAPI loopback）。"""
        try:
            import soundcard as sc
        except Exception as e:
            self.error_cb(f"未安装 soundcard，无法内录：{type(e).__name__}: {e}")
            self.running = False
            return
        # soundcard 导入后会强制“总是显示”该警告，须在导入之后才真正屏蔽
        warnings.filterwarnings("ignore", message=".*data discontinuity in recording.*")
        needs_com = _com_init()
        try:
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
                    # silero VAD 是 16kHz 模型，内录块在 feed 前会降到 16k，采样率必须跟着设成 16k。
                    self.segmenter.sample_rate = SAMPLE_RATE
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
                    # 立体声合并成单声道，避免只取左声道漏掉内容（如内容在右/中间声道）。
                    mono = arr.mean(axis=1) if arr.ndim == 2 else arr
                    mono = np.clip(mono, -0.98, 0.98)
                    self.current_level = float(np.sqrt(np.mean(np.square(mono))))
                    mono16 = _to_16k(np.ascontiguousarray(mono, dtype=np.float32), self.capture_rate)
                    self._record(mono16, SAMPLE_RATE)
                    self.segmenter.feed(np.ascontiguousarray(mono16, dtype=np.float32))
            finally:
                try:
                    rec.__exit__(None, None, None)
                except Exception:
                    pass
        finally:
            if needs_com:
                _com_uninit()

    # ---------------- 识别 ----------------
    def _asr_loop(self):
        self.status_cb("正在加载语音模型（首次约 10~20 秒）…")
        clog(f"开始加载识别模型 -> {self.model_size}")
        try:
            self.model = WhisperModel(self.model_size, device="cpu", compute_type="int8")
        except Exception as e:
            self.error_cb(f"语音模型加载失败：{e}")
            clog(f"模型加载失败：{type(e).__name__}: {e}")
            self.running = False
            return
        self.current_model = self.model_size
        self.status_cb("模型就绪，正在听…")
        clog(f"模型就绪 -> {self.current_model}")

        while self.running:
            # 运行中切换模型：在空闲时（拿到下一段之前）重载
            if self._model_change_pending and self._model_change_pending != self.current_model:
                new = self._model_change_pending
                self._model_change_pending = None
                self.status_cb(f"正在切换模型到 {new}…")
                clog(f"正在切换模型 -> {new}")
                try:
                    self.model = WhisperModel(new, device="cpu", compute_type="int8")
                    self.current_model = new
                    self.model_size = new
                    self.status_cb(f"已切换到模型 {new}，继续听…")
                    clog(f"已切换模型 -> {new}")
                except Exception as e:
                    self.error_cb(f"切换模型失败：{type(e).__name__}: {e}")
                    clog(f"切换模型失败：{type(e).__name__}: {e}")
            try:
                seg, dur = self.segmenter.out_q.get(timeout=0.5)
            except queue.Empty:
                continue
            if seg is None:
                break
            try:
                seg = _to_16k(np.ascontiguousarray(seg, dtype=np.float32), self.segmenter.sample_rate)
                seg_iters, info = self.model.transcribe(
                    seg, beam_size=1, language="en", vad_filter=True,
                    condition_on_previous_text=False,
                    initial_prompt=self.asr_prompt,
                )
                text = "".join(s.text for s in seg_iters).strip()
                self.segments_count += 1
                # 跳过太短的残片（很可能是噪声/幻听/被截断），避免翻出奇怪内容
                if len(text.split()) < self.min_words:
                    clog(f"跳过过短片段：{text!r}")
                    continue
                if text:
                    t0 = time.time()
                    self._seq += 1
                    self._asr_q.put((text, t0, self._seq))
                    self.log_cb("EN", text)
                    clog(f"识别(EN): {text}")
            except Exception as e:
                self.error_cb(f"识别出错：{type(e).__name__}: {e}")

    # ---------------- 翻译 ----------------
    def _translate_loop(self):
        """多线程并行翻译，并按序号有序输出，降低排队延迟且不打乱顺序。"""
        executor = ThreadPoolExecutor(max_workers=self.translation_workers)
        self._translate_pool = executor
        try:
            pending: "dict[int, object]" = {}
            next_emit = 1  # seq 从 1 开始
            while True:
                # 每 5 秒打印一次“积压心跳”，反映各队列堆积情况即使没在翻译
                now = time.time()
                if now - self._last_metrics >= 5.0:
                    self._last_metrics = now
                    pend_s = self.segmenter.out_q.qsize()
                    clog(f"[积压] 待翻译={self._asr_q.qsize()} 待识别={pend_s} "
                         f"结果队列={self.result_q.qsize()} 模型={self.current_model}")
                    if pend_s > 6 and now - self._last_lag_warn >= 15:
                        self._last_lag_warn = now
                        clog("⚠ 识别跟不上（待识别段数过多），结果会明显延迟。"
                             "建议：切换到 base.en，或增大分段上限，或改用文件模式。")
                try:
                    item = self._asr_q.get(timeout=0.5)
                except queue.Empty:
                    item = None
                if item is not None:
                    text, t0, seq = item
                    ctx, sec_title = self._retrieve_context(text)  # 只在协调线程做，避免竞态
                    fut = executor.submit(self._do_translate, text, t0, ctx, sec_title)
                    pending[seq] = fut
                # 每次 get 之后都按序号释放已完成的结果（含等待新条目期间完成的）
                while next_emit in pending:
                    f = pending[next_emit]
                    if not f.done():
                        break
                    self.result_q.put(f.result())
                    pending.pop(next_emit)
                    next_emit += 1
                if item is None:
                    if not self.running:
                        break
                    continue
        finally:
            executor.shutdown(wait=False)

    def _do_translate(self, text: str, t0: float, ctx: str, sec_title: str) -> dict:
        try:
            zh = self.translator.translate(text, context=ctx)
            backend = self.translator.last_backend
            err = ""
        except Exception as e:
            zh = ""
            backend = "error"
            err = str(e)[:200]
        lag = time.time() - t0
        clog(f"翻译({backend}) 延迟 {lag:.1f}s | 页:{sec_title or '-'} | "
             f"积压:待翻={self._asr_q.qsize()} 待识={self.segmenter.out_q.qsize()} "
             f"待显={self.result_q.qsize()} | {zh[:24]}")
        return {"en": text, "zh": zh, "backend": backend, "err": err,
                "t0": t0, "section": sec_title, "latency": lag}

    def _retrieve_context(self, text: str) -> tuple[str, str]:
        """用关键词重叠检索当前最相关的课件页，返回 (上下文文本, 页标题)。"""
        if not self.course_sections:
            return "", ""
        import re as _re
        words = set(_re.findall(r"[a-z0-9-]{2,}", text.lower()))
        scores = []
        for title, body in self.course_sections:
            low = (title + " " + body).lower()
            scores.append(sum(1 for w in words if w in low))
        if not scores or max(scores) == 0:
            return "", ""
        best = max(range(len(scores)), key=lambda i: scores[i])
        # 平滑：若上次命中的邻页分数接近，则停留，避免频繁跳页
        prev = self._last_section
        if prev is not None and abs(prev - best) <= 1 and scores[best] < scores[prev] + 3:
            best = prev
        self._last_section = best
        title, body = self.course_sections[best]
        self._last_section_title = title
        return f"[{title}] {body[:500]}", title


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


def _write_with_retry(path: str, mode: str, text: str,
                      tries: int = 14, base_delay: float = 0.05) -> OSError | None:
    """带指数退避重试的写入。返回 None 表示成功，否则返回最后一次 OSError。

    某些环境（杀软 / EDR 实时扫描、OneDrive、索引服务）会在写入瞬间短暂锁定文件，
    导致一次性 open+write 偶发 PermissionError。这里用退避重试扛过去。
    """
    last = None
    for i in range(tries):
        try:
            with open(path, mode, encoding="utf-8") as f:
                f.write(text)
                f.flush()
                # 强制落盘：否则断电/硬关机时，最后写入的内容可能仍在系统页缓存里丢失。
                os.fsync(f.fileno())
            return None
        except OSError as e:
            last = e
            time.sleep(min(base_delay * (2 ** min(i, 6)), 1.0))
    return last


class MarkdownLogger:
    """把实时识别+翻译结果持续追加写入 markdown 文件（每个会话一个文件）。"""

    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self.entries: list[tuple[str, str, str]] = []  # (en, zh, section)
        header = f"# 同声传译记录\n\n> 开始时间：{datetime.now():%Y-%m-%d %H:%M:%S}\n\n"
        err = _write_with_retry(path, "w", header)
        if err is not None:
            raise OSError(f"无法创建转写文件 {path}: {err}")

    @classmethod
    def auto(cls, directory: str | None = None) -> "MarkdownLogger":
        d = directory or transcripts_dir()
        # 毫秒 + 进程号，避免同一秒开启的多个会话/实例生成同名文件互相争抢。
        name = f"同声传译_{datetime.now():%Y%m%d_%H%M%S_%f}_{os.getpid()}.md"
        return cls(os.path.join(d, name))

    def append(self, en: str, zh: str, backend: str = "", section: str = ""):
        ts = datetime.now().strftime("%H:%M:%S")
        note = f"（{backend}）" if backend else ""
        sec = f"§{section} " if section else ""
        line = f"**{ts}** {sec}EN: {en}\n\nZH: {zh}{note}\n\n---\n\n"
        self.entries.append((en, zh, section))
        with self._lock:
            err = _write_with_retry(self.path, "a", line)
            if err is None:
                return
            # 主文件持续被锁：降级追加到备用文件，尽量保住内容，并明确告知。
            try:
                base, ext = os.path.splitext(self.path)
                fb = f"{base}.bak{ext}"
                err2 = _write_with_retry(fb, "a", line)
                if err2 is None:
                    sys.stderr.write(f"[markdown] 主文件被锁，已改存备用文件：{fb}（{type(err).__name__}）\n")
                else:
                    sys.stderr.write(f"[markdown] 转写保存失败 {type(err).__name__}: {err}（备用也失败：{err2}）\n")
            except Exception as e:
                sys.stderr.write(f"[markdown] 转写保存失败 {type(err).__name__}: {err}（备用异常：{e}）\n")


def finalize_transcript(logger):
    """用 AI 总结整段内容，并给 Markdown 重写标题（含时间+主题）+ 追加摘要。"""
    if not logger or not logger.entries:
        clog("本次没有可总结的内容。")
        return
    try:
        from translation import Translator
        tr = Translator()
        text = "\n".join(f"EN: {en}" for en, zh, sec in logger.entries)
        if len(text) > 6000:
            text = text[:6000] + "\n…（内容较长，已截断用于摘要）"
        title, summary = tr.summarize(text)
    except Exception as e:
        clog(f"AI 总结失败：{type(e).__name__}: {e}")
        return

    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    try:
        with open(logger.path, encoding="utf-8") as f:
            old = f.read()
    except OSError:
        old = ""
    idx = old.find("**")
    body = old[idx:] if idx >= 0 else old

    safe_title = re.sub(r'[\\/:*?"<>|]+', "_", title).strip() or "同声传译"
    new_header = (f"# 同声传译 · {title} · {ts}\n\n"
                  f"## 内容摘要\n\n{summary}\n\n---\n\n")
    _write_with_retry(logger.path, "w", new_header + body)

    new_name = f"同声传译_{safe_title}_{datetime.now():%Y%m%d_%H%M%S}.md"
    new_path = os.path.join(os.path.dirname(logger.path), new_name)
    try:
        os.rename(logger.path, new_path)
        logger.path = new_path
    except OSError:
        pass
    clog(f"已生成标题与摘要：{title}")
    clog(f"摘要：{summary[:80]}")


# ----------------------------------------------------------------------------
# 图形界面
# ----------------------------------------------------------------------------
class GUI:
    def __init__(self, root, opts):
        self.root = root
        self.opts = opts
        root.title("同声传译 · 麦克风实时翻译")
        root.geometry("1040x700")
        root.minsize(1000, 660)
        root.configure(bg="#f4f6fb")

        self.en_var = tk.StringVar(value="等待说话…")
        self.zh_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="就绪")
        self.lat_var = tk.StringVar(value="延迟 --")
        self.sec_var = tk.StringVar(value="")
        self.voice_var = tk.BooleanVar(value=opts.voice_enabled)
        self.rec_var = tk.BooleanVar(value=False)
        self.source_var = tk.StringVar(value="麦克风")
        self.model_var = tk.StringVar(value=opts.model)
        self.maxseg_var = tk.StringVar(value="4")
        self.course_var = tk.StringVar(value="(无课件)")
        self.device_var = tk.StringVar()
        self.skip_tts = threading.Lock()
        self.ui_q: "queue.Queue[tuple]" = queue.Queue()
        self.logger: "MarkdownLogger | None" = None
        self._start_time = 0.0
        self._no_seg_warned = False
        self._last_count = 0

        self.pipeline = None
        self._mascot_src = None  # 右侧 mascot 原图（全分辨率，用于缩放）

        self._build_widgets()
        self._refresh_courses()
        self._refresh_devices()
        self._poll()

    def _build_widgets(self):
        proj_dir = os.path.dirname(os.path.abspath(__file__))

        main = tk.Frame(self.root, bg="#f4f6fb")
        main.pack(fill="both", expand=True)

        # ---------------- side bar: mascot + settings ----------------
        sidebar = tk.Frame(main, bg="#ffffff", highlightbackground="#e1e6f0",
                           highlightthickness=1, width=250)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        self._mascot = None
        self._mascot_src = None
        mascot_path = None
        for _name in ("mascot.png", "gui_mascot.png"):
            _p = os.path.join(proj_dir, "docs", _name)
            if os.path.exists(_p):
                mascot_path = _p
                break
        if mascot_path:
            try:
                from PIL import Image, ImageTk
                _src = Image.open(mascot_path).convert("RGBA")
                _ow, _oh = _src.size
                # 右侧图：30% 透明、全分辨率，缩放时以此为基础
                _r, _g, _b, _a = _src.split()
                _a = _a.point(lambda v: int(v * 0.30))
                self._mascot_src = Image.merge("RGBA", (_r, _g, _b, _a))
                # 侧边栏头像：不透明，缩到 220x200 内
                _scale = min(220 / _ow, 200 / _oh)
                _im = _src.resize((max(1, int(_ow * _scale)),
                                   max(1, int(_oh * _scale))), Image.LANCZOS)
                self._mascot = ImageTk.PhotoImage(_im)
                tk.Label(sidebar, image=self._mascot, bg="#ffffff", bd=0).pack(padx=8, pady=8)
            except Exception:
                self._mascot = None
                self._mascot_src = None
        if self._mascot is None:
            tk.Label(sidebar, text="(暂无头像，支持 docs/mascot.png)",
                     bg="#ffffff", fg="#c0c4cc", font=("Microsoft YaHei UI", 9),
                     wraplength=220, justify="center").pack(pady=10)

        tk.Frame(sidebar, bg="#e9edf4", height=2).pack(fill="x", padx=10, pady=(6, 8))

        tk.Label(sidebar, text="声音来源", bg="#ffffff", fg="#6b7280",
                 font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", padx=10)
        self.source_box = ttk.Combobox(sidebar, values=["麦克风", "系统声音"],
                                       textvariable=self.source_var, width=24, state="readonly")
        self.source_box.pack(anchor="w", padx=10, pady=(2, 6))
        self.source_box.bind("<<ComboboxSelected>>", self._on_source)

        tk.Label(sidebar, text="设备", bg="#ffffff", fg="#6b7280",
                 font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", padx=10, pady=(6, 0))
        _dev = tk.Frame(sidebar, bg="#ffffff"); _dev.pack(fill="x", padx=10)
        self.device_box = ttk.Combobox(_dev, textvariable=self.device_var, width=18,
                                       state="readonly")
        self.device_box.pack(side="left", fill="x", expand=True)
        tk.Button(_dev, text="刷新", command=self._refresh_devices,
                  bg="#e5e7eb", fg="#374151", font=("Microsoft YaHei UI", 9),
                  padx=6, pady=2, bd=0, cursor="hand2").pack(side="left", padx=(4, 0))

        tk.Label(sidebar, text="识别模型", bg="#ffffff", fg="#6b7280",
                 font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", padx=10, pady=(10, 0))
        self.model_box = ttk.Combobox(sidebar, textvariable=self.model_var,
                                      values=["tiny.en", "base.en", "small.en", "medium.en",
                                              "large-v3-turbo", "large-v3"],
                                      width=22, state="readonly")
        self.model_box.pack(anchor="w", padx=10, pady=(2, 4))
        self.model_box.bind("<<ComboboxSelected>>", self._on_model)
        tk.Label(sidebar, text="[越大越准但越慢；大模型建议配合文件模式]",
                 bg="#ffffff", fg="#9ca3af", font=("Microsoft YaHei UI", 8),
                 wraplength=220, justify="left").pack(anchor="w", padx=10)

        tk.Label(sidebar, text="课程课件", bg="#ffffff", fg="#6b7280",
                 font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", padx=10, pady=(10, 0))
        _crs = tk.Frame(sidebar, bg="#ffffff"); _crs.pack(fill="x", padx=10)
        self.course_box = ttk.Combobox(_crs, textvariable=self.course_var, width=18,
                                       state="readonly")
        self.course_box.pack(side="left", fill="x", expand=True)
        tk.Button(_crs, text="刷新", command=self._refresh_courses,
                  bg="#e5e7eb", fg="#374151", font=("Microsoft YaHei UI", 9),
                  padx=6, pady=2, bd=0, cursor="hand2").pack(side="left", padx=(4, 0))

        tk.Label(sidebar, text="灵敏度（低=更灵敏，高=抗噪）", bg="#ffffff", fg="#6b7280",
                 font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", padx=10, pady=(10, 0))
        _sens = tk.Frame(sidebar, bg="#ffffff"); _sens.pack(fill="x", padx=10)
        self.sens_scale = ttk.Scale(_sens, from_=1.0, to=8.0, value=3.0, command=self._on_sens)
        self.sens_scale.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.sens_val = tk.Label(_sens, text="3.0", bg="#ffffff", font=("Microsoft YaHei UI", 10))
        self.sens_val.pack(side="left")

        tk.Label(sidebar, text="分段上限", bg="#ffffff", fg="#6b7280",
                 font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", padx=10, pady=(8, 0))
        self.maxseg_box = ttk.Combobox(sidebar, textvariable=self.maxseg_var,
                                       values=["4", "5", "6", "8", "10"], width=22, state="readonly")
        self.maxseg_box.pack(anchor="w", padx=10, pady=(2, 4))
        tk.Label(sidebar, text="[小=更快但更易切断]", bg="#ffffff", fg="#9ca3af",
                 font=("Microsoft YaHei UI", 8)).pack(anchor="w", padx=10)

        # ---------------- main content ----------------
        content = tk.Frame(main, bg="#f4f6fb")
        content.pack(side="left", fill="both", expand=True)

        top = tk.Frame(content, bg="#f4f6fb")
        top.pack(fill="x", padx=12, pady=(10, 4))
        tk.Label(top, textvariable=self.status_var, bg="#f4f6fb", fg="#1f6feb",
                 font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w")

        meter_row = tk.Frame(content, bg="#f4f6fb")
        meter_row.pack(fill="x", padx=12, pady=(0, 4))
        self.meter = ttk.Progressbar(meter_row, orient="horizontal", maximum=1.0, value=0.0)
        self.meter.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.meter_label = tk.Label(meter_row, text="待机", bg="#f4f6fb", fg="#9ca3af",
                                    font=("Microsoft YaHei UI", 10), width=16, anchor="e")
        self.meter_label.pack(side="left")
        self.lat = tk.Label(meter_row, textvariable=self.lat_var, bg="#f4f6fb", fg="#dc2626",
                            font=("Microsoft YaHei UI", 10, "bold"))
        self.lat.pack(side="left", padx=(10, 0))
        self.sec = tk.Label(meter_row, textvariable=self.sec_var, bg="#f4f6fb", fg="#7c3aed",
                            font=("Microsoft YaHei UI", 10))
        self.sec.pack(side="left", padx=(10, 0))

        en_card = tk.Frame(content, bg="#ffffff", highlightbackground="#e1e6f0", highlightthickness=1)
        en_card.pack(fill="x", padx=12, pady=6)
        tk.Label(en_card, text="英文原文", bg="#ffffff", fg="#6b7280",
                 font=("Microsoft YaHei UI", 10)).pack(anchor="w", padx=10, pady=(8, 0))
        tk.Label(en_card, textvariable=self.en_var, bg="#ffffff", fg="#111827",
                 font=("Microsoft YaHei UI", 15), wraplength=660, justify="left",
                 anchor="w").pack(fill="x", padx=10, pady=(2, 10))

        zh_card = tk.Frame(content, bg="#ffffff", highlightbackground="#e1e6f0", highlightthickness=1)
        zh_card.pack(fill="x", padx=12, pady=6)
        tk.Label(zh_card, text="中文翻译", bg="#ffffff", fg="#6b7280",
                 font=("Microsoft YaHei UI", 10)).pack(anchor="w", padx=10, pady=(8, 0))
        tk.Label(zh_card, textvariable=self.zh_var, bg="#ffffff", fg="#0b7a3b",
                 font=("Microsoft YaHei UI", 17, "bold"), wraplength=660, justify="left",
                 anchor="w").pack(fill="x", padx=10, pady=(2, 10))

        ctrl = tk.Frame(content, bg="#f4f6fb")
        ctrl.pack(fill="x", padx=12, pady=6)
        self.start_btn = tk.Button(ctrl, text="▶ 开始", command=self.toggle,
                                   bg="#1f6feb", fg="white", font=("Microsoft YaHei UI", 11),
                                   padx=18, pady=6, bd=0, cursor="hand2")
        self.start_btn.pack(side="left", padx=(0, 8))
        self.save_btn = tk.Button(ctrl, text="清屏", command=self.clear,
                                  bg="#e5e7eb", fg="#374151", font=("Microsoft YaHei UI", 10),
                                  padx=12, pady=6, bd=0, cursor="hand2")
        self.save_btn.pack(side="left", padx=4)
        tk.Checkbutton(ctrl, text="中文语音播报", variable=self.voice_var, command=self._on_voice,
                       bg="#f4f6fb", font=("Microsoft YaHei UI", 10),
                       activebackground="#f4f6fb").pack(side="left", padx=12)
        tk.Checkbutton(ctrl, text="录制音频存文件", variable=self.rec_var,
                       bg="#f4f6fb", font=("Microsoft YaHei UI", 10),
                       activebackground="#f4f6fb").pack(side="left", padx=4)

        tk.Label(content, text="记录", bg="#f4f6fb", fg="#6b7280",
                 font=("Microsoft YaHei UI", 10)).pack(anchor="w", padx=12, pady=(10, 0))
        log_frame = tk.Frame(content, bg="#ffffff", highlightbackground="#e1e6f0", highlightthickness=1)
        log_frame.pack(fill="both", expand=True, padx=12, pady=(2, 12))
        # 左：日志文字（列可伸缩）；右：mascot（列固定宽）。用 grid 保证总宽=日志框宽。
        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_columnconfigure(1, weight=0)
        log_frame.grid_rowconfigure(0, weight=1)
        self.log = tk.Text(log_frame, bg="#ffffff", fg="#374151", wrap="word",
                           font=("Microsoft YaHei UI", 10), bd=0, state="disabled")
        self.log.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        self.log.tag_configure("gray", foreground="#9aa0a6")
        self._side_img = None
        self._side = None
        if self._mascot_src:
            self._side = tk.Frame(log_frame, bg="#ffffff", width=0)
            self._side.grid(row=0, column=1, sticky="ns")
            self._side.grid_propagate(False)
            self._side_label = tk.Label(self._side, bg="#ffffff", bd=0)
            self._side_label.pack(fill="both", expand=True)
            log_frame.bind("<Configure>", self._on_log_layout)

    def _on_log_layout(self, event):
        """按日志框高度布局右侧 mascot（30% 透明、撑满高、宽=高*比例；总宽不变）。"""
        if not self._mascot_src or self._side is None:
            return
        src = self._mascot_src
        h = max(30, event.height - 10)
        aspect = src.width / src.height
        # 图片列宽=高度*比例，但不超日志框宽度的 55%，保证左边文字有足够空间
        w = max(30, min(int(h * aspect), int(event.width * 0.55)))
        if int(self._side.cget("width")) != w:
            self._side.configure(width=w)
        sc = min((w - 2) / src.width, (event.height - 8) / src.height)
        nw = max(1, int(src.width * sc))
        nh = max(1, int(src.height * sc))
        from PIL import Image, ImageTk
        self._side_img = ImageTk.PhotoImage(src.resize((nw, nh), Image.LANCZOS))
        self._side_label.configure(image=self._side_img)

    # ---------------- 设备 ----------------
    def _refresh_devices(self):
        if self.source_var.get() == "系统声音":
            self._devices = {}
            items = []
            try:
                import soundcard as sc
                warnings.filterwarnings("ignore", message=".*data discontinuity in recording.*")
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
        clog(f"声音来源 -> {self.source_var.get()}")
        self._refresh_devices()

    def _on_model(self, event=None):
        m = self.model_var.get()
        clog(f"识别模型选择 -> {m}")
        if self.pipeline:
            self.pipeline.request_model_change(m)
        else:
            clog("尚未启动，将在下次开始生效")

    def _refresh_courses(self):
        proj_dir = os.path.dirname(os.path.abspath(__file__))
        found = []
        for sub in ("courseware", "docs"):
            d = os.path.join(proj_dir, sub)
            if os.path.isdir(d):
                for f in sorted(os.listdir(d)):
                    if f.lower().endswith(".md"):
                        found.append(os.path.join(d, f))
        vals = ["(无课件)"] + found
        self.course_box["values"] = vals
        if self.course_var.get() not in vals:
            self.course_var.set("(无课件)")

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
                clog(">>> 停止")
                self._after_stop_finalize()
            else:
                clog(">>> 开始")
                self._build_pipeline()
                self.start_btn.configure(text="■ 停止")
                self.logger = MarkdownLogger.auto()
                self._show_hint(f"记录将保存到：{self.logger.path}")
                clog(f"Markdown 记录 -> {self.logger.path}")
                self._start_time = time.time()
                self._no_seg_warned = False
                self._last_count = 0
                self.pipeline.start()
        except Exception as e:
            self.status_var.set("⚠ 启动出错：" + str(e))
            self._append_log("ERR", f"启动出错: {type(e).__name__}: {e}")

    def _after_stop_finalize(self):
        """停止后：若录了内容，用 AI 总结并重写转写稿标题。"""
        self.status_var.set("正在用 AI 总结本次内容…")
        if self.logger is not None:
            threading.Thread(target=finalize_transcript, args=(self.logger,), daemon=True).start()

    def _show_hint(self, line: str):
        self._append_log("INFO", line)

    def _build_pipeline(self):
        source = "system" if self.source_var.get() == "系统声音" else "mic"
        course_file = None if self.course_var.get() == "(无课件)" else self.course_var.get()
        self.pipeline = Pipeline(
            model_size=self.model_var.get(),
            voice_enabled=self.voice_var.get(),
            source=source,
            save_audio=self.rec_var.get(),
            max_seg=float(self.maxseg_var.get()),
            course_file=course_file,
            device=self._selected_device(),
            sensitivity=float(self.sens_scale.get()),
            status_cb=lambda s: self.ui_q.put(("status", s)),
            segment_cb=None,
            error_cb=lambda e: self.ui_q.put(("error", e)),
            log_cb=lambda kind, text: self.ui_q.put(("log", kind, text)),
        )

    def clear(self):
        clog(">>> 清屏")
        self.en_var.set("等待说话…")
        self.zh_var.set("")
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _on_voice(self):
        on = self.voice_var.get()
        clog(f"中文语音播报 -> {'开' if on else '关'}")
        if self.pipeline:
            self.pipeline.voice_enabled = on
            if self.pipeline.tts:
                self.pipeline.tts.enabled = on
        self.status_var.set("中文语音播报：开" if on else "中文语音播报：关")

    def _on_sens(self, val):
        clog(f"灵敏度 -> {float(val):.1f}")
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
            tag = "gray"
        elif kind == "EN":
            line = f"[{ts}] EN: {text}\n"
            tag = None
        elif kind == "ZH":
            line = f"    ZH: {text}\n"
            tag = None
        else:
            line = text + "\n"
            tag = "gray"
        self._log_line(line, tag)

    def _log_line(self, line: str, tag: str | None = None):
        self.log.configure(state="normal")
        if tag:
            self.log.insert("end", line, tag)
        else:
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
        if not isinstance(item, dict):
            return  # 停止时队列里的 None 哨兵
        en = item.get("en", "")
        zh = item.get("zh", "")
        backend = item.get("backend", "")
        lat = item.get("latency")
        if isinstance(lat, (int, float)):
            self.lat_var.set(f"延迟 {lat:.1f}s")
        sec = item.get("section")
        if sec:
            self.sec_var.set(f"§ {sec}")
        self.en_var.set(en)
        if zh:
            self.zh_var.set(zh)
            self._append_log("ZH", zh)
        elif item.get("err"):
            self.zh_var.set("(翻译失败，仅显示原文)")
            self._append_log("ERR", item.get("err"))
        if self.logger and en:
            self.logger.append(en, zh, backend, sec)
        if self.pipeline and self.voice_var.get() and zh:
            self.pipeline.tts.speak(zh)

    def on_close(self):
        if self.pipeline:
            self.pipeline.stop()
        if self.logger is not None:
            try:
                clog(f"已停止，转写稿保存位置：{self.logger.path}")
                self._append_log("INFO", f"已停止，转写稿保存位置：{self.logger.path}")
                finalize_transcript(self.logger)
            except Exception:
                pass
        self.root.destroy()


# ----------------------------------------------------------------------------
# 控制台模式
# ----------------------------------------------------------------------------
def run_console(opts):
    trans = Translator()
    print(f"{_C_GRAY}已使用 API key：{trans.key_summary()}{_C_RESET}")
    src_txt = "系统声音" if opts.source == "system" else "麦克风"
    print(f"{_C_GRAY}正在从{src_txt}实时识别并翻译… Ctrl+C 退出。{_C_RESET}\n")
    pipe = Pipeline(model_size=opts.model, voice_enabled=opts.voice_enabled,
                    source=opts.source, device=opts.device, sensitivity=opts.sensitivity,
                    save_audio=opts.save_audio,
                    course_file=opts.course,
                    max_seg=opts.max_seg, min_silence=opts.min_silence,
                    min_words=opts.min_words,
                    status_cb=lambda s: print(f"{_C_GRAY}[状态] {s}{_C_RESET}"),
                    segment_cb=None,
                    error_cb=lambda e: print(f"{_C_GRAY}[出错] {e}{_C_RESET}"),
                    log_cb=_console_log)
    # 存好 translator 引用
    print(f"{_C_GRAY}按 Enter 开始采集…{_C_RESET}")
    input()
    logger = MarkdownLogger.auto()
    print(f"{_C_GRAY}记录将保存到：{logger.path}{_C_RESET}")
    pipe.start()
    t0 = time.time()
    try:
        while True:
            try:
                item = pipe.result_q.get(timeout=0.5)
            except queue.Empty:
                continue
            if item is None:
                break
            en = item["en"]; zh = item["zh"]
            print(f"{_C_GRAY}{'─' * 60}{_C_RESET}")
            print("EN:", en)
            if zh:
                print("ZH:", zh)
            if item.get("err"):
                print(f"{_C_GRAY}   (翻译失败: {item['err']}){_C_RESET}")
            print(f"{_C_GRAY}   延迟: {item['latency']:.1f}s | {item['backend']}{_C_RESET}")
            logger.append(en, zh, item.get("backend", ""))
    except KeyboardInterrupt:
        pass
    finally:
        pipe.stop()
        try:
            print("正在用 AI 总结本次内容…")
            finalize_transcript(logger)
            p = logger.path
            print(f"{_C_GRAY}\n[已结束] 转写稿保存位置：{p}{_C_RESET}")
            bak = os.path.splitext(p)[0] + ".bak" + os.path.splitext(p)[1]
            if os.path.exists(bak):
                print(f"{_C_GRAY}[提示] 主文件曾被锁定，另有备用稿：{bak}{_C_RESET}")
        except Exception:
            pass


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
            f.flush()
            os.fsync(f.fileno())
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
    ap.add_argument("--model", default="base.en",
                    help="whisper 模型（tiny.en/base.en/small.en/medium.en/"
                         "large-v3-turbo/large-v3；实时默认 base.en，tiny.en 最快，大模型建议文件模式）")
    ap.add_argument("--console", action="store_true", help="控制台模式")
    ap.add_argument("--file", default=None, help="识别单个音频文件（mp3/wav 等）")
    ap.add_argument("--save", action="store_true", help="文件模式保存 markdown 记录")
    ap.add_argument("--voice", dest="voice_enabled", action="store_true", default=True,
                    help="开启中文语音（默认开）")
    ap.add_argument("--no-voice", dest="voice_enabled", action="store_false", help="关闭中文语音")
    ap.add_argument("--sensitivity", type=float, default=3.0)
    ap.add_argument("--max-seg", type=float, default=4.0,
                    help="分段上限（秒），默认 4.0；调大使长句不易被切断但延迟更高")
    ap.add_argument("--min-silence", type=float, default=0.5,
                    help="判定一句结束的静音时长（秒），默认 0.5")
    ap.add_argument("--min-words", type=int, default=3,
                    help="少于该单词数的识别片段会被跳过（默认 3；设 1 表示不过滤）")
    ap.add_argument("--list-devices", action="store_true", help="列出麦克风设备")
    ap.add_argument("--test-mic", action="store_true", help="自检麦克风电平")
    ap.add_argument("--source", choices=["mic", "system"], default="mic",
                    help="声音来源：mic=麦克风，system=电脑内部声音(内录)")
    ap.add_argument("--save-audio", action="store_true",
                    help="同时把采集到的声音录入 recordings\\*.wav（16kHz 单声道）")
    ap.add_argument("--course", default=None,
                    help="课程课件 Markdown 路径（如 courseware\\xxx.md），用于术语对齐")
    ap.add_argument("--device", default=None,
                    help="指定设备名或ID（麦克风输入或内录设备）；默认自动选择")
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
