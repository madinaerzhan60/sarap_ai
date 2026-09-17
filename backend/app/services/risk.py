from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from app.models import AIAnalysis, NormalizedMention, RiskResult

CRITICAL = r"food poisoning|отрав|улану|fraud|мошен|алаяқ|lawsuit|суд|police|полици|scam|danger|қауіп|discrimination|injury|data leak"


def calculate(mention: NormalizedMention, analysis: AIAnalysis, repeat_count: int = 0) -> RiskResult:
    score = 0
    reasons: list[str] = []
    if mention.rating is not None and mention.rating <= 2:
        score += 20; reasons.append("rating ≤ 2")
    if re.search(CRITICAL, mention.text, re.I):
        score += 25; reasons.append("critical keyword")
    if analysis.severity in {"high", "critical"}:
        score += 25; reasons.append(f"{analysis.severity} AI severity")
    if analysis.sentiment in {"negative", "mixed"}:
        score += 15; reasons.append(f"{analysis.sentiment} sentiment")
    negative_aspects = [item.aspect for item in analysis.aspects if item.sentiment == "negative"]
    if negative_aspects:
        score += 10; reasons.append(f"negative aspect: {negative_aspects[0]}")
    if any(aspect in {"staff", "food", "security", "safety"} for aspect in negative_aspects):
        score += 5; reasons.append("sensitive business aspect")
    published = mention.published_at or mention.collected_at
    if published >= datetime.now(timezone.utc) - timedelta(hours=24):
        score += 5; reasons.append("recent mention")
    if repeat_count >= 2:
        score += 10; reasons.append("repeat complaint")
    if mention.source in {"news", "instagram", "threads", "x"}:
        score += 10; reasons.append("potential high reach")
    if analysis.confidence < 0.7:
        score += 5; reasons.append("low AI confidence")
    elif analysis.escalated:
        score += 5; reasons.append("strong-model review required")
    score = min(100, score)
    level = "Critical" if score >= 80 else "High" if score >= 60 else "Medium" if score >= 30 else "Low"
    return RiskResult(score=score, level=level, reasons=reasons)
