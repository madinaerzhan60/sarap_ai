from app.scrapers import browser_runtime
from app.scrapers.browser_runtime import browser_diagnostics


def test_browser_diagnostics_detects_explicit_executable(monkeypatch, tmp_path):
    executable = tmp_path / "chromium"
    executable.write_text("browser")
    executable.chmod(0o755)
    monkeypatch.setenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE", str(executable))

    result = browser_diagnostics()

    assert result["playwright_configured"] is True
    assert result["chromium_found"] is True
    assert result["chromium_path_available"] is True
    assert result["chromium_location"] == str(executable)
    assert "proxy" not in result


def test_browser_diagnostics_uses_serverless_chromium_on_vercel(monkeypatch, tmp_path):
    executable = tmp_path / "chromium"
    executable.write_text("browser")
    executable.chmod(0o755)
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.delenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE", raising=False)
    monkeypatch.setattr(browser_runtime, "_serverless_chromium", lambda: (str(executable), ["--no-sandbox"]))

    result = browser_diagnostics()

    assert result["runtime"] == "sparticuz"
    assert result["chromium_found"] is True
    assert result["chromium_path_available"] is True
    assert result["chromium_location"] == str(executable)
    assert result["runtime_error"] is None
