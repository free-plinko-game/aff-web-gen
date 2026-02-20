"""Menu management tests.

Tests for:
- Menu columns on SitePage model
- _build_nav_links / _build_footer_links with configured vs legacy fallback
- Menu route (GET/POST)
- Menu defaults applied at page creation
- Integration (detail tab, built site reflects config)
- Sub-menu dropdowns (nav_parent_id, nested nav links)
"""

import json
import os
import shutil
import tempfile
import uuid
from datetime import datetime, timezone

import pytest

from app.models import (
    db as _db, Site, SitePage, SiteBrand, Brand, BrandGeo, BrandVertical,
    Geo, Vertical, PageType, Domain,
)
from app.services.site_builder import (
    build_site, _build_nav_links, _build_footer_links, _page_url_for_link,
)
from app.routes.sites import _menu_defaults_for_page_type


# --- Fixture content data (minimal for build tests) ---

HOMEPAGE_CONTENT = {
    'hero_title': 'Menu Test Home',
    'hero_subtitle': 'Testing menu',
    'intro_paragraph': 'Welcome.',
    'top_brands': [],
    'why_trust_us': 'Experts.',
    'faq': [{'question': 'Q?', 'answer': 'A.'}],
    'closing_paragraph': 'Done.',
}

COMPARISON_CONTENT = {
    'hero_title': 'Compare',
    'hero_subtitle': 'Side by side',
    'intro_paragraph': 'Comparison.',
    'comparison_rows': [],
    'faq': [],
    'closing_paragraph': 'Choose.',
}

EVERGREEN_CONTENT = {
    'hero_title': 'Guide Title',
    'hero_subtitle': 'A guide',
    'intro_paragraph': 'Intro.',
    'sections': [{'heading': 'Section 1', 'content': 'Content.'}],
    'key_takeaways': ['Point 1'],
    'faq': [],
    'closing_paragraph': 'End.',
}

BRAND_REVIEW_CONTENT = {
    'hero_title': 'Brand Review',
    'hero_subtitle': 'Full review',
    'intro_paragraphs': ['Review.'],
    'intro_paragraph': 'Review.',
    'pros': ['Pro'], 'cons': ['Con'],
    'features_sections': [{'heading': 'Features', 'content': 'Good.'}],
    'features_review': 'Good.',
    'user_experience': 'Easy.',
    'verdict': 'Recommended.',
    'faq': [],
}


def _make_site_with_pages(db, include_menu_config=False):
    """Helper: create a site with homepage, comparison, evergreen, and brand review pages."""
    uid = uuid.uuid4().hex[:6]
    geo = Geo.query.filter_by(code='gb').first()
    vertical = Vertical.query.filter_by(slug='sports-betting').first()

    brand = Brand(name=f'MenuBrand-{uid}', slug=f'menubrand-{uid}', rating=4.5)
    db.session.add(brand)
    db.session.flush()

    bg = BrandGeo(brand_id=brand.id, geo_id=geo.id, welcome_bonus='£30 Free', is_active=True)
    bv = BrandVertical(brand_id=brand.id, vertical_id=vertical.id)
    db.session.add_all([bg, bv])
    db.session.flush()

    site = Site(name=f'Menu Site {uid}', geo_id=geo.id, vertical_id=vertical.id, status='generated')
    db.session.add(site)
    db.session.flush()

    sb = SiteBrand(site_id=site.id, brand_id=brand.id, rank=1)
    db.session.add(sb)
    db.session.flush()

    pt_home = PageType.query.filter_by(slug='homepage').first()
    pt_comp = PageType.query.filter_by(slug='comparison').first()
    pt_ever = PageType.query.filter_by(slug='evergreen').first()
    pt_review = PageType.query.filter_by(slug='brand-review').first()

    pages = []

    p_home = SitePage(
        site_id=site.id, page_type_id=pt_home.id, slug='index', title='Homepage',
        content_json=json.dumps(HOMEPAGE_CONTENT), is_generated=True,
        generated_at=datetime.now(timezone.utc),
    )
    pages.append(p_home)

    p_comp = SitePage(
        site_id=site.id, page_type_id=pt_comp.id, slug='comparison', title='Comparison',
        content_json=json.dumps(COMPARISON_CONTENT), is_generated=True,
        generated_at=datetime.now(timezone.utc),
    )
    pages.append(p_comp)

    p_ever = SitePage(
        site_id=site.id, page_type_id=pt_ever.id, slug='football-betting',
        title='Football Betting Guide', evergreen_topic='Football Betting Guide',
        content_json=json.dumps(EVERGREEN_CONTENT), is_generated=True,
        generated_at=datetime.now(timezone.utc),
    )
    pages.append(p_ever)

    p_review = SitePage(
        site_id=site.id, page_type_id=pt_review.id, slug=brand.slug,
        title=f'{brand.name} Review', brand_id=brand.id,
        content_json=json.dumps(BRAND_REVIEW_CONTENT), is_generated=True,
        generated_at=datetime.now(timezone.utc),
    )
    pages.append(p_review)

    if include_menu_config:
        p_comp.show_in_nav = True
        p_comp.show_in_footer = True
        p_comp.nav_order = 10
        p_comp.nav_label = 'Compare'

        p_ever.show_in_nav = True
        p_ever.show_in_footer = True
        p_ever.nav_order = 50
        p_ever.nav_label = None

        p_review.show_in_nav = False
        p_review.show_in_footer = True
        p_review.nav_order = 100
        p_review.nav_label = None

    db.session.add_all(pages)
    db.session.flush()

    return site, brand, pages


