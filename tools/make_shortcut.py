"""Put a proper, icon-carrying shortcut for 启动同声传译.exe on the Desktop
and in the Start menu.

Run from the project root:

    .venv\\Scripts\\python.exe tools\\make_shortcut.py
    # or double-click  创建桌面快捷方式.bat

Uses the built-in Windows Script Host COM object through PowerShell, so it
needs no extra packages.
"""

from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(ROOT, "启动同声传译.exe")
DESCRIPTION = "同声传译 · 实时翻译（live-interpreter）"

PS = r"""
$ErrorActionPreference = 'Stop'
$exe = $env:LI_EXE
$root = $env:LI_ROOT
if (-not (Test-Path -LiteralPath $exe)) { throw "missing exe: $exe" }

$shell = New-Object -ComObject WScript.Shell
$targets = @()
$targets += (Join-Path ([Environment]::GetFolderPath('Desktop')) '同声传译.lnk')
$startMenu = Join-Path ([Environment]::GetFolderPath('Programs')) '同声传译.lnk'
$targets += $startMenu

foreach ($lnk in $targets) {
  $dir = Split-Path -Parent $lnk
  if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
  $sc = $shell.CreateShortcut($lnk)
  $sc.TargetPath = $exe
  $sc.WorkingDirectory = $root
  $sc.IconLocation = "$exe,0"
  $sc.Description = $env:LI_DESC
  $sc.Save()
  Write-Output "created $lnk"
}
"""


def main() -> int:
    if not os.path.exists(TARGET):
        print(f"[shortcut] not found: {TARGET}")
        print("[shortcut] build it first:  build_launcher.bat")
        return 1

    env = os.environ.copy()
    env["LI_EXE"] = TARGET
    env["LI_ROOT"] = ROOT
    env["LI_DESC"] = DESCRIPTION

    rc = subprocess.call(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", PS],
        env=env,
    )
    if rc != 0:
        print("[shortcut] PowerShell failed - shortcut not created.")
        return rc
    print("[shortcut] done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

