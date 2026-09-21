from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable


STOPWORDS = {
    # English
    "about", "after", "again", "also", "been", "being", "could", "from", "have", "just", "only", "really", "that", "their", "there", "they", "this", "very", "were", "with", "would", "the", "and",
    # Russian
    "был", "была", "были", "будет", "ведь", "вот", "для", "даже", "если", "есть", "как", "когда", "который", "крайне", "можно", "очень", "просто", "также", "того", "только", "чтобы", "этот", "эта", "это",
    # Kazakh
    "бірақ", "болады", "болды", "ғана", "деген", "дейін", "және", "жақсы", "кейін", "мен", "осы", "өте", "тағы", "үшін",
}

VARIANTS = {
    "преподаватель": "Преподаватели", "преподаватели": "Преподаватели", "преподавателя": "Преподаватели", "преподавателей": "Преподаватели", "преподы": "Преподаватели", "препод": "Преподаватели",
    "teacher": "Teachers", "teachers": "Teachers", "instructor": "Teachers", "instructors": "Teachers",
    "оқытушы": "Оқытушылар", "оқытушылар": "Оқытушылар", "мұғалім": "Оқытушылар", "мұғалімдер": "Оқытушылар",
}


def top_topics(texts: Iterable[str], aliases: Iterable[str] = (), limit: int = 10) -> list[tuple[str, int]]:
    alias_words = {word.casefold() for alias in aliases for word in re.findall(r"[^\W\d_]+", alias, re.UNICODE) if len(word) >= 3}
    counts: Counter[str] = Counter()
    for text in texts:
        seen: set[str] = set()
        for raw in re.findall(r"[^\W\d_]+", text.casefold(), re.UNICODE):
            if len(raw) < 4 or raw in STOPWORDS or raw in alias_words:
                continue
            topic = VARIANTS.get(raw, raw.capitalize())
            seen.add(topic)
        counts.update(seen)
    return counts.most_common(limit)
