"""Phase 2 tests: Site configuration wizard."""

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import (
    db as _db, Site, SiteBrand, SitePage, Brand, BrandGeo, BrandVertical,
    Geo, Vertical, PageType,
)


def _create_test_brand(db, slug, geo_code, vertical_slug, name=None):
    """Helper: create a brand with GEO and vertical associations."""
    brand = Brand(name=name or slug.title(), slug=slug)
    db.session.add(brand)
    db.session.flush()

    geo = Geo.query.filter_by(code=geo_code).first()
    vertical = Vertical.query.filter_by(slug=vertical_slug).first()

    db.session.add(BrandGeo(brand_id=brand.id, geo_id=geo.id, is_active=True, welcome_bonus='Test Bonus'))
    db.session.add(BrandVertical(brand_id=brand.id, vertical_id=vertical.id))
    db.session.flush()
    return brand


# --- 2.1 Wizard Steps Load ---

class TestWizardLoad:

    def test_wizard_page_loads(self, client):
        response = client.get('/sites/create')
        assert response.status_code == 200

    def test_wizard_contains_geos(self, client):
        response = client.get('/sites/create')
        assert b'United Kingdom' in response.data
        assert b'Germany' in response.data
        assert b'Brazil' in response.data

    def test_wizard_geos_match_seed(self, client, db):
        response = client.get('/sites/create')
        geos = Geo.query.all()
        for geo in geos:
            assert geo.name.encode() in response.data


# --- 2.2 Site Creation (Happy Path) ---

class TestSiteCreationHappyPath:

    def test_full_wizard_submission(self, client, db):
        # Create 3 test brands for gb + sports-betting
        b1 = _create_test_brand(db, 'brand-alpha', 'gb', 'sports-betting', 'Brand Alpha')
        b2 = _create_test_brand(db, 'brand-beta', 'gb', 'sports-betting', 'Brand Beta')
        b3 = _create_test_brand(db, 'brand-gamma', 'gb', 'sports-betting', 'Brand Gamma')
        db.session.commit()

        geo = Geo.query.filter_by(code='gb').first()
        vertical = Vertical.query.filter_by(slug='sports-betting').first()

        data = {
            'site_name': 'Test UK Sports Site',
            'geo_id': str(geo.id),
            'vertical_id': str(vertical.id),
            'brand_ids': [str(b1.id), str(b2.id), str(b3.id)],
            f'brand_rank_{b1.id}': '1',
            f'brand_rank_{b2.id}': '2',
            f'brand_rank_{b3.id}': '3',
            'page_types': ['homepage', 'comparison', 'brand-review', 'bonus-review'],
            'evergreen_topics': ['How to Bet on Football', 'Understanding Odds'],
        }
        response = client.post('/sites/create', data=data, follow_redirects=True)
        assert response.status_code == 200

        site = Site.query.filter_by(name='Test UK Sports Site').first()
        assert site is not None
        assert site.status == 'draft'

        # Check site_brands
        site_brands = SiteBrand.query.filter_by(site_id=site.id).order_by(SiteBrand.rank).all()
        assert len(site_brands) == 3
        assert site_brands[0].rank == 1
        assert site_brands[1].rank == 2
        assert site_brands[2].rank == 3

        # Check site_pages
        pages = SitePage.query.filter_by(site_id=site.id).all()
        page_types = {(p.page_type.slug, p.brand_id, p.evergreen_topic) for p in pages}

        # 1 homepage + 1 comparison + 3 brand reviews + 3 bonus reviews + 2 evergreen = 10
        assert len(pages) == 10

        # Check homepage and comparison exist
        homepage = [p for p in pages if p.page_type.slug == 'homepage']
        assert len(homepage) == 1
        assert homepage[0].slug == 'index'

        comparison = [p for p in pages if p.page_type.slug == 'comparison']
        assert len(comparison) == 1

        # Check brand reviews — one per brand
        brand_reviews = [p for p in pages if p.page_type.slug == 'brand-review']
        assert len(brand_reviews) == 3
        brand_review_slugs = {p.slug for p in brand_reviews}
        assert brand_review_slugs == {'brand-alpha', 'brand-beta', 'brand-gamma'}

        # Check bonus reviews — one per brand
        bonus_reviews = [p for p in pages if p.page_type.slug == 'bonus-review']
        assert len(bonus_reviews) == 3

        # Check evergreen pages
        evergreen_pages = [p for p in pages if p.page_type.slug == 'evergreen']
        assert len(evergreen_pages) == 2
        topics = {p.evergreen_topic for p in evergreen_pages}
        assert topics == {'How to Bet on Football', 'Understanding Odds'}
        slugs = {p.slug for p in evergreen_pages}
        assert 'how-to-bet-on-football' in slugs
        assert 'understanding-odds' in slugs


# --- 2.3 Duplicate Prevention ---

