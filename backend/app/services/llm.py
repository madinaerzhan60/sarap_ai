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
"Positive review" or "Problem". The summary must tell a manager what the person
is talking about, not merely that they are satisfied or dissatisfied. Keep it
grounded only in the review text, preserve useful concrete details, and use the
same language as the review where practical. For very short reactions, say that
the reaction is brief and has no specific details. Words such as scam,
deception, cannot log in, no support and do not buy are negative. If a numeric
rating is provided, use 1-2 as negative, 3 as neutral and 4-5 as positive. Never
invent facts."""


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
    return {"score": 0.0, "summary": "No significant repeated recommendation yet.", "recommendations": {"urgent_fix": [], "improve": [], "keep_doing": []}}

async def generate_reply_draft(text: str, sentiment: str, language: str, content_type: str, business_context: str = "") -> str:
    """Generate an editable draft without inventing policies, promises or contact details."""
    prompt = f"""Write one concise business reply draft to this customer {content_type}.
Language: {language}. Sentiment: {sentiment}. Known context: {business_context or 'none'}.
Acknowledge the exact message. Never invent refunds, policies, contact details, facts or promises.
If it is a question and the answer is unknown, say the team needs to clarify it.
Return plain reply text only.\n\nCUSTOMER MESSAGE:\n{text[:5000]}"""
    if os.getenv("GROQ_API_KEY"):
        try:
            payload = {"model": os.getenv("GROQ_FAST_MODEL", "openai/gpt-oss-20b"), "temperature": .2, "messages": [{"role": "system", "content": "You write natural, safe customer service reply drafts."}, {"role": "user", "content": prompt}]}
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post("https://api.groq.com/openai/v1/chat/completions", headers={"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"}, json=payload)
                response.raise_for_status()
            draft = str(response.json()["choices"][0]["message"]["content"]).strip()
            if draft:
                return draft[:5000]
        except (httpx.HTTPError, KeyError, ValueError):
            pass
    russian = language in {"ru", "mixed", "mixed_kz_ru"} or any("а" <= char.lower() <= "я" for char in text)
    if content_type == "question":
        return "Спасибо за вопрос. Нам нужно уточнить эту информацию у команды, чтобы ответить точно." if russian else "Thank you for the question. We need to confirm this with the team before giving you an exact answer."
    if sentiment == "positive":
        return "Спасибо за тёплый отзыв! Рады, что вам понравился опыт." if russian else "Thank you for the kind feedback! We are glad you enjoyed your experience."
    if sentiment == "negative":
        return "Спасибо, что рассказали об этом. Нам жаль, что ваш опыт оказался неудачным. Мы передадим описанную проблему команде для проверки." if russian else "Thank you for telling us. We are sorry your experience was disappointing. We will share the issue you described with the team for review."
    return "Спасибо за обратную связь. Мы учтём ваше замечание." if russian else "Thank you for your feedback. We will take your comment into account."
