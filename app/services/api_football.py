"""API-Football client with rate limiting for the free tier.

Free tier: 100 requests/day. Each match uses ~3 additional requests
(H2H, odds, team stats). Default cap: 20 matches/day = ~66 requests.
"""

import logging
import os
from datetime import datetime, timedelta

import requests

logger = logging.getLogger(__name__)

API_BASE = 'https://v3.football.api-sports.io'
DEFAULT_MAX_MATCHES = 20


class APIFootballError(Exception):
    pass


class RateLimitError(APIFootballError):
    pass


class APIFootballClient:
    def __init__(self, api_key=None, max_matches_per_day=None):
        self.api_key = api_key or os.getenv('API_FOOTBALL_KEY', '')
        self.max_matches = max_matches_per_day or int(
            os.getenv('TIPS_MAX_MATCHES_PER_DAY', str(DEFAULT_MAX_MATCHES))
        )
        self._request_count = 0
        self.headers = {
            'x-apisports-key': self.api_key,
        }

    def _get(self, endpoint, params=None):
        """Make a rate-limited GET request."""
        if self._request_count >= 100:
            logger.warning('API-Football daily request limit reached (100)')
            raise RateLimitError('Daily API limit reached')

        url = f'{API_BASE}/{endpoint}'
        resp = requests.get(url, headers=self.headers, params=params, timeout=15)
        self._request_count += 1

        resp.raise_for_status()
        data = resp.json()

        if data.get('errors') and isinstance(data['errors'], dict) and data['errors']:
            error_msg = str(data['errors'])
            logger.error('API-Football error: %s', error_msg)
            raise APIFootballError(error_msg)

        return data.get('response', [])

    def get_fixtures(self, league_id, season, next_hours=48):
        """Fetch upcoming fixtures for a league within the next N hours."""
        now = datetime.utcnow()
        from_date = now.strftime('%Y-%m-%d')
        to_date = (now + timedelta(hours=next_hours)).strftime('%Y-%m-%d')

        return self._get('fixtures', {
            'league': league_id,
            'season': season,
            'from': from_date,
            'to': to_date,
            'status': 'NS',
        })

    def get_h2h(self, team1_id, team2_id, last=5):
        """Fetch head-to-head records between two teams."""
        return self._get('fixtures/headtohead', {
            'h2h': f'{team1_id}-{team2_id}',
            'last': last,
        })

    def get_odds(self, fixture_id):
        """Fetch pre-match odds for a fixture."""
        return self._get('odds', {
            'fixture': fixture_id,
        })

    def get_team_stats(self, team_id, league_id, season):
        """Fetch team statistics for the current season."""
        return self._get('teams/statistics', {
            'team': team_id,
            'league': league_id,
            'season': season,
        })


def build_match_data_package(client, fixture, league_id, season):
    """Build a comprehensive data package for a single fixture.

    Uses 3 additional API calls (H2H, odds, home team stats).
    Returns a dict ready for prompt construction.
    """
    fixture_info = fixture.get('fixture', {})
    teams = fixture.get('teams', {})
    home = teams.get('home', {})
    away = teams.get('away', {})
    league = fixture.get('league', {})

    package = {
        'fixture_id': fixture_info.get('id'),
        'date': fixture_info.get('date', ''),
        'venue': (fixture_info.get('venue') or {}).get('name', ''),
        'home_team': home.get('name', ''),
        'home_team_id': home.get('id'),
        'away_team': away.get('name', ''),
        'away_team_id': away.get('id'),
        'league_name': league.get('name', ''),
        'league_country': league.get('country', ''),
        'round': league.get('round', ''),
    }

    # H2H (1 request)
    try:
        h2h = client.get_h2h(home['id'], away['id'], last=5)
        package['h2h'] = [
            {
                'date': m.get('fixture', {}).get('date', ''),
                'home': m.get('teams', {}).get('home', {}).get('name', ''),
                'away': m.get('teams', {}).get('away', {}).get('name', ''),
                'score': f"{m.get('goals', {}).get('home', '?')}-{m.get('goals', {}).get('away', '?')}",
                'winner': (
                    m.get('teams', {}).get('home', {}).get('name', '')
                    if m.get('teams', {}).get('home', {}).get('winner')
                    else m.get('teams', {}).get('away', {}).get('name', '')
                    if m.get('teams', {}).get('away', {}).get('winner')
                    else 'Draw'
                ),
            }
            for m in h2h
        ]
    except Exception as e:
        logger.warning('H2H fetch failed for fixture %s: %s', package['fixture_id'], e)
        package['h2h'] = []

    # Odds (1 request)
    try:
        odds_data = client.get_odds(package['fixture_id'])
        package['odds'] = {}
        if odds_data:
            bookmakers = odds_data[0].get('bookmakers', [])
            if bookmakers:
                bets = bookmakers[0].get('bets', [])
                match_winner = next((b for b in bets if b.get('name') == 'Match Winner'), None)
                if match_winner:
                    package['odds']['match_winner'] = {
                        v['value']: v['odd'] for v in match_winner.get('values', [])
                    }
                over_under = next((b for b in bets if 'Over/Under' in (b.get('name') or '')), None)
                if over_under:
                    package['odds']['over_under'] = {
                        v['value']: v['odd'] for v in over_under.get('values', [])
                    }
                btts = next((b for b in bets if b.get('name') == 'Both Teams Score'), None)
                if btts:
                    package['odds']['btts'] = {
                        v['value']: v['odd'] for v in btts.get('values', [])
                    }
    except Exception as e:
        logger.warning('Odds fetch failed for fixture %s: %s', package['fixture_id'], e)
        package['odds'] = {}

    # Home team season stats (1 request)
    try:
        stats = client.get_team_stats(home['id'], league_id, season)
        if stats:
            package['home_stats'] = _extract_team_stats(stats)
        else:
            package['home_stats'] = {}
    except Exception as e:
        logger.warning('Stats fetch failed for %s: %s', home.get('name'), e)
        package['home_stats'] = {}

    return package


def _extract_team_stats(stats_response):
    """Extract key stats from team statistics response."""
    fixtures = stats_response.get('fixtures', {})
    goals = stats_response.get('goals', {})
    return {
        'played': fixtures.get('played', {}).get('total', 0),
        'wins': fixtures.get('wins', {}).get('total', 0),
        'draws': fixtures.get('draws', {}).get('total', 0),
        'losses': fixtures.get('loses', {}).get('total', 0),
        'goals_for': goals.get('for', {}).get('total', {}).get('total', 0),
        'goals_against': goals.get('against', {}).get('total', {}).get('total', 0),
        'form': stats_response.get('form', ''),
    }
