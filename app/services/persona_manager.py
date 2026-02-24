"""Generate AI bot personas for the comment system."""

import json
import logging

from flask import current_app

from ..models import db, CommentUser, Site
from .content_generator import call_openai

logger = logging.getLogger(__name__)

AVATAR_STYLES = ['bottts', 'avataaars', 'identicon', 'thumbs']


def generate_personas(site_id, count=10, app=None):
    """Generate bot personas for a site.

    Returns the number of newly created personas.
    """
    site = db.session.get(Site, site_id)
    if not site:
        raise ValueError(f'Site {site_id} not found')

    geo = site.geo

    if app:
        api_key = app.config.get('OPENAI_API_KEY', '')
        model = app.config.get('OPENAI_MODEL', 'gpt-4o-mini')
    else:
        api_key = current_app.config.get('OPENAI_API_KEY', '')
        model = current_app.config.get('OPENAI_MODEL', 'gpt-4o-mini')

    if not api_key:
        raise ValueError('OPENAI_API_KEY not configured')

    # Check existing usernames to avoid duplicates
    existing = {u.username for u in CommentUser.query.filter_by(site_id=site_id).all()}

    prompt = f"""Generate {count} unique commenter personas for a {geo.name} sports betting community forum.

Each persona should feel like a real person from {geo.name} who follows sports betting. Mix of casual bettors, sharp punters, and newbies.

For each persona provide:
- username: a realistic forum username (lowercase, no spaces, 6-15 chars). Avoid generic names like "user123".
- display_name: their display name
- avatar_style: one of {json.dumps(AVATAR_STYLES)}
- personality: 1-2 sentence description of their commenting style
- expertise_level: one of "novice", "intermediate", "expert"
- writing_style: one of "casual", "analytical", "enthusiastic", "sarcastic"
- typical_topics: array of 2-3 topics they usually comment about

Return a JSON object with key "personas" containing an array of persona objects."""

    result = call_openai(prompt, api_key, model, max_tokens=4096)
    personas = result.get('personas', [])

    created = 0
    for p in personas:
        username = p.get('username', '').strip().lower()
        if not username or username in existing:
            continue

        user = CommentUser(
            site_id=site_id,
            username=username,
            display_name=p.get('display_name', username),
            avatar_style=p.get('avatar_style', 'bottts'),
            avatar_seed=username,
            persona_json=json.dumps(p),
            is_bot=True,
        )
        db.session.add(user)
        existing.add(username)
        created += 1

    db.session.commit()
    logger.info('Created %d personas for site %d', created, site_id)
    return created
