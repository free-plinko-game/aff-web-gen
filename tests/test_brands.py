"""Phase 1 tests: Brand CRUD routes and GEO associations."""

import io
import os
import uuid

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


class TestBrandNewFields:

    def test_create_brand_with_company_details(self, client, db):
        data = {
            'name': 'CompanyBrand',
            'slug': 'companybrand',
            'parent_company': 'Acme Corp',
            'support_methods': 'Live Chat, Email',
            'support_email': 'help@test.com',
            'available_languages': 'English, Spanish',
            'has_ios_app': '1',
            'has_android_app': '1',
        }
        response = client.post('/brands/new', data=data, follow_redirects=True)
        assert response.status_code == 200
        brand = Brand.query.filter_by(slug='companybrand').first()
        assert brand is not None
        assert brand.parent_company == 'Acme Corp'
        assert brand.support_methods == 'Live Chat, Email'
        assert brand.support_email == 'help@test.com'
        assert brand.available_languages == 'English, Spanish'
        assert brand.has_ios_app is True
        assert brand.has_android_app is True

    def test_create_brand_without_apps(self, client, db):
        data = {
            'name': 'NoAppBrand',
            'slug': 'noappbrand',
        }
        response = client.post('/brands/new', data=data, follow_redirects=True)
        assert response.status_code == 200
        brand = Brand.query.filter_by(slug='noappbrand').first()
        assert brand is not None
        assert brand.has_ios_app is False
        assert brand.has_android_app is False

    def test_create_brand_with_geo_ratings(self, client, db):
        geo = Geo.query.filter_by(code='gb').first()
        data = {
            'name': 'RatingBrand',
            'slug': 'ratingbrand',
            f'geo_active_{geo.id}': '1',
            f'geo_bonus_{geo.id}': '100% up to £50',
            f'geo_payment_methods_{geo.id}': 'Visa, PayPal',
            f'geo_withdrawal_timeframe_{geo.id}': '24 hours',
            f'geo_rating_bonus_{geo.id}': '4.5',
            f'geo_rating_usability_{geo.id}': '4.0',
            f'geo_rating_mobile_app_{geo.id}': '3.5',
            f'geo_rating_payments_{geo.id}': '4.2',
            f'geo_rating_support_{geo.id}': '3.8',
            f'geo_rating_licensing_{geo.id}': '5.0',
            f'geo_rating_rewards_{geo.id}': '4.1',
        }
        response = client.post('/brands/new', data=data, follow_redirects=True)
        assert response.status_code == 200

        brand = Brand.query.filter_by(slug='ratingbrand').first()
        assert brand is not None
        bg = BrandGeo.query.filter_by(brand_id=brand.id, geo_id=geo.id).first()
        assert bg is not None
        assert bg.payment_methods == 'Visa, PayPal'
        assert bg.withdrawal_timeframe == '24 hours'
        assert bg.rating_bonus == 4.5
        assert bg.rating_usability == 4.0
        assert bg.rating_mobile_app == 3.5
        assert bg.rating_payments == 4.2
        assert bg.rating_support == 3.8
        assert bg.rating_licensing == 5.0
        assert bg.rating_rewards == 4.1

    def test_edit_brand_company_details(self, client, db):
        brand = Brand(name='EditCompany', slug='editcompany')
        db.session.add(brand)
        db.session.commit()

        data = {
            'name': 'EditCompany',
            'website_url': '',
            'affiliate_link': '',
            'description': '',
            'founded_year': '',
            'rating': '',
            'parent_company': 'New Corp',
            'support_methods': 'Phone',
            'support_email': 'new@test.com',
            'available_languages': 'French',
            'has_ios_app': '1',
        }
        response = client.post(f'/brands/{brand.id}/edit', data=data, follow_redirects=True)
        assert response.status_code == 200

        db.session.refresh(brand)
        assert brand.parent_company == 'New Corp'
        assert brand.has_ios_app is True
        assert brand.has_android_app is False


class TestBulkDeleteBrands:

    def test_bulk_delete_multiple(self, client, db):
        uid = uuid.uuid4().hex[:8]
        brands = []
        for i in range(3):
            b = Brand(name=f'BulkDel{i}-{uid}', slug=f'bulkdel{i}-{uid}')
            db.session.add(b)
            db.session.flush()
            brands.append(b)

        resp = client.post('/brands/bulk-delete', data={
            'brand_ids': [str(b.id) for b in brands],
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'3 brands deleted' in resp.data
        for b in brands:
            assert _db.session.get(Brand, b.id) is None

    def test_bulk_delete_none_selected(self, client, db):
        resp = client.post('/brands/bulk-delete', data={}, follow_redirects=True)
        assert resp.status_code == 200
        assert b'No brands selected' in resp.data

    def test_bulk_delete_single(self, client, db):
        uid = uuid.uuid4().hex[:8]
        b = Brand(name=f'SingleDel-{uid}', slug=f'singledel-{uid}')
        db.session.add(b)
        db.session.flush()
        bid = b.id

        resp = client.post('/brands/bulk-delete', data={
            'brand_ids': str(bid),
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'1 brand deleted' in resp.data
        assert _db.session.get(Brand, bid) is None

    def test_bulk_delete_with_geos(self, client, db):
        """Bulk delete cascades to brand_geos."""
        uid = uuid.uuid4().hex[:8]
        geo = Geo.query.filter_by(code='gb').first()
        b = Brand(name=f'GeoDelB-{uid}', slug=f'geodelb-{uid}')
        db.session.add(b)
        db.session.flush()
        bg = BrandGeo(brand_id=b.id, geo_id=geo.id, is_active=True, welcome_bonus='Free')
        db.session.add(bg)
        db.session.flush()
        bid = b.id

        resp = client.post('/brands/bulk-delete', data={
            'brand_ids': str(bid),
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert _db.session.get(Brand, bid) is None
        assert BrandGeo.query.filter_by(brand_id=bid).count() == 0
