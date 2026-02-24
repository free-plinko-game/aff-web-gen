"""Seed AI-generated comments for article pages."""

import json
import logging
import random
from datetime import datetime, timedelta, timezone

from flask import current_app

from ..models import db, Comment, CommentUser, Site, SitePage
from .content_generator import call_openai
from ..routes.comments_api import seed_comment, seed_votes

logger = logging.getLogger(__name__)


def seed_comments_for_page(site_id, page_slug, page_title, app=None):
    """Generate and seed comments for a single page.

    Returns the number of comments created. Idempotent — skips if page
    already has comments.
    """
    # Skip if already has comments
    existing = Comment.query.filter_by(site_id=site_id, page_slug=page_slug).count()
    if existing > 0:
        logger.info('Page %s already has %d comments, skipping', page_slug, existing)
        return 0

    # Load bot personas
    bots = CommentUser.query.filter_by(site_id=site_id, is_bot=True).all()
    if len(bots) < 3:
        logger.warning('Site %d has only %d personas, need at least 3', site_id, len(bots))
        return 0

    # Load page content for context
    page = SitePage.query.filter_by(site_id=site_id, slug=page_slug).first()
    page_context = ''
    if page and page.content_json:
        try:
            content = json.loads(page.content_json)
            page_context = content.get('hero_subtitle', '')
            sections = content.get('sections', [])
            if sections:
                page_context += ' ' + sections[0].get('content', '')[:200]
        except (json.JSONDecodeError, TypeError):
            pass

    if app:
        api_key = app.config.get('OPENAI_API_KEY', '')
        model = app.config.get('OPENAI_MODEL', 'gpt-4o-mini')
    else:
        api_key = current_app.config.get('OPENAI_API_KEY', '')
        model = current_app.config.get('OPENAI_MODEL', 'gpt-4o-mini')

    if not api_key:
        logger.error('OPENAI_API_KEY not configured')
        return 0

    # Pick 3-6 random personas
    num_commenters = min(random.randint(3, 6), len(bots))
    selected_bots = random.sample(bots, num_commenters)

    # Build persona descriptions for prompt
    persona_descriptions = []
    for bot in selected_bots:
        persona = {}
        if bot.persona_json:
            try:
                persona = json.loads(bot.persona_json)
            except (json.JSONDecodeError, TypeError):
                pass
        persona_descriptions.append({
            'username': bot.username,
            'personality': persona.get('personality', 'casual sports fan'),
            'expertise_level': persona.get('expertise_level', 'intermediate'),
            'writing_style': persona.get('writing_style', 'casual'),
        })

    prompt = f"""Generate realistic user comments for a sports betting article titled "{page_title}".

Article context: {page_context[:300]}

Write comments as these users:
{json.dumps(persona_descriptions, indent=2)}

Rules:
- Each comment should be 1-3 sentences, feeling natural and conversational
- Comments should engage with the article content (agree, disagree, add insight, ask questions)
- Include 1-2 replies to other comments (use "reply_to" field with the username being replied to)
- Mix of substantive comments and casual reactions
- No promotional or spam-like content
- Keep it authentic — some mild disagreement is good

Return a JSON object with key "comments" containing an array of objects:
{{ "username": "...", "body": "...", "reply_to": null or "username_being_replied_to" }}"""

    try:
        result = call_openai(prompt, api_key, model, max_tokens=2048)
    except Exception as e:
        logger.error('OpenAI call failed for comment generation: %s', e)
        return 0

    comments_data = result.get('comments', [])
    if not comments_data:
        return 0

    # Map usernames to bot user objects
    bot_map = {b.username: b for b in bots}

    # Determine base time for staggering
    base_time = datetime.now(timezone.utc) - timedelta(hours=random.randint(2, 8))
    if page and page.published_date:
        base_time = page.published_date + timedelta(hours=random.randint(1, 4))

    # Create comments
    created_comments = {}  # username -> Comment (for reply linking)
    created_count = 0
    time_offset = 0

    for cd in comments_data:
        username = cd.get('username', '')
        body = cd.get('body', '').strip()
        reply_to = cd.get('reply_to')

        bot_user = bot_map.get(username)
        if not bot_user or not body:
            continue

        # Stagger timestamps
        time_offset += random.randint(5, 45)  # minutes apart
        comment_time = base_time + timedelta(minutes=time_offset)

        # Find parent if this is a reply
        parent_id = None
        if reply_to and reply_to in created_comments:
            parent_id = created_comments[reply_to].id

        comment = seed_comment(
            site_id=site_id,
            page_slug=page_slug,
            user_id=bot_user.id,
            body=body,
            parent_id=parent_id,
            created_at=comment_time,
        )
        created_comments[username] = comment
        created_count += 1

        # Seed votes
        if parent_id:
            seed_votes(comment, random.randint(1, 3), 0, bots)
        else:
            seed_votes(comment, random.randint(3, 8), random.randint(0, 1), bots)

    db.session.commit()
    logger.info('Seeded %d comments for page %s (site %d)', created_count, page_slug, site_id)
    return created_count
