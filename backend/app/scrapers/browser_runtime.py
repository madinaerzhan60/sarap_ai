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


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _is_serverless() -> bool:
    return bool(
        os.getenv("VERCEL")
        or os.getenv("VERCEL_ENV")
        or os.getenv("AWS_LAMBDA_FUNCTION_NAME")
        or Path("/var/task").is_dir()
    )


def _serverless_chromium() -> tuple[str, list[str]]:
    """Return Chromium and libraries prepared during the Vercel build."""
    runtime = _project_root() / ".serverless-chromium"
    executable = runtime / "chromium"
    try:
        if not executable.is_file():
            raise FileNotFoundError(executable)
        lambda_lib = runtime / "al2023" / "lib"
        os.environ.setdefault("FONTCONFIG_PATH", str(runtime / "fonts"))
        os.environ.setdefault("VK_ICD_FILENAMES", str(runtime / "vk_swiftshader_icd.json"))
        os.environ["LD_LIBRARY_PATH"] = ":".join(
            dict.fromkeys([str(runtime), str(lambda_lib), *os.getenv("LD_LIBRARY_PATH", "").split(":")])
        ).rstrip(":")
        return str(executable), _SERVERLESS_CHROMIUM_ARGS
    except Exception as exc:
        detail = str(exc).strip().splitlines()[0]
        raise BrowserRuntimeError(
            "chromium_not_installed",
            f"Serverless Chromium is unavailable: {detail}",
        ) from exc


_SERVERLESS_CHROMIUM_ARGS = [
    "--ash-no-nudges",
    "--disable-domain-reliability",
    "--disable-print-preview",
    "--disk-cache-size=33554432",
    "--no-default-browser-check",
    "--no-pings",
    "--single-process",
    "--font-render-hinting=none",
    "--disable-features=AudioServiceOutOfProcess,IsolateOrigins,site-per-process",
    "--enable-features=SharedArrayBuffer",
    "--disable-webgl",
    "--allow-running-insecure-content",
    "--disable-setuid-sandbox",
    "--disable-site-isolation-trials",
    "--disable-web-security",
    "--headless=shell",
    "--no-sandbox",
    "--no-zygote",
]


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
    serverless_error: str | None = None
    if _is_serverless() and not explicit:
        try:
            explicit, _ = _serverless_chromium()
        except BrowserRuntimeError as exc:
            serverless_error = str(exc)
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
        "runtime": "sparticuz" if _is_serverless() else "playwright",
        "runtime_error": serverless_error,
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
        serverless_args: list[str] = []
        if _is_serverless() and not explicit:
            try:
                explicit, serverless_args = _serverless_chromium()
            except BrowserRuntimeError:
                await playwright.stop()
                raise
        if not explicit and Path(mac_chrome).is_file() and not _is_serverless():
            explicit = mac_chrome
        args = serverless_args or (["--no-sandbox", "--disable-dev-shm-usage"] if _is_serverless() or os.name == "posix" and not Path(mac_chrome).is_file() else [])
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
            log.exception("Playwright Chromium launch failed: %s", message)
            code = "chromium_not_installed" if "Executable doesn't exist" in message or "playwright install" in message else "browser_launch_failed"
            useful_lines = [line.strip() for line in message.splitlines() if line.strip()]
            detail = " | ".join(useful_lines[:6])[:900]
            raise BrowserRuntimeError(code, f"Playwright could not launch Chromium: {detail}") from exc
        log.info("playwright_configured=true chromium_found=true chromium_path_available=true browser_started=true")
        return playwright, browser


browser_manager = BrowserManager()


async def launch_chromium(proxy: dict[str, str] | None = None) -> tuple[Playwright, Browser]:
    return await browser_manager.launch(proxy)
