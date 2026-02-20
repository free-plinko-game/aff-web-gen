"""Tests for Add Page enhancements: Bulk CSV Upload and AI Suggestions."""

import io
import json
import uuid
from unittest.mock import patch

import pytest

from app.models import (
    db as _db, Site, SitePage, SiteBrand, Brand, BrandGeo, BrandVertical,
    Geo, Vertical, PageType,
)


# --- Fixtures ---

@pytest.fixture
def site_with_brands(db):
    """Create a site with 2 brands assigned, no pages."""
    uid = uuid.uuid4().hex[:8]
    geo = Geo.query.filter_by(code='au').first()
    vertical = Vertical.query.filter_by(slug='sports-betting').first()

    brands = []
    for i, (name, slug) in enumerate([
        ('BulkBrandA', f'bulk-a-{uid}'),
        ('BulkBrandB', f'bulk-b-{uid}'),
    ]):
        b = Brand(name=name, slug=slug, rating=4.5 - i * 0.5)
        db.session.add(b)
        db.session.flush()
        db.session.add(BrandGeo(brand_id=b.id, geo_id=geo.id,
                                welcome_bonus=f'${50 - i*10} Free', is_active=True))
        db.session.add(BrandVertical(brand_id=b.id, vertical_id=vertical.id))
        brands.append(b)
    db.session.flush()

    site = Site(name=f'Bulk Test {uid}', geo_id=geo.id, vertical_id=vertical.id, status='draft')
    db.session.add(site)
    db.session.flush()

    for i, b in enumerate(brands):
        db.session.add(SiteBrand(site_id=site.id, brand_id=b.id, rank=i + 1))
    db.session.flush()

    return site, brands


# ============================================================
# Bulk CSV Upload
# ============================================================