# ===== MODEL TESTS =====

class TestMenuModelColumns:
    """Test menu columns on SitePage model."""

    def test_default_values(self, db):
        """New SitePage has show_in_nav=False, show_in_footer=False, nav_order=0, nav_label=None."""
        geo = Geo.query.filter_by(code='gb').first()
        vertical = Vertical.query.filter_by(slug='sports-betting').first()
        pt = PageType.query.filter_by(slug='evergreen').first()

        site = Site(name='Defaults Test', geo_id=geo.id, vertical_id=vertical.id)
        db.session.add(site)
        db.session.flush()

        page = SitePage(
            site_id=site.id, page_type_id=pt.id,
            slug='test-defaults', title='Test Defaults',
            evergreen_topic='Test Defaults',
        )
        db.session.add(page)
        db.session.flush()

        assert page.show_in_nav is False
        assert page.show_in_footer is False
        assert page.nav_order == 0
        assert page.nav_label is None

    def test_columns_settable(self, db):
        """Menu columns can be set and persisted."""
        geo = Geo.query.filter_by(code='gb').first()
        vertical = Vertical.query.filter_by(slug='sports-betting').first()
        pt = PageType.query.filter_by(slug='evergreen').first()

        site = Site(name='Settable Test', geo_id=geo.id, vertical_id=vertical.id)
        db.session.add(site)
        db.session.flush()

        page = SitePage(
            site_id=site.id, page_type_id=pt.id,
            slug='test-set', title='Test Set',
            evergreen_topic='Test Set',
            show_in_nav=True, show_in_footer=True,
            nav_order=42, nav_label='Custom Label',
        )
        db.session.add(page)
        db.session.flush()

        fetched = db.session.get(SitePage, page.id)
        assert fetched.show_in_nav is True
        assert fetched.show_in_footer is True
        assert fetched.nav_order == 42
        assert fetched.nav_label == 'Custom Label'

    def test_nav_label_nullable(self, db):
        """nav_label can be set to None (falls back to title)."""
        geo = Geo.query.filter_by(code='gb').first()
        vertical = Vertical.query.filter_by(slug='sports-betting').first()
        pt = PageType.query.filter_by(slug='comparison').first()

        site = Site(name='Nullable Test', geo_id=geo.id, vertical_id=vertical.id)
        db.session.add(site)
        db.session.flush()

        page = SitePage(
            site_id=site.id, page_type_id=pt.id,
            slug='comparison', title='Comparison',
            nav_label='Compare',
        )
        db.session.add(page)
        db.session.flush()

        page.nav_label = None
        db.session.flush()
        assert db.session.get(SitePage, page.id).nav_label is None


# ===== BUILDER TESTS =====

