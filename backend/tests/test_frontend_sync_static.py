from pathlib import Path


APP_JS = Path(__file__).resolve().parents[2] / "frontend" / "app.js"
STYLES_CSS = Path(__file__).resolve().parents[2] / "frontend" / "styles.css"


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


def test_mentions_controls_stay_compact_and_do_not_expose_old_filters():
    source = APP_JS.read_text(encoding="utf-8")
    mentions_start = source.index("function mentions()")
    mentions_end = source.index("function progressRow", mentions_start)
    mentions_body = source[mentions_start:mentions_end]

    assert 'placeholder="Search mentions…"' in mentions_body
    assert "mentions-filters-btn" in mentions_body
    assert "Export CSV" in mentions_body
    assert "+ Manual import" in mentions_body
    assert "headerFilter('source','Source'" in mentions_body
    assert "headerFilter('type','Type'" in mentions_body
    assert "headerFilter('sentiment','Sentiment'" in mentions_body
    assert "sortButton('Rating','rating')" in mentions_body
    assert "sortButton('Risk','risk')" in mentions_body
    assert "sortButton('Published date','newest')" in mentions_body
    assert "Included / ignored" in mentions_body
    assert "Author type" not in mentions_body
    assert "<div class=\"popover-label\">Analysis</div>" not in mentions_body


def test_mentions_filters_are_absolute_overlay_styles():
    styles = STYLES_CSS.read_text(encoding="utf-8")
    popover_start = styles.index(".filters-popover {")
    popover_end = styles.index(".popover-title", popover_start)
    popover_block = styles[popover_start:popover_end]
    anchor_start = styles.index(".popover-anchor {")
    anchor_end = styles.index(".filter-popover-btn", anchor_start)
    anchor_block = styles[anchor_start:anchor_end]

    assert "position: relative" in anchor_block
    assert "display: inline-flex" in anchor_block
    assert "position: absolute" in popover_block
    assert "top: calc(100% + 4px)" in popover_block
    assert "z-index: 200" in popover_block
    assert "max-height: 250px" in popover_block
    assert "background: rgba(30, 143, 133, .12);\n  color: var(--teal-dark);\n  border-color: rgba(30, 143, 133, .28);\n}" in styles
