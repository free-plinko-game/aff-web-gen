"""Phase 8 tests: Content Editor & Advanced Features.

Tests for:
- 8.1 Structured Content Editor with Live Preview
- 8.2 Custom CTA Tables
- 8.3 Schema Markup / Structured Data
- 8.4 Brand Overrides per Site
- 8.5 Content Freshness Alerts
"""

import json
import os
import shutil
import tempfile
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

from app.models import (
    db as _db, Site, SitePage, SiteBrand, SiteBrandOverride, Brand, BrandGeo, BrandVertical,
    Geo, Vertical, PageType, Domain, ContentHistory, CTATable, CTATableRow,
)
from app.services.site_builder import build_site
from app.services.schema_generator import generate_schema
from app.services.preview_renderer import render_page_preview


# --- Fixture content data ---

HOMEPAGE_CONTENT = {
    'hero_title': 'Best Sites UK',
    'hero_subtitle': 'Compare the top options',
    'intro_paragraph': 'Welcome.',
    'top_brands': [{'name': 'P8BrandA', 'slug': 'p8-a', 'bonus': '£30 free',
                    'rating': 4.5, 'short_description': 'Great', 'selling_points': ['Fast']}],
    'why_trust_us': 'We are experts.',
    'faq': [{'question': 'Is it safe?', 'answer': 'Yes.'}],
    'closing_paragraph': 'Sign up today.',
}

COMPARISON_CONTENT = {
    'hero_title': 'Compare Sites',
    'hero_subtitle': 'Side by side',
    'intro_paragraph': 'Comparison.',
    'comparison_rows': [
        {'brand': 'P8BrandA', 'slug': 'p8-a', 'bonus': '£30', 'rating': 4.5,
         'pros': ['Good odds'], 'cons': ['Slow withdrawals'], 'verdict': 'Top pick'},
    ],
    'faq': [{'question': 'Which is best?', 'answer': 'BrandA.'}],
    'closing_paragraph': 'Choose wisely.',
}

BRAND_REVIEW_CONTENT = {
    'hero_title': 'P8BrandA Review',
    'hero_subtitle': 'Full review',
    'intro_paragraphs': ['Leading bookmaker.'],
    'intro_paragraph': 'Leading bookmaker.',
    'pros': ['Good odds'], 'cons': ['Slow withdrawals'],
    'features_sections': [{'heading': 'Markets', 'content': 'Wide range.'}],
    'features_review': 'Great features.',
    'user_experience': 'Easy.',
    'verdict': 'Recommended.',
    'faq': [{'question': 'Safe?', 'answer': 'Yes.'}],
}

BONUS_REVIEW_CONTENT = {
    'hero_title': 'P8BrandA Bonus Review',
    'hero_subtitle': 'Welcome offer details',
    'bonus_overview': {'offer': '£30 free', 'code': 'WELCOME', 'min_deposit': '£10',
                       'wagering_requirements': '5x', 'validity': '30 days'},
    'how_to_claim': ['Register', 'Deposit', 'Bet'],
    'terms_summary': 'Standard terms.',
    'pros': ['Generous'], 'cons': ['Wagering'],
    'similar_offers': 'Others available.',
    'verdict': 'Worth it.',
    'faq': [{'question': 'Code?', 'answer': 'WELCOME.'}],
}

EVERGREEN_CONTENT = {
    'hero_title': 'How to Bet',
    'hero_subtitle': 'Guide',
    'intro_paragraph': 'Intro.',
    'sections': [{'heading': 'Start', 'content': 'Choose a site.'}],
    'key_takeaways': ['Start small'],
    'faq': [{'question': 'Legal?', 'answer': 'Yes.'}],
    'closing_paragraph': 'Good luck.',
}