class TestBuildNavLinks:
    """Test _build_nav_links with configured vs legacy fallback."""

    def test_legacy_fallback_when_no_nav_configured(self, db):
        """When no pages have show_in_nav=True, use legacy behavior."""
        site, brand, pages = _make_site_with_pages(db, include_menu_config=False)
        links = _build_nav_links(pages)

        labels = [l['label'] for l in links]
        assert labels[0] == 'Home'
        assert 'Compare' in labels
        assert 'Football Betting Guide' in labels
        # Brand review should NOT be in legacy nav
        assert not any(brand.name in l for l in labels)

    def test_configured_nav_uses_show_in_nav(self, db):
        """When pages have show_in_nav=True, only those appear."""
        site, brand, pages = _make_site_with_pages(db, include_menu_config=True)
        links = _build_nav_links(pages)

        labels = [l['label'] for l in links]
        assert labels[0] == 'Home'
        assert 'Compare' in labels
        assert 'Football Betting Guide' in labels
        # Brand review has show_in_nav=False
        assert f'{brand.name} Review' not in labels

    def test_nav_order_sorting(self, db):
        """Pages are sorted by nav_order."""
        site, brand, pages = _make_site_with_pages(db, include_menu_config=True)
        # Swap orders: evergreen first (10), comparison second (50)
        for p in pages:
            if p.page_type.slug == 'evergreen':
                p.show_in_nav = True
                p.nav_order = 10
            elif p.page_type.slug == 'comparison':
                p.show_in_nav = True
                p.nav_order = 50
        db.session.flush()

        links = _build_nav_links(pages)
        # Home is always first
        assert links[0]['label'] == 'Home'
        assert links[1]['label'] == 'Football Betting Guide'  # order 10
        assert links[2]['label'] == 'Compare'  # order 50

    def test_nav_label_fallback_to_title(self, db):
        """nav_label is used when set, title when None."""
        site, brand, pages = _make_site_with_pages(db, include_menu_config=True)
        # Comparison has nav_label='Compare', evergreen has nav_label=None
        links = _build_nav_links(pages)

        comp_link = next(l for l in links if l['url'] == 'comparison.html')
        assert comp_link['label'] == 'Compare'

        ever_link = next(l for l in links if 'football' in l['url'])
        assert ever_link['label'] == 'Football Betting Guide'

    def test_home_always_first(self, db):
        """Home link is always present and first, regardless of config."""
        site, brand, pages = _make_site_with_pages(db, include_menu_config=True)
        links = _build_nav_links(pages)
        assert links[0] == {'url': 'index.html', 'label': 'Home'}

    def test_empty_pages_only_home(self, db):
        """With no pages, only Home link returned."""
        links = _build_nav_links([])
        assert len(links) == 1
        assert links[0]['label'] == 'Home'


class TestBuildFooterLinks:
    """Test _build_footer_links with configured vs legacy fallback."""

    def test_legacy_fallback_returns_none(self, db):
        """When no pages have show_in_footer=True, returns None."""
        site, brand, pages = _make_site_with_pages(db, include_menu_config=False)
        result = _build_footer_links(pages)
        assert result is None

    def test_configured_returns_categorized_dict(self, db):
        """When pages have show_in_footer=True, returns categorized dict."""
        site, brand, pages = _make_site_with_pages(db, include_menu_config=True)
        result = _build_footer_links(pages)

        assert isinstance(result, dict)
        assert 'brand_reviews' in result
        assert 'guides' in result
        assert 'bonuses' in result

        # Brand review is in footer
        assert len(result['brand_reviews']) == 1
        assert brand.name in result['brand_reviews'][0]['label']

        # Comparison and evergreen are in guides
        assert len(result['guides']) == 2

    def test_footer_respects_nav_order(self, db):
        """Footer items sorted by nav_order."""
        site, brand, pages = _make_site_with_pages(db, include_menu_config=True)
        result = _build_footer_links(pages)

        # Guides: comparison (order 10) before evergreen (order 50)
        assert result['guides'][0]['label'] == 'Compare'
        assert result['guides'][1]['label'] == 'Football Betting Guide'


class TestPageUrlForLink:
    """Test _page_url_for_link returns correct URLs per page type."""

    def test_all_page_types(self, db):
        site, brand, pages = _make_site_with_pages(db, include_menu_config=False)

        for p in pages:
            url = _page_url_for_link(p)
            if p.page_type.slug == 'homepage':
                assert url == 'index.html'
            elif p.page_type.slug == 'comparison':
                assert url == 'comparison.html'
            elif p.page_type.slug == 'brand-review':
                assert url == f'reviews/{p.slug}.html'
            elif p.page_type.slug == 'evergreen':
                assert url == f'{p.slug}.html'


