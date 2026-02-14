"""Phase 4 tests: Static site builder.

Uses fixture content data — no real OpenAI calls.
"""

import json
import os
import shutil
import tempfile
import uuid

import pytest

from app.models import (
    db as _db, Site, SitePage, SiteBrand, Brand, BrandGeo, BrandVertical,
    Geo, Vertical, PageType, Domain,
)
from app.services.site_builder import build_site


# --- Fixture content data ---

HOMEPAGE_CONTENT = {
    'hero_title': 'Best Sports Betting Sites UK',
    'hero_subtitle': 'Compare the top bookmakers in the United Kingdom',
    'intro_paragraph': 'Welcome to our site.',
    'top_brands': [{'name': 'BrandA', 'slug': 'brand-a', 'bonus': '£30 free', 'rating': 4.5, 'short_description': 'Great site'}],
    'why_trust_us': 'We are experts.',
    'faq': [{'question': 'Is it safe?', 'answer': 'Yes.'}],
    'closing_paragraph': 'Sign up today.',
}

COMPARISON_CONTENT = {
    'hero_title': 'Compare Sports Betting Sites',
    'hero_subtitle': 'Side by side comparison',
    'intro_paragraph': 'Here is our comparison.',
    'comparison_rows': [
        {'brand': 'BrandA', 'slug': 'brand-a', 'bonus': '£30 free', 'rating': 4.5,
         'pros': ['Good odds'], 'cons': ['Slow withdrawals'], 'verdict': 'Top pick'},
        {'brand': 'BrandB', 'slug': 'brand-b', 'bonus': '£20 free', 'rating': 4.0,
         'pros': ['Fast payouts'], 'cons': ['Limited markets'], 'verdict': 'Good choice'},
        {'brand': 'BrandC', 'slug': 'brand-c', 'bonus': '£10 free', 'rating': 3.5,
         'pros': ['Simple UI'], 'cons': ['Few sports'], 'verdict': 'Decent'},
    ],
    'faq': [{'question': 'Which is best?', 'answer': 'BrandA.'}],
    'closing_paragraph': 'Choose wisely.',
}

BRAND_REVIEW_CONTENT = {
    'hero_title': 'BrandA Review',
    'hero_subtitle': 'Full review of BrandA',
    'intro_paragraph': 'BrandA is a leading bookmaker.',
    'rating': 4.5,
    'pros': ['Good odds', 'Live streaming'],
    'cons': ['Slow withdrawals'],
    'bonus_section': {'title': 'Welcome Bonus', 'description': '£30 free', 'how_to_claim': ['Register', 'Deposit']},
    'features_review': 'Great features.',
    'user_experience': 'Easy to use.',
    'payment_methods': 'Cards and e-wallets.',
    'verdict': 'Highly recommended.',
    'faq': [{'question': 'Is BrandA safe?', 'answer': 'Yes.'}],
}

BONUS_REVIEW_CONTENT = {
    'hero_title': 'BrandA Bonus Review',
    'hero_subtitle': 'Welcome offer details',
    'bonus_overview': {'offer': '£30 free', 'code': 'WELCOME', 'min_deposit': '£10',
                       'wagering_requirements': '5x', 'validity': '30 days'},
    'how_to_claim': ['Register', 'Deposit £10', 'Place a bet'],
    'terms_summary': 'Standard terms apply.',
    'pros': ['Generous offer'],
    'cons': ['Wagering requirements'],
    'similar_offers': 'BrandB offers £20.',
    'verdict': 'Worth claiming.',
    'faq': [{'question': 'Do I need a code?', 'answer': 'Use WELCOME.'}],
}

EVERGREEN_CONTENT = {
    'hero_title': 'How to Bet on Football',
    'hero_subtitle': 'A complete guide for beginners',
    'intro_paragraph': 'Football betting is popular.',
    'sections': [
        {'heading': 'Getting Started', 'content': 'First, choose a bookmaker.'},
        {'heading': 'Understanding Odds', 'content': 'Odds represent probability.'},
    ],
    'key_takeaways': ['Start small', 'Research teams'],
    'faq': [{'question': 'Is it legal?', 'answer': 'Yes.'}],
    'closing_paragraph': 'Good luck!',
}

EVERGREEN_CONTENT_2 = {
    'hero_title': 'Understanding Odds',
    'hero_subtitle': 'How betting odds work',
    'intro_paragraph': 'Odds can be confusing.',
    'sections': [
        {'heading': 'Decimal Odds', 'content': 'Most common in Europe.'},
        {'heading': 'Fractional Odds', 'content': 'Common in the UK.'},
    ],
    'key_takeaways': ['Learn all formats'],
    'faq': [{'question': 'Which is easiest?', 'answer': 'Decimal.'}],
    'closing_paragraph': 'Practice makes perfect.',
}