@pytest.fixture
def p8_site(db):
    """Create a site with 2 brands and full page set for Phase 8 testing."""
    uid = uuid.uuid4().hex[:8]
    geo = Geo.query.filter_by(code='gb').first()
    vertical = Vertical.query.filter_by(slug='sports-betting').first()

    brands = []
    for i, (name, slug) in enumerate([('P8BrandA', f'p8-a-{uid}'), ('P8BrandB', f'p8-b-{uid}')]):
        b = Brand(name=name, slug=slug, rating=4.5 - i * 0.5,
                  affiliate_link=f'https://aff.{slug}.com',
                  website_url=f'https://{slug}.com',
                  logo_filename=f'{slug}.png' if i == 0 else None,
                  founded_year=2010 + i, parent_company=f'{name} Ltd',
                  support_methods='Live Chat, Email', support_email=f'help@{slug}.com',
                  available_languages='English', has_ios_app=True, has_android_app=(i == 0))
        db.session.add(b)
        db.session.flush()
        db.session.add(BrandGeo(brand_id=b.id, geo_id=geo.id,
                                welcome_bonus=f'£{30 - i*10} free', bonus_code='WELCOME',
                                is_active=True, license_info='UKGC #99999',
                                payment_methods='Visa, PayPal',
                                withdrawal_timeframe='1-3 days',
                                rating_bonus=4.5, rating_usability=4.0,
                                rating_mobile_app=3.5, rating_payments=4.2,
                                rating_support=3.8, rating_licensing=5.0, rating_rewards=4.1))
        db.session.add(BrandVertical(brand_id=b.id, vertical_id=vertical.id))
        brands.append(b)
    db.session.flush()

    site = Site(name=f'Phase8 Test {uid}', geo_id=geo.id, vertical_id=vertical.id, status='generated')
    db.session.add(site)
    db.session.flush()

    for i, b in enumerate(brands):
        db.session.add(SiteBrand(site_id=site.id, brand_id=b.id, rank=i + 1))
    db.session.flush()

    now = datetime.now(timezone.utc)
    pt_home = PageType.query.filter_by(slug='homepage').first()
    pt_comp = PageType.query.filter_by(slug='comparison').first()
    pt_review = PageType.query.filter_by(slug='brand-review').first()
    pt_bonus = PageType.query.filter_by(slug='bonus-review').first()
    pt_eg = PageType.query.filter_by(slug='evergreen').first()

    pages = {}
    pages['home'] = SitePage(
        site_id=site.id, page_type_id=pt_home.id, slug='index', title='Homepage',
        content_json=json.dumps(HOMEPAGE_CONTENT), is_generated=True, generated_at=now,
    )
    pages['comp'] = SitePage(
        site_id=site.id, page_type_id=pt_comp.id, slug='comparison', title='Compare',
        content_json=json.dumps(COMPARISON_CONTENT), is_generated=True, generated_at=now,
    )
    pages['review'] = SitePage(
        site_id=site.id, page_type_id=pt_review.id, brand_id=brands[0].id,
        slug=brands[0].slug, title=f'{brands[0].name} Review',
        content_json=json.dumps(BRAND_REVIEW_CONTENT), is_generated=True, generated_at=now,
    )
    pages['bonus'] = SitePage(
        site_id=site.id, page_type_id=pt_bonus.id, brand_id=brands[0].id,
        slug=brands[0].slug, title=f'{brands[0].name} Bonus Review',
        content_json=json.dumps(BONUS_REVIEW_CONTENT), is_generated=True, generated_at=now,
    )
    pages['evergreen'] = SitePage(
        site_id=site.id, page_type_id=pt_eg.id, evergreen_topic='How to Bet',
        slug='how-to-bet', title='How to Bet',
        content_json=json.dumps(EVERGREEN_CONTENT), is_generated=True, generated_at=now,
    )
    for p in pages.values():
        db.session.add(p)
    db.session.flush()

    return {'site': site, 'brands': brands, 'pages': pages, 'uid': uid, 'geo': geo, 'vertical': vertical}


# ===========================================================================
# 8.1 — Structured Content Editor with Live Preview
# ===========================================================================

