# -*- coding: utf-8 -*-
"""交互式同声传译配置菜单：启动后按提示选择，最后自动启动命令行实时识别。"""

import os
import sys
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
TONGCHUAN = os.path.join(HERE, "tongchuan.py")

MODELS = {
    "1": ("tiny.en",        "tiny（最快，最不准）"),
    "2": ("base.en",        "base（推荐实时）"),
    "3": ("small.en",       "small（较准但偏慢）"),
    "4": ("medium.en",      "medium（很慢，建议文件模式）"),
    "5": ("large-v3-turbo", "large-turbo（最准，建议文件模式）"),
    "6": ("large-v3",       "large-v3（最准，建议文件模式）"),
}


def _ask(prompt, default=None, valid=None, cast=None):
    while True:
        raw = input(prompt).strip()
        if not raw and default is not None:
            return default
        if valid is not None and raw not in valid:
            print("  无效输入，请重新输入。")
            continue
        if cast is not None:
            try:
                return cast(raw)
            except ValueError:
                print("  请输入有效数值。")
                continue
        return raw


def main():
    print("=" * 56)
    print("   同声传译 · 交互式命令行配置")
    print("=" * 56)
    print("  每项直接回车 = 使用默认值；可一路回车快速启动。\n")
    while True:
        c = _ask("声音来源: [1]麦克风  [2]系统声音  (默认1): ", "1", {"1", "2"})
        src = "mic" if c == "1" else "system"

        print("识别模型:")
        for k, (_, desc) in MODELS.items():
            print(f"  [{k}] {desc}")
        mk = _ask("  请选择 (默认2): ", "2", set(MODELS))
        model = MODELS[mk][0]

        save = _ask("保存录音到 recordings\\? (y/n, 默认y): ", "y", {"y", "n"})
        voice = _ask("中文朗读? (y/n, 默认n): ", "n", {"y", "n"})
        maxseg = _ask("分段上限(秒, 默认4.0): ", "4.0", cast=float)
        minsil = _ask("静音判据(秒, 默认0.5): ", "0.5", cast=float)
        minwords = _ask("最少词数(默认3, 设1=不过滤): ", "3", cast=int)
        course = input("课件 Markdown 路径(回车跳过): ").strip()

        print("\n确认配置：")
        print(f"  来源={src}  模型={model}  保存录音={'是' if save=='y' else '否'}  朗读={'是' if voice=='y' else '否'}")
        print(f"  分段上限={maxseg}s  静音判据={minsil}s  最少词数={minwords}" + (f"  课件={course}" if course else ""))
        ok = _ask("确认开始? (y/n, 默认y): ", "y", {"y", "n"})
        if ok != "y":
            print("已取消，重新配置。\n")
            continue

        cmd = [PY, TONGCHUAN, "--console", "--source", src, "--model", model,
               "--max-seg", str(maxseg), "--min-silence", str(minsil),
               "--min-words", str(minwords)]
        if save == "y":
            cmd.append("--save-audio")
        cmd.append("--voice" if voice == "y" else "--no-voice")
        if course:
            cmd += ["--course", course]

        os.environ["PYTHONUTF8"] = "1"
        print("\n正在启动同声传译；进入后按 Enter 开始采集，Ctrl+C 停止。\n" + "-" * 56)
        try:
            subprocess.call(cmd)
        except KeyboardInterrupt:
            pass

        again = _ask("\n【已结束】再跑一次/重新配置? (y/n, 默认n): ", "n", {"y", "n"})
        if again != "y":
            print("再见。")
            break


if __name__ == "__main__":
    main()
