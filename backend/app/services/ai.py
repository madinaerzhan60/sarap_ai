from __future__ import annotations

import re

from app.models import AIAnalysis, Aspect

NEGATIVE = r"груб|долго|ужас|плох|дорог|опозд|отрав|мошен|обман|подстав|не\s+могу|не\s+работ|не\s+отвеч|не\s+покуп|никак(?:ой|ая)\s+поддерж|не\s+объяс|надоел|убирают\s+время|не\s+сотруднич|оценк.{0,20}ниже|ниже.{0,30}оцен|последн(?:им|ий).{0,20}раз|разочар|проблем|жалоб|дөрекі|баяу|жаман|күту|қауіп|қызмет\s+етпейді|шешуді\s+үйрен|late|wait|fraud|scam|injur"
POSITIVE = r"хорош|вкусн|отлич|керемет|жақсы|жаксы|күшті|дәмді|круто|супер|нравит|луч(?:ш|шее)|выгодн|удобн|балд[её]ж|советую|благодар|довольн|спасибо|рада|превосход|шикар|замечатель|приятн|ұнайды|унады|ыңғайлы|great|good|love|recommend|best"
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


def analyze(text: str, rating: float | None = None) -> AIAnalysis:
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
    if rating is not None:
        sentiment = "negative" if rating <= 2 else "neutral" if rating == 3 else "positive"
    score = max(-1.0, min(1.0, (positive - negative) / max(1, positive + negative)))
    critical = bool(re.search(r"отрав|fraud|мошен|полици|суд|injur|дискрим|қауіп", text, re.I))
    confidence = 0.82 if rating is not None else 0.78 if sentiment == "mixed" or language == "mixed_kz_ru" else 0.9 if positive or negative else 0.62
    return AIAnalysis(
        language=language,
        sentiment=sentiment,
        summary=" ".join(text.split())[:160],
        sentiment_score=score,
        severity="critical" if critical else "high" if negative >= 2 else "medium" if negative else "low",
        confidence=confidence,
        aspects=aspects,
        escalated=critical or language == "mixed_kz_ru" or confidence < 0.8,
    )