class TestDuplicatePrevention:

    def test_duplicate_site_brand(self, db):
        geo = Geo.query.filter_by(code='gb').first()
        vertical = Vertical.query.filter_by(slug='sports-betting').first()
        brand = _create_test_brand(db, 'dup-test-brand', 'gb', 'sports-betting')

        site = Site(name='Dup Test Site', geo_id=geo.id, vertical_id=vertical.id)
        db.session.add(site)
        db.session.flush()

        sb1 = SiteBrand(site_id=site.id, brand_id=brand.id, rank=1)
        db.session.add(sb1)
        db.session.flush()

        sb2 = SiteBrand(site_id=site.id, brand_id=brand.id, rank=2)
        db.session.add(sb2)
        with pytest.raises(IntegrityError):
            db.session.flush()


# --- 2.4 Partial Unique Indexes on site_pages ---

class TestPartialUniqueIndexes:

    def _make_site(self, db):
        geo = Geo.query.filter_by(code='gb').first()
        vertical = Vertical.query.filter_by(slug='sports-betting').first()
        site = Site(name='Index Test Site', geo_id=geo.id, vertical_id=vertical.id)
        db.session.add(site)
        db.session.flush()
        return site

    def test_duplicate_global_page(self, db):
        site = self._make_site(db)
        pt = PageType.query.filter_by(slug='homepage').first()

        p1 = SitePage(site_id=site.id, page_type_id=pt.id, slug='index', title='Home')
        db.session.add(p1)
        db.session.flush()

        p2 = SitePage(site_id=site.id, page_type_id=pt.id, slug='index2', title='Home 2')
        db.session.add(p2)
        with pytest.raises(IntegrityError):
            db.session.flush()

    def test_duplicate_brand_page(self, db):
        site = self._make_site(db)
        brand = _create_test_brand(db, 'idx-brand', 'gb', 'sports-betting')
        pt = PageType.query.filter_by(slug='brand-review').first()

        p1 = SitePage(site_id=site.id, page_type_id=pt.id, brand_id=brand.id,
                      slug=brand.slug, title='Review 1')
        db.session.add(p1)
        db.session.flush()

        p2 = SitePage(site_id=site.id, page_type_id=pt.id, brand_id=brand.id,
                      slug='other', title='Review 2')
        db.session.add(p2)
        with pytest.raises(IntegrityError):
            db.session.flush()

    def test_duplicate_evergreen_page(self, db):
        site = self._make_site(db)
        pt = PageType.query.filter_by(slug='evergreen').first()

        p1 = SitePage(site_id=site.id, page_type_id=pt.id,
                      evergreen_topic='How to Bet on Football',
                      slug='how-to-bet-on-football', title='How to Bet on Football')
        db.session.add(p1)
        db.session.flush()

        p2 = SitePage(site_id=site.id, page_type_id=pt.id,
                      evergreen_topic='How to Bet on Football',
                      slug='how-to-bet-on-football-2', title='Duplicate')
        db.session.add(p2)
        with pytest.raises(IntegrityError):
            db.session.flush()

    def test_two_different_evergreen_pages_allowed(self, db):
        site = self._make_site(db)
        pt = PageType.query.filter_by(slug='evergreen').first()

        p1 = SitePage(site_id=site.id, page_type_id=pt.id,
                      evergreen_topic='How to Bet on Football',
                      slug='how-to-bet-on-football', title='How to Bet on Football')
        p2 = SitePage(site_id=site.id, page_type_id=pt.id,
                      evergreen_topic='Understanding Odds',
                      slug='understanding-odds', title='Understanding Odds')
        db.session.add(p1)
        db.session.add(p2)
        db.session.flush()  # Should NOT raise

        pages = SitePage.query.filter_by(site_id=site.id, page_type_id=pt.id).all()
        assert len(pages) == 2


# --- 2.5 Brand Filtering ---

class TestBrandFiltering:

    def test_api_filters_by_geo_and_vertical(self, client, db):
        # Brand A: gb + sports-betting
        _create_test_brand(db, 'filter-a', 'gb', 'sports-betting', 'Brand A')
        # Brand B: gb + casino
        _create_test_brand(db, 'filter-b', 'gb', 'casino', 'Brand B')
        # Brand C: de + sports-betting
        _create_test_brand(db, 'filter-c', 'de', 'sports-betting', 'Brand C')
        db.session.commit()

        geo_gb = Geo.query.filter_by(code='gb').first()
        vert_sports = Vertical.query.filter_by(slug='sports-betting').first()

        response = client.get(f'/api/brands/filter?geo_id={geo_gb.id}&vertical_id={vert_sports.id}')
        assert response.status_code == 200

        data = response.get_json()
        slugs = {b['slug'] for b in data}
        assert 'filter-a' in slugs
        assert 'filter-b' not in slugs  # wrong vertical
        assert 'filter-c' not in slugs  # wrong geo
