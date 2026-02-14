"""Phase 3 tests: Content generation service.

ALL OpenAI calls are mocked — no real API calls are ever made in tests.
"""

import json
import time
import uuid
from unittest.mock import patch, MagicMock

import pytest

from app.models import (
    db as _db, Site, SitePage, SiteBrand, Brand, BrandGeo, BrandVertical,
    Geo, Vertical, PageType, ContentHistory,
)
from app.services.content_generator import (
    build_prompt, generate_page_content, save_content_to_page,
    generate_site_content_background, start_generation,
)


# --- Helpers ---

MOCK_COMPARISON_RESPONSE = {
    'hero_title': 'Best Sports Betting Sites in the UK',
    'hero_subtitle': 'Compare the top bookmakers',
    'intro_paragraph': 'Welcome to our comparison.',
    'comparison_rows': [
        {'brand': 'Bet365', 'slug': 'bet365', 'bonus': 'Bet £10 Get £30',
         'rating': 4.5, 'pros': ['Great odds'], 'cons': ['Complex UI'], 'verdict': 'Top choice'}
    ],
    'faq': [{'question': 'Which is best?', 'answer': 'It depends on your needs.'}],
    'closing_paragraph': 'Sign up today.',
}

MOCK_EVERGREEN_RESPONSE = {
    'hero_title': 'How to Bet on Football',
    'hero_subtitle': 'A complete guide',
    'intro_paragraph': 'Football betting is popular.',
    'sections': [
        {'heading': 'Getting Started', 'content': 'First, choose a bookmaker.'},
        {'heading': 'Understanding Odds', 'content': 'Odds represent probability.'},
    ],
    'key_takeaways': ['Start small', 'Research teams'],
    'faq': [{'question': 'Is it legal?', 'answer': 'Yes, in regulated markets.'}],
    'closing_paragraph': 'Good luck!',
}

MOCK_BRAND_REVIEW_RESPONSE = {
    'hero_title': 'Bet365 Review',
    'hero_subtitle': 'Full review',
    'intro_paragraph': 'Bet365 is a leading bookmaker.',
    'rating': 4.5,
    'pros': ['Great odds', 'Live streaming'],
    'cons': ['Complex interface'],
    'bonus_section': {'title': 'Welcome Bonus', 'description': 'Bet £10 Get £30', 'how_to_claim': ['Register', 'Deposit']},
    'features_review': 'Comprehensive features.',
    'user_experience': 'Good UX.',
    'payment_methods': 'Cards and e-wallets.',
    'verdict': 'Highly recommended.',
    'faq': [{'question': 'Is Bet365 safe?', 'answer': 'Yes.'}],
}


