"""Build the Windows installer (dist/installer/同声传译-<版本>-安装包.exe).

Usage (from the project root)::

    build_installer.bat
    # or
    .venv\\Scripts\\python.exe tools\\build_installer.py

Needs Inno Setup 6 (ISCC.exe).  The script also makes sure the .iss file carries
a UTF-8 BOM, otherwise Inno would read the Chinese strings as ANSI garbage.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ISS = os.path.join(ROOT, "installer", "live-interpreter.iss")
OUT_DIR = os.path.join(ROOT, "release")

ISCC_CANDIDATES = (
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
)


def log(msg: str) -> None:
    try:
        print(msg, flush=True)
    except Exception:
        pass


def find_iscc() -> str | None:
    found = shutil.which("ISCC.exe") or shutil.which("ISCC")
    if found:
        return found
    for path in ISCC_CANDIDATES:
        if os.path.exists(path):
            return path
    return None


def ensure_bom(path: str) -> None:
    with open(path, "rb") as fh:
        data = fh.read()
    if not data.startswith(b"\xef\xbb\xbf"):
        with open(path, "wb") as fh:
            fh.write(b"\xef\xbb\xbf" + data)
        log("[installer] added UTF-8 BOM to " + os.path.basename(path))


def main() -> int:
    iscc = find_iscc()
    if iscc is None:
        log("[installer] Inno Setup 6 not found.")
        log("[installer]   install it from https://jrsoftware.org/isdl.php")
        log("[installer]   (or run: winget install JRSoftware.InnoSetup)")
        return 1

    if not os.path.exists(ISS):
        log(f"[installer] missing script: {ISS}")
        return 1
    ensure_bom(ISS)

    launcher = os.path.join(ROOT, "启动同声传译.exe")
    if not os.path.exists(launcher):
        log("[installer] launcher exe missing - running build_launcher first ...")
        rc = subprocess.call([sys.executable, os.path.join(ROOT, "tools", "build_launcher.py")], cwd=ROOT)
        if rc != 0:
            return rc

    os.makedirs(OUT_DIR, exist_ok=True)
    log(f"[installer] {iscc} {ISS}")
    rc = subprocess.call([iscc, ISS], cwd=ROOT)
    if rc != 0:
        log("[installer] ISCC failed.")
        return rc

    built = [f for f in os.listdir(OUT_DIR) if f.lower().endswith(".exe")]
    for name in sorted(built):
        path = os.path.join(OUT_DIR, name)
        log(f"[installer] -> {name}  ({os.path.getsize(path) / 1048576:.1f} MB)")
    log("[installer] done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