# ===== ROUTE TESTS =====

class TestMenuRoute:
    """Test the menu management route."""

    def test_menu_get_returns_200(self, client, db):
        site, brand, pages = _make_site_with_pages(db)
        resp = client.get(f'/sites/{site.id}/menu')
        assert resp.status_code == 200
        assert b'Menu Settings' in resp.data

    def test_menu_shows_all_pages(self, client, db):
        site, brand, pages = _make_site_with_pages(db)
        resp = client.get(f'/sites/{site.id}/menu')
        for p in pages:
            assert p.title.encode() in resp.data

    def test_menu_post_saves_show_in_nav(self, client, db):
        site, brand, pages = _make_site_with_pages(db)
        comp = next(p for p in pages if p.page_type.slug == 'comparison')

        resp = client.post(f'/sites/{site.id}/menu', data={
            f'page_{comp.id}_show_in_nav': 'on',
            f'page_{comp.id}_show_in_footer': '',
            f'page_{comp.id}_nav_order': '10',
            f'page_{comp.id}_nav_label': '',
        }, follow_redirects=True)

        assert resp.status_code == 200
        updated = db.session.get(SitePage, comp.id)
        assert updated.show_in_nav is True

    def test_menu_post_saves_show_in_footer(self, client, db):
        site, brand, pages = _make_site_with_pages(db)
        review = next(p for p in pages if p.page_type.slug == 'brand-review')

        resp = client.post(f'/sites/{site.id}/menu', data={
            f'page_{review.id}_show_in_nav': '',
            f'page_{review.id}_show_in_footer': 'on',
            f'page_{review.id}_nav_order': '100',
            f'page_{review.id}_nav_label': '',
        }, follow_redirects=True)

        assert resp.status_code == 200
        updated = db.session.get(SitePage, review.id)
        assert updated.show_in_footer is True

    def test_menu_post_saves_nav_order(self, client, db):
        site, brand, pages = _make_site_with_pages(db)
        ever = next(p for p in pages if p.page_type.slug == 'evergreen')

        resp = client.post(f'/sites/{site.id}/menu', data={
            f'page_{ever.id}_show_in_nav': 'on',
            f'page_{ever.id}_show_in_footer': 'on',
            f'page_{ever.id}_nav_order': '77',
            f'page_{ever.id}_nav_label': '',
        }, follow_redirects=True)

        updated = db.session.get(SitePage, ever.id)
        assert updated.nav_order == 77

    def test_menu_post_saves_nav_label(self, client, db):
        site, brand, pages = _make_site_with_pages(db)
        comp = next(p for p in pages if p.page_type.slug == 'comparison')

        resp = client.post(f'/sites/{site.id}/menu', data={
            f'page_{comp.id}_show_in_nav': 'on',
            f'page_{comp.id}_show_in_footer': '',
            f'page_{comp.id}_nav_order': '10',
            f'page_{comp.id}_nav_label': 'My Custom Label',
        }, follow_redirects=True)

        updated = db.session.get(SitePage, comp.id)
        assert updated.nav_label == 'My Custom Label'

    def test_menu_post_clears_empty_nav_label(self, client, db):
        site, brand, pages = _make_site_with_pages(db)
        comp = next(p for p in pages if p.page_type.slug == 'comparison')
        comp.nav_label = 'Old Label'
        db.session.flush()

        resp = client.post(f'/sites/{site.id}/menu', data={
            f'page_{comp.id}_show_in_nav': '',
            f'page_{comp.id}_show_in_footer': '',
            f'page_{comp.id}_nav_order': '0',
            f'page_{comp.id}_nav_label': '',
        }, follow_redirects=True)

        updated = db.session.get(SitePage, comp.id)
        assert updated.nav_label is None

    def test_menu_post_redirects_with_flash(self, client, db):
        site, brand, pages = _make_site_with_pages(db)
        resp = client.post(f'/sites/{site.id}/menu', data={})
        assert resp.status_code == 302
        assert f'/sites/{site.id}' in resp.headers['Location']