@pytest.fixture
def built_site(app, db):
    """Create a full site with 3 brands, all page types, and build it."""
    uid = uuid.uuid4().hex[:8]
    geo = Geo.query.filter_by(code='gb').first()
    vertical = Vertical.query.filter_by(slug='sports-betting').first()

    # Create 3 brands
    brands = []
    for i, (name, slug) in enumerate([('BrandA', f'brand-a-{uid}'), ('BrandB', f'brand-b-{uid}'), ('BrandC', f'brand-c-{uid}')]):
        b = Brand(name=name, slug=slug, rating=4.5 - i * 0.5,
                  affiliate_link=f'https://aff.{slug}.com', logo_filename=f'{slug}.png' if i == 0 else None)
        db.session.add(b)
        db.session.flush()
        db.session.add(BrandGeo(brand_id=b.id, geo_id=geo.id, welcome_bonus=f'£{30 - i*10} free',
                                bonus_code='WELCOME', is_active=True))
        db.session.add(BrandVertical(brand_id=b.id, vertical_id=vertical.id))
        brands.append(b)
    db.session.flush()

    # Create site
    site = Site(name=f'Test Site {uid}', geo_id=geo.id, vertical_id=vertical.id, status='generated')
    db.session.add(site)
    db.session.flush()

    for i, b in enumerate(brands):
        db.session.add(SiteBrand(site_id=site.id, brand_id=b.id, rank=i + 1))

    # Create pages with content
    content_map = {
        'homepage': (HOMEPAGE_CONTENT, None, None, 'index', 'Homepage'),
        'comparison': (COMPARISON_CONTENT, None, None, 'comparison', 'Compare'),
    }
    for slug, (content, brand_id, topic, page_slug, title) in content_map.items():
        pt = PageType.query.filter_by(slug=slug).first()
        db.session.add(SitePage(
            site_id=site.id, page_type_id=pt.id, slug=page_slug, title=title,
            content_json=json.dumps(content), is_generated=True,
            generated_at=db.session.query(db.func.current_timestamp()).scalar(),
        ))

    # Brand reviews and bonus reviews for each brand
    pt_review = PageType.query.filter_by(slug='brand-review').first()
    pt_bonus = PageType.query.filter_by(slug='bonus-review').first()
    for b in brands:
        db.session.add(SitePage(
            site_id=site.id, page_type_id=pt_review.id, brand_id=b.id,
            slug=b.slug, title=f'{b.name} Review',
            content_json=json.dumps(BRAND_REVIEW_CONTENT), is_generated=True,
            generated_at=db.session.query(db.func.current_timestamp()).scalar(),
        ))
        db.session.add(SitePage(
            site_id=site.id, page_type_id=pt_bonus.id, brand_id=b.id,
            slug=b.slug, title=f'{b.name} Bonus Review',
            content_json=json.dumps(BONUS_REVIEW_CONTENT), is_generated=True,
            generated_at=db.session.query(db.func.current_timestamp()).scalar(),
        ))

    # Evergreen pages
    pt_eg = PageType.query.filter_by(slug='evergreen').first()
    db.session.add(SitePage(
        site_id=site.id, page_type_id=pt_eg.id,
        evergreen_topic='How to Bet on Football', slug='how-to-bet-on-football',
        title='How to Bet on Football',
        content_json=json.dumps(EVERGREEN_CONTENT), is_generated=True,
        generated_at=db.session.query(db.func.current_timestamp()).scalar(),
    ))
    db.session.add(SitePage(
        site_id=site.id, page_type_id=pt_eg.id,
        evergreen_topic='Understanding Odds', slug='understanding-odds',
        title='Understanding Odds',
        content_json=json.dumps(EVERGREEN_CONTENT_2), is_generated=True,
        generated_at=db.session.query(db.func.current_timestamp()).scalar(),
    ))
    db.session.flush()

    # Create a test logo file for brand-a
    logos_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'logos')
    os.makedirs(logos_dir, exist_ok=True)
    logo_path = os.path.join(logos_dir, f'brand-a-{uid}.png')
    with open(logo_path, 'wb') as f:
        f.write(b'fake png data')

    # Build
    output_dir = tempfile.mkdtemp()
    version_dir = build_site(site, output_dir, app.config['UPLOAD_FOLDER'])

    yield {
        'site': site,
        'brands': brands,
        'version_dir': version_dir,
        'output_dir': output_dir,
        'uid': uid,
    }

    # Cleanup
    shutil.rmtree(output_dir, ignore_errors=True)


