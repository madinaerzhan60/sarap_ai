from __future__ import annotations

import logging
import os
import tarfile
import tempfile
from pathlib import Path
from typing import Any

import brotli
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
    """Extract the Lambda-compatible browser and return its recommended flags."""
    package_bin = _project_root() / "node_modules" / "@sparticuz" / "chromium" / "bin"
    executable = Path(tempfile.gettempdir()) / "chromium"
    try:
        if not executable.is_file():
            _inflate_brotli(package_bin / "chromium.br", executable)
            executable.chmod(0o700)
        _inflate_tar_brotli(package_bin / "fonts.tar.br", Path(tempfile.gettempdir()) / "fonts")
        _inflate_tar_brotli(package_bin / "swiftshader.tar.br", Path(tempfile.gettempdir()))
        lambda_lib = Path(tempfile.gettempdir()) / "al2023" / "lib"
        _inflate_tar_brotli(package_bin / "al2023.tar.br", lambda_lib.parent)
        os.environ.setdefault("FONTCONFIG_PATH", str(Path(tempfile.gettempdir()) / "fonts"))
        os.environ["LD_LIBRARY_PATH"] = ":".join(
            dict.fromkeys([str(lambda_lib), *os.getenv("LD_LIBRARY_PATH", "").split(":")])
        ).rstrip(":")
        return str(executable), _SERVERLESS_CHROMIUM_ARGS
    except Exception as exc:
        detail = str(exc).strip().splitlines()[0]
        raise BrowserRuntimeError(
            "chromium_not_installed",
            f"Serverless Chromium is unavailable: {detail}",
        ) from exc


def _inflate_brotli(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    decoder = brotli.Decompressor()
    with source.open("rb") as compressed, destination.open("wb") as output:
        while chunk := compressed.read(4 * 1024 * 1024):
            output.write(decoder.process(chunk))


def _inflate_tar_brotli(source: Path, destination: Path) -> None:
    marker = destination / f".{source.stem}.ready"
    if marker.is_file():
        return
    archive = Path(tempfile.gettempdir()) / f"{source.stem}.tar"
    _inflate_brotli(source, archive)
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as bundle:
        bundle.extractall(destination)
    archive.unlink(missing_ok=True)
    marker.touch()


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
            code = "chromium_not_installed" if "Executable doesn't exist" in message or "playwright install" in message else "browser_launch_failed"
            raise BrowserRuntimeError(code, f"Playwright could not launch Chromium: {message.splitlines()[0]}") from exc
        log.info("playwright_configured=true chromium_found=true chromium_path_available=true browser_started=true")
        return playwright, browser


browser_manager = BrowserManager()


async def launch_chromium(proxy: dict[str, str] | None = None) -> tuple[Playwright, Browser]:
    return await browser_manager.launch(proxy)
