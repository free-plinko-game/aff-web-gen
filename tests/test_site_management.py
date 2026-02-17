"""Phase 7 tests: Site Management Hub.

Tests for add page, edit page, delete page, sitemap viewer,
robots.txt editor, rebuild awareness, and regeneration with notes.
"""

import json
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

from app.models import (
    db as _db, Site, SitePage, SiteBrand, Brand, BrandGeo, BrandVertical,
    Geo, Vertical, PageType, Domain, ContentHistory,
)


# --- Fixtures ---

@pytest.fixture
def site_with_brands(db):
    """Create a site with 2 brands assigned, no pages yet."""
    uid = uuid.uuid4().hex[:8]
    geo = Geo.query.filter_by(code='gb').first()
    vertical = Vertical.query.filter_by(slug='sports-betting').first()

    brands = []
    for i, (name, slug) in enumerate([('MgmtBrandA', f'mgmt-a-{uid}'), ('MgmtBrandB', f'mgmt-b-{uid}')]):
        b = Brand(name=name, slug=slug, rating=4.5 - i * 0.5,
                  affiliate_link=f'https://aff.{slug}.com')
        db.session.add(b)
        db.session.flush()
        db.session.add(BrandGeo(brand_id=b.id, geo_id=geo.id, welcome_bonus=f'£{30 - i*10} free',
                                is_active=True))
        db.session.add(BrandVertical(brand_id=b.id, vertical_id=vertical.id))
        brands.append(b)
    db.session.flush()

    site = Site(name=f'Mgmt Test {uid}', geo_id=geo.id, vertical_id=vertical.id, status='draft')
    db.session.add(site)
    db.session.flush()

    for i, b in enumerate(brands):
        db.session.add(SiteBrand(site_id=site.id, brand_id=b.id, rank=i + 1))
    db.session.flush()

    return site, brands


@pytest.fixture
def site_with_pages(site_with_brands, db):
    """Site with brands + a homepage and one brand review page (generated)."""
    site, brands = site_with_brands
    pt_home = PageType.query.filter_by(slug='homepage').first()
    pt_review = PageType.query.filter_by(slug='brand-review').first()
    now = datetime.now(timezone.utc)

    home = SitePage(
        site_id=site.id, page_type_id=pt_home.id,
        slug='index', title='Homepage',
        content_json='{"hero_title": "Welcome"}',
        is_generated=True, generated_at=now,
    )
    review = SitePage(
        site_id=site.id, page_type_id=pt_review.id,
        brand_id=brands[0].id, slug=brands[0].slug,
        title=f'{brands[0].name} Review',
        content_json='{"hero_title": "Review"}',
        is_generated=True, generated_at=now,
    )
    db.session.add_all([home, review])
    db.session.flush()

    site.status = 'generated'
    db.session.flush()

    return site, brands, home, review


# --- 7.1 Add New Pages ---

