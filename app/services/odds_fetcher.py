"""Odds fetcher service.

Fetches fixture odds from API-Football for all configured leagues,
stores/updates OddsFixture and OddsData records. Designed to run
via cron (twice daily) or manual trigger from admin.
"""

import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# API-Football bet name → our market key
MARKET_MAP = {
    'Match Winner': 'h2h',
    'Home/Away': 'h2h',
    'Goals Over/Under': 'totals',
    'Over/Under': 'totals',
    'Both Teams Score': 'btts',
    'Both Teams - Loss': 'btts',
    'Double Chance': 'double_chance',
}

# API-Football outcome value → clean display label
OUTCOME_MAP = {
    # h2h
    'Home': 'Home',
    'Draw': 'Draw',
    'Away': 'Away',
    # totals
    'Over 0.5': 'Over 0.5',
    'Under 0.5': 'Under 0.5',
    'Over 1.5': 'Over 1.5',
    'Under 1.5': 'Under 1.5',
    'Over 2.5': 'Over 2.5',
    'Under 2.5': 'Under 2.5',
    'Over 3.5': 'Over 3.5',
    'Under 3.5': 'Under 3.5',
    # btts
    'Yes': 'Yes',
    'No': 'No',
    # double_chance
    'Home/Draw': 'Home/Draw',
    'Home/Away': 'Home/Away',
    'Draw/Away': 'Draw/Away',
}