# --- 4.1 Build Output Structure ---

class TestBuildOutputStructure:

    def test_output_directory_exists(self, built_site):
        assert os.path.isdir(built_site['version_dir'])

    def test_index_html_exists(self, built_site):
        assert os.path.isfile(os.path.join(built_site['version_dir'], 'index.html'))

    def test_comparison_html_exists(self, built_site):
        assert os.path.isfile(os.path.join(built_site['version_dir'], 'comparison.html'))

    def test_reviews_directory_exists(self, built_site):
        reviews_dir = os.path.join(built_site['version_dir'], 'reviews')
        assert os.path.isdir(reviews_dir)
        # One HTML per brand
        html_files = [f for f in os.listdir(reviews_dir) if f.endswith('.html')]
        assert len(html_files) == 3

    def test_bonuses_directory_exists(self, built_site):
        bonuses_dir = os.path.join(built_site['version_dir'], 'bonuses')
        assert os.path.isdir(bonuses_dir)
        html_files = [f for f in os.listdir(bonuses_dir) if f.endswith('.html')]
        assert len(html_files) == 3

    def test_evergreen_pages_exist(self, built_site):
        assert os.path.isfile(os.path.join(built_site['version_dir'], 'how-to-bet-on-football.html'))
        assert os.path.isfile(os.path.join(built_site['version_dir'], 'understanding-odds.html'))

    def test_assets_exist(self, built_site):
        assert os.path.isfile(os.path.join(built_site['version_dir'], 'assets', 'css', 'style.css'))
        assert os.path.isfile(os.path.join(built_site['version_dir'], 'assets', 'js', 'main.js'))

    def test_sitemap_exists(self, built_site):
        assert os.path.isfile(os.path.join(built_site['version_dir'], 'sitemap.xml'))

    def test_robots_exists(self, built_site):
        assert os.path.isfile(os.path.join(built_site['version_dir'], 'robots.txt'))


# --- 4.2 HTML Content Rendered ---

class TestHTMLContentRendered:

    def test_homepage_contains_hero_title(self, built_site):
        html = open(os.path.join(built_site['version_dir'], 'index.html'), encoding='utf-8').read()
        assert HOMEPAGE_CONTENT['hero_title'] in html

    def test_homepage_contains_brand_names(self, built_site):
        html = open(os.path.join(built_site['version_dir'], 'index.html'), encoding='utf-8').read()
        assert 'BrandA' in html

    def test_homepage_contains_affiliate_links(self, built_site):
        uid = built_site['uid']
        html = open(os.path.join(built_site['version_dir'], 'index.html'), encoding='utf-8').read()
        assert f'https://aff.brand-a-{uid}.com' in html

    def test_no_raw_jinja_tags(self, built_site):
        for root, dirs, files in os.walk(built_site['version_dir']):
            for f in files:
                if f.endswith('.html'):
                    content = open(os.path.join(root, f), encoding='utf-8').read()
                    assert '{{' not in content, f'Raw Jinja2 tag found in {f}'
                    assert '{%' not in content, f'Raw Jinja2 tag found in {f}'


# --- 4.3 Internal Linking ---

class TestInternalLinking:

    def test_homepage_nav_has_comparison_link(self, built_site):
        html = open(os.path.join(built_site['version_dir'], 'index.html'), encoding='utf-8').read()
        assert 'comparison.html' in html

    def test_homepage_nav_has_evergreen_links(self, built_site):
        html = open(os.path.join(built_site['version_dir'], 'index.html'), encoding='utf-8').read()
        assert 'how-to-bet-on-football.html' in html
        assert 'understanding-odds.html' in html

    def test_homepage_footer_has_all_links(self, built_site):
        html = open(os.path.join(built_site['version_dir'], 'index.html'), encoding='utf-8').read()
        assert 'index.html' in html
        assert 'comparison.html' in html

    def test_comparison_links_to_reviews(self, built_site):
        uid = built_site['uid']
        html = open(os.path.join(built_site['version_dir'], 'comparison.html'), encoding='utf-8').read()
        assert f'reviews/brand-a-{uid}.html' in html or 'reviews/brand-a' in html

    def test_brand_review_links_to_bonus(self, built_site):
        uid = built_site['uid']
        review_file = os.path.join(built_site['version_dir'], 'reviews', f'brand-a-{uid}.html')
        html = open(review_file, encoding='utf-8').read()
        assert f'bonuses/brand-a-{uid}.html' in html

    def test_bonus_review_links_to_brand_review(self, built_site):
        uid = built_site['uid']
        bonus_file = os.path.join(built_site['version_dir'], 'bonuses', f'brand-a-{uid}.html')
        html = open(bonus_file, encoding='utf-8').read()
        assert f'reviews/brand-a-{uid}.html' in html