class TestAddPage:

    def test_add_page_form_loads(self, client, site_with_brands):
        site, brands = site_with_brands
        resp = client.get(f'/sites/{site.id}/add-page')
        assert resp.status_code == 200
        assert b'Add Page' in resp.data

    def test_add_evergreen_page(self, client, site_with_brands, db):
        site, brands = site_with_brands
        pt = PageType.query.filter_by(slug='evergreen').first()
        resp = client.post(f'/sites/{site.id}/add-page', data={
            'page_type': 'evergreen',
            'evergreen_topic': 'How to Bet on Tennis',
        }, follow_redirects=True)
        assert resp.status_code == 200
        page = SitePage.query.filter_by(
            site_id=site.id, page_type_id=pt.id, evergreen_topic='How to Bet on Tennis'
        ).first()
        assert page is not None
        assert page.slug == 'how-to-bet-on-tennis'
        assert page.is_generated is False

    def test_add_homepage(self, client, site_with_brands, db):
        site, brands = site_with_brands
        resp = client.post(f'/sites/{site.id}/add-page', data={
            'page_type': 'homepage',
        }, follow_redirects=True)
        assert resp.status_code == 200
        pt = PageType.query.filter_by(slug='homepage').first()
        page = SitePage.query.filter_by(site_id=site.id, page_type_id=pt.id).first()
        assert page is not None
        assert page.slug == 'index'

    def test_add_duplicate_homepage_rejected(self, client, site_with_pages, db):
        site, brands, home, review = site_with_pages
        resp = client.post(f'/sites/{site.id}/add-page', data={
            'page_type': 'homepage',
        }, follow_redirects=True)
        assert b'already has a Homepage' in resp.data

    def test_add_brand_review(self, client, site_with_brands, db):
        site, brands = site_with_brands
        resp = client.post(f'/sites/{site.id}/add-page', data={
            'page_type': 'brand-review',
            'brand_id': str(brands[0].id),
        }, follow_redirects=True)
        assert resp.status_code == 200
        pt = PageType.query.filter_by(slug='brand-review').first()
        page = SitePage.query.filter_by(
            site_id=site.id, page_type_id=pt.id, brand_id=brands[0].id
        ).first()
        assert page is not None
        assert page.slug == brands[0].slug

    def test_add_duplicate_brand_review_rejected(self, client, site_with_pages, db):
        site, brands, home, review = site_with_pages
        resp = client.post(f'/sites/{site.id}/add-page', data={
            'page_type': 'brand-review',
            'brand_id': str(brands[0].id),
        }, follow_redirects=True)
        assert b'already exists' in resp.data

    def test_add_brand_review_for_second_brand(self, client, site_with_pages, db):
        site, brands, home, review = site_with_pages
        resp = client.post(f'/sites/{site.id}/add-page', data={
            'page_type': 'brand-review',
            'brand_id': str(brands[1].id),
        }, follow_redirects=True)
        assert resp.status_code == 200
        pt = PageType.query.filter_by(slug='brand-review').first()
        page = SitePage.query.filter_by(
            site_id=site.id, page_type_id=pt.id, brand_id=brands[1].id
        ).first()
        assert page is not None

    def test_add_page_missing_topic_rejected(self, client, site_with_brands, db):
        site, brands = site_with_brands
        resp = client.post(f'/sites/{site.id}/add-page', data={
            'page_type': 'evergreen',
            'evergreen_topic': '',
        }, follow_redirects=True)
        assert b'enter a topic' in resp.data

    def test_add_bonus_review(self, client, site_with_brands, db):
        site, brands = site_with_brands
        resp = client.post(f'/sites/{site.id}/add-page', data={
            'page_type': 'bonus-review',
            'brand_id': str(brands[0].id),
        }, follow_redirects=True)
        assert resp.status_code == 200
        pt = PageType.query.filter_by(slug='bonus-review').first()
        page = SitePage.query.filter_by(
            site_id=site.id, page_type_id=pt.id, brand_id=brands[0].id
        ).first()
        assert page is not None


# --- 7.2 Edit Page ---