class TestEditPageNewFields:
    """Test new fields on the edit page: meta_title, custom_head, cta_table, content_json editing."""

    def test_edit_page_shows_meta_title(self, client, p8_site):
        site = p8_site['site']
        page = p8_site['pages']['home']
        resp = client.get(f'/sites/{site.id}/pages/{page.id}/edit')
        assert resp.status_code == 200
        assert b'meta_title' in resp.data
        assert b'Meta Title' in resp.data

    def test_edit_page_shows_custom_head(self, client, p8_site):
        site = p8_site['site']
        page = p8_site['pages']['home']
        resp = client.get(f'/sites/{site.id}/pages/{page.id}/edit')
        assert b'custom_head' in resp.data

    def test_edit_page_shows_cta_table_selector(self, client, p8_site, db):
        site = p8_site['site']
        page = p8_site['pages']['home']
        # Create a CTA table
        ct = CTATable(site_id=site.id, name='Test Table', slug='test-table')
        db.session.add(ct)
        db.session.flush()
        resp = client.get(f'/sites/{site.id}/pages/{page.id}/edit')
        assert b'Test Table' in resp.data
        assert b'cta_table_id' in resp.data

    def test_save_meta_title(self, client, p8_site, db):
        site = p8_site['site']
        page = p8_site['pages']['home']
        resp = client.post(f'/sites/{site.id}/pages/{page.id}/edit', data={
            'action': 'save',
            'title': page.title,
            'slug': page.slug,
            'meta_title': 'Custom SEO Title',
            'meta_description': '',
            'custom_head': '',
            'regeneration_notes': '',
            'content_json': page.content_json,
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(page)
        assert page.meta_title == 'Custom SEO Title'

    def test_save_custom_head(self, client, p8_site, db):
        site = p8_site['site']
        page = p8_site['pages']['home']
        resp = client.post(f'/sites/{site.id}/pages/{page.id}/edit', data={
            'action': 'save',
            'title': page.title,
            'slug': page.slug,
            'meta_title': '',
            'meta_description': '',
            'custom_head': '<script>analytics()</script>',
            'regeneration_notes': '',
            'content_json': page.content_json,
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(page)
        assert page.custom_head == '<script>analytics()</script>'

    def test_save_cta_table_assignment(self, client, p8_site, db):
        site = p8_site['site']
        page = p8_site['pages']['home']
        ct = CTATable(site_id=site.id, name='CTA1', slug='cta1')
        db.session.add(ct)
        db.session.flush()
        resp = client.post(f'/sites/{site.id}/pages/{page.id}/edit', data={
            'action': 'save',
            'title': page.title,
            'slug': page.slug,
            'meta_title': '',
            'meta_description': '',
            'custom_head': '',
            'regeneration_notes': '',
            'content_json': page.content_json,
            'cta_table_id': str(ct.id),
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(page)
        assert page.cta_table_id == ct.id

    def test_edit_content_json(self, client, p8_site, db):
        site = p8_site['site']
        page = p8_site['pages']['home']
        new_content = json.dumps({'hero_title': 'Updated Title'})
        resp = client.post(f'/sites/{site.id}/pages/{page.id}/edit', data={
            'action': 'save',
            'title': page.title,
            'slug': page.slug,
            'meta_title': '',
            'meta_description': '',
            'custom_head': '',
            'regeneration_notes': '',
            'content_json': new_content,
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(page)
        assert json.loads(page.content_json)['hero_title'] == 'Updated Title'

    def test_invalid_json_rejected(self, client, p8_site, db):
        site = p8_site['site']
        page = p8_site['pages']['home']
        original = page.content_json
        resp = client.post(f'/sites/{site.id}/pages/{page.id}/edit', data={
            'action': 'save',
            'title': page.title,
            'slug': page.slug,
            'meta_title': '',
            'meta_description': '',
            'custom_head': '',
            'regeneration_notes': '',
            'content_json': '{bad json',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'Invalid JSON' in resp.data
        db.session.refresh(page)
        # Content should not have been updated
        assert page.content_json == original

    def test_edit_page_shows_preview_iframe(self, client, p8_site):
        site = p8_site['site']
        page = p8_site['pages']['home']
        resp = client.get(f'/sites/{site.id}/pages/{page.id}/edit')
        assert b'previewFrame' in resp.data
        assert b'Live Preview' in resp.data

    def test_edit_page_shows_content_editor(self, client, p8_site):
        site = p8_site['site']
        page = p8_site['pages']['home']
        resp = client.get(f'/sites/{site.id}/pages/{page.id}/edit')
        assert b'contentEditor' in resp.data
        assert b'hero_title' in resp.data  # Content JSON should be visible


class TestPreviewAPI:
    """Test the page preview API endpoint."""

    def test_preview_returns_html(self, client, p8_site):
        site = p8_site['site']
        page = p8_site['pages']['home']
        resp = client.get(f'/api/sites/{site.id}/pages/{page.id}/preview')
        assert resp.status_code == 200
        assert resp.content_type.startswith('text/html')
        assert b'Best Sites UK' in resp.data

    def test_preview_brand_review(self, client, p8_site):
        site = p8_site['site']
        page = p8_site['pages']['review']
        resp = client.get(f'/api/sites/{site.id}/pages/{page.id}/preview')
        assert resp.status_code == 200
        assert b'Review' in resp.data

    def test_preview_wrong_page_404(self, client, p8_site):
        site = p8_site['site']
        resp = client.get(f'/api/sites/{site.id}/pages/99999/preview')
        assert resp.status_code == 404

    def test_preview_wrong_site_404(self, client, p8_site):
        page = p8_site['pages']['home']
        resp = client.get(f'/api/sites/99999/pages/{page.id}/preview')
        assert resp.status_code == 404

    def test_preview_contains_asset_links(self, client, p8_site):
        site = p8_site['site']
        page = p8_site['pages']['home']
        resp = client.get(f'/api/sites/{site.id}/pages/{page.id}/preview')
        # Should reference the preview-assets endpoint
        assert b'/api/sites/' in resp.data
        assert b'preview-assets' in resp.data

    def test_preview_page_no_content(self, client, p8_site, db):
        """Preview should still work for pages without content (empty content)."""
        site = p8_site['site']
        page = p8_site['pages']['home']
        page.content_json = None
        db.session.flush()
        resp = client.get(f'/api/sites/{site.id}/pages/{page.id}/preview')
        assert resp.status_code == 200


class TestPreviewAssets:
    """Test the asset-serving route for preview iframe."""

    def test_serve_css(self, client, p8_site):
        site = p8_site['site']
        resp = client.get(f'/api/sites/{site.id}/preview-assets/css/style.css')
        assert resp.status_code == 200

    def test_serve_js(self, client, p8_site):
        site = p8_site['site']
        resp = client.get(f'/api/sites/{site.id}/preview-assets/js/main.js')
        assert resp.status_code == 200

    def test_serve_nonexistent_404(self, client, p8_site):
        site = p8_site['site']
        resp = client.get(f'/api/sites/{site.id}/preview-assets/nonexistent.xyz')
        assert resp.status_code == 404


class TestPreviewRenderer:
    """Test the preview_renderer.py service directly."""

    def test_render_homepage(self, app, p8_site):
        site = p8_site['site']
        page = p8_site['pages']['home']
        html = render_page_preview(page, site, asset_url_prefix='/preview/')
        assert 'Best Sites UK' in html
        assert '/preview/' in html  # Asset prefix used

    def test_render_brand_review(self, app, p8_site):
        site = p8_site['site']
        page = p8_site['pages']['review']
        html = render_page_preview(page, site)
        assert 'Review' in html

    def test_render_comparison(self, app, p8_site):
        site = p8_site['site']
        page = p8_site['pages']['comp']
        html = render_page_preview(page, site)
        assert 'Compare' in html

    def test_render_evergreen(self, app, p8_site):
        site = p8_site['site']
        page = p8_site['pages']['evergreen']
        html = render_page_preview(page, site)
        assert 'How to Bet' in html

    def test_render_bonus_review(self, app, p8_site):
        site = p8_site['site']
        page = p8_site['pages']['bonus']
        html = render_page_preview(page, site)
        assert 'Bonus' in html

    def test_custom_head_in_preview(self, app, p8_site, db):
        site = p8_site['site']
        page = p8_site['pages']['home']
        page.custom_head = '<meta name="test" content="phase8">'
        db.session.flush()
        html = render_page_preview(page, site)
        assert '<meta name="test" content="phase8">' in html

    def test_meta_title_in_preview(self, app, p8_site, db):
        site = p8_site['site']
        page = p8_site['pages']['home']
        page.meta_title = 'SEO Custom Title'
        db.session.flush()
        html = render_page_preview(page, site)
        assert '<title>SEO Custom Title</title>' in html


# ===========================================================================
# 8.2 — Custom CTA Tables
# ===========================================================================

class TestCTATableCRUD:
    """Test CTA table creation, editing, deletion."""

    def test_cta_table_list_loads(self, client, p8_site):
        site = p8_site['site']
        resp = client.get(f'/sites/{site.id}/cta-tables')
        assert resp.status_code == 200
        assert b'CTA Tables' in resp.data

    def test_create_cta_table(self, client, p8_site, db):
        site = p8_site['site']
        brands = p8_site['brands']
        resp = client.post(f'/sites/{site.id}/cta-tables/create', data={
            'name': 'Top Picks P8',
            'row_brand_ids': [str(brands[0].id), str(brands[1].id)],
            f'row_{brands[0].id}_bonus': '£30 Free Bet',
            f'row_{brands[0].id}_cta': 'Claim Now',
            f'row_{brands[0].id}_badge': "Editor's Pick",
            f'row_{brands[0].id}_visible': 'on',
            f'row_{brands[1].id}_visible': 'on',
        }, follow_redirects=True)
        assert resp.status_code == 200
        table = CTATable.query.filter_by(site_id=site.id, slug='top-picks-p8').first()
        assert table is not None
        assert len(table.rows) == 2
        assert table.rows[0].custom_bonus_text == '£30 Free Bet'
        assert table.rows[0].custom_badge == "Editor's Pick"

    def test_create_cta_duplicate_slug_rejected(self, client, p8_site, db):
        site = p8_site['site']
        ct = CTATable(site_id=site.id, name='Dup Test', slug='dup-test')
        db.session.add(ct)
        db.session.flush()
        resp = client.post(f'/sites/{site.id}/cta-tables/create', data={
            'name': 'Dup Test',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'already exists' in resp.data

    def test_edit_cta_table(self, client, p8_site, db):
        site = p8_site['site']
        brands = p8_site['brands']
        ct = CTATable(site_id=site.id, name='Edit Me', slug='edit-me')
        db.session.add(ct)
        db.session.flush()
        row = CTATableRow(cta_table_id=ct.id, brand_id=brands[0].id, rank=1, is_visible=True)
        db.session.add(row)
        db.session.flush()

        resp = client.post(f'/sites/{site.id}/cta-tables/{ct.id}/edit', data={
            'name': 'Edited Name',
            'row_brand_ids': [str(brands[1].id)],
            f'row_{brands[1].id}_visible': 'on',
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(ct)
        assert ct.name == 'Edited Name'

    def test_delete_cta_table(self, client, p8_site, db):
        site = p8_site['site']
        ct = CTATable(site_id=site.id, name='Delete Me', slug='delete-me')
        db.session.add(ct)
        db.session.flush()
        ct_id = ct.id
        resp = client.post(f'/sites/{site.id}/cta-tables/{ct_id}/delete', follow_redirects=True)
        assert resp.status_code == 200
        assert db.session.get(CTATable, ct_id) is None

    def test_delete_cta_table_clears_page_fk(self, client, p8_site, db):
        site = p8_site['site']
        page = p8_site['pages']['home']
        ct = CTATable(site_id=site.id, name='FK Test', slug='fk-test')
        db.session.add(ct)
        db.session.flush()
        page.cta_table_id = ct.id
        db.session.flush()
        ct_id = ct.id
        resp = client.post(f'/sites/{site.id}/cta-tables/{ct_id}/delete', follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(page)
        assert page.cta_table_id is None

    def test_cta_table_wrong_site_404(self, client, p8_site, db):
        site = p8_site['site']
        ct = CTATable(site_id=site.id, name='Wrong', slug='wrong')
        db.session.add(ct)
        db.session.flush()
        resp = client.post(f'/sites/99999/cta-tables/{ct.id}/delete')
        assert resp.status_code == 404


class TestCTATableInBuild:
    """Test that CTA tables are rendered in built HTML."""

    def test_cta_table_rendered_in_build(self, app, p8_site, db):
        site = p8_site['site']
        brands = p8_site['brands']
        page = p8_site['pages']['home']

        ct = CTATable(site_id=site.id, name='Build Test', slug='build-test')
        db.session.add(ct)
        db.session.flush()
        row = CTATableRow(cta_table_id=ct.id, brand_id=brands[0].id, rank=1,
                          custom_bonus_text='50 Free Spins', custom_cta_text='Get Bonus',
                          is_visible=True)
        db.session.add(row)
        page.cta_table_id = ct.id
        db.session.flush()

        output_dir = tempfile.mkdtemp()
        try:
            version_dir = build_site(site, output_dir, app.config['UPLOAD_FOLDER'])
            with open(os.path.join(version_dir, 'index.html'), 'r', encoding='utf-8') as f:
                html = f.read()
            assert '50 Free Spins' in html
            assert 'Get Bonus' in html
        finally:
            shutil.rmtree(output_dir, ignore_errors=True)


# ===========================================================================
# 8.3 — Schema Markup / Structured Data
# ===========================================================================

class TestSchemaGenerator:
    """Test JSON-LD schema generation for each page type."""

    def test_homepage_schema(self):
        result = generate_schema(
            'homepage', HOMEPAGE_CONTENT, 'Homepage', 'TestSite', 'test.com', '/index.html')
        assert 'WebSite' in result
        assert 'FAQPage' in result
        assert 'application/ld+json' in result

    def test_brand_review_schema(self):
        brand_info = {'name': 'BrandA', 'website_url': 'https://branda.com', 'rating': 4.5}
        result = generate_schema(
            'brand-review', BRAND_REVIEW_CONTENT, 'BrandA Review', 'TestSite',
            'test.com', '/reviews/branda.html', brand_info=brand_info, rating=4.5)
        assert 'Review' in result
        assert 'ratingValue' in result
        assert '4.5' in result
        assert 'FAQPage' in result

    def test_bonus_review_schema(self):
        result = generate_schema(
            'bonus-review', BONUS_REVIEW_CONTENT, 'Bonus Review', 'TestSite',
            'test.com', '/bonuses/branda.html', rating=4.0)
        assert 'Review' in result

    def test_comparison_schema(self):
        result = generate_schema(
            'comparison', COMPARISON_CONTENT, 'Compare', 'TestSite',
            'test.com', '/comparison.html')
        assert 'ItemList' in result
        assert 'P8BrandA' in result

    def test_evergreen_schema(self):
        result = generate_schema(
            'evergreen', EVERGREEN_CONTENT, 'How to Bet', 'TestSite',
            'test.com', '/how-to-bet.html')
        assert 'Article' in result
        assert 'FAQPage' in result

    def test_no_faq_skips_faq_schema(self):
        content = {'hero_title': 'No FAQ'}
        result = generate_schema(
            'homepage', content, 'No FAQ', 'TestSite', 'test.com', '/index.html')
        assert 'FAQPage' not in result
        assert 'WebSite' in result

    def test_schema_in_built_html(self, app, p8_site, db):
        site = p8_site['site']
        output_dir = tempfile.mkdtemp()
        try:
            version_dir = build_site(site, output_dir, app.config['UPLOAD_FOLDER'])
            with open(os.path.join(version_dir, 'index.html'), 'r', encoding='utf-8') as f:
                html = f.read()
            assert 'application/ld+json' in html
            assert 'WebSite' in html
        finally:
            shutil.rmtree(output_dir, ignore_errors=True)


# ===========================================================================
# 8.4 — Brand Overrides per Site
# ===========================================================================

class TestBrandOverrides:
    """Test site-specific brand data overrides."""

    def test_overrides_page_loads(self, client, p8_site):
        site = p8_site['site']
        resp = client.get(f'/sites/{site.id}/brand-overrides')
        assert resp.status_code == 200
        assert b'Brand Overrides' in resp.data

    def test_save_override(self, client, p8_site, db):
        site = p8_site['site']
        sb = SiteBrand.query.filter_by(site_id=site.id).order_by(SiteBrand.rank).first()
        resp = client.post(f'/sites/{site.id}/brand-overrides', data={
            f'brand_{sb.id}_description': 'Custom description here',
            f'brand_{sb.id}_affiliate_link': 'https://custom-aff.com',
            f'brand_{sb.id}_welcome_bonus': '£100 Free',
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(sb)
        assert sb.override is not None
        assert sb.override.custom_description == 'Custom description here'
        assert sb.override.custom_affiliate_link == 'https://custom-aff.com'
        assert sb.override.custom_welcome_bonus == '£100 Free'

    def test_clear_override(self, client, p8_site, db):
        site = p8_site['site']
        sb = SiteBrand.query.filter_by(site_id=site.id).order_by(SiteBrand.rank).first()
        override = SiteBrandOverride(
            site_brand_id=sb.id, custom_description='Old desc')
        db.session.add(override)
        db.session.flush()

        # Submit with all fields empty
        resp = client.post(f'/sites/{site.id}/brand-overrides', data={
            f'brand_{sb.id}_description': '',
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(sb)
        assert sb.override is None

    def test_override_used_in_build(self, app, p8_site, db):
        site = p8_site['site']
        brands = p8_site['brands']
        sb = SiteBrand.query.filter_by(site_id=site.id, brand_id=brands[0].id).first()
        override = SiteBrandOverride(
            site_brand_id=sb.id,
            custom_affiliate_link='https://override-aff.com',
            custom_welcome_bonus='£999 Override Bonus',
        )
        db.session.add(override)
        db.session.flush()

        output_dir = tempfile.mkdtemp()
        try:
            version_dir = build_site(site, output_dir, app.config['UPLOAD_FOLDER'])
            with open(os.path.join(version_dir, 'index.html'), 'r', encoding='utf-8') as f:
                html = f.read()
            assert 'https://override-aff.com' in html
            assert '£999 Override Bonus' in html
        finally:
            shutil.rmtree(output_dir, ignore_errors=True)

    def test_override_in_preview(self, app, p8_site, db):
        site = p8_site['site']
        brands = p8_site['brands']
        sb = SiteBrand.query.filter_by(site_id=site.id, brand_id=brands[0].id).first()
        override = SiteBrandOverride(
            site_brand_id=sb.id,
            custom_affiliate_link='https://preview-override.com',
        )
        db.session.add(override)
        db.session.flush()

        page = p8_site['pages']['home']
        html = render_page_preview(page, site)
        assert 'https://preview-override.com' in html


class TestSiteBrandOverrideModel:
    """Test SiteBrandOverride model constraints."""

    def test_create_override(self, db, p8_site):
        sb = SiteBrand.query.filter_by(site_id=p8_site['site'].id).first()
        ov = SiteBrandOverride(
            site_brand_id=sb.id,
            custom_description='Test desc',
            custom_selling_points='["Point 1", "Point 2"]',
            custom_bonus_code='OVERRIDE',
            internal_notes='Internal only',
        )
        db.session.add(ov)
        db.session.flush()
        assert ov.id is not None
        assert ov.site_brand == sb

    def test_override_cascade_delete(self, db, p8_site):
        sb = SiteBrand.query.filter_by(site_id=p8_site['site'].id).first()
        ov = SiteBrandOverride(site_brand_id=sb.id, custom_description='Cascade test')
        db.session.add(ov)
        db.session.flush()
        ov_id = ov.id
        db.session.delete(sb)
        db.session.flush()
        assert db.session.get(SiteBrandOverride, ov_id) is None


# ===========================================================================
# 8.5 — Content Freshness Alerts
# ===========================================================================

class TestFreshnessAlerts:
    """Test freshness tracking and stale content alerts."""

    def test_fresh_page_badge(self, client, p8_site):
        site = p8_site['site']
        resp = client.get(f'/sites/{site.id}')
        assert resp.status_code == 200
        assert b'Fresh' in resp.data

    def test_stale_page_badge(self, client, p8_site, db):
        site = p8_site['site']
        page = p8_site['pages']['home']
        page.generated_at = datetime.now(timezone.utc) - timedelta(days=60)
        site.freshness_threshold_days = 30
        db.session.flush()
        resp = client.get(f'/sites/{site.id}')
        assert b'Stale' in resp.data

    def test_update_freshness_threshold(self, client, p8_site, db):
        site = p8_site['site']
        resp = client.post(f'/sites/{site.id}/update-freshness', data={
            'threshold': '45',
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(site)
        assert site.freshness_threshold_days == 45

    def test_invalid_threshold_rejected(self, client, p8_site, db):
        site = p8_site['site']
        old = site.freshness_threshold_days
        resp = client.post(f'/sites/{site.id}/update-freshness', data={
            'threshold': '999',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'Invalid' in resp.data

    def test_dashboard_stale_widget(self, client, p8_site, db):
        site = p8_site['site']
        page = p8_site['pages']['home']
        page.generated_at = datetime.now(timezone.utc) - timedelta(days=60)
        site.freshness_threshold_days = 30
        db.session.flush()
        resp = client.get('/')
        assert resp.status_code == 200
        assert b'Stale Content' in resp.data or b'stale' in resp.data.lower()


# ===========================================================================
# Phase 8 Schema Tests
# ===========================================================================

class TestPhase8Schema:
    """Verify all Phase 8 model columns exist."""

    def test_site_page_has_meta_title(self, db, p8_site):
        page = p8_site['pages']['home']
        page.meta_title = 'Test Meta Title'
        db.session.flush()
        db.session.refresh(page)
        assert page.meta_title == 'Test Meta Title'

    def test_site_page_has_custom_head(self, db, p8_site):
        page = p8_site['pages']['home']
        page.custom_head = '<link rel="canonical" href="...">'
        db.session.flush()
        db.session.refresh(page)
        assert page.custom_head == '<link rel="canonical" href="...">'

    def test_site_has_custom_head(self, db, p8_site):
        site = p8_site['site']
        site.custom_head = '<script>global()</script>'
        db.session.flush()
        db.session.refresh(site)
        assert site.custom_head == '<script>global()</script>'

    def test_site_page_has_cta_table_fk(self, db, p8_site):
        site = p8_site['site']
        page = p8_site['pages']['home']
        ct = CTATable(site_id=site.id, name='Schema Test', slug='schema-test')
        db.session.add(ct)
        db.session.flush()
        page.cta_table_id = ct.id
        db.session.flush()
        db.session.refresh(page)
        assert page.cta_table_id == ct.id
        assert page.cta_table.name == 'Schema Test'

    def test_site_has_freshness_threshold(self, db, p8_site):
        site = p8_site['site']
        site.freshness_threshold_days = 14
        db.session.flush()
        db.session.refresh(site)
        assert site.freshness_threshold_days == 14

    def test_cta_table_model(self, db, p8_site):
        site = p8_site['site']
        ct = CTATable(site_id=site.id, name='Model Test', slug='model-test')
        db.session.add(ct)
        db.session.flush()
        assert ct.id is not None
        assert ct.site_id == site.id

    def test_cta_table_row_model(self, db, p8_site):
        site = p8_site['site']
        brands = p8_site['brands']
        ct = CTATable(site_id=site.id, name='Row Test', slug='row-test')
        db.session.add(ct)
        db.session.flush()
        row = CTATableRow(cta_table_id=ct.id, brand_id=brands[0].id, rank=1,
                          custom_bonus_text='Free', custom_cta_text='Go',
                          custom_badge='Best', is_visible=True)
        db.session.add(row)
        db.session.flush()
        assert row.id is not None
        assert row.brand.name == brands[0].name

    def test_site_brand_override_model(self, db, p8_site):
        sb = SiteBrand.query.filter_by(site_id=p8_site['site'].id).first()
        ov = SiteBrandOverride(site_brand_id=sb.id, custom_description='Override test')
        db.session.add(ov)
        db.session.flush()
        assert ov.id is not None
        assert sb.override == ov


# ===========================================================================
# Build Integration: custom_head and meta_title in output
# ===========================================================================

class TestBuildCustomHeadMetaTitle:
    """Verify custom_head and meta_title appear in built HTML."""

    def test_meta_title_in_built_html(self, app, p8_site, db):
        site = p8_site['site']
        page = p8_site['pages']['home']
        page.meta_title = 'SEO Override Title'
        db.session.flush()

        output_dir = tempfile.mkdtemp()
        try:
            version_dir = build_site(site, output_dir, app.config['UPLOAD_FOLDER'])
            with open(os.path.join(version_dir, 'index.html'), 'r', encoding='utf-8') as f:
                html = f.read()
            assert '<title>SEO Override Title</title>' in html
        finally:
            shutil.rmtree(output_dir, ignore_errors=True)

    def test_custom_head_in_built_html(self, app, p8_site, db):
        site = p8_site['site']
        page = p8_site['pages']['home']
        page.custom_head = '<meta name="phase8" content="test">'
        db.session.flush()

        output_dir = tempfile.mkdtemp()
        try:
            version_dir = build_site(site, output_dir, app.config['UPLOAD_FOLDER'])
            with open(os.path.join(version_dir, 'index.html'), 'r', encoding='utf-8') as f:
                html = f.read()
            assert '<meta name="phase8" content="test">' in html
        finally:
            shutil.rmtree(output_dir, ignore_errors=True)

    def test_site_wide_custom_head(self, app, p8_site, db):
        site = p8_site['site']
        site.custom_head = '<script>sitewide()</script>'
        db.session.flush()

        output_dir = tempfile.mkdtemp()
        try:
            version_dir = build_site(site, output_dir, app.config['UPLOAD_FOLDER'])
            with open(os.path.join(version_dir, 'index.html'), 'r', encoding='utf-8') as f:
                html = f.read()
            assert '<script>sitewide()</script>' in html
        finally:
            shutil.rmtree(output_dir, ignore_errors=True)