# ===== DEFAULT TESTS =====

class TestMenuDefaults:
    """Test that page creation applies correct menu defaults."""

    def test_defaults_comparison(self, db):
        defaults = _menu_defaults_for_page_type('comparison')
        assert defaults['show_in_nav'] is True
        assert defaults['show_in_footer'] is True
        assert defaults['nav_order'] == 10
        assert defaults['nav_label'] == 'Compare'

    def test_defaults_evergreen(self, db):
        defaults = _menu_defaults_for_page_type('evergreen')
        assert defaults['show_in_nav'] is True
        assert defaults['show_in_footer'] is True
        assert defaults['nav_order'] == 50

    def test_defaults_brand_review(self, db):
        defaults = _menu_defaults_for_page_type('brand-review')
        assert defaults['show_in_nav'] is False
        assert defaults['show_in_footer'] is True
        assert defaults['nav_order'] == 100

    def test_defaults_homepage(self, db):
        defaults = _menu_defaults_for_page_type('homepage')
        assert defaults['show_in_nav'] is False
        assert defaults['show_in_footer'] is False

    def test_wizard_applies_defaults(self, client, db):
        """Wizard-created pages get correct menu defaults."""
        uid = uuid.uuid4().hex[:6]
        geo = Geo.query.filter_by(code='gb').first()
        vertical = Vertical.query.filter_by(slug='sports-betting').first()

        brand = Brand(name=f'WizBrand-{uid}', slug=f'wizbrand-{uid}', rating=4.0)
        db.session.add(brand)
        db.session.flush()
        bg = BrandGeo(brand_id=brand.id, geo_id=geo.id, welcome_bonus='£10', is_active=True)
        bv = BrandVertical(brand_id=brand.id, vertical_id=vertical.id)
        db.session.add_all([bg, bv])
        db.session.flush()

        resp = client.post('/sites/create', data={
            'site_name': f'WizSite-{uid}',
            'geo_id': geo.id,
            'vertical_id': vertical.id,
            'brand_ids': [brand.id],
            f'brand_rank_{brand.id}': 1,
            'page_types': ['homepage', 'comparison', 'evergreen'],
            'evergreen_topics': ['Test Guide'],
        }, follow_redirects=True)

        assert resp.status_code == 200

        site = Site.query.filter_by(name=f'WizSite-{uid}').first()
        assert site is not None

        for p in site.site_pages:
            if p.page_type.slug == 'comparison':
                assert p.show_in_nav is True
                assert p.show_in_footer is True
                assert p.nav_order == 10
            elif p.page_type.slug == 'evergreen':
                assert p.show_in_nav is True
                assert p.show_in_footer is True
                assert p.nav_order == 50
            elif p.page_type.slug == 'homepage':
                assert p.show_in_nav is False
                assert p.show_in_footer is False


# ===== INTEGRATION TESTS =====

class TestMenuIntegration:
    """Integration tests for menu management."""

    def test_detail_page_has_menu_tab(self, client, db):
        site, brand, pages = _make_site_with_pages(db)
        resp = client.get(f'/sites/{site.id}')
        assert resp.status_code == 200
        assert b'Menu' in resp.data
        assert f'/sites/{site.id}/menu'.encode() in resp.data

    def test_built_site_nav_reflects_config(self, db):
        """Build a site with menu config and verify HTML nav matches."""
        site, brand, pages = _make_site_with_pages(db, include_menu_config=True)

        # Assign domain
        dom = Domain(domain=f'menu-test-{uuid.uuid4().hex[:6]}.com', status='assigned')
        db.session.add(dom)
        db.session.flush()
        site.domain_id = dom.id
        db.session.flush()

        output_dir = tempfile.mkdtemp()
        upload_dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(upload_dir, 'logos'), exist_ok=True)

        try:
            version_dir = build_site(site, output_dir, upload_dir)

            # Read homepage
            with open(os.path.join(version_dir, 'index.html'), 'r', encoding='utf-8') as f:
                html = f.read()

            # Nav should have Home, Compare, Football Betting Guide
            assert 'Home' in html
            assert 'Compare' in html
            assert 'Football Betting Guide' in html

            # Brand review should NOT be in nav (show_in_nav=False)
            # But the brand name may appear elsewhere in the page, so check the nav section
            nav_section = html.split('<nav')[1].split('</nav>')[0]
            assert f'{brand.name} Review' not in nav_section

        finally:
            shutil.rmtree(output_dir)
            shutil.rmtree(upload_dir)

    def test_built_site_footer_reflects_config(self, db):
        """Build a site with menu config and verify footer uses configured links."""
        site, brand, pages = _make_site_with_pages(db, include_menu_config=True)

        dom = Domain(domain=f'footer-test-{uuid.uuid4().hex[:6]}.com', status='assigned')
        db.session.add(dom)
        db.session.flush()
        site.domain_id = dom.id
        db.session.flush()

        output_dir = tempfile.mkdtemp()
        upload_dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(upload_dir, 'logos'), exist_ok=True)

        try:
            version_dir = build_site(site, output_dir, upload_dir)

            with open(os.path.join(version_dir, 'index.html'), 'r', encoding='utf-8') as f:
                html = f.read()

            footer = html.split('<footer')[1].split('</footer>')[0]

            # Brand review should be in footer (show_in_footer=True)
            assert brand.name in footer
            # Compare should be in footer guides
            assert 'Compare All' in footer

        finally:
            shutil.rmtree(output_dir)
            shutil.rmtree(upload_dir)