class TestEditPage:

    def test_edit_page_form_loads(self, client, site_with_pages):
        site, brands, home, review = site_with_pages
        resp = client.get(f'/sites/{site.id}/pages/{home.id}/edit')
        assert resp.status_code == 200
        assert b'Edit Page' in resp.data
        assert home.title.encode() in resp.data

    def test_save_page_updates_fields(self, client, site_with_pages, db):
        site, brands, home, review = site_with_pages
        resp = client.post(f'/sites/{site.id}/pages/{home.id}/edit', data={
            'title': 'Updated Homepage Title',
            'meta_description': 'A new meta description',
            'slug': 'index',
            'regeneration_notes': 'Focus on mobile experience',
            'action': 'save',
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(home)
        assert home.title == 'Updated Homepage Title'
        assert home.meta_description == 'A new meta description'
        assert home.regeneration_notes == 'Focus on mobile experience'

    @patch('app.services.content_generator._generate_single_page_background')
    def test_save_and_regenerate_starts_background(self, mock_bg, client, site_with_pages, db):
        site, brands, home, review = site_with_pages
        resp = client.post(f'/sites/{site.id}/pages/{home.id}/edit', data={
            'title': 'Homepage',
            'meta_description': '',
            'slug': 'index',
            'regeneration_notes': 'Add live streaming section',
            'action': 'save_and_regenerate',
        }, follow_redirects=True)
        assert resp.status_code == 200
        # The background thread should have been started
        # (we mock the inner function but start_single_page_generation launches a thread)

    def test_edit_wrong_site_404(self, client, site_with_pages, db):
        site, brands, home, review = site_with_pages
        resp = client.get(f'/sites/9999/pages/{home.id}/edit')
        assert resp.status_code == 404


# --- 7.2 Regeneration with Notes ---

class TestRegenerationNotes:

    def test_notes_appended_to_prompt(self, db, site_with_pages):
        """Verify generate_page_content_with_notes appends notes to the prompt."""
        from app.services.content_generator import generate_page_content_with_notes
        site, brands, home, review = site_with_pages
        home.regeneration_notes = 'Focus on mobile app'
        db.session.flush()

        with patch('app.services.content_generator.call_openai') as mock_api:
            mock_api.return_value = {'hero_title': 'Updated'}
            result, prompt = generate_page_content_with_notes(home, site, 'fake-key', 'gpt-4o-mini')

        assert 'Focus on mobile app' in prompt
        assert 'Additional instructions' in prompt
        mock_api.assert_called_once()

    def test_notes_archived_in_history(self, db, site_with_pages):
        """Verify save_content_to_page_with_notes archives notes in content_history."""
        from app.services.content_generator import save_content_to_page_with_notes
        site, brands, home, review = site_with_pages
        home.regeneration_notes = 'Target keyword: best UK sites'
        db.session.flush()

        save_content_to_page_with_notes(home, {'hero_title': 'New Content'}, db.session)
        db.session.flush()

        history = ContentHistory.query.filter_by(site_page_id=home.id).first()
        assert history is not None
        assert history.regeneration_notes == 'Target keyword: best UK sites'
        assert history.content_json == '{"hero_title": "Welcome"}'

    def test_notes_cleared_after_generation(self, db, site_with_pages):
        """Verify regeneration_notes are cleared from the page after generation."""
        from app.services.content_generator import save_content_to_page_with_notes
        site, brands, home, review = site_with_pages
        home.regeneration_notes = 'Some notes'
        db.session.flush()

        save_content_to_page_with_notes(home, {'hero_title': 'New'}, db.session)
        db.session.flush()

        assert home.regeneration_notes is None

    def test_notes_without_existing_content(self, db, site_with_brands):
        """Verify save works when page has no prior content (no history created)."""
        from app.services.content_generator import save_content_to_page_with_notes
        site, brands = site_with_brands
        pt = PageType.query.filter_by(slug='homepage').first()
        page = SitePage(
            site_id=site.id, page_type_id=pt.id,
            slug='index', title='Homepage',
        )
        db.session.add(page)
        db.session.flush()

        page.regeneration_notes = 'First generation'
        save_content_to_page_with_notes(page, {'hero_title': 'First'}, db.session)
        db.session.flush()

        # No history should be created since there was no previous content
        history = ContentHistory.query.filter_by(site_page_id=page.id).all()
        assert len(history) == 0
        assert page.is_generated is True
        assert page.regeneration_notes is None


# --- 7.3 Sitemap Viewer ---

class TestSitemapViewer:

    def test_detail_shows_page_urls(self, client, site_with_pages):
        site, brands, home, review = site_with_pages
        resp = client.get(f'/sites/{site.id}')
        assert resp.status_code == 200
        assert b'/index.html' in resp.data
        assert f'/reviews/{brands[0].slug}.html'.encode() in resp.data

    def test_detail_shows_page_count(self, client, site_with_pages):
        site, brands, home, review = site_with_pages
        resp = client.get(f'/sites/{site.id}')
        assert b'2 pages' in resp.data
        assert b'2 generated' in resp.data

    def test_detail_shows_full_urls_with_domain(self, client, site_with_pages, db):
        site, brands, home, review = site_with_pages
        domain = Domain(domain='testsite.co.uk', status='assigned')
        db.session.add(domain)
        db.session.flush()
        site.domain_id = domain.id
        db.session.flush()

        resp = client.get(f'/sites/{site.id}')
        assert b'https://testsite.co.uk/index.html' in resp.data

    def test_detail_shows_not_generated_badge(self, client, site_with_brands, db):
        site, brands = site_with_brands
        pt = PageType.query.filter_by(slug='homepage').first()
        page = SitePage(
            site_id=site.id, page_type_id=pt.id,
            slug='index', title='Homepage',
        )
        db.session.add(page)
        db.session.flush()

        resp = client.get(f'/sites/{site.id}')
        assert b'Not Generated' in resp.data


# --- 7.4 Robots.txt Editor ---

class TestRobotsTxtEditor:

    def test_robots_tab_shows_default(self, client, site_with_pages):
        site, brands, home, review = site_with_pages
        resp = client.get(f'/sites/{site.id}')
        assert b'robots.txt' in resp.data
        assert b'User-agent: *' in resp.data

    def test_save_custom_robots(self, client, site_with_pages, db):
        site, brands, home, review = site_with_pages
        resp = client.post(f'/api/sites/{site.id}/robots-txt',
                           json={'content': 'User-agent: *\nDisallow: /private/'},
                           content_type='application/json')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        db.session.refresh(site)
        assert site.custom_robots_txt == 'User-agent: *\nDisallow: /private/'

    def test_reset_robots_to_default(self, client, site_with_pages, db):
        site, brands, home, review = site_with_pages
        site.custom_robots_txt = 'custom content'
        db.session.flush()

        resp = client.post(f'/api/sites/{site.id}/robots-txt',
                           json={'content': None},
                           content_type='application/json')
        assert resp.status_code == 200
        db.session.refresh(site)
        assert site.custom_robots_txt is None

    def test_custom_robots_used_in_build(self, app, site_with_pages, db):
        """Verify site_builder uses custom_robots_txt when set."""
        import tempfile
        from app.services.site_builder import build_site
        site, brands, home, review = site_with_pages
        site.custom_robots_txt = 'User-agent: Googlebot\nDisallow: /bonuses/'
        db.session.flush()

        output_dir = tempfile.mkdtemp()
        upload_folder = app.config['UPLOAD_FOLDER']
        build_site(site, output_dir, upload_folder)

        import os
        robots_path = os.path.join(site.output_path, 'robots.txt')
        with open(robots_path) as f:
            content = f.read()
        assert 'Googlebot' in content
        assert 'Disallow: /bonuses/' in content


# --- 7.5 Rebuild Awareness ---

class TestRebuildAwareness:

    def test_no_banner_when_never_built(self, client, site_with_brands, db):
        """No rebuild banner when site has never been built and no generated pages."""
        site, brands = site_with_brands
        resp = client.get(f'/sites/{site.id}')
        assert b'Rebuild needed' not in resp.data

    def test_banner_when_generated_but_never_built(self, client, site_with_pages):
        """Show rebuild banner when pages are generated but site was never built."""
        site, brands, home, review = site_with_pages
        resp = client.get(f'/sites/{site.id}')
        assert b'Rebuild needed' in resp.data

    def test_no_banner_after_build(self, client, site_with_pages, db):
        """No banner when built_at is after all generated_at timestamps."""
        site, brands, home, review = site_with_pages
        site.built_at = datetime.now(timezone.utc) + timedelta(seconds=1)
        site.status = 'built'
        db.session.flush()

        resp = client.get(f'/sites/{site.id}')
        assert b'Rebuild needed' not in resp.data

    def test_banner_when_page_regenerated_after_build(self, client, site_with_pages, db):
        """Show banner when a page was regenerated after the last build."""
        site, brands, home, review = site_with_pages
        site.built_at = datetime.now(timezone.utc) - timedelta(hours=1)
        site.status = 'built'
        # Page was generated after the build
        home.generated_at = datetime.now(timezone.utc)
        db.session.flush()

        resp = client.get(f'/sites/{site.id}')
        assert b'Rebuild needed' in resp.data

    def test_banner_when_ungenerated_page_exists(self, client, site_with_pages, db):
        """Show banner when there are ungenerated pages (newly added)."""
        site, brands, home, review = site_with_pages
        site.built_at = datetime.now(timezone.utc) + timedelta(seconds=1)
        site.status = 'built'
        db.session.flush()

        # Add a new ungenerated page
        pt = PageType.query.filter_by(slug='evergreen').first()
        new_page = SitePage(
            site_id=site.id, page_type_id=pt.id,
            evergreen_topic='New Topic', slug='new-topic', title='New Topic',
        )
        db.session.add(new_page)
        db.session.flush()

        resp = client.get(f'/sites/{site.id}')
        assert b'Rebuild needed' in resp.data

    def test_built_at_set_on_build(self, app, site_with_pages, db):
        """Verify build_site sets site.built_at."""
        import tempfile
        from app.services.site_builder import build_site
        site, brands, home, review = site_with_pages
        assert site.built_at is None

        output_dir = tempfile.mkdtemp()
        upload_folder = app.config['UPLOAD_FOLDER']
        build_site(site, output_dir, upload_folder)

        assert site.built_at is not None
        assert site.status == 'built'


# --- Delete Page ---

class TestDeletePage:

    def test_delete_page(self, client, site_with_pages, db):
        site, brands, home, review = site_with_pages
        page_id = review.id
        resp = client.post(f'/sites/{site.id}/pages/{page_id}/delete', follow_redirects=True)
        assert resp.status_code == 200
        assert db.session.get(SitePage, page_id) is None

    def test_delete_page_wrong_site_404(self, client, site_with_pages):
        site, brands, home, review = site_with_pages
        resp = client.post(f'/sites/9999/pages/{review.id}/delete')
        assert resp.status_code == 404

    def test_delete_page_cascades_history(self, client, site_with_pages, db):
        """Deleting a page also deletes its content history."""
        site, brands, home, review = site_with_pages
        # Create a history entry for the page
        history = ContentHistory(
            site_page_id=home.id,
            content_json='{"old": "content"}',
            generated_at=datetime.now(timezone.utc),
            version=1,
        )
        db.session.add(history)
        db.session.flush()
        history_id = history.id

        resp = client.post(f'/sites/{site.id}/pages/{home.id}/delete', follow_redirects=True)
        assert resp.status_code == 200
        assert db.session.get(ContentHistory, history_id) is None


# --- Schema Tests ---

class TestPhase7Schema:

    def test_site_page_has_regeneration_notes(self, db, site_with_pages):
        site, brands, home, review = site_with_pages
        home.regeneration_notes = 'Test notes'
        db.session.flush()
        db.session.refresh(home)
        assert home.regeneration_notes == 'Test notes'

    def test_content_history_has_regeneration_notes(self, db, site_with_pages):
        site, brands, home, review = site_with_pages
        history = ContentHistory(
            site_page_id=home.id,
            content_json='{"test": true}',
            generated_at=datetime.now(timezone.utc),
            regeneration_notes='Used these notes',
            version=1,
        )
        db.session.add(history)
        db.session.flush()
        db.session.refresh(history)
        assert history.regeneration_notes == 'Used these notes'

    def test_site_has_built_at(self, db, site_with_brands):
        site, brands = site_with_brands
        now = datetime.now(timezone.utc)
        site.built_at = now
        db.session.flush()
        db.session.refresh(site)
        assert site.built_at is not None

    def test_site_has_custom_robots_txt(self, db, site_with_brands):
        site, brands = site_with_brands
        site.custom_robots_txt = 'User-agent: *\nDisallow: /'
        db.session.flush()
        db.session.refresh(site)
        assert site.custom_robots_txt == 'User-agent: *\nDisallow: /'
