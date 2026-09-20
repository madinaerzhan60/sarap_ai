from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = (ROOT / "frontend" / "app.js").read_text()


def test_industry_options_are_product_list():
    assert "['Restaurants & cafés','Retail','Education','Healthcare','Hospitality','Services','Other']" in APP


def test_onboarding_does_not_request_alias_or_social_fields():
    section = APP[APP.index("function onboarding()") : APP.index("const navItems") ]
    assert 'name="aliases"' not in section
    assert 'name="handle"' not in section
    assert 'name="website"' not in section
    assert "onboarding-add-source" in section


def test_source_cards_keep_unknown_count_and_modal_closes_after_success():
    assert "s.items==null?'—':s.items" in APP
    source_submit = APP[APP.index("if(kind==='source')") : APP.index("if(kind==='source-edit')") ]
    assert "closeModal();render();toast('Source added'" in source_submit


def test_mentions_include_required_filters_and_published_date():
    for value in ('source','type','sentiment','author','analysis','reply','date','rating','risk','sort'):
        assert f'data-mention-filter="{value}"' in APP
    assert "Published date" in APP