# ===== SUB-MENU / DROPDOWN TESTS =====

class TestNavParentModel:
    """Test nav_parent_id self-referential FK on SitePage."""

    def test_nav_parent_id_defaults_to_none(self, db):
        site, brand, pages = _make_site_with_pages(db)
        for p in pages:
            assert p.nav_parent_id is None

    def test_nav_parent_id_settable(self, db):
        site, brand, pages = _make_site_with_pages(db)
        parent = next(p for p in pages if p.page_type.slug == 'comparison')
        child = next(p for p in pages if p.page_type.slug == 'brand-review')

        child.nav_parent_id = parent.id
        db.session.flush()

        fetched = db.session.get(SitePage, child.id)
        assert fetched.nav_parent_id == parent.id

    def test_nav_parent_relationship(self, db):
        site, brand, pages = _make_site_with_pages(db)
        parent = next(p for p in pages if p.page_type.slug == 'comparison')
        child = next(p for p in pages if p.page_type.slug == 'brand-review')

        child.nav_parent_id = parent.id
        db.session.flush()

        assert child.nav_parent.id == parent.id
        assert child in parent.nav_children

    def test_nav_parent_rejects_self_reference(self, db):
        site, brand, pages = _make_site_with_pages(db)
        page = next(p for p in pages if p.page_type.slug == 'comparison')

        with pytest.raises(ValueError, match='own parent'):
            page.nav_parent_id = page.id

    def test_nav_parent_rejects_multi_level(self, db):
        site, brand, pages = _make_site_with_pages(db)
        parent = next(p for p in pages if p.page_type.slug == 'comparison')
        child = next(p for p in pages if p.page_type.slug == 'brand-review')
        grandchild = next(p for p in pages if p.page_type.slug == 'evergreen')

        child.nav_parent_id = parent.id
        db.session.flush()

        with pytest.raises(ValueError, match='one level'):
            grandchild.nav_parent_id = child.id


