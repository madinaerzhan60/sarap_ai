from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod

import httpx

from app.models import AIAnalysis
from app.services.ai import analyze as local_fallback

SYSTEM_PROMPT = """You analyze reputation mentions for Kazakhstan businesses.
Return JSON only with: language, sentiment, sentiment_score, severity,
confidence, aspects (array of {aspect, sentiment}), escalated.
Support Kazakh, Russian, English and mixed Kazakh/Russian. Preserve aspect-level
sentiment. Never invent facts that are not in the source text."""


def _json_text(value: str) -> str:
    value = value.strip()
    if value.startswith("```"):
        value = value.split("\n", 1)[1].rsplit("```", 1)[0]
    return value.strip()


class LLMProvider(ABC):
    @abstractmethod
    async def analyze(self, text: str) -> AIAnalysis: ...


class GroqProvider(LLMProvider):
    """Fast, low-cost first pass using Groq's OpenAI-compatible endpoint."""

    async def analyze(self, text: str) -> AIAnalysis:
        key = os.environ["GROQ_API_KEY"]
        model = os.getenv("GROQ_FAST_MODEL", "openai/gpt-oss-20b")
        payload = {
            "model": model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
        }
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json=payload,
            )
            response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return AIAnalysis.model_validate(json.loads(_json_text(content)))


class GeminiProvider(LLMProvider):
    """Strong pass for ambiguous, mixed-language and critical mentions."""

    async def analyze(self, text: str) -> AIAnalysis:
        key = os.environ["GEMINI_API_KEY"]
        model = os.getenv("GEMINI_STRONG_MODEL", "gemini-flash-latest")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        payload = {
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": text}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
        }
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, headers={"x-goog-api-key": key}, json=payload)
            response.raise_for_status()
        content = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        return AIAnalysis.model_validate(json.loads(_json_text(content)))


def needs_strong_model(result: AIAnalysis) -> bool:
    return (
        result.confidence < 0.8
        or result.language == "mixed_kz_ru"
        or result.sentiment == "mixed"
        or result.severity in {"high", "critical"}
    )


async def analyze_with_cascade(text: str) -> AIAnalysis:
    """Groq first, Gemini only when needed; deterministic local fallback without keys."""
    if os.getenv("GROQ_API_KEY"):
        try:
            first = await GroqProvider().analyze(text)
        except (httpx.HTTPError, KeyError, ValueError):
            first = local_fallback(text)
    else:
        first = local_fallback(text)

    if needs_strong_model(first) and os.getenv("GEMINI_API_KEY"):
        try:
            strong = await GeminiProvider().analyze(text)
            return strong.model_copy(update={"escalated": True})
        except (httpx.HTTPError, KeyError, ValueError):
            pass
    return first