class TestBulkCSVUpload:

    def test_upload_mixed_page_types(self, client, site_with_brands):
        site, brands = site_with_brands
        csv_content = (
            "page_type,brand_slug,evergreen_topic\n"
            "homepage,,\n"
            "comparison,,\n"
            f"brand-review,{brands[0].slug},\n"
            f"bonus-review,{brands[1].slug},\n"
            "evergreen,,How to Pick a Sportsbook\n"
        )
        data = {
            'csv_file': (io.BytesIO(csv_content.encode()), 'pages.csv'),
        }
        resp = client.post(
            f'/sites/{site.id}/bulk-add-pages',
            data=data,
            content_type='multipart/form-data',
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b'5 pages added' in resp.data

        pages = SitePage.query.filter_by(site_id=site.id).all()
        page_types = {p.page_type.slug for p in pages}
        assert 'homepage' in page_types
        assert 'comparison' in page_types
        assert 'brand-review' in page_types
        assert 'bonus-review' in page_types
        assert 'evergreen' in page_types

    def test_skip_duplicate_pages(self, client, site_with_brands, db):
        site, brands = site_with_brands

        # Pre-create a homepage
        pt = PageType.query.filter_by(slug='homepage').first()
        db.session.add(SitePage(site_id=site.id, page_type_id=pt.id,
                                slug='index', title='Homepage'))
        db.session.flush()

        csv_content = (
            "page_type,brand_slug,evergreen_topic\n"
            "homepage,,\n"
            "comparison,,\n"
        )
        data = {'csv_file': (io.BytesIO(csv_content.encode()), 'pages.csv')}
        resp = client.post(
            f'/sites/{site.id}/bulk-add-pages',
            data=data,
            content_type='multipart/form-data',
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b'1 pages added' in resp.data
        assert b'1 duplicates skipped' in resp.data

    def test_skip_brand_not_assigned(self, client, site_with_brands):
        site, brands = site_with_brands
        csv_content = (
            "page_type,brand_slug,evergreen_topic\n"
            "brand-review,nonexistent-brand-xyz,\n"
        )
        data = {'csv_file': (io.BytesIO(csv_content.encode()), 'pages.csv')}
        resp = client.post(
            f'/sites/{site.id}/bulk-add-pages',
            data=data,
            content_type='multipart/form-data',
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b'not assigned to site' in resp.data

    def test_invalid_page_type(self, client, site_with_brands):
        site, brands = site_with_brands
        csv_content = (
            "page_type,brand_slug,evergreen_topic\n"
            "invalid-type,,\n"
        )
        data = {'csv_file': (io.BytesIO(csv_content.encode()), 'pages.csv')}
        resp = client.post(
            f'/sites/{site.id}/bulk-add-pages',
            data=data,
            content_type='multipart/form-data',
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b'unknown page type' in resp.data

    def test_empty_csv(self, client, site_with_brands):
        site, brands = site_with_brands
        csv_content = "page_type,brand_slug,evergreen_topic\n"
        data = {'csv_file': (io.BytesIO(csv_content.encode()), 'pages.csv')}
        resp = client.post(
            f'/sites/{site.id}/bulk-add-pages',
            data=data,
            content_type='multipart/form-data',
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b'0 pages added' in resp.data

    def test_no_file_uploaded(self, client, site_with_brands):
        site, _ = site_with_brands
        resp = client.post(
            f'/sites/{site.id}/bulk-add-pages',
            data={},
            content_type='multipart/form-data',
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b'Please select a CSV file' in resp.data


class TestCSVTemplate:

    def test_download_csv_template(self, client, db):
        resp = client.get('/api/page-csv-template')
        assert resp.status_code == 200
        assert resp.content_type == 'text/csv; charset=utf-8'
        assert b'page_type,brand_slug,evergreen_topic' in resp.data
        assert b'homepage' in resp.data


# ============================================================
# AI Page Suggestions
# ============================================================

class TestAISuggestions:

    def test_gap_analysis_missing_pages(self, client, site_with_brands):
        """Should return missing homepage, comparison, and brand reviews."""
        site, brands = site_with_brands

        resp = client.post(f'/api/sites/{site.id}/suggest-pages')
        assert resp.status_code == 200
        data = resp.get_json()

        missing_types = [m['page_type'] for m in data['missing_pages']]
        assert 'homepage' in missing_types
        assert 'comparison' in missing_types
        # Both brands should have missing brand-review and bonus-review
        missing_brand_reviews = [
            m for m in data['missing_pages'] if m['page_type'] == 'brand-review'
        ]
        assert len(missing_brand_reviews) == 2

    def test_gap_analysis_with_existing_pages(self, client, site_with_brands, db):
        """Pages that already exist should NOT show up in missing_pages."""
        site, brands = site_with_brands

        # Create homepage + one brand review
        pt_home = PageType.query.filter_by(slug='homepage').first()
        pt_review = PageType.query.filter_by(slug='brand-review').first()
        db.session.add(SitePage(site_id=site.id, page_type_id=pt_home.id,
                                slug='index', title='Homepage'))
        db.session.add(SitePage(site_id=site.id, page_type_id=pt_review.id,
                                brand_id=brands[0].id, slug=brands[0].slug,
                                title=f'{brands[0].name} Review'))
        db.session.flush()

        resp = client.post(f'/api/sites/{site.id}/suggest-pages')
        data = resp.get_json()

        missing_types = [m['page_type'] for m in data['missing_pages']]
        assert 'homepage' not in missing_types
        # Only one brand-review missing (brands[1])
        brand_review_slugs = [
            m['brand_slug'] for m in data['missing_pages']
            if m['page_type'] == 'brand-review'
        ]
        assert brands[0].slug not in brand_review_slugs
        assert brands[1].slug in brand_review_slugs

    @patch('app.routes.api.call_openai')
    def test_ai_evergreen_suggestions(self, mock_openai, client, site_with_brands, app):
        """Should return AI-generated evergreen suggestions when API key is set."""
        site, _ = site_with_brands
        mock_openai.return_value = {
            'suggestions': [
                {'topic': 'Best Betting Apps in Australia', 'keyword': 'betting apps australia', 'reason': 'High search volume'},
                {'topic': 'How to Read Betting Odds', 'keyword': 'betting odds guide', 'reason': 'Evergreen beginner topic'},
            ]
        }

        app.config['OPENAI_API_KEY'] = 'test-key-123'
        try:
            resp = client.post(f'/api/sites/{site.id}/suggest-pages')
            data = resp.get_json()

            assert len(data['suggested_evergreen']) == 2
            assert data['suggested_evergreen'][0]['topic'] == 'Best Betting Apps in Australia'
            mock_openai.assert_called_once()
        finally:
            app.config.pop('OPENAI_API_KEY', None)

    def test_no_api_key_returns_gap_only(self, client, site_with_brands, app):
        """Without API key, should still return gap analysis but no AI suggestions."""
        site, _ = site_with_brands
        app.config.pop('OPENAI_API_KEY', None)

        resp = client.post(f'/api/sites/{site.id}/suggest-pages')
        data = resp.get_json()

        assert len(data['missing_pages']) > 0
        assert data['suggested_evergreen'] == []


class TestAddSuggestedPages:

    def test_add_pages_from_suggestions(self, client, site_with_brands):
        site, brands = site_with_brands
        payload = {
            'pages': [
                {'page_type': 'homepage', 'brand_slug': '', 'evergreen_topic': ''},
                {'page_type': 'brand-review', 'brand_slug': brands[0].slug, 'evergreen_topic': ''},
                {'page_type': 'evergreen', 'brand_slug': '', 'evergreen_topic': 'Guide to Sports Betting'},
            ]
        }
        resp = client.post(
            f'/sites/{site.id}/add-suggested-pages',
            data=json.dumps(payload),
            content_type='application/json',
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['added'] == 3
        assert data['skipped'] == 0

    def test_skip_duplicates_in_suggestions(self, client, site_with_brands, db):
        site, brands = site_with_brands

        # Pre-create homepage
        pt = PageType.query.filter_by(slug='homepage').first()
        db.session.add(SitePage(site_id=site.id, page_type_id=pt.id,
                                slug='index', title='Homepage'))
        db.session.flush()

        payload = {
            'pages': [
                {'page_type': 'homepage', 'brand_slug': '', 'evergreen_topic': ''},
                {'page_type': 'comparison', 'brand_slug': '', 'evergreen_topic': ''},
            ]
        }
        resp = client.post(
            f'/sites/{site.id}/add-suggested-pages',
            data=json.dumps(payload),
            content_type='application/json',
        )
        data = resp.get_json()
        assert data['added'] == 1
        assert data['skipped'] == 1
