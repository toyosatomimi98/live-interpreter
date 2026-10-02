"""Build 启动同声传译.exe  (the click-to-run launcher).

Usage (from the project root):

    build_launcher.bat
    # or
    .venv\\Scripts\\python.exe tools\\build_launcher.py

The result is a single, icon-carrying exe in the project root.  It stays
small on purpose: the heavy lifting (torch / whisper / tkinter) stays in the
project's .venv, which the launcher starts.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD_NAME = "live-interpreter"           # ascii name used while building
EXE_TARGET = "启动同声传译.exe"            # what the user double-clicks
EXE_TARGET_EN = "live-interpreter.exe"    # ascii alias, handy for scripts

ICON = os.path.join(ROOT, "assets", "app.ico")
VERSION_FILE = os.path.join(ROOT, "tools", "version_info.txt")


def log(msg: str) -> None:
    try:
        print(msg, flush=True)
    except Exception:
        pass


def ensure_pyinstaller() -> bool:
    try:
        import PyInstaller  # noqa: F401

        return True
    except ImportError:
        log("[build] PyInstaller not found - installing it into .venv ...")
        rc = subprocess.call([sys.executable, "-m", "pip", "install", "pyinstaller"])
        if rc != 0:
            log("[build] pip install pyinstaller failed - check your network/proxy.")
            return False
        return True


def ensure_icon() -> None:
    if os.path.exists(ICON):
        return
    log("[build] assets/app.ico missing - regenerating it ...")
    subprocess.check_call([sys.executable, os.path.join(ROOT, "tools", "make_icon.py")])


def main() -> int:
    if not ensure_pyinstaller():
        return 1
    ensure_icon()

    dist = os.path.join(ROOT, "dist")
    work = os.path.join(ROOT, "build", "pyinstaller")
    spec = os.path.join(ROOT, "build")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        os.path.join(ROOT, "launcher.py"),
        "--name", BUILD_NAME,
        "--onefile",
        "--noconsole",
        "--noconfirm",
        "--clean",
        "--icon", ICON,
        "--distpath", dist,
        "--workpath", work,
        "--specpath", spec,
        # the launcher shells out to the venv; it must not drag the whole
        # scientific stack (or tkinter) into the exe
        "--exclude-module", "tkinter",
        "--exclude-module", "numpy",
        "--exclude-module", "PIL",
        "--exclude-module", "torch",
        "--exclude-module", "faster_whisper",
    ]
    if os.path.exists(VERSION_FILE):
        cmd += ["--version-file", VERSION_FILE]

    log("[build] " + " ".join(cmd))
    rc = subprocess.call(cmd, cwd=ROOT)
    if rc != 0:
        log("[build] PyInstaller failed.")
        return rc

    built = os.path.join(dist, BUILD_NAME + ".exe")
    if not os.path.exists(built):
        log(f"[build] expected output missing: {built}")
        return 1

    for name in (EXE_TARGET, EXE_TARGET_EN):
        target = os.path.join(ROOT, name)
        try:
            shutil.copy2(built, target)
            log(f"[build] -> {name}  ({os.path.getsize(target) / 1048576:.1f} MB)")
        except OSError as exc:
            log(f"[build] could not write {name}: {exc}")
            return 1
    log("[build] done. Double-click " + EXE_TARGET + " to start.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

