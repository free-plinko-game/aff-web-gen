"""Phase 6 tests — Polish & QA: flash messages, bulk import, content history, preview."""

import io
import json
import os
import uuid
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest

from app.models import (
    db as _db, Site, SitePage, Brand, BrandGeo, BrandVertical,
    Geo, Vertical, PageType, Domain, ContentHistory,
)
from app.services.content_generator import save_content_to_page


def _uid():
    return uuid.uuid4().hex[:8]


# ── 6.1  Flash Messages ────────────────────────────────────────

class TestFlashMessages:

    def test_brand_create_flash(self, app, db, client):
        """Creating a brand flashes 'Brand created successfully'."""
        uid = _uid()
        resp = client.post('/brands/new', data={
            'name': f'FlashBrand-{uid}',
            'slug': f'flashbrand-{uid}',
        }, follow_redirects=True)
        assert b'Brand created successfully' in resp.data

    def test_brand_duplicate_slug_flash(self, app, db, client):
        """Duplicate slug flashes error message."""
        uid = _uid()
        client.post('/brands/new', data={
            'name': f'Brand-{uid}', 'slug': f'dup-{uid}',
        })
        resp = client.post('/brands/new', data={
            'name': f'Brand2-{uid}', 'slug': f'dup-{uid}',
        }, follow_redirects=True)
        assert b'already exists' in resp.data

    @patch('app.routes.sites.deploy_site')
    def test_deploy_flash(self, mock_deploy, app, db, client):
        """Deploying a site flashes 'Site deployed successfully'."""
        uid = _uid()
        geo = Geo.query.filter_by(code='gb').first()
        vertical = Vertical.query.filter_by(slug='sports-betting').first()

        domain = Domain(domain=f'flash-{uid}.co.uk', status='assigned')
        db.session.add(domain)
        db.session.flush()

        site = Site(
            name=f'Flash Site {uid}', geo_id=geo.id, vertical_id=vertical.id,
            domain_id=domain.id, status='built', output_path='/tmp/fake',
        )
        db.session.add(site)
        db.session.flush()

        def fake_deploy(site_obj, config):
            site_obj.status = 'deployed'
            site_obj.deployed_at = datetime.now(timezone.utc)
            site_obj.domain.status = 'deployed'
            return '/var/www/sites/test/releases/v1'

        mock_deploy.side_effect = fake_deploy

        resp = client.post(f'/sites/{site.id}/deploy', follow_redirects=True)
        assert b'Site deployed successfully' in resp.data


# ── 6.2  Bulk Brand Import ─────────────────────────────────────

class TestBulkImport:

    def test_import_page_loads(self, app, db, client):
        """GET /brands/import returns 200."""
        resp = client.get('/brands/import')
        assert resp.status_code == 200
        assert b'Bulk Brand Import' in resp.data

    def test_import_5_brands(self, app, db, client):
        """Import a CSV with 5 brands: all created in DB."""
        uid = _uid()
        csv_content = "name,slug,website_url,affiliate_link,rating\n"
        for i in range(1, 6):
            csv_content += f"Import Brand {i}-{uid},import-{i}-{uid},https://example.com,,{3.0 + i * 0.3}\n"

        data = {
            'csv_file': (io.BytesIO(csv_content.encode('utf-8')), 'brands.csv'),
        }
        resp = client.post('/brands/import', data=data, content_type='multipart/form-data',
                           follow_redirects=True)

        assert b'5 brands imported' in resp.data

        for i in range(1, 6):
            brand = Brand.query.filter_by(slug=f'import-{i}-{uid}').first()
            assert brand is not None
            assert brand.name == f'Import Brand {i}-{uid}'

    def test_import_skips_duplicate_slug(self, app, db, client):
        """CSV with a duplicate slug: that row skipped, others imported."""
        uid = _uid()

        # Create an existing brand
        brand = Brand(name=f'Existing-{uid}', slug=f'existing-{uid}')
        db.session.add(brand)
        db.session.flush()

        csv_content = "name,slug,website_url,affiliate_link,rating\n"
        csv_content += f"Existing Dup,existing-{uid},,,\n"  # duplicate
        csv_content += f"New Brand A,newbrand-a-{uid},,,4.0\n"
        csv_content += f"New Brand B,newbrand-b-{uid},,,3.5\n"

        data = {
            'csv_file': (io.BytesIO(csv_content.encode('utf-8')), 'brands.csv'),
        }
        resp = client.post('/brands/import', data=data, content_type='multipart/form-data',
                           follow_redirects=True)

        assert b'2 brands imported' in resp.data
        assert b'1 skipped' in resp.data
        assert b'Skipped duplicate slug' in resp.data

        assert Brand.query.filter_by(slug=f'newbrand-a-{uid}').first() is not None
        assert Brand.query.filter_by(slug=f'newbrand-b-{uid}').first() is not None

    def test_import_no_file_flashes_error(self, app, db, client):
        """Import without selecting a file flashes error."""
        resp = client.post('/brands/import', data={}, follow_redirects=True)
        assert b'Please select a CSV file' in resp.data


# ── 6.3  Content History Viewer ─────────────────────────────────

