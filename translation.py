"""
翻译后端：中文翻译。

优先级：
  1. DeepSeek (OpenAI 兼容 chat/completions)，自动从本机 Codex 配置读取 key
  2. Google 免费翻译接口（无需 key，但可能限流/被墙）
  3. 仅返回英文原文（兜底）

密钥来源（不写死在代码里）：
  环境变量 DEEPSEEK_API_KEY / OPENAI_API_KEY
  或本机 ~/.codex/config.toml 里的 experimental_bearer_token
  或项目目录下的 .env（DEEPSEEK_API_KEY=sk-...）
"""

from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request


# 面向“电子与计算机工程”专业内容的翻译提示词。
ECE_SYSTEM_PROMPT = (
    "You are a simultaneous interpreter for a Chinese student of Electronic and "
    "Computer Engineering. Cover domains such as computer architecture, hardware "
    "optimization, caches and memory hierarchy, parallel and distributed "
    "computing, computer networks, signal processing, control, and machine "
    "learning. Translate the given English into fluent, natural Simplified "
    "Chinese. Preserve key technical terms, acronyms, and English abbreviations "
    "(e.g., Fourier transform, convolution, VLSI, FPGA, PWM, state-space, "
    "gradient descent, DFT, LQR, SIMD, MESI, MPI, TCP/IP). If a term is hard to "
    "translate naturally, give the Chinese translation followed by the original in "
    "brackets, e.g., 卷积（convolution）. Translate faithfully and completely: "
    "preserve every technical detail, numeric value, logic connective (if/only "
    "if/whereas/therefore), and the full meaning of each clause. Do NOT summarize, "
    "simplify, omit, or add your own examples. Keep mathematical notation, "
    "equations, and variable names unchanged. Output ONLY the Chinese translation."
)


def _find_key_in_codex_config() -> str | None:
    for path in (
        os.path.expanduser("~/.codex/config.toml"),
    ):
        try:
            with open(path, encoding="utf-8") as f:
                txt = f.read()
        except OSError:
            continue
        m = re.search(r'experimental_bearer_token\s*=\s*"([^"]+)"', txt)
        if m and m.group(1):
            return m.group(1).strip()
    return None


def load_api_key() -> str | None:
    """返回可用的 API key，找不到则返回 None。"""
    for env_name in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY"):
        v = os.environ.get(env_name)
        if v and v.strip():
            return v.strip()

    # 项目目录下 .env
    if os.path.exists(".env"):
        try:
            for line in open(".env", encoding="utf-8"):
                line = line.strip()
                if line.startswith("DEEPSEEK_API_KEY="):
                    val = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if val:
                        return val
        except OSError:
            pass

    return _find_key_in_codex_config()


def _mask(key: str | None) -> str:
    if not key:
        return "<none>"
    if len(key) <= 8:
        return "***"
    return key[:3] + "***" + key[-3:]


class Translator:
    """可插拔翻译器。translate() 返回中文字符串；失败时抛异常。"""

    def __init__(self, api_key: str | None = None,
                 base_url: str = "https://api.deepseek.com/",
                 model: str = "deepseek-chat",
                 system_prompt: str | None = None):
        self.api_key = api_key or load_api_key()
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.system_prompt = system_prompt or ECE_SYSTEM_PROMPT
        self.last_backend = "none"
        self.last_error = ""

    def _deepseek(self, text: str) -> str:
        body = json.dumps({
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": text},
            ],
            "temperature": 0.0,
        }).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self.api_key,
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
        content = data["choices"][0]["message"]["content"].strip()
        self.last_backend = "deepseek"
        return content

    def _google(self, text: str) -> str:
        url = ("https://translate.googleapis.com/translate_a/single"
               "?client=gtx&sl=en&tl=zh-CN&dt=t&q=" + urllib.parse.quote(text[:4500]))
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.load(resp)
        parts = [item[0] for item in data[0] if item and item[0]]
        out = "".join(parts).strip()
        self.last_backend = "google"
        self.last_error = ""
        return out

    def translate(self, text: str) -> str:
        """返回中文翻译；全部后端失败时抛异常。"""
        text = (text or "").strip()
        if not text:
            return ""

        self.last_error = ""
        if self.api_key:
            try:
                return self._deepseek(text)
            except Exception as e:
                self.last_error = f"deepseek: {type(e).__name__}: {e}"
        else:
            self.last_error = "no api key"

        # 无 key 或 DeepSeek 失败时，尝试免费 Google 接口
        try:
            return self._google(text)
        except Exception as e:
            self.last_error += f" | google: {type(e).__name__}: {e}"

        raise RuntimeError(self.last_error or "translation failed")

    def key_summary(self) -> str:
        return _mask(self.api_key)


if __name__ == "__main__":
    t = Translator()
    print("api_key:", t.key_summary(), "| model:", t.model)
    print("->", t.translate("Reinforcement learning enables robots to learn "
                            "complex manipulation skills from visual inputs."))
