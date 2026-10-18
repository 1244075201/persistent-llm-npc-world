"""
Small LLM client abstraction for experiments.

This file is intentionally independent from the original Generative Agents
runtime. It does not import utils.py and can be used without running Smallville.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Iterable, List, Optional


class LLMClient:
    """Minimal text generation interface."""

    def complete(self, prompt: str, max_tokens: int = 256, temperature: float = 0.7) -> str:
        raise NotImplementedError

    def embed(self, text: str) -> List[float]:
        raise NotImplementedError


@dataclass
class OpenAIClient(LLMClient):
    """OpenAI client compatible with the legacy openai==0.27 API used here."""

    api_key: Optional[str] = None
    chat_model: str = "gpt-3.5-turbo"
    embedding_model: str = "text-embedding-ada-002"

    def __post_init__(self) -> None:
        import openai

        self._openai = openai
        self._openai.api_key = self.api_key or os.environ.get("OPENAI_API_KEY")
        if not self._openai.api_key:
            raise RuntimeError("OPENAI_API_KEY is not set and no api_key was provided.")

    def complete(self, prompt: str, max_tokens: int = 256, temperature: float = 0.7) -> str:
        completion = self._openai.ChatCompletion.create(
            model=self.chat_model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return completion["choices"][0]["message"]["content"]

    def embed(self, text: str) -> List[float]:
        cleaned = text.replace("\n", " ") or "this is blank"
        response = self._openai.Embedding.create(input=[cleaned], model=self.embedding_model)
        return response["data"][0]["embedding"]


@dataclass
class LocalModelClient(LLMClient):
    """
    Minimal HTTP client for local OpenAI-compatible or Ollama-like endpoints.

    Expected JSON response shapes:
    - {"response": "..."} for Ollama generate
    - {"choices": [{"message": {"content": "..."}}]} for OpenAI-compatible chat
    - {"choices": [{"text": "..."}]} for OpenAI-compatible completion
    """

    endpoint: str = "http://localhost:11434/api/generate"
    model: str = "llama3.2"
    timeout: int = 120

    def complete(self, prompt: str, max_tokens: int = 256, temperature: float = 0.7) -> str:
        print("[LocalModelClient] endpoint:", self.endpoint)
        print("[LocalModelClient] model:", self.model)
        print("[LocalModelClient] prompt preview:", prompt[:300].replace("\n", "\\n"))
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": max_tokens, "temperature": temperature},
        }
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                status_code = response.status
                response_text = response.read().decode("utf-8")
                print("[LocalModelClient] HTTP status:", status_code)
                print("[LocalModelClient] response text preview:", response_text[:1000].replace("\n", "\\n"))
                body = json.loads(response_text)
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Local model request failed: {exc}") from exc

        print("[LocalModelClient] parsed JSON keys:", list(body.keys()))
        final_text = None
        if "response" in body:
            final_text = str(body["response"])
            print("[LocalModelClient] final extracted text length:", len(final_text))
            return final_text
        if body.get("choices"):
            choice = body["choices"][0]
            if "message" in choice:
                final_text = str(choice["message"]["content"])
                print("[LocalModelClient] final extracted text length:", len(final_text))
                return final_text
            if "text" in choice:
                final_text = str(choice["text"])
                print("[LocalModelClient] final extracted text length:", len(final_text))
                return final_text
        raise RuntimeError(f"Unsupported local model response shape: {body}")

    def embed(self, text: str) -> List[float]:
        raise NotImplementedError("Local embedding is endpoint-specific; add it when needed.")


@dataclass
class DeepSeekAPIClient(LLMClient):
    """DeepSeek OpenAI-compatible chat completions client."""

    api_key: Optional[str] = None
    model: str = "deepseek-chat"
    base_url: str = "https://api.deepseek.com"
    timeout: int = 120

    def __post_init__(self) -> None:
        self.api_key = self.api_key or os.environ.get("DEEPSEEK_API_KEY")
        self.model = os.environ.get("DEEPSEEK_MODEL", self.model)
        if not self.api_key:
            raise RuntimeError(
                "DEEPSEEK_API_KEY is not set. Set it before using the deepseek_api backend, "
                "for example: $env:DEEPSEEK_API_KEY=\"your_key_here\""
            )

    def generate(self, prompt: str, max_tokens: int = 300, temperature: float = 0.2) -> str:
        endpoint = f"{self.base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a strict NPC planning assistant. Return only the requested numbered list.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            endpoint,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                response_text = response.read().decode("utf-8")
                body = json.loads(response_text)
        except urllib.error.HTTPError as exc:
            error_text = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"DeepSeek API request failed with HTTP {exc.code}: {error_text}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"DeepSeek API request failed: {exc}") from exc

        try:
            return str(body["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Unsupported DeepSeek API response shape: {body}") from exc

    def complete(self, prompt: str, max_tokens: int = 300, temperature: float = 0.2) -> str:
        return self.generate(prompt, max_tokens=max_tokens, temperature=temperature)

    def embed(self, text: str) -> List[float]:
        raise NotImplementedError("DeepSeekAPIClient currently implements chat generation only.")


@dataclass
class MockClient(LLMClient):
    """Deterministic client for fast tests and prompt plumbing checks."""

    completions: Optional[Iterable[str]] = None

    def __post_init__(self) -> None:
        self._responses = iter(self.completions or [])

    def complete(self, prompt: str, max_tokens: int = 256, temperature: float = 0.7) -> str:
        try:
            return next(self._responses)
        except StopIteration:
            return (
                "1) wake up and complete the morning routine at 7:00 am, "
                "2) eat breakfast at 8:00 am, "
                "3) work on community tasks from 9:00 am to 12:00 pm, "
                "4) have lunch at 12:00 pm, "
                "5) talk with neighbors from 2:00 pm to 3:00 pm, "
                "6) relax at home at 8:00 pm"
            )

    def embed(self, text: str) -> List[float]:
        # Stable toy embedding for tests; not semantically meaningful.
        total = sum(ord(ch) for ch in text)
        return [float((total + i) % 997) / 997.0 for i in range(16)]


def get_llm_client_from_env() -> LLMClient:
    """Create an experiment client from LLM_REPLACEMENT_BACKEND."""

    backend = os.environ.get("LLM_REPLACEMENT_BACKEND", "mock").lower()
    if backend == "mock":
        return MockClient()
    if backend == "local":
        return LocalModelClient(model=os.environ.get("LOCAL_MODEL", "llama3.2"))
    if backend == "deepseek_api":
        return DeepSeekAPIClient()
    raise RuntimeError(
        f"Unsupported LLM_REPLACEMENT_BACKEND={backend!r}. "
        "Expected one of: mock, local, deepseek_api."
    )
