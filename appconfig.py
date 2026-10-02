"""live-interpreter 的用户配置（config.json）。

安装包会把「安装位置之外」的设置——录音保存位置、笔记保存位置、API key、
默认声音来源与模型——写进用户配置里；程序启动时读取。

查找顺序（同名键，后面的覆盖前面的）::

    1. 环境变量        调用方自己处理，例如 RECORDINGS_DIR / TRANSCRIPTS_DIR
    2. <程序目录>\\config.json                 便携版 / 手动放置
    3. %APPDATA%\\live-interpreter\\config.json  安装包写入的用户配置

优先级：命令行参数 > 环境变量 > 配置文件 > 代码里的默认值。
"""

from __future__ import annotations

import json
import os

APP_DIR_NAME = "live-interpreter"
CONFIG_NAME = "config.json"

_CACHE: dict | None = None


def app_dir() -> str:
    """程序目录（tongchuan.py 所在目录）。"""
    return os.path.dirname(os.path.abspath(__file__))


def user_config_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.join(
        os.path.expanduser("~"), "AppData", "Roaming"
    )
    return os.path.join(base, APP_DIR_NAME)


def user_config_path() -> str:
    return os.path.join(user_config_dir(), CONFIG_NAME)


def portable_config_path() -> str:
    return os.path.join(app_dir(), CONFIG_NAME)


def _read_json(path: str) -> dict:
    try:
        # utf-8-sig：安装包用 Inno 写出来的是带 BOM 的 UTF-8，普通编辑器写的是不带 BOM 的
        with open(path, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def load_config(refresh: bool = False) -> dict:
    """合并后的配置字典。读不到文件时返回空字典（不抛异常）。"""
    global _CACHE
    if _CACHE is not None and not refresh:
        return _CACHE
    merged: dict = {}
    merged.update(_read_json(user_config_path()))
    merged.update(_read_json(portable_config_path()))
    _CACHE = merged
    return merged


def get(key: str, default=None):
    """取一个配置项；空白字符串按「没配」处理。"""
    value = load_config().get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    return value


def update_user_config(values: dict, remove=()) -> str:
    """合并写入用户配置，返回写入路径（给设置向导/脚本用）。"""
    path = user_config_path()
    data = _read_json(path)
    for key in remove:
        data.pop(key, None)
    for key, value in values.items():
        if value is None or (isinstance(value, str) and not value.strip()):
            data.pop(key, None)
        else:
            data[key] = value
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, path)
    load_config(refresh=True)
    return path

