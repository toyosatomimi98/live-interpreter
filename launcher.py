"""live-interpreter launcher.

This is the source of `启动同声传译.exe` (see build_launcher.bat).  It is a
small, windowless program whose only job is to start the real GUI
(`tongchuan.py`) with the project's own virtual environment, so users never
have to touch a .bat file.

Behaviour
---------
* looks for  ``.venv\\Scripts\\pythonw.exe``  next to the exe and uses it;
* if the environment is missing, offers to run the one-time setup
  (``install.bat``);
* starts the GUI detached, with no console window;
* if the GUI dies within a few seconds it shows a dialog with the error tail
  and points at 诊断.bat, instead of failing silently.

Extra arguments are forwarded to tongchuan.py, e.g.::

    启动同声传译.exe --source system
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

APP_SCRIPT = "tongchuan.py"
SETUP_SCRIPT = "install.bat"
DOCTOR_SCRIPT = "诊断.bat"
LOG_NAME = os.path.join("_tmp", "launcher.log")

DETACHED = 0x00000008          # DETACHED_PROCESS
NEW_GROUP = 0x00000200         # CREATE_NEW_PROCESS_GROUP
NO_WINDOW = 0x08000000         # CREATE_NO_WINDOW
NEW_CONSOLE = 0x00000010       # CREATE_NEW_CONSOLE


# --------------------------------------------------------------------------- ui
MB_YESNO = 0x00000004
MB_ICONERROR = 0x00000010
MB_ICONINFO = 0x00000040
MB_TOPMOST = 0x00040000
MB_SETFOREGROUND = 0x00010000
IDYES = 6


def _message(text: str, title: str = "同声传译", style: int = 0) -> int:
    """Show a native Win32 dialog (no tkinter needed).  1 = yes/ok, 0 = no."""
    flags = MB_TOPMOST | MB_SETFOREGROUND
    if style == 1:
        flags |= MB_YESNO
    elif style == 2:
        flags |= MB_ICONERROR
    else:
        flags |= MB_ICONINFO
    try:
        import ctypes

        answer = ctypes.windll.user32.MessageBoxW(None, text, title, flags)
        return 1 if (style != 1 or answer == IDYES) else 0
    except Exception:
        try:
            sys.stderr.write(text + "\n")
        except Exception:
            pass
        return 0 if style == 1 else 1


# ------------------------------------------------------------------- discovery
def app_root() -> str:
    """Folder that holds tongchuan.py: next to the exe / launcher script."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def venv_python(root: str) -> str | None:
    """Return the best interpreter of the project venv, or None."""
    candidates = [
        os.path.join(root, ".venv", "Scripts", "pythonw.exe"),
        os.path.join(root, ".venv", "Scripts", "python.exe"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def child_env(root: str) -> dict:
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
    env["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
    env.pop("PYTHONHOME", None)
    return env


# ---------------------------------------------------------------------- actions
def run_setup(root: str) -> None:
    """Open install.bat in its own console so the user sees the progress."""
    setup = os.path.join(root, SETUP_SCRIPT)
    if not os.path.exists(setup):
        _message(f"找不到安装脚本：\n{setup}", style=2)
        return
    subprocess.Popen(["cmd", "/c", setup], cwd=root, creationflags=NEW_CONSOLE)


def read_tail(path: str, limit: int = 1600) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return ""
    text = text.strip()
    return text[-limit:] if len(text) > limit else text


def start_gui(root: str, py: str) -> int:
    script = os.path.join(root, APP_SCRIPT)
    if not os.path.exists(script):
        _message(f"找不到主程序：\n{script}\n\n请确认 exe 放在项目根目录。", style=2)
        return 1

    log_path = os.path.join(root, LOG_NAME)
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        log = open(log_path, "w", encoding="utf-8", errors="replace")
    except OSError:
        log = subprocess.DEVNULL  # type: ignore[assignment]
        log_path = ""

    cmd = [py, script] + sys.argv[1:]
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=root,
            env=child_env(root),
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=DETACHED | NEW_GROUP | NO_WINDOW,
        )
    except OSError as exc:
        if log_path:
            log.close()
        _message(f"启动失败：\n{exc}", style=2)
        return 1

    # Give the GUI a moment: if it dies immediately something is wrong and the
    # user should see why (missing package, no microphone driver, ...).
    deadline = time.time() + 6.0
    while time.time() < deadline:
        if proc.poll() is not None:
            break
        time.sleep(0.25)

    rc = proc.poll()
    if log_path:
        log.close()
    if rc is None:
        return 0  # still running: all good

    tail = read_tail(log_path) if log_path else ""
    if rc == 0 and "traceback" not in tail.lower():
        return 0

    doctor = os.path.join(root, DOCTOR_SCRIPT)
    hint = f"\n\n可以双击 {os.path.basename(doctor)} 做一次体检，" \
           "或把下面的信息发给维护者。"
    _message(f"同声传译启动后立刻退出了（退出码 {rc}）。{hint}\n\n{tail}", style=2)
    return 1


# ------------------------------------------------------------------------- main
def main() -> int:
    root = app_root()
    os.chdir(root)

    py = venv_python(root)
    if py is None:
        if _message(
            "还没有安装运行环境（.venv）。\n\n"
            "现在运行一次性的安装程序吗？\n"
            "（会自动装依赖、下载语音模型，需要联网，大约几分钟）",
            style=1,
        ):
            run_setup(root)
        return 1

    return start_gui(root, py)


if __name__ == "__main__":
    sys.exit(main())