class TestContentHistory:

    def _create_page_with_content(self, db, version_count=1):
        """Create a site with a page and generate content version_count times."""
        uid = _uid()
        geo = Geo.query.filter_by(code='gb').first()
        vertical = Vertical.query.filter_by(slug='sports-betting').first()

        site = Site(name=f'History Site {uid}', geo_id=geo.id, vertical_id=vertical.id, status='generated')
        db.session.add(site)
        db.session.flush()

        pt = PageType.query.filter_by(slug='homepage').first()
        page = SitePage(
            site_id=site.id, page_type_id=pt.id, slug='index', title='Home',
        )
        db.session.add(page)
        db.session.flush()

        for v in range(version_count):
            content = {'hero_title': f'Version {v + 1} content', 'version': v + 1}
            save_content_to_page(page, content, db.session)
            db.session.flush()

        return site, page

    def test_generate_3_times_creates_2_history_records(self, app, db):
        """Generate content 3 times: 2 history records (current is in page)."""
        site, page = self._create_page_with_content(db, version_count=3)

        history_count = ContentHistory.query.filter_by(site_page_id=page.id).count()
        assert history_count == 2  # versions 1 and 2 in history, version 3 is current

        current = json.loads(page.content_json)
        assert current['version'] == 3

    def test_history_page_loads(self, app, db, client):
        """GET content history page returns 200 with history entries."""
        site, page = self._create_page_with_content(db, version_count=3)

        resp = client.get(f'/sites/{site.id}/pages/{page.id}/history')
        assert resp.status_code == 200
        assert b'Version 1' in resp.data
        assert b'Version 2' in resp.data
        assert b'Current Version' in resp.data

    def test_restore_version(self, app, db, client):
        """Restore version 1: page.content_json matches version 1, new history created."""
        site, page = self._create_page_with_content(db, version_count=3)

        # Get version 1 history entry
        v1_entry = ContentHistory.query.filter_by(
            site_page_id=page.id, version=1
        ).first()
        assert v1_entry is not None

        v1_content = v1_entry.content_json

        resp = client.post(
            f'/sites/{site.id}/pages/{page.id}/restore/{v1_entry.id}',
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b'Content restored to version 1' in resp.data

        # Current content should now match version 1
        assert page.content_json == v1_content

        # A new history record should have been created for the replaced content (was version 3)
        history_count = ContentHistory.query.filter_by(site_page_id=page.id).count()
        assert history_count == 3  # v1, v2, + newly saved v3

    def test_history_empty_for_ungenerated_page(self, app, db, client):
        """History page for ungenerated page shows no records."""
        uid = _uid()
        geo = Geo.query.filter_by(code='gb').first()
        vertical = Vertical.query.filter_by(slug='sports-betting').first()

        site = Site(name=f'Empty Site {uid}', geo_id=geo.id, vertical_id=vertical.id, status='draft')
        db.session.add(site)
        db.session.flush()

        pt = PageType.query.filter_by(slug='homepage').first()
        page = SitePage(
            site_id=site.id, page_type_id=pt.id, slug='index', title='Home',
        )
        db.session.add(page)
        db.session.flush()

        resp = client.get(f'/sites/{site.id}/pages/{page.id}/history')
        assert resp.status_code == 200
        assert b'No previous versions found' in resp.data


# ── Site Preview ────────────────────────────────────────────────

class TestSitePreview:

    def test_preview_serves_built_site(self, app, db, client, tmp_path):
        """Preview route serves index.html from the built output."""
        uid = _uid()
        geo = Geo.query.filter_by(code='gb').first()
        vertical = Vertical.query.filter_by(slug='sports-betting').first()

        site = Site(name=f'Preview Site {uid}', geo_id=geo.id, vertical_id=vertical.id, status='built')
        db.session.add(site)
        db.session.flush()

        # Create output files
        output_dir = os.path.join(str(tmp_path), f'{site.id}_preview')
        os.makedirs(output_dir, exist_ok=True)
        with open(os.path.join(output_dir, 'index.html'), 'w') as f:
            f.write('<html><body>Preview Content</body></html>')

        site.output_path = output_dir
        db.session.flush()

        resp = client.get(f'/sites/{site.id}/preview/')
        assert resp.status_code == 200
        assert b'Preview Content' in resp.data

    def test_preview_serves_subpath(self, app, db, client, tmp_path):
        """Preview route serves files in subdirectories."""
        uid = _uid()
        geo = Geo.query.filter_by(code='gb').first()
        vertical = Vertical.query.filter_by(slug='sports-betting').first()

        site = Site(name=f'SubPreview {uid}', geo_id=geo.id, vertical_id=vertical.id, status='built')
        db.session.add(site)
        db.session.flush()

        output_dir = os.path.join(str(tmp_path), f'{site.id}_subpreview')
        reviews_dir = os.path.join(output_dir, 'reviews')
        os.makedirs(reviews_dir, exist_ok=True)
        with open(os.path.join(reviews_dir, 'test.html'), 'w') as f:
            f.write('<html><body>Review Page</body></html>')

        site.output_path = output_dir
        db.session.flush()

        resp = client.get(f'/sites/{site.id}/preview/reviews/test.html')
        assert resp.status_code == 200
        assert b'Review Page' in resp.data

    def test_preview_without_build_redirects(self, app, db, client):
        """Preview without output_path flashes error and redirects."""
        uid = _uid()
        geo = Geo.query.filter_by(code='gb').first()
        vertical = Vertical.query.filter_by(slug='sports-betting').first()

        site = Site(name=f'NoBuild {uid}', geo_id=geo.id, vertical_id=vertical.id, status='draft')
        db.session.add(site)
        db.session.flush()

        resp = client.get(f'/sites/{site.id}/preview/', follow_redirects=True)
        assert resp.status_code == 200
        assert b'must be built' in resp.data