class TestBuildNavLinksDropdown:
    """Test _build_nav_links with parent/child dropdown structure."""

    def test_child_pages_appear_under_parent(self, db):
        """Children with nav_parent_id appear in dropdown without needing show_in_nav."""
        site, brand, pages = _make_site_with_pages(db, include_menu_config=True)
        parent = next(p for p in pages if p.page_type.slug == 'comparison')
        child = next(p for p in pages if p.page_type.slug == 'brand-review')

        child.nav_parent_id = parent.id
        db.session.flush()

        links = _build_nav_links(pages)
        parent_entry = next(l for l in links if l['label'] == 'Compare')
        assert 'children' in parent_entry
        assert len(parent_entry['children']) == 1
        assert brand.name in parent_entry['children'][0]['label']

    def test_parent_link_is_clickable(self, db):
        site, brand, pages = _make_site_with_pages(db, include_menu_config=True)
        parent = next(p for p in pages if p.page_type.slug == 'comparison')
        child = next(p for p in pages if p.page_type.slug == 'brand-review')

        child.nav_parent_id = parent.id
        db.session.flush()

        links = _build_nav_links(pages)
        parent_entry = next(l for l in links if l['label'] == 'Compare')
        assert parent_entry['url'] == 'comparison.html'

    def test_child_order_within_dropdown(self, db):
        """Children sorted by nav_order within their dropdown."""
        site, brand, pages = _make_site_with_pages(db, include_menu_config=True)
        parent = next(p for p in pages if p.page_type.slug == 'comparison')
        child1 = next(p for p in pages if p.page_type.slug == 'brand-review')
        child2 = next(p for p in pages if p.page_type.slug == 'evergreen')

        child1.nav_parent_id = parent.id
        child1.nav_order = 200

        child2.nav_parent_id = parent.id
        child2.nav_order = 100
        db.session.flush()

        links = _build_nav_links(pages)
        parent_entry = next(l for l in links if l['label'] == 'Compare')
        assert len(parent_entry['children']) == 2
        # child2 (order 100) before child1 (order 200)
        assert parent_entry['children'][0]['label'] == 'Football Betting Guide'
        assert brand.name in parent_entry['children'][1]['label']

    def test_child_without_show_in_nav_still_appears(self, db):
        """Children appear in dropdown via nav_parent_id, regardless of show_in_nav."""
        site, brand, pages = _make_site_with_pages(db, include_menu_config=True)
        parent = next(p for p in pages if p.page_type.slug == 'comparison')
        child = next(p for p in pages if p.page_type.slug == 'brand-review')

        child.show_in_nav = False
        child.nav_parent_id = parent.id
        db.session.flush()

        links = _build_nav_links(pages)
        parent_entry = next(l for l in links if l['label'] == 'Compare')
        assert 'children' in parent_entry
        assert len(parent_entry['children']) == 1

    def test_parent_show_in_nav_false_hides_children(self, db):
        """If parent has show_in_nav=False, the dropdown doesn't appear."""
        site, brand, pages = _make_site_with_pages(db, include_menu_config=True)
        parent = next(p for p in pages if p.page_type.slug == 'comparison')
        child = next(p for p in pages if p.page_type.slug == 'brand-review')

        parent.show_in_nav = False  # parent hidden from top-level
        child.nav_parent_id = parent.id
        db.session.flush()

        links = _build_nav_links(pages)
        # Parent not in nav, so its children are orphaned
        labels = [l['label'] for l in links]
        assert 'Compare' not in labels
        assert f'{brand.name} Review' not in labels

    def test_top_level_no_children_key(self, db):
        """Top-level items without children have no 'children' key."""
        site, brand, pages = _make_site_with_pages(db, include_menu_config=True)
        links = _build_nav_links(pages)
        for link in links:
            assert 'children' not in link