# --- 4.4 Sitemap ---

class TestSitemap:

    def test_sitemap_contains_all_pages(self, built_site):
        xml = open(os.path.join(built_site['version_dir'], 'sitemap.xml'), encoding='utf-8').read()
        assert 'index.html' in xml
        assert 'comparison.html' in xml
        assert 'reviews/' in xml
        assert 'bonuses/' in xml
        assert 'how-to-bet-on-football.html' in xml
        assert 'understanding-odds.html' in xml

    def test_sitemap_has_lastmod(self, built_site):
        xml = open(os.path.join(built_site['version_dir'], 'sitemap.xml'), encoding='utf-8').read()
        assert '<lastmod>' in xml


# --- 4.5 Robots.txt ---

class TestRobotsTxt:

    def test_robots_allows_all(self, built_site):
        txt = open(os.path.join(built_site['version_dir'], 'robots.txt'), encoding='utf-8').read()
        assert 'User-agent: *' in txt
        assert 'Allow: /' in txt

    def test_robots_has_sitemap(self, built_site):
        txt = open(os.path.join(built_site['version_dir'], 'robots.txt'), encoding='utf-8').read()
        assert 'Sitemap: https://example.com/sitemap.xml' in txt


# --- 4.6 Logo Handling ---

class TestLogoHandling:

    def test_logo_copied_to_output(self, built_site):
        uid = built_site['uid']
        logo_path = os.path.join(built_site['version_dir'], 'assets', 'logos', f'brand-a-{uid}.png')
        assert os.path.isfile(logo_path)

    def test_homepage_references_logo(self, built_site):
        uid = built_site['uid']
        html = open(os.path.join(built_site['version_dir'], 'index.html'), encoding='utf-8').read()
        assert f'assets/logos/brand-a-{uid}.png' in html


# --- 4.7 Missing Logo Fallback ---

class TestMissingLogoFallback:

    def test_no_broken_image_for_missing_logo(self, built_site):
        uid = built_site['uid']
        # BrandB and BrandC have no logo
        html = open(os.path.join(built_site['version_dir'], 'comparison.html'), encoding='utf-8').read()
        # Should NOT have an img tag for brand-b or brand-c logos
        assert f'brand-b-{uid}.png' not in html
        assert f'brand-c-{uid}.png' not in html
        # But BrandB and BrandC names should still appear
        assert 'BrandB' in html
        assert 'BrandC' in html


# --- 4.8 Versioned Builds ---

class TestVersionedBuilds:

    def test_rebuild_creates_v2(self, app, db):
        uid = uuid.uuid4().hex[:8]
        geo = Geo.query.filter_by(code='gb').first()
        vertical = Vertical.query.filter_by(slug='sports-betting').first()

        brand = Brand(name='VBrand', slug=f'vbrand-{uid}', rating=4.0, affiliate_link='https://aff.test.com')
        db.session.add(brand)
        db.session.flush()
        db.session.add(BrandGeo(brand_id=brand.id, geo_id=geo.id, welcome_bonus='£10', is_active=True))
        db.session.add(BrandVertical(brand_id=brand.id, vertical_id=vertical.id))

        site = Site(name=f'Version Test {uid}', geo_id=geo.id, vertical_id=vertical.id,
                    status='generated', current_version=1)
        db.session.add(site)
        db.session.flush()
        db.session.add(SiteBrand(site_id=site.id, brand_id=brand.id, rank=1))

        pt = PageType.query.filter_by(slug='homepage').first()
        db.session.add(SitePage(
            site_id=site.id, page_type_id=pt.id, slug='index', title='Home',
            content_json=json.dumps(HOMEPAGE_CONTENT), is_generated=True,
        ))
        db.session.flush()

        output_dir = tempfile.mkdtemp()
        try:
            # Build v1
            v1_dir = build_site(site, output_dir, app.config['UPLOAD_FOLDER'])
            assert os.path.isdir(v1_dir)
            assert 'v1' in v1_dir

            # Increment version and rebuild
            site.current_version = 2
            site.status = 'generated'
            v2_dir = build_site(site, output_dir, app.config['UPLOAD_FOLDER'])
            assert os.path.isdir(v2_dir)
            assert 'v2' in v2_dir

            # v1 should still exist
            assert os.path.isdir(v1_dir)
            assert site.current_version == 2
        finally:
            shutil.rmtree(output_dir, ignore_errors=True)
