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


# 本地后端默认参数（OpenAI 兼容 /chat/completions，如 Ollama / llama.cpp / vLLM）
DEFAULT_LOCAL_BASE_URL = "http://localhost:11434/v1"
DEFAULT_LOCAL_MODEL = "qwen2.5:14b"


# 面向“电子与计算机工程”专业内容的翻译提示词。
ECE_SYSTEM_PROMPT = (
    "You are a simultaneous interpreter for a Chinese student of Electronic and "
    "Computer Engineering. Cover domains such as computer architecture, hardware "
    "optimization, caches and memory hierarchy, parallel and distributed "
    "computing, computer networks, signal processing, control, and machine "
    "learning. Translate the given English into fluent, natural Simplified "
    "Chinese.\n"
    "The English input comes from automatic speech recognition and may contain "
    "mis-transcribed words (homophones, wrong proper nouns, or implausible words). "
    "Before translating, infer the speaker's intended words from context and "
    "phonetic similarity, e.g. \"Saquon Barclay\" -> Saquon Barkley, \"messy\" -> MESI, "
    "\"Sequin\" -> Saquon. Only correct when the original is clearly implausible "
    "and a more likely intended term exists; otherwise translate faithfully.\n"
    "Preserve key technical terms, acronyms, and English abbreviations "
    "(e.g., Fourier transform, convolution, VLSI, FPGA, PWM, state-space, "
    "gradient descent, DFT, LQR, SIMD, MESI, MPI, TCP/IP). If a term is hard to "
    "translate naturally, give the Chinese translation followed by the original in "
    "brackets, e.g., 卷积（convolution）. Translate faithfully and completely: "
    "preserve every technical detail, numeric value, logic connective (if/only "
    "if/whereas/therefore), and the full meaning of each clause. Do NOT summarize, "
    "simplify, omit, or add your own examples. Keep mathematical notation, "
    "equations, and variable names unchanged. The input may be a fragmentary or "
    "incomplete utterance: translate whatever text is present as faithfully as "
    "possible. Never ask for clarification, never describe the input as "
    "incomplete, never add notes or meta commentary — always output ONLY the "
    "Chinese translation."
)

