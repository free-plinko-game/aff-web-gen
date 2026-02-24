"""Automated betting tips pipeline.

Fetches upcoming football fixtures from API-Football, generates AI match
predictions/tips, and creates tips-article pages. Designed to run daily
via cron — fully idempotent (deduplicates by fixture_id).
"""

import json
import logging
import os
import re
import threading
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _slugify(text):
    """Convert text to a URL-safe slug."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_]+', '-', text)
    text = re.sub(r'-+', '-', text)
    return text.strip('-')


def fetch_and_generate_tips(site_id, app=None):
    """Main pipeline: fetch fixtures, generate tips, create pages.

    Args:
        site_id: Site ID to process
        app: Flask app instance (needed for app context if called from thread/cron)

    Returns:
        int: Number of new tips pages created
    """
    from ..models import db, Site, SitePage, PageType
    from .api_football import APIFootballClient, RateLimitError
    from .content_generator import build_prompt, call_openai, save_content_to_page
    from .site_builder import build_site

    site = db.session.get(Site, site_id)
    if not site:
        logger.error('Site %d not found', site_id)
        return 0

    if not site.tips_leagues:
        logger.info('Site %d has no tips_leagues configured, skipping', site_id)
        return 0

    try:
        leagues = json.loads(site.tips_leagues)
    except (json.JSONDecodeError, TypeError):
        logger.error('Invalid tips_leagues JSON for site %d', site_id)
        return 0

    if not leagues:
        return 0

    # Get config
    if app:
        api_football_key = app.config.get('API_FOOTBALL_KEY', '')
        openai_key = app.config.get('OPENAI_API_KEY', '')
        openai_model = app.config.get('OPENAI_MODEL', 'gpt-4o-mini')
        max_matches = app.config.get('TIPS_MAX_MATCHES_PER_DAY', 20)
    else:
        from flask import current_app
        api_football_key = current_app.config.get('API_FOOTBALL_KEY', '')
        openai_key = current_app.config.get('OPENAI_API_KEY', '')
        openai_model = current_app.config.get('OPENAI_MODEL', 'gpt-4o-mini')
        max_matches = current_app.config.get('TIPS_MAX_MATCHES_PER_DAY', 20)

    if not api_football_key:
        logger.error('API_FOOTBALL_KEY not configured')
        return 0
    if not openai_key:
        logger.error('OPENAI_API_KEY not configured')
        return 0

    # Get tips page types
    tips_article_pt = PageType.query.filter_by(slug='tips-article').first()
    tips_landing_pt = PageType.query.filter_by(slug='tips').first()
    if not tips_article_pt:
        logger.error('tips-article PageType not found — run seed')
        return 0

    # Find existing fixture IDs for this site to skip duplicates
    existing_fixture_ids = set(
        fid for (fid,) in
        db.session.query(SitePage.fixture_id)
        .filter(SitePage.site_id == site_id, SitePage.fixture_id.isnot(None))
        .all()
    )

    # Find tips landing page (for nav_parent_id)
    tips_landing = SitePage.query.filter_by(
        site_id=site_id, page_type_id=tips_landing_pt.id
    ).first() if tips_landing_pt else None

    geo = site.geo
    vertical = site.vertical
    client = APIFootballClient(api_football_key)

    created_count = 0
    all_fixtures = []

    # Step 1: Fetch fixtures for all leagues
    for league_config in leagues:
        league_id = league_config.get('league_id')
        season = league_config.get('season', datetime.now().year)
        league_name = league_config.get('name', f'League {league_id}')

        if not league_id:
            continue

        try:
            fixtures = client.get_fixtures(league_id, season, next_hours=48)
            logger.info('Found %d fixtures for %s (league %d)',
                        len(fixtures), league_name, league_id)

            for fixture in fixtures:
                fixture_id = fixture.get('fixture', {}).get('id')
                if fixture_id and fixture_id not in existing_fixture_ids:
                    all_fixtures.append({
                        'fixture': fixture,
                        'league_id': league_id,
                        'season': season,
                        'league_name': league_name,
                    })
        except RateLimitError:
            logger.warning('Rate limit reached while fetching fixtures for %s', league_name)
            break
        except Exception as e:
            logger.error('Failed to fetch fixtures for %s: %s', league_name, e)
            continue

    # Cap at max matches per day
    all_fixtures = all_fixtures[:max_matches]
    logger.info('Processing %d new fixtures for site %d', len(all_fixtures), site_id)

    # Step 2: For each fixture, build data package + generate content
    for item in all_fixtures:
        fixture = item['fixture']
        league_id = item['league_id']
        season = item['season']
        league_name = item['league_name']

        fixture_data = fixture.get('fixture', {})
        fixture_id = fixture_data.get('id')
        home_team = fixture.get('teams', {}).get('home', {})
        away_team = fixture.get('teams', {}).get('away', {})
        home_name = home_team.get('name', 'Home')
        away_name = away_team.get('name', 'Away')

        # Build date-prefixed slug
        match_date_str = fixture_data.get('date', '')
        try:
            match_date = datetime.fromisoformat(match_date_str.replace('Z', '+00:00'))
            date_prefix = match_date.strftime('%Y-%m-%d')
        except (ValueError, AttributeError):
            date_prefix = datetime.now().strftime('%Y-%m-%d')
            match_date = datetime.now(timezone.utc)

        slug = _slugify(f"{date_prefix}-{home_name}-vs-{away_name}")
        title = f"{home_name} vs {away_name}"

        try:
            # Build match data package (H2H, odds, stats — 3 API calls)
            from .api_football import build_match_data_package
            match_data = build_match_data_package(client, fixture, league_id, season)

            # Add league name context
            match_data['league_name'] = league_name

            # Generate AI content
            match_data_json = json.dumps(match_data, default=str)
            prompt = build_prompt(
                'tips-article', geo, vertical,
                evergreen_topic=title,
                match_data=match_data_json,
            )
            content_data = call_openai(prompt, openai_key, openai_model)

            # Create the SitePage
            page = SitePage(
                site_id=site_id,
                page_type_id=tips_article_pt.id,
                evergreen_topic=title,
                slug=slug,
                title=title,
                fixture_id=fixture_id,
                published_date=datetime.now(timezone.utc),
                show_in_nav=False,
                show_in_footer=False,
                nav_order=0,
            )
            if tips_landing:
                page.nav_parent_id = tips_landing.id

            # Auto-assign default author if set
            if site.default_author_id:
                page.author_id = site.default_author_id

            db.session.add(page)
            db.session.flush()  # Get page.id

            save_content_to_page(page, content_data, db.session)
            db.session.commit()

            created_count += 1
            logger.info('Created tip: %s (fixture %d)', title, fixture_id)

        except RateLimitError:
            logger.warning('Rate limit reached after creating %d tips', created_count)
            db.session.rollback()
            break
        except Exception as e:
            logger.error('Failed to create tip for %s: %s', title, e)
            db.session.rollback()
            continue

    # Step 3: Build site if new pages were created
    if created_count > 0:
        logger.info('Created %d new tips for site %d', created_count, site_id)
        try:
            if app:
                output_dir = os.path.join(app.root_path, 'output')
                upload_folder = app.config.get('UPLOAD_FOLDER', 'uploads')
            else:
                from flask import current_app
                output_dir = os.path.join(current_app.root_path, '..', 'output')
                upload_folder = current_app.config.get('UPLOAD_FOLDER', 'uploads')

            # Refresh the site object
            site = db.session.get(Site, site_id)
            build_site(site, output_dir, upload_folder)
            site.current_version += 1
            db.session.commit()
            logger.info('Site %d rebuilt after tips generation', site_id)

            # Auto-deploy if site was already deployed
            if site.status == 'deployed' and site.domain:
                try:
                    from .deployer import deploy_site
                    deploy_config = app.config if app else current_app.config
                    deploy_site(site, deploy_config)
                    db.session.commit()
                    logger.info('Site %d auto-deployed after tips generation', site_id)
                except Exception as e:
                    logger.error('Auto-deploy failed for site %d: %s', site_id, e)
        except Exception as e:
            logger.error('Build failed for site %d after tips generation: %s', site_id, e)

    return created_count


def run_tips_pipeline_background(app, site_id):
    """Launch the tips pipeline in a background daemon thread.

    Args:
        app: Flask app instance
        site_id: Site ID to process
    """
    def _run():
        with app.app_context():
            try:
                count = fetch_and_generate_tips(site_id, app=app)
                logger.info('Tips pipeline completed for site %d: %d new tips', site_id, count)
            except Exception as e:
                logger.error('Tips pipeline failed for site %d: %s', site_id, e)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    logger.info('Tips pipeline started in background for site %d', site_id)
