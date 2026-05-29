"""
Unified AI Provider — single interface for OpenAI, Anthropic Claude,
Google Gemini (SDK), and Gemini CLI.

Select provider via AI_PROVIDER in config/.env:
    AI_PROVIDER=openai        → GPT-4o / GPT-4o-mini
    AI_PROVIDER=anthropic     → Claude Sonnet / Haiku
    AI_PROVIDER=gemini        → Gemini Pro / Flash (Python SDK)
    AI_PROVIDER=gemini_cli    → Gemini CLI subprocess (legacy default)

Usage:
    ai = AIProvider()
    text   = ai.complete("Your prompt")
    text   = ai.complete("Your prompt", use_large_model=True)
    parsed = ai.parse_json(text, default={})
"""

import os
import re
import json
import time
import subprocess
import requests

from config import Config


class AIProvider:

    def __init__(self):
        self.provider = Config.AI_PROVIDER.lower().strip()
        self._client = None
        self._init_client()

    # ─────────────────────────────────────────────────────────────────────────
    # Client initialisation
    # ─────────────────────────────────────────────────────────────────────────

    def _init_client(self):
        if self.provider == "openai":
            if not Config.OPENAI_API_KEY:
                raise ValueError(
                    "AI_PROVIDER=openai requires OPENAI_API_KEY to be set in config/.env"
                )
            try:
                from openai import OpenAI
                kwargs = {"api_key": Config.OPENAI_API_KEY}
                if Config.AI_BASE_URL:
                    kwargs["base_url"] = Config.AI_BASE_URL
                self._client = OpenAI(**kwargs)
            except ImportError:
                raise ImportError(
                    "openai package not installed. Run: pip install openai"
                )

        elif self.provider == "anthropic":
            if not Config.ANTHROPIC_API_KEY:
                raise ValueError(
                    "AI_PROVIDER=anthropic requires ANTHROPIC_API_KEY to be set in config/.env"
                )
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)
            except ImportError:
                raise ImportError(
                    "anthropic package not installed. Run: pip install anthropic"
                )

        elif self.provider == "gemini":
            if not Config.GEMINI_API_KEY:
                raise ValueError(
                    "AI_PROVIDER=gemini requires GEMINI_API_KEY to be set in config/.env"
                )
            try:
                from google import genai as google_genai  # noqa: F401 — validate install
                self._client = google_genai.Client(api_key=Config.GEMINI_API_KEY)
            except ImportError:
                raise ImportError(
                    "google-genai package not installed. Run: pip install google-genai"
                )

        elif self.provider == "vertexai":
            project = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT_ID")
            if not project:
                raise ValueError(
                    "AI_PROVIDER=vertexai requires GOOGLE_CLOUD_PROJECT to be set in config/.env"
                )
            try:
                from google import genai as google_genai  # noqa: F401 — validate install
                location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
                self._client = google_genai.Client(
                    vertexai=True, project=project, location=location
                )
            except ImportError:
                raise ImportError(
                    "google-genai package not installed. Run: pip install google-genai"
                )

        elif self.provider == "custom":
            if not Config.CUSTOM_AI_URL:
                raise ValueError(
                    "AI_PROVIDER=custom requires CUSTOM_AI_URL to be set in config/.env"
                )

        elif self.provider == "gemini_cli":
            pass  # No SDK client — uses subprocess

        else:
            raise ValueError(
                f"Unknown AI_PROVIDER: '{self.provider}'. "
                "Choose from: openai, anthropic, gemini, vertexai, custom, gemini_cli"
            )

    # ─────────────────────────────────────────────────────────────────────────
    # Public interface
    # ─────────────────────────────────────────────────────────────────────────

    def complete(
        self,
        prompt: str,
        use_large_model: bool = False,
        temperature: float = None,
        work_dir: str = None,
    ) -> str:
        """
        Send a prompt and return the raw text response.

        Args:
            prompt:          Full prompt text.
            use_large_model: True → powerful/expensive tier; False → fast/cheap tier.
            temperature:     Sampling temperature. Defaults to Config.AI_TEMPERATURE
                             (0 = fully deterministic, 1 = maximally creative).
                             Code review tasks: 0.1–0.2. JSON parsing: 0.1.
            work_dir:        Working directory. Only relevant for gemini_cli provider.

        Returns:
            str: The AI response as plain text.
        """
        if temperature is None:
            temperature = Config.AI_TEMPERATURE
        model = Config.AI_POWERFUL_MODEL if use_large_model else Config.AI_FAST_MODEL

        if self.provider == "openai":
            return self._call_openai(prompt, model, temperature)
        elif self.provider == "anthropic":
            return self._call_anthropic(prompt, model, temperature)
        elif self.provider == "gemini":
            return self._call_gemini_sdk(prompt, model, temperature)
        elif self.provider == "vertexai":
            return self._call_vertexai(prompt, model, temperature)
        elif self.provider == "custom":
            return self._call_custom(prompt)
        elif self.provider == "gemini_cli":
            return self._call_gemini_cli(prompt, model, work_dir)

    def parse_json(self, text: str, default=None):
        """
        Extract and parse JSON from an AI response.
        Handles markdown fences, leading/trailing prose, and bare JSON arrays.
        """
        if default is None:
            default = {}
        if not text:
            return default
        try:
            # Strip markdown code fences
            clean = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`").strip()

            # Try to find the outermost JSON object or array
            match = re.search(r"(\{.*\}|\[.*\])", clean, re.DOTALL)
            if match:
                return json.loads(match.group(1))
            return json.loads(clean)
        except Exception:
            return default

    # ─────────────────────────────────────────────────────────────────────────
    # Provider implementations
    # ─────────────────────────────────────────────────────────────────────────

    def _call_openai(self, prompt: str, model: str, temperature: float, attempt: int = 1) -> str:
        try:
            response = self._client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=8192,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            err = str(e)
            if ("429" in err or "rate_limit" in err.lower()) and attempt <= 5:
                wait = attempt * 10
                print(f"      [AIProvider/OpenAI] Rate-limited. Retrying in {wait}s (attempt {attempt}/5)...")
                time.sleep(wait)
                return self._call_openai(prompt, model, temperature, attempt + 1)
            raise

    def _call_anthropic(self, prompt: str, model: str, temperature: float, attempt: int = 1) -> str:
        try:
            response = self._client.messages.create(
                model=model,
                max_tokens=8192,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text or ""
        except Exception as e:
            err = str(e)
            if ("429" in err or "rate_limit" in err.lower() or "overloaded" in err.lower()) and attempt <= 5:
                wait = attempt * 10
                print(f"      [AIProvider/Anthropic] Rate-limited. Retrying in {wait}s (attempt {attempt}/5)...")
                time.sleep(wait)
                return self._call_anthropic(prompt, model, temperature, attempt + 1)
            raise

    def _call_gemini_sdk(self, prompt: str, model: str, temperature: float, attempt: int = 1) -> str:
        try:
            from google.genai import types as genai_types
            response = self._client.models.generate_content(
                model=model,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    temperature=temperature,
                    max_output_tokens=8192,
                ),
            )
            return response.text or ""
        except Exception as e:
            err = str(e)
            if ("429" in err or "quota" in err.lower() or "resource_exhausted" in err.lower()) and attempt <= 5:
                wait = attempt * 10
                print(f"      [AIProvider/Gemini] Quota hit. Retrying in {wait}s (attempt {attempt}/5)...")
                time.sleep(wait)
                return self._call_gemini_sdk(prompt, model, temperature, attempt + 1)
            raise

    def _call_vertexai(self, prompt: str, model: str, temperature: float, attempt: int = 1) -> str:
        try:
            from google.genai import types as genai_types
            response = self._client.models.generate_content(
                model=model,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    temperature=temperature,
                    max_output_tokens=8192,
                ),
            )
            return response.text or ""
        except Exception as e:
            err = str(e)
            if ("429" in err or "quota" in err.lower() or "resource_exhausted" in err.lower()) and attempt <= 5:
                wait = attempt * 10
                print(f"      [AIProvider/VertexAI] Quota hit. Retrying in {wait}s (attempt {attempt}/5)...")
                time.sleep(wait)
                return self._call_vertexai(prompt, model, temperature, attempt + 1)
            raise

    def _call_custom(self, prompt: str, attempt: int = 1) -> str:
        try:
            resp = requests.post(
                Config.CUSTOM_AI_URL,
                auth=(Config.CUSTOM_AI_USER, Config.CUSTOM_AI_PASSWORD),
                json={"prompt": prompt},
                timeout=300,
            )
            if resp.status_code != 200:
                raise requests.HTTPError(f"Custom AI bridge error (HTTP {resp.status_code}): {resp.text[:300]}")
            data = resp.json()
            text = data.get("response") or data.get("text") or data.get("content") or ""
            if not text:
                raise ValueError(f"Custom AI bridge returned no text. Keys: {list(data.keys())}")
            return text
        except requests.Timeout as exc:
            raise TimeoutError("Custom AI bridge timed out after 300s") from exc
        except Exception as e:
            err = str(e)
            if ("429" in err or "rate" in err.lower()) and attempt <= 3:
                wait = attempt * 10
                print(f"      [AIProvider/Custom] Rate-limited. Retrying in {wait}s...")
                time.sleep(wait)
                return self._call_custom(prompt, attempt + 1)
            raise

    def _call_gemini_cli(self, prompt: str, model: str, work_dir: str = None, attempt: int = 1) -> str:
        env = os.environ.copy()
        google_project = os.getenv("GOOGLE_CLOUD_PROJECT", "")
        if google_project:
            env["GOOGLE_CLOUD_PROJECT"] = google_project

        cmd = [
            Config.GEMINI_CLI_BIN,
            "--prompt", "Respond to the attached context completely and accurately.",
            "--model", model,
            "--approval-mode", "yolo",
        ]

        try:
            result = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                env=env,
                cwd=work_dir,
                timeout=600,
            )
            if result.returncode != 0:
                err_text = result.stderr or ""
                if "429" in err_text and attempt <= 5:
                    wait = attempt * 10
                    print(f"      [AIProvider/GeminiCLI] Rate-limited. Retrying in {wait}s...")
                    time.sleep(wait)
                    return self._call_gemini_cli(prompt, model, work_dir, attempt + 1)
                raise Exception(
                    f"Gemini CLI error (exit {result.returncode}): {err_text[:500]}"
                )

            output = result.stdout.strip()
            if not output:
                raise Exception(
                    f"Gemini CLI returned empty output. Stderr: {result.stderr[:300]}"
                )
            return output

        except subprocess.TimeoutExpired:
            raise Exception("Gemini CLI call timed out after 600s")
