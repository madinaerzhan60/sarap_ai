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

TOPIC_PATTERNS = [
    ("staff_communication", "коммуникация сотрудников", r"груб|дөрекі|персонал|сотрудник|менеджер|приемн|приёмн|адмис|admission|staff|rude"),
    ("dormitory", "общежитие", r"общежит|общаг|дорм|жатақхана|dorm"),
    ("transport_access", "транспорт и расположение", r"каскелен|далеко|автобус|шаттл|транспорт|дорог.{0,20}(?:до|в)|location|transport|shuttle"),
    ("food_canteen", "еда и столовая", r"столов|еда|кофе|блюд|тағам|дәм|асхана|canteen|food"),
    ("academic_registration", "академическая регистрация", r"кредит|зарегистр|дисциплин|регистрац|portal|портал|schedule|расписан"),
    ("teaching_quality", "качество обучения", r"преподав|учител|сабақ|лекци|teacher|professor|teaching|class"),
    ("campus_atmosphere", "кампус и атмосфера", r"кампус|трц|атмосфер|красив|мест.{0,25}(?:поспать|отдох)|student life|clubs|club|ивент|event"),
    ("support_response", "ответ поддержки", r"поддержк|не\s+отвеч|игнор|support|no reply"),
    ("pricing_money", "деньги и оплата", r"деньг|оплат|дорог|цен|стоимост|баға|қымбат|price|cost|refund"),
    ("scam_fairness", "честность и доверие", r"обман|мошен|подстав|розыгрыш|scam|fraud|deception"),
]


def _is_russian_like(text: str) -> bool:
    return bool(re.search(r"[а-яё]", text, re.I))


def _short_reaction_summary(compact: str, sentiment: str) -> str | None:
    letters = re.findall(r"[\wа-яёәғқңөұүһі]+", compact, re.I)
    has_heart = bool(re.search(r"[❤♥💕💖😍🥰👍🔥✨]", compact))
    if len("".join(letters)) > 18 or len(letters) > 3:
        return None
    russian = _is_russian_like(compact)
    if has_heart and not letters:
        return "Краткая положительная реакция без текстовых деталей." if russian or sentiment != "negative" else "Brief positive reaction without text details."
    if sentiment == "positive":
        return "Краткая положительная оценка без дополнительных деталей." if russian else "Brief positive assessment without additional details."
    if sentiment == "negative":
        return "Краткая резко негативная оценка без конкретной причины." if russian else "Brief strongly negative assessment without a specific reason."
    if sentiment == "mixed":
        return "Краткая смешанная оценка без дополнительных деталей." if russian else "Brief mixed assessment without additional details."
    return "Краткая реакция без конкретных деталей." if russian else "Brief reaction without specific details."


def extract_review_topic(text: str, sentiment: str = "neutral") -> tuple[str, str]:
    compact = " ".join(text.split())
    lowered = compact.casefold()
    if _short_reaction_summary(compact, sentiment):
        return ("low_signal", "низкосигнальный короткий отзыв")
    for tag, label, pattern in TOPIC_PATTERNS:
        if re.search(pattern, lowered, re.I):
            return tag, label
    return ("low_signal", "низкосигнальный отзыв без конкретной темы")


