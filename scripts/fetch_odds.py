#!/usr/bin/env python3
"""Cron script for the odds comparison pipeline.

Fetches odds from API-Football for all sites with odds enabled,
then triggers a site rebuild so the static pages reflect the latest data.

Usage:
    python scripts/fetch_odds.py

Cron (twice daily at 6am and 6pm UTC):
    0 6,18 * * * cd /opt/aff-web-gen && /opt/aff-web-gen/venv/bin/python scripts/fetch_odds.py >> /var/log/odds-fetcher.log 2>&1
"""

import logging
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger('odds_cron')


def main():
    from app import create_app
    from app.models import OddsConfig

    app = create_app()

    with app.app_context():
        # Find all sites with odds enabled
        configs = OddsConfig.query.filter_by(enabled=True).all()

        if not configs:
            logger.info('No sites have odds enabled — nothing to do')
            return

        logger.info('Found %d site(s) with odds enabled', len(configs))

        from app.services.odds_fetcher import fetch_odds
        from app.services.site_builder import build_site
        from app.models import db, Site

        total_fixtures = 0
        total_odds = 0

        for config in configs:
            site = db.session.get(Site, config.site_id)
            if not site:
                continue

            logger.info('Processing site %d: %s', site.id, site.name)
            try:
                result = fetch_odds(site.id, app=app)
                total_fixtures += result.get('fixtures_updated', 0)
                total_odds += result.get('odds_stored', 0)
                logger.info('Site %d: %d fixtures updated, %d odds stored, %d API calls',
                            site.id, result['fixtures_updated'], result['odds_stored'],
                            result['api_calls'])
            except Exception as e:
                logger.error('Odds fetch failed for site %d: %s', site.id, e)
                continue

            # Rebuild site if there are fixtures
            if result.get('fixtures_updated', 0) > 0:
                try:
                    output_dir = os.path.join(app.root_path, '..', 'output')
                    upload_folder = app.config.get('UPLOAD_FOLDER', 'uploads')
                    build_site(site, output_dir, upload_folder)
                    site.current_version += 1
                    db.session.commit()
                    logger.info('Site %d rebuilt after odds fetch', site.id)

                    # Auto-deploy if previously deployed
                    if site.status == 'deployed' and site.domain:
                        try:
                            from app.services.deployer import deploy_site
                            deploy_site(site, app.config)
                            db.session.commit()
                            logger.info('Site %d auto-deployed after odds update', site.id)
                        except Exception as e:
                            logger.error('Auto-deploy failed for site %d: %s', site.id, e)
                except Exception as e:
                    logger.error('Build failed for site %d: %s', site.id, e)

        logger.info('Odds pipeline complete. Total: %d fixtures, %d odds',
                     total_fixtures, total_odds)


if __name__ == '__main__':
    main()
