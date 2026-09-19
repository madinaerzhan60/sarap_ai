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


def test_serverless_detection_does_not_require_vercel_system_variables(monkeypatch):
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("VERCEL_ENV", raising=False)
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
    original_is_dir = browser_runtime.Path.is_dir

    def fake_is_dir(path):
        if str(path) == "/var/task":
            return True
        return original_is_dir(path)

    monkeypatch.setattr(browser_runtime.Path, "is_dir", fake_is_dir)

    assert browser_runtime._is_serverless() is True


def test_serverless_runtime_exposes_swiftshader_libraries(monkeypatch, tmp_path):
    runtime = tmp_path / ".serverless-chromium"
    runtime.mkdir()
    executable = runtime / "chromium"
    executable.write_text("browser")
    executable.chmod(0o755)
    monkeypatch.setattr(browser_runtime, "_project_root", lambda: tmp_path)
    monkeypatch.delenv("LD_LIBRARY_PATH", raising=False)
    monkeypatch.delenv("VK_ICD_FILENAMES", raising=False)

    resolved, _ = browser_runtime._serverless_chromium()

    assert resolved == str(executable)
    assert str(runtime) in browser_runtime.os.environ["LD_LIBRARY_PATH"]
    assert browser_runtime.os.environ["VK_ICD_FILENAMES"] == str(runtime / "vk_swiftshader_icd.json")
