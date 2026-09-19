from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from playwright.async_api import Browser, Playwright, async_playwright

log = logging.getLogger("sarap.playwright")


class BrowserRuntimeError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _project_browser_path() -> Path:
    return Path(__file__).resolve().parents[3] / ".playwright-browsers"


def configure_browser_path() -> str | None:
    configured = os.getenv("PLAYWRIGHT_BROWSERS_PATH", "").strip()
    if configured:
        return configured
    bundled = _project_browser_path()
    if bundled.is_dir():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(bundled)
        return str(bundled)
    return None


def browser_diagnostics() -> dict[str, Any]:
    configured_path = configure_browser_path()
    explicit = os.getenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE", "").strip()
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    if configured_path:
        root = Path(configured_path)
        candidates.extend(path for path in root.rglob("*") if path.name in {"chrome", "Chromium", "headless_shell"})
    mac_chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    if mac_chrome.is_file():
        candidates.append(mac_chrome)
    found = next((path for path in candidates if path.is_file()), None)
    return {
        "playwright_configured": True,
        "chromium_found": found is not None,
        "chromium_path_available": bool(found and os.access(found, os.X_OK)),
        "chromium_location": str(found) if found else None,
        "browser_store": configured_path,
    }


class BrowserManager:
    """Single launch policy shared by every Playwright source connector."""

    async def launch(self, proxy: dict[str, str] | None = None) -> tuple[Playwright, Browser]:
        configure_browser_path()
        diagnostics = browser_diagnostics()
        log.info(
            "playwright_configured=%s chromium_found=%s chromium_path_available=%s browser_started=false",
            str(diagnostics["playwright_configured"]).lower(),
            str(diagnostics["chromium_found"]).lower(),
            str(diagnostics["chromium_path_available"]).lower(),
        )
        playwright = await async_playwright().start()
        explicit = os.getenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE", "").strip()
        mac_chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        if not explicit and Path(mac_chrome).is_file() and not os.getenv("VERCEL"):
            explicit = mac_chrome
        args = ["--no-sandbox", "--disable-dev-shm-usage"] if os.getenv("VERCEL") or os.name == "posix" and not Path(mac_chrome).is_file() else []
        try:
            expected = Path(explicit or playwright.chromium.executable_path)
            if not expected.is_file():
                raise BrowserRuntimeError("chromium_not_installed", f"Chromium executable was not found at {expected}")
            browser = await playwright.chromium.launch(
                headless=True,
                proxy=proxy,
                executable_path=explicit or None,
                args=args,
            )
        except BrowserRuntimeError:
            await playwright.stop()
            raise
        except Exception as exc:
            await playwright.stop()
            message = str(exc)
            code = "chromium_not_installed" if "Executable doesn't exist" in message or "playwright install" in message else "browser_launch_failed"
            raise BrowserRuntimeError(code, f"Playwright could not launch Chromium: {message.splitlines()[0]}") from exc
        log.info("playwright_configured=true chromium_found=true chromium_path_available=true browser_started=true")
        return playwright, browser


browser_manager = BrowserManager()


async def launch_chromium(proxy: dict[str, str] | None = None) -> tuple[Playwright, Browser]:
    return await browser_manager.launch(proxy)
