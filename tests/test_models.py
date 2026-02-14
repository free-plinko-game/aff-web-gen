"""Phase 1 tests: Seed data, unique constraints, model relationships."""

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import db as _db, Geo, Vertical, PageType, Brand, BrandGeo, BrandVertical, Domain


# --- 1.1 Seed Data Loaded ---

class TestSeedData:

    def test_all_geos_seeded(self, db):
        geos = Geo.query.all()
        assert len(geos) == 7

    def test_geo_codes_match(self, db):
        codes = {g.code for g in Geo.query.all()}
        assert codes == {'gb', 'de', 'br', 'ng', 'ca', 'in', 'au'}

    def test_all_verticals_seeded(self, db):
        verticals = Vertical.query.all()
        assert len(verticals) == 3

    def test_vertical_slugs_match(self, db):
        slugs = {v.slug for v in Vertical.query.all()}
        assert slugs == {'sports-betting', 'casino', 'esports-betting'}

    def test_all_page_types_seeded(self, db):
        page_types = PageType.query.all()
        assert len(page_types) == 5

    def test_page_type_slugs_match(self, db):
        slugs = {pt.slug for pt in PageType.query.all()}
        assert slugs == {'homepage', 'comparison', 'brand-review', 'bonus-review', 'evergreen'}


# --- 1.2 Unique Constraints ---

class TestUniqueConstraints:

    def test_brand_slug_unique(self, db):
        b1 = Brand(name='UniqueTest', slug='unique-constraint-test')
        db.session.add(b1)
        db.session.flush()

        b2 = Brand(name='UniqueTest Dup', slug='unique-constraint-test')
        db.session.add(b2)
        with pytest.raises(IntegrityError):
            db.session.flush()

    def test_domain_unique(self, db):
        d1 = Domain(domain='unique-constraint-test.co.uk')
        db.session.add(d1)
        db.session.flush()

        d2 = Domain(domain='unique-constraint-test.co.uk')
        db.session.add(d2)
        with pytest.raises(IntegrityError):
            db.session.flush()

    def test_brand_geo_unique(self, db):
        brand = Brand(name='TestBrand', slug='testbrand-bg')
        db.session.add(brand)
        db.session.flush()
        geo = Geo.query.filter_by(code='gb').first()

        bg1 = BrandGeo(brand_id=brand.id, geo_id=geo.id, welcome_bonus='Test')
        db.session.add(bg1)
        db.session.flush()

        bg2 = BrandGeo(brand_id=brand.id, geo_id=geo.id, welcome_bonus='Duplicate')
        db.session.add(bg2)
        with pytest.raises(IntegrityError):
            db.session.flush()

    def test_brand_vertical_unique(self, db):
        brand = Brand(name='TestBrand', slug='testbrand-bv')
        db.session.add(brand)
        db.session.flush()
        vertical = Vertical.query.filter_by(slug='sports-betting').first()

        bv1 = BrandVertical(brand_id=brand.id, vertical_id=vertical.id)
        db.session.add(bv1)
        db.session.flush()

        bv2 = BrandVertical(brand_id=brand.id, vertical_id=vertical.id)
        db.session.add(bv2)
        with pytest.raises(IntegrityError):
            db.session.flush()


# --- 1.3 Model Relationships ---

class TestModelRelationships:

    def test_brand_geos_relationship(self, db):
        brand = Brand(name='RelBrand', slug='relbrand-geo')
        db.session.add(brand)
        db.session.flush()

        gb = Geo.query.filter_by(code='gb').first()
        de = Geo.query.filter_by(code='de').first()

        db.session.add(BrandGeo(brand_id=brand.id, geo_id=gb.id))
        db.session.add(BrandGeo(brand_id=brand.id, geo_id=de.id))
        db.session.flush()

        assert len(brand.brand_geos) == 2

    def test_brand_verticals_relationship(self, db):
        brand = Brand(name='RelBrand', slug='relbrand-vert')
        db.session.add(brand)
        db.session.flush()

        sports = Vertical.query.filter_by(slug='sports-betting').first()
        casino = Vertical.query.filter_by(slug='casino').first()

        db.session.add(BrandVertical(brand_id=brand.id, vertical_id=sports.id))
        db.session.add(BrandVertical(brand_id=brand.id, vertical_id=casino.id))
        db.session.flush()

        assert len(brand.brand_verticals) == 2

    def test_domain_default_status(self, db):
        domain = Domain(domain='test-default.com')
        db.session.add(domain)
        db.session.flush()
        assert domain.status == 'available'
