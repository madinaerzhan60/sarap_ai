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


def summarize_review(text: str, sentiment: str) -> str:
    """Create a short meaning-based summary without repeating the review."""
    compact = " ".join(text.split())
    lowered = compact.casefold()
    if not re.search(r"[а-яё]", compact, re.I):
        if sentiment == "positive":
            return "The customer is satisfied with the overall experience."
        if sentiment == "negative":
            return "The customer reports a problem with the experience."
        return "The customer shares a general opinion without a clear rating."
    rules = [
        (r"розыгрыш|выигра.{0,20}абонемент", "Пользователь сомневается в честности розыгрыша годового абонемента."),
        (r"позвон|звон.{0,35}продаж|продажниц", "Пользователь жалуется на нежелательный звонок отдела продаж."),
        (r"не\s+(?:могу|получается).{0,45}(?:войти|зайти)|не\s+работ.{0,30}прилож", "Пользователь сообщает о проблеме со входом или работой приложения."),
        (r"поддержк.{0,35}(?:не\s+отвеч|никак|игнор)", "Пользователь жалуется на отсутствие ответа службы поддержки."),
        (r"убирают\s+время|время.{0,30}(?:зал|клуб)", "Пользователь недоволен ограничениями времени посещения залов."),
        (r"обман|мошен|подстав", "Пользователь подозревает обман или несправедливое отношение."),
        (r"дорог|цен|стоимост", "Пользователь недоволен стоимостью услуги."),
        (r"долго|очеред|ожида", "Пользователь жалуется на долгое ожидание."),
        (r"груб|персонал|сотрудник|менеджер", "Пользователь оценивает качество работы сотрудников."),
        (r"приложен.{0,45}(?:спорт|занят)|(?:спорт|занят).{0,45}приложен", "Пользователь хвалит приложение для занятий спортом."),
        (r"приложен|сервис|разнообраз", "Пользователь положительно оценивает приложение, сервис и выбор услуг."),
        (r"удобн|выгодн", "Пользователь отмечает удобство и пользу сервиса."),
    ]
    for pattern, summary in rules:
        if re.search(pattern, lowered, re.I):
            return summary
    if sentiment == "positive":
        return "Пользователь положительно оценивает сервис."
    if sentiment == "negative":
        return "Пользователь сообщает о негативном опыте с сервисом."
    if sentiment == "mixed":
        return "Пользователь отмечает одновременно преимущества и недостатки сервиса."
    return "Пользователь делится мнением без однозначной оценки."


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
        summary=summarize_review(text, sentiment),
        sentiment_score=score,
        severity="critical" if critical else "high" if negative >= 2 else "medium" if negative else "low",
        confidence=confidence,
        aspects=aspects,
        escalated=critical or language == "mixed_kz_ru" or confidence < 0.8,
    )
