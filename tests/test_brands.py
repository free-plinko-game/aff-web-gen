"""Phase 1 tests: Brand CRUD routes and GEO associations."""

import io
import os

from app.models import db as _db, Brand, BrandGeo, BrandVertical, Geo, Vertical


# --- 1.4 Brand CRUD Routes ---

class TestBrandCRUD:

    def test_brand_list_page(self, client):
        response = client.get('/brands/')
        assert response.status_code == 200

    def test_create_brand(self, client, db):
        data = {
            'name': 'Bet365',
            'slug': 'bet365',
            'website_url': 'https://bet365.com',
            'affiliate_link': 'https://aff.bet365.com/123',
            'description': 'Leading betting site',
            'founded_year': '2000',
            'rating': '4.5',
        }
        response = client.post('/brands/new', data=data, follow_redirects=True)
        assert response.status_code == 200
        brand = Brand.query.filter_by(slug='bet365').first()
        assert brand is not None
        assert brand.name == 'Bet365'
        assert brand.rating == 4.5

    def test_create_brand_duplicate_slug(self, client, db):
        # Create first
        data = {'name': 'Brand A', 'slug': 'dup-slug'}
        client.post('/brands/new', data=data)

        # Attempt duplicate
        data2 = {'name': 'Brand B', 'slug': 'dup-slug'}
        response = client.post('/brands/new', data=data2, follow_redirects=True)
        assert response.status_code == 200
        assert b'already exists' in response.data
        # Should still be only one brand with this slug
        assert Brand.query.filter_by(slug='dup-slug').count() == 1

    def test_create_brand_with_logo(self, client, db, app):
        data = {
            'name': 'LogoBrand',
            'slug': 'logobrand',
        }
        data['logo'] = (io.BytesIO(b'fake image data'), 'logo.png')
        response = client.post('/brands/new', data=data, content_type='multipart/form-data',
                               follow_redirects=True)
        assert response.status_code == 200
        brand = Brand.query.filter_by(slug='logobrand').first()
        assert brand is not None
        assert brand.logo_filename == 'logobrand.png'
        # Verify file exists
        logo_path = os.path.join(app.config['UPLOAD_FOLDER'], 'logos', 'logobrand.png')
        assert os.path.exists(logo_path)

    def test_edit_brand_page(self, client, db):
        brand = Brand(name='EditMe', slug='editme')
        db.session.add(brand)
        db.session.commit()

        response = client.get(f'/brands/{brand.id}/edit')
        assert response.status_code == 200
        assert b'EditMe' in response.data

    def test_edit_brand_submit(self, client, db):
        brand = Brand(name='OldName', slug='editsubmit')
        db.session.add(brand)
        db.session.commit()

        data = {
            'name': 'NewName',
            'website_url': 'https://new.com',
            'affiliate_link': '',
            'description': 'Updated',
            'founded_year': '',
            'rating': '',
        }
        response = client.post(f'/brands/{brand.id}/edit', data=data, follow_redirects=True)
        assert response.status_code == 200

        db.session.refresh(brand)
        assert brand.name == 'NewName'

    def test_delete_brand(self, client, db):
        brand = Brand(name='DeleteMe', slug='deleteme')
        db.session.add(brand)
        db.session.commit()
        brand_id = brand.id

        response = client.post(f'/brands/{brand_id}/delete', follow_redirects=True)
        assert response.status_code == 200
        assert _db.session.get(Brand, brand_id) is None


# --- 1.5 Brand-GEO Association ---

class TestBrandGeoAssociation:

    def test_create_brand_with_geo(self, client, db):
        geo = Geo.query.filter_by(code='gb').first()
        vertical = Vertical.query.filter_by(slug='sports-betting').first()

        data = {
            'name': 'GeoBrand',
            'slug': 'geobrand',
            f'geo_active_{geo.id}': '1',
            f'geo_bonus_{geo.id}': 'Bet £10 Get £30',
            f'geo_code_{geo.id}': 'WELCOME30',
            f'geo_license_{geo.id}': 'UKGC #12345',
            'vertical_ids': str(vertical.id),
        }
        response = client.post('/brands/new', data=data, follow_redirects=True)
        assert response.status_code == 200

        brand = Brand.query.filter_by(slug='geobrand').first()
        assert brand is not None

        bg = BrandGeo.query.filter_by(brand_id=brand.id, geo_id=geo.id).first()
        assert bg is not None
        assert bg.welcome_bonus == 'Bet £10 Get £30'
        assert bg.bonus_code == 'WELCOME30'
        assert bg.license_info == 'UKGC #12345'

        bv = BrandVertical.query.filter_by(brand_id=brand.id, vertical_id=vertical.id).first()
        assert bv is not None
