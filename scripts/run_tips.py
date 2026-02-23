#!/usr/bin/env python3
"""Daily cron script for the betting tips pipeline.

Fetches upcoming fixtures, generates AI match tips, and publishes them
for all sites that have tips_leagues configured.

Usage:
    python scripts/run_tips.py

Cron (daily at 6am):
    0 6 * * * cd /opt/aff-web-gen && /opt/aff-web-gen/venv/bin/python scripts/run_tips.py >> /var/log/tips-pipeline.log 2>&1
"""

import logging
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger('tips_cron')


def main():
    from app import create_app
    from app.models import Site

    app = create_app()

    with app.app_context():
        # Find all sites with tips_leagues configured
        sites = Site.query.filter(Site.tips_leagues.isnot(None)).all()

        if not sites:
            logger.info('No sites have tips_leagues configured — nothing to do')
            return

        logger.info('Found %d site(s) with tips configured', len(sites))

        from app.services.tips_pipeline import fetch_and_generate_tips

        total_created = 0
        for site in sites:
            logger.info('Processing site %d: %s', site.id, site.name)
            try:
                count = fetch_and_generate_tips(site.id, app=app)
                total_created += count
                logger.info('Site %d: created %d new tips', site.id, count)
            except Exception as e:
                logger.error('Site %d failed: %s', site.id, e)

        logger.info('Tips pipeline complete. Total new tips created: %d', total_created)


if __name__ == '__main__':
    main()
