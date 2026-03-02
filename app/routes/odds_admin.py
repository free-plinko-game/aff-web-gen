"""Admin routes for odds comparison management."""

import json
import logging

from flask import Blueprint, render_template, jsonify, request, current_app, abort

from ..models import db, Site, OddsConfig, OddsFixture, OddsData

logger = logging.getLogger(__name__)

bp = Blueprint('odds_admin', __name__, url_prefix='/sites')


@bp.route('/<int:site_id>/odds-comparison')
def odds_comparison(site_id):
    """Odds comparison admin page."""
    site = db.session.get(Site, site_id)
    if not site:
        abort(404)

    config = OddsConfig.query.filter_by(site_id=site_id).first()
    fixtures = (
        OddsFixture.query
        .filter_by(site_id=site_id)
        .order_by(OddsFixture.kickoff.asc())
        .all()
    )

    # Stats
    total_fixtures = len(fixtures)
    total_odds = OddsData.query.join(OddsFixture).filter(
        OddsFixture.site_id == site_id
    ).count()

    # Parse config for template
    bookmaker_ids = []
    manual_bookmakers = []
    markets = ['h2h']
    leagues = []
    if config:
        try:
            bookmaker_ids = json.loads(config.bookmaker_ids) if config.bookmaker_ids else []
        except (json.JSONDecodeError, TypeError):
            pass
        try:
            manual_bookmakers = json.loads(config.manual_bookmakers) if config.manual_bookmakers else []
        except (json.JSONDecodeError, TypeError):
            pass
        try:
            markets = json.loads(config.markets) if config.markets else ['h2h']
        except (json.JSONDecodeError, TypeError):
            pass
        try:
            leagues = json.loads(config.leagues) if config.leagues else []
        except (json.JSONDecodeError, TypeError):
            pass

    return render_template(
        'sites/odds_comparison.html',
        site=site,
        config=config,
        fixtures=fixtures,
        total_fixtures=total_fixtures,
        total_odds=total_odds,
        bookmaker_ids=bookmaker_ids,
        manual_bookmakers=manual_bookmakers,
        markets=markets,
        leagues_json=json.dumps(leagues, indent=2) if leagues else '',
    )


@bp.route('/<int:site_id>/odds-comparison/save-config', methods=['POST'])
def save_odds_config(site_id):
    """Save odds comparison configuration."""
    site = db.session.get(Site, site_id)
    if not site:
        return jsonify({'error': 'Site not found'}), 404

    data = request.get_json(silent=True) or {}

    config = OddsConfig.query.filter_by(site_id=site_id).first()
    if not config:
        config = OddsConfig(site_id=site_id)
        db.session.add(config)

    if 'enabled' in data:
        config.enabled = bool(data['enabled'])
    if 'bookmaker_ids' in data:
        config.bookmaker_ids = json.dumps(data['bookmaker_ids'])
    if 'manual_bookmakers' in data:
        config.manual_bookmakers = json.dumps(data['manual_bookmakers'])
    if 'markets' in data:
        config.markets = json.dumps(data['markets'])
    if 'leagues' in data:
        leagues = data['leagues']
        if isinstance(leagues, str):
            # Validate JSON
            try:
                parsed = json.loads(leagues)
                if not isinstance(parsed, list):
                    return jsonify({'error': 'leagues must be a JSON array'}), 400
                config.leagues = leagues
            except json.JSONDecodeError:
                return jsonify({'error': 'Invalid JSON for leagues'}), 400
        else:
            config.leagues = json.dumps(leagues)
    if 'lookahead_hours' in data:
        config.lookahead_hours = int(data['lookahead_hours'])

    db.session.commit()
    return jsonify({'success': True})


@bp.route('/<int:site_id>/odds-comparison/fetch', methods=['POST'])
def fetch_odds_now(site_id):
    """Manually trigger odds fetch for a site (background thread)."""
    site = db.session.get(Site, site_id)
    if not site:
        return jsonify({'error': 'Site not found'}), 404

    config = OddsConfig.query.filter_by(site_id=site_id).first()
    if not config or not config.enabled:
        return jsonify({'error': 'Odds comparison not enabled'}), 400

    from ..services.odds_fetcher import run_odds_fetch_background
    run_odds_fetch_background(current_app._get_current_object(), site_id)

    return jsonify({'success': True, 'message': 'Odds fetch started in background'})


@bp.route('/<int:site_id>/odds-comparison/fetch-fixture/<int:fixture_id>', methods=['POST'])
def fetch_fixture_odds(site_id, fixture_id):
    """Re-fetch odds for a single fixture."""
    from ..services.odds_fetcher import fetch_single_fixture_odds
    result = fetch_single_fixture_odds(site_id, fixture_id)
    if 'error' in result:
        return jsonify(result), 400
    return jsonify({'success': True, **result})


@bp.route('/<int:site_id>/odds-comparison/fixtures')
def list_odds_fixtures(site_id):
    """Return fixtures as JSON for the admin table."""
    site = db.session.get(Site, site_id)
    if not site:
        return jsonify({'error': 'Site not found'}), 404

    league_filter = request.args.get('league')
    status_filter = request.args.get('status')

    query = OddsFixture.query.filter_by(site_id=site_id)
    if league_filter:
        query = query.filter_by(league_name=league_filter)
    if status_filter:
        query = query.filter_by(status=status_filter)

    fixtures = query.order_by(OddsFixture.kickoff.asc()).all()

    result = []
    for f in fixtures:
        # Count unique bookmakers with odds for this fixture
        bookie_count = db.session.query(
            db.func.count(db.func.distinct(OddsData.bookmaker_id))
        ).filter_by(odds_fixture_id=f.id).scalar() or 0

        result.append({
            'id': f.id,
            'fixture_id': f.fixture_id,
            'league_name': f.league_name,
            'home_team': f.home_team,
            'away_team': f.away_team,
            'kickoff': f.kickoff.isoformat() if f.kickoff else '',
            'status': f.status,
            'bookmaker_count': bookie_count,
            'updated_at': f.updated_at.isoformat() if f.updated_at else '',
        })

    # Get distinct leagues for filter dropdown
    leagues = db.session.query(OddsFixture.league_name).filter_by(
        site_id=site_id
    ).distinct().order_by(OddsFixture.league_name).all()

    return jsonify({
        'fixtures': result,
        'leagues': [l[0] for l in leagues],
        'total': len(result),
    })
