#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""下载语音识别模型到本机缓存（装一次，之后离线可用）。

用法：
    .venv\\Scripts\\python.exe setup_models.py base.en small.en

直连 HuggingFace 失败时会自动改用国内镜像 hf-mirror.com 重试一次。
已有模型的会跳过，所以重复运行是安全的。
"""

from __future__ import annotations

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from doctor import _dir_size, _find_model_dir, _hf_cache_root  # noqa: E402

MIN_BYTES = 5 * 1024 * 1024   # 小于 5MB 视为没下载完整


def already_have(size: str) -> bool:
    path = _find_model_dir(_hf_cache_root(), size)
    return bool(path) and _dir_size(path) > MIN_BYTES


def download(size: str) -> None:
    """真正触发下载：构造一次 WhisperModel 即会把模型缓存到本地。"""
    from faster_whisper import WhisperModel

    WhisperModel(size, device="cpu", compute_type="int8")


def fetch(size: str) -> bool:
    if already_have(size):
        print(f"[跳过] {size} 已在本机，无需重新下载")
        return True
    print(f"[下载] {size} …（进度条由 HuggingFace 显示，可能较慢）")
    try:
        download(size)
    except Exception as e:
        print(f"[直连失败] {size}: {type(e).__name__}: {str(e)[:200]}")
        if os.environ.get("LI_MIRROR_TRIED"):
            return False
        print("[重试] 改用国内镜像 hf-mirror.com 再试一次 …")
        env = dict(os.environ, HF_ENDPOINT="https://hf-mirror.com", LI_MIRROR_TRIED="1")
        r = subprocess.run([sys.executable, os.path.abspath(__file__), size], env=env)
        return r.returncode == 0
    print(f"[完成] {size} 下载完成")
    return True


def main() -> int:
    sizes = sys.argv[1:]
    if not sizes:
        sizes = ["base.en", "small.en"]

    failed = [size for size in sizes if not fetch(size)]

    print()
    if failed:
        print("以下模型没能下载：" + ", ".join(failed))
        print("可以先继续用（首次用到时程序会再尝试下载）；网络通畅后重跑本脚本即可补上。")
        return 1
    print("语音模型已就绪。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
