from __future__ import annotations

import re

from app.models import AIAnalysis, Aspect

NEGATIVE = r"груб|долго|ужас|плох|дорог|опозд|отрав|мошен|дөрекі|баяу|жаман|күту|қауіп|late|wait|fraud|injur"
POSITIVE = r"хорош|вкусн|отлич|керемет|жақсы|күшті|дәмді|great|good|love"
CYRILLIC_KZ = r"[әғқңөұүһі]"

ASPECTS = {
    "product": r"кофе|еда|блюд|дәм|тағам|product|food",
    "staff": r"кассир|официант|персонал|қызметкер|staff|rude|груб|дөрекі",
    "waiting_time": r"долго|очеред|күту|баяу|wait|late",
    "delivery": r"достав|жеткіз|delivery|courier",
    "price": r"цен|дорог|баға|қымбат|price",
    "cleanliness": r"гряз|таза|dirty|clean",
    "atmosphere": r"атмосфер|интерьер|atmosphere",
}


def detect_language(text: str) -> str:
    has_kz = bool(re.search(CYRILLIC_KZ, text, re.I))
    has_ru = bool(re.search(r"[ёыэъ]", text, re.I)) or bool(re.search(r"\b(но|очень|больше|персонал|заказ|кассир|кофе)\b", text, re.I))
    if has_kz and has_ru:
        return "mixed_kz_ru"
    if has_kz:
        return "kk"
    if re.search(r"[а-я]", text, re.I):
        return "ru"
    return "en"


def analyze(text: str) -> AIAnalysis:
    negative = len(re.findall(NEGATIVE, text, re.I))
    positive = len(re.findall(POSITIVE, text, re.I))
    language = detect_language(text)
    aspects: list[Aspect] = []
    for name, pattern in ASPECTS.items():
        if re.search(pattern, text, re.I):
            local_negative = bool(re.search(NEGATIVE, text, re.I))
            if name == "product" and positive:
                sentiment = "positive"
            else:
                sentiment = "negative" if local_negative else "positive"
            aspects.append(Aspect(aspect=name, sentiment=sentiment))
    if not aspects:
        aspects = [Aspect(aspect="overall", sentiment="negative" if negative else "positive")]
    sentiment = "mixed" if negative and positive else "negative" if negative else "positive" if positive else "neutral"
    score = max(-1.0, min(1.0, (positive - negative) / max(1, positive + negative)))
    critical = bool(re.search(r"отрав|fraud|мошен|полици|суд|injur|дискрим|қауіп", text, re.I))
    confidence = 0.78 if sentiment == "mixed" or language == "mixed_kz_ru" else 0.9
    return AIAnalysis(
        language=language,
        sentiment=sentiment,
        sentiment_score=score,
        severity="critical" if critical else "high" if negative >= 2 else "medium" if negative else "low",
        confidence=confidence,
        aspects=aspects,
        escalated=critical or language == "mixed_kz_ru" or confidence < 0.8,
    )