# 用于录制结束后的内容总结。
SUMMARY_SYSTEM_PROMPT = (
    "You are a study assistant. Given the transcript of an English lecture or "
    "lesson, write a concise Chinese summary. Respond in EXACTLY this format, "
    "with nothing else:\n"
    "标题：<一句话中文标题，概括主题，不含日期时间>\n"
    "摘要：<2-4 句中文摘要，概括主要内容>"
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
                 backend: str = "auto",
                 system_prompt: str | None = None,
                 glossary: str = ""):
        self.backend = (backend or "auto").lower()
        self.api_key = api_key or load_api_key()
        if self.backend == "local":
            # 本地 OpenAI 兼容后端（如 Ollama / llama.cpp / vLLM），通常无需 API key
            self.base_url = (base_url or DEFAULT_LOCAL_BASE_URL).rstrip("/")
            self.model = model or DEFAULT_LOCAL_MODEL
        else:
            self.base_url = (base_url or "https://api.deepseek.com/").rstrip("/")
            self.model = model or "deepseek-chat"
        self.system_prompt = system_prompt or ECE_SYSTEM_PROMPT
        self.glossary = glossary
        self.last_backend = "none"
        self.last_error = ""

    def _chat(self, system_prompt: str, user_text: str) -> str:
        body = json.dumps({
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            "temperature": 0.3,
        }).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        req = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=body, method="POST", headers=headers,
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.load(resp)
        return data["choices"][0]["message"]["content"].strip()

    def summarize(self, text: str) -> tuple[str, str]:
        """返回 (标题, 摘要)。需 DeepSeek key；失败抛异常。"""
        if not self.api_key:
            raise RuntimeError("no api key")
        raw = self._chat(SUMMARY_SYSTEM_PROMPT, text)
        title = summary = ""
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("标题"):
                title = line.split("：", 1)[-1].strip() or line.split(":", 1)[-1].strip()
            elif line.startswith("摘要"):
                summary = line.split("：", 1)[-1].strip() or line.split(":", 1)[-1].strip()
        if not title:
            title = (raw.splitlines()[0] if raw.splitlines() else "")[:40]
        if not summary:
            summary = raw[:300]
        return title, summary

    def _deepseek(self, text: str, context: str = "") -> str:
        content = self.system_prompt
        if self.glossary:
            content += ("\n\n术语表（翻译时请优先使用这些标准译法）:\n" + self.glossary)
        if context:
            content += ("\n\n当前讲义背景（据此理解语境，术语以其为准）:\n" + context)
        content = self._chat(content, text)
        self.last_backend = "deepseek"
        return content

    def _local(self, text: str, context: str = "") -> str:
        content = self.system_prompt
        if self.glossary:
            content += ("\n\n术语表（翻译时请优先使用这些标准译法）：\n" + self.glossary)
        if context:
            content += ("\n\n当前讲义背景（据此理解语境，术语以其为准）：\n" + context)
        content = self._chat(content, text)
        self.last_backend = "local"
        self.last_error = ""
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

    def translate(self, text: str, context: str = "") -> str:
        """返回中文翻译；全部后端失败时抛异常。"""
        text = (text or "").strip()
        if not text:
            return ""

        self.last_error = ""
        # 显式后端 local：本地 OpenAI 兼容（如 Ollama / llama.cpp / vLLM）
        if self.backend == "local":
            try:
                return self._local(text, context)
            except Exception as e:
                self.last_error = f"local: {type(e).__name__}: {e}"
                raise RuntimeError(self.last_error)
        # 显式后端 deepseek：仅云端
        if self.backend == "deepseek":
            if self.api_key:
                try:
                    return self._deepseek(text, context)
                except Exception as e:
                    self.last_error = f"deepseek: {type(e).__name__}: {e}"
            else:
                self.last_error = "deepseek: no api key"
            raise RuntimeError(self.last_error or "translation failed")
        # 显式后端 google：免费接口
        if self.backend == "google":
            try:
                return self._google(text)
            except Exception as e:
                self.last_error = f"google: {type(e).__name__}: {e}"
                raise RuntimeError(self.last_error)

        # 默认 auto：有 key 走 DeepSeek，否则/失败用 Google
        if self.api_key:
            try:
                return self._deepseek(text, context)
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


def build_translator(backend: str | None = None,
                     base_url: str | None = None,
                     model: str | None = None,
                     system_prompt: str | None = None,
                     glossary: str = "") -> Translator:
    """根据参数/环境变量构造 Translator，便于命令行与 UI 统一接入本地后端。

    优先级：函数参数 > 环境变量 > 默认。
      TRANSLATE_BACKEND   -> auto|deepseek|local|google
      LOCAL_LLM_BASE_URL  -> 本地 OpenAI 兼容地址（默认 http://localhost:11434/v1）
      LOCAL_LLM_MODEL     -> 本地模型名（默认 qwen2.5:14b）
    """
    backend = (backend or os.environ.get("TRANSLATE_BACKEND") or "auto").lower()
    kwargs = {"backend": backend, "system_prompt": system_prompt, "glossary": glossary}
    if backend == "local":
        kwargs["base_url"] = (base_url or os.environ.get("LOCAL_LLM_BASE_URL")
                              or DEFAULT_LOCAL_BASE_URL)
        kwargs["model"] = (model or os.environ.get("LOCAL_LLM_MODEL")
                           or DEFAULT_LOCAL_MODEL)
    else:
        if base_url:
            kwargs["base_url"] = base_url
        if model:
            kwargs["model"] = model
    return Translator(**kwargs)


if __name__ == "__main__":
    t = Translator()
    print("api_key:", t.key_summary(), "| model:", t.model)
    print("->", t.translate("Reinforcement learning enables robots to learn "
                            "complex manipulation skills from visual inputs."))