def _topic_summary_ru(lowered: str) -> str | None:
    positive: list[str] = []
    negative: list[str] = []
    if re.search(r"кампус|трц|красив|мест.{0,25}(?:поспать|отдох)|отдых", lowered):
        positive.append("красивый кампус и места для отдыха")
    if re.search(r"каскелен|далеко|располож", lowered):
        negative.append("расположения в Каскелене")
    if re.search(r"деньг|оплат", lowered) and re.search(r"пофиг|безразлич|главное|приоритет", lowered):
        return "Жалуется на безразличное отношение и считает, что приоритет отдается деньгам."
    if re.search(r"при[её]мн.{0,25}(?:общежит|общаг)|(?:общежит|общаг).{0,35}при[её]мн", lowered) and re.search(r"груб|хам|не\s+объяс|объяснен|понятн", lowered):
        return "Жалуется на грубое общение приемной комиссии общежития и отсутствие понятных объяснений."
    if re.search(r"общежит|общаг|жатақхана", lowered) and re.search(r"груб|хам|не\s+объяс|очеред|мест", lowered):
        return "Жалуется на проблемы с общежитием и коммуникацией сотрудников."
    if re.search(r"кредит", lowered) and re.search(r"зарегистр|дисциплин", lowered):
        return "Жалуется на проблемы с академическими кредитами и невозможность зарегистрироваться на дисциплины после оплаты."
    if re.search(r"поддержк.{0,35}(?:не\s+отвеч|никак|игнор)", lowered):
        return "Жалуется на отсутствие ответа службы поддержки."
    if re.search(r"не\s+(?:могу|получается).{0,45}(?:войти|зайти)|не\s+работ.{0,30}прилож", lowered):
        return "Сообщает о проблеме со входом или работой приложения."
    if re.search(r"розыгрыш|выигра.{0,20}абонемент", lowered):
        return "Сомневается в честности розыгрыша годового абонемента."
    if re.search(r"позвон|звон.{0,35}продаж|продажниц", lowered):
        return "Жалуется на нежелательный звонок отдела продаж."
    if re.search(r"обман|мошен|подстав", lowered):
        return "Подозревает обман или несправедливое отношение."
    if re.search(r"долго|очеред|ожида", lowered):
        return "Жалуется на долгое ожидание."
    if re.search(r"груб|персонал|сотрудник|менеджер", lowered):
        return "Жалуется на неприятное взаимодействие с сотрудниками."
    if re.search(r"дорог|цен|стоимост", lowered):
        return "Недоволен стоимостью услуги."
    if re.search(r"приложен.{0,45}(?:спорт|занят)|(?:спорт|занят).{0,45}приложен", lowered):
        return "Хвалит приложение для занятий спортом."
    if positive and negative:
        return f"Отмечает {', '.join(positive)}, но снижает оценку из-за {', '.join(negative)}."
    if positive:
        return f"Отмечает {', '.join(positive)}."
    if negative:
        return f"Жалуется на {', '.join(negative)}."
    if re.search(r"удобн|выгодн", lowered):
        return "Отмечает удобство и пользу сервиса."
    if re.search(r"вкусн|кофе|еда|тағам|дәм", lowered):
        return "Оценивает качество еды или напитков."
    return None


def _topic_summary_en(lowered: str) -> str | None:
    if re.search(r"cannot|can't|unable", lowered) and re.search(r"log ?in|register|sign ?up", lowered):
        return "Reports being unable to log in or register."
    if re.search(r"support|service", lowered) and re.search(r"ignore|no reply|doesn't answer|not answer", lowered):
        return "Complains that support or service does not respond."
    if re.search(r"wait|late|queue|slow", lowered):
        return "Complains about slow service or long waiting time."
    if re.search(r"expensive|price|cost", lowered):
        return "Complains about the price or cost."
    if re.search(r"campus|beautiful|place to rest|sleep", lowered):
        return "Mentions the campus or resting places as a positive detail."
    if re.search(r"great|good|love|recommend|best", lowered):
        return "Praises a specific positive experience but gives few details."
    return None


def summarize_review(text: str, sentiment: str) -> str:
    """Create a short meaning-based summary without repeating the review."""
    compact = " ".join(text.split())
    lowered = compact.casefold()
    short = _short_reaction_summary(compact, sentiment)
    if short:
        return short
    if _is_russian_like(compact):
        topical = _topic_summary_ru(lowered)
        if topical:
            return topical
    else:
        topical = _topic_summary_en(lowered)
        if topical:
            return topical
    if sentiment == "positive":
        return "Краткая положительная оценка без дополнительных деталей." if _is_russian_like(compact) else "Brief positive assessment without additional details."
    if sentiment == "negative":
        return "Краткая негативная оценка без конкретной причины." if _is_russian_like(compact) else "Brief negative assessment without a specific reason."
    if sentiment == "mixed":
        return "Краткая смешанная оценка без дополнительных деталей." if _is_russian_like(compact) else "Brief mixed assessment without additional details."
    return "Краткое мнение без однозначной оценки и конкретных деталей." if _is_russian_like(compact) else "Brief opinion without clear sentiment or specific details."


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
