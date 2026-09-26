from pathlib import Path


APP_JS = Path(__file__).resolve().parents[2] / "frontend" / "app.js"


def test_source_sync_refreshes_workspace_data_without_full_reload():
    source = APP_JS.read_text(encoding="utf-8")
    poll_start = source.index("async function pollBackendSource")
    poll_end = source.index("function mapStoredSource", poll_start)
    poll_body = source[poll_start:poll_end]

    assert "window.location.reload" not in poll_body
    assert "await loadWorkspace()" in poll_body
    assert "applyWorkspace(workspace)" in poll_body
    assert "await loadProductData()" in poll_body
    assert "await loadAnalyticsData(true)" in poll_body


def test_source_sync_button_prevents_duplicate_polls():
    source = APP_JS.read_text(encoding="utf-8")
    assert "const syncingSourceIds = new Set()" in source
    assert "if(syncingSourceIds.has(source.id))return" in source
    assert "syncingSourceIds.add(source.id)" in source
    assert "syncingSourceIds.delete(source.id)" in source
    assert "disabled" in source and "Syncing..." in source