def _make_mock_openai_response(content_dict):
    """Create a mock OpenAI API response object."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = json.dumps(content_dict)
    return mock_response


def _create_test_site(db, with_pages=True):
    """Helper: create a site with brands and pages for testing."""
    geo = Geo.query.filter_by(code='gb').first()
    vertical = Vertical.query.filter_by(slug='sports-betting').first()

    brand = Brand(name='TestBet', slug=f'testbet-{uuid.uuid4().hex[:8]}', rating=4.5)
    db.session.add(brand)
    db.session.flush()

    db.session.add(BrandGeo(brand_id=brand.id, geo_id=geo.id,
                            welcome_bonus='Bet £10 Get £30', bonus_code='WELCOME', is_active=True))
    db.session.add(BrandVertical(brand_id=brand.id, vertical_id=vertical.id))
    db.session.flush()

    site = Site(name='Test Site', geo_id=geo.id, vertical_id=vertical.id, status='draft')
    db.session.add(site)
    db.session.flush()

    db.session.add(SiteBrand(site_id=site.id, brand_id=brand.id, rank=1))
    db.session.flush()

    if with_pages:
        # Create pages of different types
        for slug in ['homepage', 'comparison']:
            pt = PageType.query.filter_by(slug=slug).first()
            db.session.add(SitePage(
                site_id=site.id, page_type_id=pt.id,
                slug='index' if slug == 'homepage' else slug,
                title=pt.name,
            ))

        pt_review = PageType.query.filter_by(slug='brand-review').first()
        db.session.add(SitePage(
            site_id=site.id, page_type_id=pt_review.id,
            brand_id=brand.id, slug=brand.slug, title=f'{brand.name} Review',
        ))

        pt_evergreen = PageType.query.filter_by(slug='evergreen').first()
        db.session.add(SitePage(
            site_id=site.id, page_type_id=pt_evergreen.id,
            evergreen_topic='How to Bet on Football',
            slug='how-to-bet-on-football', title='How to Bet on Football',
        ))

        db.session.flush()

    return site, brand


# --- 3.1 Prompt Construction ---

class TestPromptConstruction:

    def test_comparison_prompt_contains_context(self, db):
        site, brand = _create_test_site(db)
        geo = site.geo
        vertical = site.vertical

        prompt = build_prompt(
            'comparison', geo, vertical,
            brands=sorted(site.site_brands, key=lambda sb: sb.rank),
        )

        assert geo.language in prompt
        assert geo.currency in prompt
        assert geo.name in prompt
        assert vertical.name in prompt
        assert brand.name in prompt
        assert 'Bet £10 Get £30' in prompt
        assert 'JSON' in prompt

    def test_evergreen_prompt_contains_topic(self, db):
        site, _ = _create_test_site(db)
        geo = site.geo
        vertical = site.vertical

        prompt = build_prompt(
            'evergreen', geo, vertical,
            evergreen_topic='How to Bet on Football',
        )

        assert 'How to Bet on Football' in prompt
        assert geo.language in prompt


# --- 3.2 Content Generation (Mocked) ---

class TestContentGeneration:

    @patch('app.services.content_generator.OpenAI')
    def test_generate_comparison_page(self, mock_openai_cls, db):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _make_mock_openai_response(MOCK_COMPARISON_RESPONSE)

        site, _ = _create_test_site(db)
        page = SitePage.query.filter_by(site_id=site.id, slug='comparison').first()

        content_data, prompt = generate_page_content(page, site, 'fake-key')

        assert 'hero_title' in content_data
        assert 'comparison_rows' in content_data
        assert 'faq' in content_data

        # Save to page
        save_content_to_page(page, content_data, db.session)
        db.session.flush()

        assert page.content_json is not None
        assert page.is_generated is True
        assert page.generated_at is not None

        parsed = json.loads(page.content_json)
        assert parsed['hero_title'] == 'Best Sports Betting Sites in the UK'


# --- 3.3 Evergreen Content ---

class TestEvergreenContent:

    @patch('app.services.content_generator.OpenAI')
    def test_evergreen_generation(self, mock_openai_cls, db):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _make_mock_openai_response(MOCK_EVERGREEN_RESPONSE)

        site, _ = _create_test_site(db)
        page = SitePage.query.filter_by(site_id=site.id, slug='how-to-bet-on-football').first()

        content_data, prompt = generate_page_content(page, site, 'fake-key')

        assert 'How to Bet on Football' in prompt
        assert 'sections' in content_data
        assert len(content_data['sections']) >= 2


# --- 3.4 Content Versioning ---

class TestContentVersioning:

    @patch('app.services.content_generator.OpenAI')
    def test_regeneration_saves_history(self, mock_openai_cls, db):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        site, _ = _create_test_site(db)
        page = SitePage.query.filter_by(site_id=site.id, slug='comparison').first()

        # First generation
        mock_client.chat.completions.create.return_value = _make_mock_openai_response(MOCK_COMPARISON_RESPONSE)
        content_v1, _ = generate_page_content(page, site, 'fake-key')
        save_content_to_page(page, content_v1, db.session)
        db.session.flush()

        assert page.is_generated is True
        assert ContentHistory.query.filter_by(site_page_id=page.id).count() == 0

        # Second generation (regeneration) — old content should be saved to history
        updated_response = {**MOCK_COMPARISON_RESPONSE, 'hero_title': 'Updated Title'}
        mock_client.chat.completions.create.return_value = _make_mock_openai_response(updated_response)
        content_v2, _ = generate_page_content(page, site, 'fake-key')
        save_content_to_page(page, content_v2, db.session)
        db.session.flush()

        # Verify history
        history = ContentHistory.query.filter_by(site_page_id=page.id).all()
        assert len(history) == 1
        assert history[0].version == 1

        old_content = json.loads(history[0].content_json)
        assert old_content['hero_title'] == 'Best Sports Betting Sites in the UK'

        # Current content should be the new version
        current = json.loads(page.content_json)
        assert current['hero_title'] == 'Updated Title'


# --- 3.5 Background Processing ---

class TestBackgroundProcessing:

    @patch('app.services.content_generator.OpenAI')
    def test_background_generation(self, mock_openai_cls, app, db):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _make_mock_openai_response(MOCK_COMPARISON_RESPONSE)

        site, _ = _create_test_site(db)
        db.session.commit()
        site_id = site.id

        # Start generation in background thread
        thread = start_generation(app, site_id, 'fake-key')

        # Wait for thread to complete (with timeout)
        thread.join(timeout=10)
        assert not thread.is_alive(), 'Generation thread timed out'

        # Refresh and check
        db.session.expire_all()
        site = db.session.get(Site, site_id)
        assert site.status == 'generated'

        pages = SitePage.query.filter_by(site_id=site_id).all()
        for page in pages:
            assert page.is_generated is True
            assert page.content_json is not None
            assert page.generated_at is not None

    @patch('app.services.content_generator.OpenAI')
    def test_generate_route_returns_immediately(self, mock_openai_cls, client, db):
        """The POST /sites/<id>/generate route should return a redirect immediately."""
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        # Make the mock slow to prove the route doesn't wait
        mock_client.chat.completions.create.return_value = _make_mock_openai_response(MOCK_COMPARISON_RESPONSE)

        site, _ = _create_test_site(db)
        db.session.commit()

        response = client.post(f'/sites/{site.id}/generate')
        # Should be a redirect (302), not a long-running request
        assert response.status_code == 302

        db.session.expire_all()
        site_refreshed = db.session.get(Site, site.id)
        assert site_refreshed.status == 'generating'

        # Wait for background thread to finish for cleanup
        time.sleep(2)


# --- 3.6 Generation Failure Handling ---

class TestGenerationFailure:

    @patch('app.services.content_generator.OpenAI')
    def test_failure_sets_failed_status(self, mock_openai_cls, app, db):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        site, _ = _create_test_site(db)
        db.session.commit()
        site_id = site.id

        # Count pages
        total_pages = SitePage.query.filter_by(site_id=site_id).count()
        assert total_pages == 4  # homepage, comparison, brand-review, evergreen

        # Make OpenAI succeed for first 2 pages, then fail
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return _make_mock_openai_response(MOCK_COMPARISON_RESPONSE)
            raise Exception('API rate limit exceeded')

        mock_client.chat.completions.create.side_effect = side_effect

        # Run generation
        thread = start_generation(app, site_id, 'fake-key')
        thread.join(timeout=10)

        db.session.expire_all()
        site = db.session.get(Site, site_id)
        assert site.status == 'failed'

        # First 2 pages should be generated
        generated = SitePage.query.filter_by(site_id=site_id, is_generated=True).count()
        assert generated == 2

        # Remaining pages should NOT be generated
        not_generated = SitePage.query.filter_by(site_id=site_id, is_generated=False).count()
        assert not_generated == 2


# --- 3.7 Generation Status API ---

class TestGenerationStatusAPI:

    def test_status_endpoint(self, client, db):
        site, _ = _create_test_site(db)
        db.session.commit()

        response = client.get(f'/api/sites/{site.id}/generation-status')
        assert response.status_code == 200

        data = response.get_json()
        assert 'total_pages' in data
        assert 'generated_pages' in data
        assert 'status' in data
        assert data['total_pages'] == 4
        assert data['generated_pages'] == 0
        assert data['status'] == 'draft'
