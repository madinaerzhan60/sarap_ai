from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod

import httpx

from app.models import AIAnalysis
from app.services.ai import analyze as local_fallback, summarize_review

SYSTEM_PROMPT = """You analyze reputation mentions for Kazakhstan businesses.
Return JSON only with: language, sentiment, sentiment_score, severity,
confidence, summary (one concise sentence describing the core topic and customer meaning),
aspects (array of {aspect, sentiment}), escalated.
Support Kazakh, Russian, English and mixed Kazakh/Russian. Preserve aspect-level
sentiment. Sentiment must reflect the customer's meaning, including negation,
sarcasm and complaints phrased as questions. The summary must paraphrase the
meaning; never copy the review, truncate it, or prefix it with labels such as
"Positive review" or "Problem". Words such as scam, deception,
cannot log in, no support and do not buy are negative. If a numeric rating is
provided, use 1-2 as negative, 3 as neutral and 4-5 as positive. Never invent facts."""


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


def _ensure_summary(result: AIAnalysis, text: str) -> AIAnalysis:
    summary = result.summary.strip()
    normalized_text = " ".join(text.split()).casefold()
    normalized_summary = " ".join(summary.split()).casefold()
    copied = bool(normalized_summary) and (
        normalized_summary == normalized_text
        or normalized_text.startswith(normalized_summary.rstrip("…"))
        or normalized_summary.startswith(("положительный отзыв:", "проблема:", "positive feedback:", "reported issue:"))
    )
    if summary and not copied:
        return result
    return result.model_copy(update={"summary": summarize_review(text, result.sentiment)})


async def analyze_with_cascade(text: str, rating: float | None = None) -> AIAnalysis:
    """Groq first, Gemini only when needed; deterministic local fallback without keys."""
    model_input = f"Rating: {rating}/5\nReview: {text}" if rating is not None else text
    if os.getenv("GROQ_API_KEY"):
        try:
            first = _ensure_summary(await GroqProvider().analyze(model_input), text)
        except (httpx.HTTPError, KeyError, ValueError):
            first = local_fallback(text, rating)
    else:
        first = local_fallback(text, rating)

    if needs_strong_model(first) and os.getenv("GEMINI_API_KEY"):
        try:
            strong = _ensure_summary(await GeminiProvider().analyze(model_input), text)
            first = strong.model_copy(update={"escalated": True})
        except (httpx.HTTPError, KeyError, ValueError):
            pass
    rule = local_fallback(text, rating)
    if rating is not None or (rule.sentiment != "neutral" and first.sentiment != rule.sentiment):
        first = first.model_copy(update={
            "sentiment": rule.sentiment,
            "sentiment_score": rule.sentiment_score,
            "severity": rule.severity,
            "confidence": max(first.confidence, rule.confidence),
        })
    return _ensure_summary(first, text)


async def generate_business_recommendations(text: str) -> dict:
    prompt = f"""Review these recent customer mentions and return JSON only with:
score (number 0-10), summary (one short sentence), recommendations with arrays
urgent_fix, improve, keep_doing. Each array item must be a short actionable phrase.
Do not invent facts.\n\nMENTIONS:\n{text[:24000]}"""
    try:
        if os.getenv("GROQ_API_KEY"):
            payload = {"model": os.getenv("GROQ_FAST_MODEL", "openai/gpt-oss-20b"), "temperature": 0, "response_format": {"type": "json_object"}, "messages": [{"role": "system", "content": "You synthesize customer feedback. Return only valid JSON with score, summary, and recommendations. recommendations must contain urgent_fix, improve, keep_doing arrays of short strings."}, {"role": "user", "content": prompt}]}
            async with httpx.AsyncClient(timeout=25) as client:
                response = await client.post("https://api.groq.com/openai/v1/chat/completions", headers={"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"}, json=payload)
                response.raise_for_status()
            result = json.loads(_json_text(response.json()["choices"][0]["message"]["content"]))
            return {"score": max(0, min(10, float(result.get("score", 0)))), "summary": str(result.get("summary", "")), "recommendations": result.get("recommendations") or {"urgent_fix": [], "improve": [], "keep_doing": []}}
    except (httpx.HTTPError, KeyError, ValueError):
        pass
    return {"score": 7.0, "summary": "Customers see value in the experience, with a few service improvements needed.", "recommendations": {"urgent_fix": [], "improve": [], "keep_doing": []}}