class TestMenuRouteDropdown:
    """Test menu route handles nav_parent_id."""

    def test_menu_get_shows_parent_select(self, client, db):
        site, brand, pages = _make_site_with_pages(db)
        resp = client.get(f'/sites/{site.id}/menu')
        assert b'nav_parent_id' in resp.data
        assert b'Parent' in resp.data

    def test_menu_post_saves_nav_parent_id(self, client, db):
        site, brand, pages = _make_site_with_pages(db)
        parent = next(p for p in pages if p.page_type.slug == 'comparison')
        child = next(p for p in pages if p.page_type.slug == 'brand-review')

        resp = client.post(f'/sites/{site.id}/menu', data={
            f'page_{child.id}_nav_parent_id': str(parent.id),
            f'page_{child.id}_show_in_nav': 'on',
            f'page_{child.id}_nav_order': '100',
            f'page_{child.id}_nav_label': '',
        }, follow_redirects=True)
        assert resp.status_code == 200

        updated = db.session.get(SitePage, child.id)
        assert updated.nav_parent_id == parent.id

    def test_menu_post_clears_nav_parent_id(self, client, db):
        site, brand, pages = _make_site_with_pages(db)
        parent = next(p for p in pages if p.page_type.slug == 'comparison')
        child = next(p for p in pages if p.page_type.slug == 'brand-review')

        child.nav_parent_id = parent.id
        db.session.flush()

        resp = client.post(f'/sites/{site.id}/menu', data={
            f'page_{child.id}_nav_parent_id': '',
            f'page_{child.id}_show_in_nav': '',
            f'page_{child.id}_nav_order': '0',
            f'page_{child.id}_nav_label': '',
        }, follow_redirects=True)

        updated = db.session.get(SitePage, child.id)
        assert updated.nav_parent_id is None

    def test_menu_post_rejects_self_parent(self, client, db):
        site, brand, pages = _make_site_with_pages(db)
        page = next(p for p in pages if p.page_type.slug == 'comparison')

        resp = client.post(f'/sites/{site.id}/menu', data={
            f'page_{page.id}_nav_parent_id': str(page.id),
            f'page_{page.id}_show_in_nav': 'on',
            f'page_{page.id}_nav_order': '10',
            f'page_{page.id}_nav_label': '',
        }, follow_redirects=True)

        updated = db.session.get(SitePage, page.id)
        assert updated.nav_parent_id is None

    def test_menu_post_rejects_multi_level(self, client, db):
        """Cannot set a page as child of a page that is itself a child."""
        site, brand, pages = _make_site_with_pages(db)
        grandparent = next(p for p in pages if p.page_type.slug == 'comparison')
        parent = next(p for p in pages if p.page_type.slug == 'brand-review')
        child = next(p for p in pages if p.page_type.slug == 'evergreen')

        # First save: make parent a child of grandparent
        resp = client.post(f'/sites/{site.id}/menu', data={
            f'page_{parent.id}_nav_parent_id': str(grandparent.id),
            f'page_{parent.id}_nav_order': '0',
            f'page_{parent.id}_nav_label': '',
        }, follow_redirects=True)

        # Second save: try to make child a child of parent (who already has a parent)
        resp = client.post(f'/sites/{site.id}/menu', data={
            f'page_{parent.id}_nav_parent_id': str(grandparent.id),
            f'page_{child.id}_nav_parent_id': str(parent.id),
            f'page_{child.id}_nav_order': '0',
            f'page_{child.id}_nav_label': '',
        }, follow_redirects=True)

        updated = db.session.get(SitePage, child.id)
        assert updated.nav_parent_id is None  # rejected


class TestDropdownIntegration:
    """Integration: built site HTML has dropdown structure."""

    def test_built_site_has_dropdown_html(self, db):
        site, brand, pages = _make_site_with_pages(db, include_menu_config=True)
        parent = next(p for p in pages if p.page_type.slug == 'comparison')
        child = next(p for p in pages if p.page_type.slug == 'brand-review')

        child.nav_parent_id = parent.id
        db.session.flush()

        dom = Domain(domain=f'dropdown-{uuid.uuid4().hex[:6]}.com', status='assigned')
        db.session.add(dom)
        db.session.flush()
        site.domain_id = dom.id
        db.session.flush()

        output_dir = tempfile.mkdtemp()
        upload_dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(upload_dir, 'logos'), exist_ok=True)

        try:
            version_dir = build_site(site, output_dir, upload_dir)
            with open(os.path.join(version_dir, 'index.html'), 'r', encoding='utf-8') as f:
                html = f.read()

            nav_section = html.split('<nav')[1].split('</nav>')[0]
            assert 'nav-dropdown' in nav_section
            assert 'nav-dropdown-menu' in nav_section
            assert brand.name in nav_section
        finally:
            shutil.rmtree(output_dir)
            shutil.rmtree(upload_dir)

    def test_built_site_no_dropdown_when_no_children(self, db):
        site, brand, pages = _make_site_with_pages(db, include_menu_config=True)

        dom = Domain(domain=f'nodrop-{uuid.uuid4().hex[:6]}.com', status='assigned')
        db.session.add(dom)
        db.session.flush()
        site.domain_id = dom.id
        db.session.flush()

        output_dir = tempfile.mkdtemp()
        upload_dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(upload_dir, 'logos'), exist_ok=True)

        try:
            version_dir = build_site(site, output_dir, upload_dir)
            with open(os.path.join(version_dir, 'index.html'), 'r', encoding='utf-8') as f:
                html = f.read()

            nav_section = html.split('<nav')[1].split('</nav>')[0]
            assert 'nav-dropdown' not in nav_section
        finally:
            shutil.rmtree(output_dir)
            shutil.rmtree(upload_dir)
