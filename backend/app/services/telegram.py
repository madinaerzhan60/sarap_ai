from __future__ import annotations

import json
import os
from urllib.request import Request, urlopen

from app.models import ProcessedMention


def format_alert(item: ProcessedMention) -> str:
    aspect = next((a.aspect for a in item.analysis.aspects if a.sentiment == "negative"), "overall")
    return (
        "⚠️ SARAP Critical Alert\n\n"
        f"Source: {item.mention.source}\nRisk: {item.risk.score}/100\n"
        f"Aspect: {aspect}\nSentiment: {item.analysis.sentiment.title()}\n\n"
        f'“{item.mention.text[:500]}”\n\nOpen SARAP to review the evidence.'
    )


def send_alert(item: ProcessedMention, chat_id: str | None = None) -> bool:
    """Send to a destination loaded from telegram_connections in production."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token or not chat_id:
        return False
    body = json.dumps({"chat_id": chat_id, "text": format_alert(item)}).encode()
    request = Request(f"https://api.telegram.org/bot{token}/sendMessage", data=body, headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=10) as response:  # noqa: S310 - fixed Telegram host
        return response.status == 200
