#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""环境自检（doctor）：一条命令检查“这台电脑能不能跑起来”，并把问题说清楚。

用法：
    .venv\\Scripts\\python.exe doctor.py          # 完整检查（含联网 + 翻译实测）
    .venv\\Scripts\\python.exe doctor.py --quick  # 只查本机，不联网

双击 诊断.bat 等价于完整检查。遇到问题时把整段输出复制给维护者即可定位。
"""

from __future__ import annotations

import argparse
import glob
import os
import platform
import socket
import struct
import sys
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))

LEVEL_OK, LEVEL_WARN, LEVEL_FAIL, LEVEL_SKIP = "ok", "warn", "fail", "skip"
RESULTS: "list[tuple[str, str]]" = []

# 默认会用到的模型：base.en 用于实时字幕，small.en 用于课后文件模式精翻。
REQUIRED_MODELS = ["base.en", "small.en"]
OPTIONAL_MODELS = ["large-v3-turbo"]

NET_HOSTS = [
    ("huggingface.co", 443, "下载语音模型（首次必须）"),
    ("hf-mirror.com", 443, "模型镜像（大陆网络备用）"),
    ("api.deepseek.com", 443, "DeepSeek 翻译（有 key 时使用）"),
    ("translate.googleapis.com", 443, "Google 免费翻译（无 key 时兜底）"),
]


# ---------------------------------------------------------------------------
# 输出工具
# ---------------------------------------------------------------------------
def _emit(level: str, msg: str, mark: str) -> None:
    print(f"  [{mark}] {msg}")
    RESULTS.append((level, msg))


def ok(msg: str) -> None:
    _emit(LEVEL_OK, msg, "OK")


def warn(msg: str) -> None:
    _emit(LEVEL_WARN, msg, "!!")


def fail(msg: str) -> None:
    _emit(LEVEL_FAIL, msg, "XX")


def skip(msg: str) -> None:
    _emit(LEVEL_SKIP, msg, "--")


def info(msg: str) -> None:
    print(f"       {msg}")


def section(title: str) -> None:
    print(f"\n{title}")


def _human_size(n: int) -> str:
    if n <= 0:
        return "0 B"
    if n < 1024 * 1024:
        return f"{n / 1024:.0f} KB"
    if n < 1024 ** 3:
        return f"{n / 1024 ** 2:.0f} MB"
    return f"{n / 1024 ** 3:.1f} GB"


def _dir_size(path: str) -> int:
    total = 0
    for dirpath, _dirnames, filenames in os.walk(path):
        for name in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, name))
            except OSError:
                pass
    return total


def _pkg_version(module_name: str, dist_name: str) -> str:
    try:
        from importlib.metadata import version
        return version(dist_name)
    except Exception:
        mod = sys.modules.get(module_name)
        return getattr(mod, "__version__", "?")


# ---------------------------------------------------------------------------
# 各项检查
# ---------------------------------------------------------------------------
def check_python() -> None:
    section("[1] 系统与 Python")
    info(f"操作系统：{platform.platform()}")
    info(f"Python  ：{platform.python_version()} "
         f"({struct.calcsize('P') * 8} 位) -> {sys.executable}")

    if sys.version_info >= (3, 10):
        ok(f"Python 版本符合要求（{platform.python_version()}，需要 3.10+）")
    else:
        fail(f"Python {platform.python_version()} 太旧，需要 3.10 或更高版本")

    if struct.calcsize("P") * 8 == 32:
        warn("当前是 32 位 Python，建议改装 64 位（识别更快、可用更大模型）")

    venv_dir = os.path.join(HERE, ".venv")
    if not os.path.isdir(venv_dir):
        fail("找不到 .venv 虚拟环境 → 请先双击“安装同声传译.bat”完成安装")
    elif os.path.abspath(sys.prefix).lower().startswith(os.path.abspath(venv_dir).lower()):
        ok("正在使用项目的 .venv 虚拟环境")
    else:
        warn("当前解释器不是项目的 .venv：依赖可能不全。"
             "请用“启动同声传译.bat”启动，或运行 .venv\\Scripts\\python.exe doctor.py")

    try:
        import tkinter  # noqa: F401
        ok(f"tkinter 可用（Tk {tkinter.TkVersion}）→ 图形界面能打开")
    except Exception as e:
        fail(f"tkinter 不可用（{type(e).__name__}）→ 图形界面打不开；"
             "请重装 python.org 版 Python（安装时勾选 tcl/tk and IDLE），"
             "或改用命令行模式")


DEPS = [
    ("numpy", "numpy", True, "数值计算（必需）"),
    ("sounddevice", "sounddevice", True, "麦克风采集（必需）"),
    ("faster_whisper", "faster-whisper", True, "英文识别（必需）"),
    ("ctranslate2", "ctranslate2", True, "识别推理引擎（必需）"),
    ("av", "av", True, "音频解码（文件模式必需）"),
    ("soundcard", "soundcard", True, "系统内录（内录模式必需）"),
    ("edge_tts", "edge-tts", True, "中文朗读（可选功能）"),
    ("scipy", "scipy", True, "重采样（内录模式需要）"),
    ("pymupdf", "pymupdf", True, "课件 PDF 解析（可选功能）"),
    ("pptx", "python-pptx", True, "课件 PPT 解析（可选功能）"),
    ("PIL", "pillow", True, "图形界面头像（可选功能）"),
]


def check_deps() -> None:
    section("[2] 依赖包")
    import importlib

    missing = []
    for module_name, dist_name, required, desc in DEPS:
        try:
            importlib.import_module(module_name)
        except Exception as e:
            missing.append(dist_name)
            (fail if required else warn)(f"缺少 {dist_name}（{desc}）：{type(e).__name__}")
        else:
            ok(f"{dist_name} {_pkg_version(module_name, dist_name)}（{desc}）")
    if missing:
        info("补装依赖：双击“安装同声传译.bat”，或运行")
        info(".venv\\Scripts\\python.exe -m pip install -r requirements.txt")


def check_modules() -> None:
    section("[3] 程序模块与识别设备")
    sys.path.insert(0, HERE)
    try:
        import tongchuan
        ok("主程序模块导入正常（tongchuan / translation / courseware）")
    except Exception as e:
        fail(f"主程序模块导入失败：{type(e).__name__}: {e}")
        return

    try:
        dev, compute = tongchuan._asr_device_compute()
        if dev == "cuda":
            ok(f"识别设备：GPU（CUDA，{compute}）")
        else:
            ok("识别设备：CPU（int8）——正常；实时请用 base.en / tiny.en")
    except Exception as e:
        warn(f"识别设备探测失败（不影响启动）：{type(e).__name__}: {e}")

    try:
        import ctranslate2
        n = ctranslate2.get_cuda_device_count()
        info(f"ctranslate2 CUDA 设备数：{n}")
    except Exception:
        pass


def _hf_cache_root() -> str:
    root = os.environ.get("HF_HUB_CACHE")
    if not root:
        try:
            from huggingface_hub import constants as hfc
            root = getattr(hfc, "HF_HUB_CACHE", None)
        except Exception:
            root = None
    if not root:
        hf_home = os.environ.get("HF_HOME") or os.path.join(
            os.path.expanduser("~"), ".cache", "huggingface")
        root = os.path.join(hf_home, "hub")
    return root


def _find_model_dir(cache_root: str, size: str) -> str | None:
    matches = glob.glob(os.path.join(cache_root, f"models--*faster-whisper-{size}"))
    if not matches:
        return None
    return max(matches, key=_dir_size)


def check_models() -> None:
    section("[4] 语音模型（首次使用需联网下载，之后离线可用）")
    cache_root = _hf_cache_root()
    info(f"模型缓存目录：{cache_root}")
    endpoint = os.environ.get("HF_ENDPOINT")
    if endpoint:
        info(f"HF_ENDPOINT（镜像）：{endpoint}")

    for size in REQUIRED_MODELS + OPTIONAL_MODELS:
        path = _find_model_dir(cache_root, size)
        if path and _dir_size(path) > 1024 * 1024:
            ok(f"{size} 已就绪（{_human_size(_dir_size(path))}）")
        elif size in REQUIRED_MODELS:
            warn(f"{size} 还没下载 → 首次使用对应模式时需要联网下载（约几十 MB~几百 MB）")
        else:
            info(f"{size} 未下载（可选，仅离线精翻/最准模式需要）")


def check_network(quick: bool) -> None:
    section("[5] 网络连通性")
    if quick:
        skip("已按 --quick 跳过联网检查")
        return
    for host, port, purpose in NET_HOSTS:
        t0 = datetime.now()
        try:
            with socket.create_connection((host, port), timeout=4):
                ms = (datetime.now() - t0).total_seconds() * 1000
            ok(f"{host} 可连接（{ms:.0f} ms）——{purpose}")
        except Exception as e:
            warn(f"{host} 连不上（{type(e).__name__}）——{purpose}")


def check_translation(quick: bool) -> None:
    section("[6] 翻译后端")
    try:
        from translation import Translator, load_api_key
    except Exception as e:
        fail(f"translation 模块导入失败：{type(e).__name__}: {e}")
        return

    key = load_api_key()
    if key:
        masked = key[:3] + "***" + key[-3:] if len(key) > 8 else "***"
        ok(f"已找到 API key（{masked}）→ 走 DeepSeek，术语翻译质量最好")
    else:
        env_file = os.path.join(HERE, ".env")
        warn("没有找到 API key（环境变量 / .env / ~/.codex/config.toml 都没有）")
        info("不填也能用：会自动退回 Google 免费翻译（术语和长句质量略低）。")
        info("想要 DeepSeek：双击“设置API密钥.bat”，填入 sk- 开头的 key。")
        if not os.path.exists(env_file):
            info(f"（当前没有 {env_file}）")

    if quick:
        skip("已按 --quick 跳过翻译实测")
        return

    t0 = datetime.now()
    try:
        tr = Translator()
        out = tr.translate("The cache coherence protocol MESI keeps cores consistent.")
        ms = (datetime.now() - t0).total_seconds() * 1000
        ok(f"翻译实测成功（{tr.last_backend}，{ms:.0f} ms）：{out[:40]}")
    except Exception as e:
        fail(f"翻译实测失败：{type(e).__name__}: {str(e)[:160]}")
        info("英文字幕仍会正常显示，只是没有中文；请检查网络或 API key。")


def check_audio() -> None:
    section("[7] 音频设备")
    try:
        import sounddevice as sd
        inputs = [d for d in sd.query_devices() if d["max_input_channels"] > 0]
        if inputs:
            ok(f"发现 {len(inputs)} 个麦克风/输入设备")
            try:
                default_in = sd.default.device[0]
                info(f"默认输入设备：{sd.query_devices(default_in)['name']}")
            except Exception:
                pass
        else:
            fail("没有发现任何输入设备 → 请插好麦克风/耳机，"
                 "并在“设置 → 隐私 → 麦克风”里允许桌面应用使用麦克风")
    except Exception as e:
        fail(f"音频库无法枚举麦克风：{type(e).__name__}: {e}")

    try:
        import soundcard as sc
        mics = sc.all_microphones(include_loopback=True)
        loopbacks = [m for m in mics if getattr(m, "isloopback", False)]
        if loopbacks:
            ok(f"发现 {len(loopbacks)} 个可内录（系统声音）设备")
            for m in loopbacks[:3]:
                info(f"内录：{m.name}")
        else:
            warn("没有发现内录设备（系统声音模式不可用；麦克风/文件模式仍可用）")
    except Exception as e:
        warn(f"内录设备枚举失败（只影响系统声音模式）：{type(e).__name__}: {e}")


def check_disk() -> None:
    section("[8] 保存目录写入")
    targets = [
        (os.path.join(HERE, "transcripts"), "转写稿"),
        (os.environ.get("RECORDINGS_DIR") or os.path.join(HERE, "recordings"), "录音"),
        (os.path.join(HERE, "courseware"), "课件"),
    ]
    for path, label in targets:
        try:
            os.makedirs(path, exist_ok=True)
            probe = os.path.join(path, ".doctor_write_test")
            with open(probe, "w", encoding="utf-8") as f:
                f.write("ok")
            os.remove(probe)
            ok(f"{label}目录可写：{path}")
        except Exception as e:
            fail(f"{label}目录不可写（{type(e).__name__}: {e}）：{path}")
            info("常见原因：目录在只读盘/网盘同步盘上，或被安全软件锁定。")


def summary() -> int:
    counts = {LEVEL_OK: 0, LEVEL_WARN: 0, LEVEL_FAIL: 0, LEVEL_SKIP: 0}
    for level, _ in RESULTS:
        counts[level] = counts.get(level, 0) + 1
    print("\n" + "-" * 60)
    print(f"结果：正常 {counts[LEVEL_OK]} 项 | 警告 {counts[LEVEL_WARN]} 项 "
          f"| 失败 {counts[LEVEL_FAIL]} 项")
    if counts[LEVEL_FAIL]:
        print("结论：还有必须解决的问题（看上面 XX 开头的行）。")
        print("      解决后重跑一次“诊断.bat”；仍不行请把本窗口内容全部复制发给维护者。")
        return 1
    if counts[LEVEL_WARN]:
        print("结论：可以运行，但上面 !! 的警告建议看一下（多为可选功能或网络问题）。")
    else:
        print("结论：环境完全正常，双击“启动同声传译.bat”即可开始。")
    print("提示：遇到任何问题，把本窗口内容整段复制发给维护者最省时间。")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="同声传译环境自检")
    ap.add_argument("--quick", action="store_true", help="跳过联网/翻译实测，只查本机")
    args = ap.parse_args()

    print("=" * 60)
    print(" 同声传译 · 环境自检（doctor）")
    print(f" 项目目录：{HERE}")
    print(f" 检查时间：{datetime.now():%Y-%m-%d %H:%M:%S}")
    print("=" * 60)

    check_python()
    check_deps()
    check_modules()
    check_models()
    check_network(args.quick)
    check_translation(args.quick)
    check_audio()
    check_disk()
    return summary()


if __name__ == "__main__":
    sys.exit(main())