def _slugify(text):
    """Convert text to a URL-safe slug."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_]+', '-', text)
    text = re.sub(r'-+', '-', text)
    return text.strip('-')


def fetch_odds(site_id, app=None):
    """Main entry point: fetch and store odds for a site.

    Args:
        site_id: Site ID to process.
        app: Flask app instance (needed for app context from cron).

    Returns:
        dict: Summary with fixtures_updated, odds_stored, api_calls.
    """
    from ..models import db, Site, OddsConfig, OddsFixture, OddsData
    from .api_football import APIFootballClient, RateLimitError

    site = db.session.get(Site, site_id)
    if not site:
        logger.error('Site %d not found', site_id)
        return {'fixtures_updated': 0, 'odds_stored': 0, 'api_calls': 0}

    config = OddsConfig.query.filter_by(site_id=site_id).first()
    if not config or not config.enabled:
        logger.info('Odds not enabled for site %d', site_id)
        return {'fixtures_updated': 0, 'odds_stored': 0, 'api_calls': 0}

    try:
        leagues = json.loads(config.leagues) if config.leagues else []
    except (json.JSONDecodeError, TypeError):
        logger.error('Invalid leagues JSON for site %d odds config', site_id)
        return {'fixtures_updated': 0, 'odds_stored': 0, 'api_calls': 0}

    if not leagues:
        return {'fixtures_updated': 0, 'odds_stored': 0, 'api_calls': 0}

    try:
        bookmaker_ids = json.loads(config.bookmaker_ids) if config.bookmaker_ids else []
    except (json.JSONDecodeError, TypeError):
        bookmaker_ids = []

    try:
        markets = json.loads(config.markets) if config.markets else ['h2h']
    except (json.JSONDecodeError, TypeError):
        markets = ['h2h']

    # Get API key
    if app:
        api_key = app.config.get('API_FOOTBALL_KEY', '')
    else:
        from flask import current_app
        api_key = current_app.config.get('API_FOOTBALL_KEY', '')

    if not api_key:
        logger.error('API_FOOTBALL_KEY not configured')
        return {'fixtures_updated': 0, 'odds_stored': 0, 'api_calls': 0}

    client = APIFootballClient(api_key)
    lookahead = config.lookahead_hours or 168

    fixtures_updated = 0
    odds_stored = 0

    # Step 1: Fetch fixtures for each league
    for league_config in leagues:
        league_id = league_config.get('league_id')
        season = league_config.get('season', datetime.now().year)
        league_name = league_config.get('name', f'League {league_id}')
        league_slug = _slugify(league_name)

        if not league_id:
            continue

        try:
            fixtures = client.get_fixtures(league_id, season, next_hours=lookahead)
            logger.info('Found %d fixtures for %s (league %d)',
                        len(fixtures), league_name, league_id)
        except RateLimitError:
            logger.warning('Rate limit reached fetching fixtures for %s', league_name)
            break
        except Exception as e:
            logger.error('Failed to fetch fixtures for %s: %s', league_name, e)
            continue

        # Step 2: For each fixture, fetch odds
        for fixture in fixtures:
            fixture_info = fixture.get('fixture', {})
            fixture_id = fixture_info.get('id')
            if not fixture_id:
                continue

            teams = fixture.get('teams', {})
            home = teams.get('home', {})
            away = teams.get('away', {})
            home_name = home.get('name', 'Home')
            away_name = away.get('name', 'Away')

            # Parse kickoff
            date_str = fixture_info.get('date', '')
            try:
                kickoff = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                kickoff = datetime.now(timezone.utc)

            slug = _slugify(f'{home_name}-vs-{away_name}')

            # Upsert OddsFixture
            odds_fixture = OddsFixture.query.filter_by(
                site_id=site_id, fixture_id=fixture_id
            ).first()

            if not odds_fixture:
                odds_fixture = OddsFixture(
                    site_id=site_id,
                    fixture_id=fixture_id,
                    league_id=league_id,
                    league_name=league_name,
                    league_slug=league_slug,
                    home_team=home_name,
                    away_team=away_name,
                    home_logo=home.get('logo'),
                    away_logo=away.get('logo'),
                    kickoff=kickoff,
                    slug=slug,
                    status='upcoming',
                )
                db.session.add(odds_fixture)
                db.session.flush()
            else:
                odds_fixture.kickoff = kickoff
                odds_fixture.home_logo = home.get('logo') or odds_fixture.home_logo
                odds_fixture.away_logo = away.get('logo') or odds_fixture.away_logo
                odds_fixture.league_slug = league_slug
                odds_fixture.updated_at = datetime.now(timezone.utc)

            # Fetch odds for this fixture
            try:
                odds_response = client.get_odds(fixture_id)
            except RateLimitError:
                logger.warning('Rate limit reached fetching odds for fixture %d', fixture_id)
                db.session.commit()
                return {
                    'fixtures_updated': fixtures_updated,
                    'odds_stored': odds_stored,
                    'api_calls': client._request_count,
                }
            except Exception as e:
                logger.warning('Odds fetch failed for fixture %d: %s', fixture_id, e)
                continue

            if not odds_response:
                continue

            # Parse odds from all bookmakers in response
            for response_item in odds_response:
                bookmakers = response_item.get('bookmakers', [])
                for bk in bookmakers:
                    bk_id = bk.get('id')
                    bk_name = bk.get('name', '')

                    # Filter to configured bookmakers (if list provided)
                    if bookmaker_ids and bk_id not in bookmaker_ids:
                        continue

                    for bet in bk.get('bets', []):
                        bet_name = bet.get('name', '')
                        market_key = MARKET_MAP.get(bet_name)
                        if not market_key or market_key not in markets:
                            continue

                        for val in bet.get('values', []):
                            outcome_raw = str(val.get('value', ''))
                            odds_val = val.get('odd')
                            if odds_val is None:
                                continue

                            try:
                                odds_float = float(odds_val)
                            except (ValueError, TypeError):
                                continue

                            outcome = OUTCOME_MAP.get(outcome_raw, outcome_raw)

                            # Upsert OddsData
                            existing = OddsData.query.filter_by(
                                odds_fixture_id=odds_fixture.id,
                                bookmaker_id=bk_id,
                                market=market_key,
                                outcome=outcome,
                            ).first()

                            if existing:
                                existing.odds_value = odds_float
                                existing.last_updated = datetime.now(timezone.utc)
                            else:
                                db.session.add(OddsData(
                                    odds_fixture_id=odds_fixture.id,
                                    bookmaker_id=bk_id,
                                    bookmaker_name=bk_name,
                                    market=market_key,
                                    outcome=outcome,
                                    odds_value=odds_float,
                                ))
                                odds_stored += 1

            fixtures_updated += 1

            # Brief pause to respect rate limits
            time.sleep(0.2)

        db.session.commit()

    # Step 3: Mark past fixtures as finished
    now = datetime.now(timezone.utc)
    past = OddsFixture.query.filter(
        OddsFixture.site_id == site_id,
        OddsFixture.status == 'upcoming',
        OddsFixture.kickoff < now,
    ).all()
    for f in past:
        f.status = 'finished'

    # Step 4: Delete fixtures older than 7 days
    cutoff = now - timedelta(days=7)
    old = OddsFixture.query.filter(
        OddsFixture.site_id == site_id,
        OddsFixture.kickoff < cutoff,
    ).all()
    for f in old:
        db.session.delete(f)

    db.session.commit()

    logger.info('Odds fetch complete for site %d: %d fixtures, %d odds stored, %d API calls',
                site_id, fixtures_updated, odds_stored, client._request_count)

    return {
        'fixtures_updated': fixtures_updated,
        'odds_stored': odds_stored,
        'api_calls': client._request_count,
    }


def fetch_single_fixture_odds(site_id, odds_fixture_id):
    """Re-fetch odds for a single fixture.

    Args:
        site_id: Site ID.
        odds_fixture_id: OddsFixture record ID.

    Returns:
        dict: Summary with odds_stored, api_calls.
    """
    from ..models import db, OddsConfig, OddsFixture, OddsData
    from .api_football import APIFootballClient

    config = OddsConfig.query.filter_by(site_id=site_id).first()
    odds_fixture = db.session.get(OddsFixture, odds_fixture_id)
    if not odds_fixture or odds_fixture.site_id != site_id:
        return {'error': 'Fixture not found'}

    try:
        bookmaker_ids = json.loads(config.bookmaker_ids) if config and config.bookmaker_ids else []
    except (json.JSONDecodeError, TypeError):
        bookmaker_ids = []

    try:
        markets = json.loads(config.markets) if config and config.markets else ['h2h']
    except (json.JSONDecodeError, TypeError):
        markets = ['h2h']

    from flask import current_app
    api_key = current_app.config.get('API_FOOTBALL_KEY', '')
    if not api_key:
        return {'error': 'API_FOOTBALL_KEY not configured'}

    client = APIFootballClient(api_key)
    odds_stored = 0

    try:
        odds_response = client.get_odds(odds_fixture.fixture_id)
    except Exception as e:
        return {'error': str(e)}

    if not odds_response:
        return {'odds_stored': 0, 'api_calls': 1}

    for response_item in odds_response:
        for bk in response_item.get('bookmakers', []):
            bk_id = bk.get('id')
            bk_name = bk.get('name', '')

            if bookmaker_ids and bk_id not in bookmaker_ids:
                continue

            for bet in bk.get('bets', []):
                bet_name = bet.get('name', '')
                market_key = MARKET_MAP.get(bet_name)
                if not market_key or market_key not in markets:
                    continue

                for val in bet.get('values', []):
                    outcome_raw = str(val.get('value', ''))
                    odds_val = val.get('odd')
                    if odds_val is None:
                        continue
                    try:
                        odds_float = float(odds_val)
                    except (ValueError, TypeError):
                        continue

                    outcome = OUTCOME_MAP.get(outcome_raw, outcome_raw)

                    existing = OddsData.query.filter_by(
                        odds_fixture_id=odds_fixture.id,
                        bookmaker_id=bk_id,
                        market=market_key,
                        outcome=outcome,
                    ).first()

                    if existing:
                        existing.odds_value = odds_float
                        existing.last_updated = datetime.now(timezone.utc)
                    else:
                        db.session.add(OddsData(
                            odds_fixture_id=odds_fixture.id,
                            bookmaker_id=bk_id,
                            bookmaker_name=bk_name,
                            market=market_key,
                            outcome=outcome,
                            odds_value=odds_float,
                        ))
                        odds_stored += 1

    odds_fixture.updated_at = datetime.now(timezone.utc)
    db.session.commit()

    return {'odds_stored': odds_stored, 'api_calls': client._request_count}


def run_odds_fetch_background(app, site_id):
    """Launch the odds fetcher in a background daemon thread."""
    import threading

    def _run():
        with app.app_context():
            try:
                result = fetch_odds(site_id, app=app)
                logger.info('Odds fetch completed for site %d: %s', site_id, result)
            except Exception as e:
                logger.error('Odds fetch failed for site %d: %s', site_id, e)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    logger.info('Odds fetch started in background for site %d', site_id)
