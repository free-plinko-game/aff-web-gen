"""Content generation service using OpenAI API.

Handles prompt construction, API calls, content versioning,
and background thread orchestration.

IMPORTANT: Background threads must create their own app context
and DB session — never reuse the request's scoped session.
"""

import json
import logging
import threading
from datetime import datetime, timezone

from openai import OpenAI

logger = logging.getLogger(__name__)

from ..models import db, Site, SitePage, SiteBrand, ContentHistory, PageType


# --- Prompt Templates ---

PROMPT_TEMPLATES = {
    'homepage': """You are writing a {vertical_name} homepage for users in {geo_name}.
Language: {language}. Currency: {currency}.

Top brands (ranked): {brand_list}

Return a JSON object with:
- "hero_title": string (compelling headline, 8-12 words)
- "hero_subtitle": string (supporting tagline, 15-20 words)
- "intro_paragraph": string (2-3 sentences introducing the site)
- "top_brands": [{{ "name": string, "slug": string, "bonus": string, "rating": float, "short_description": string }}]
- "why_trust_us": string (2-3 sentences)
- "faq": [{{ "question": string, "answer": string }}] (3-5 FAQs)
- "closing_paragraph": string (1-2 sentences with call to action)

Write naturally in {language}. Use {currency} for all monetary values. Be informative and engaging.""",

    'comparison': """You are writing a {vertical_name} comparison page for users in {geo_name}.
Language: {language}. Currency: {currency}.

Brands to compare (in ranked order): {brand_list}

Return a JSON object with:
- "hero_title": string (comparison-focused headline)
- "hero_subtitle": string (15-20 words)
- "intro_paragraph": string (2-3 sentences)
- "comparison_rows": [{{ "brand": string, "slug": string, "bonus": string, "rating": float, "pros": [string], "cons": [string], "verdict": string }}]
- "faq": [{{ "question": string, "answer": string }}] (4-6 FAQs)
- "closing_paragraph": string (1-2 sentences)

Write naturally in {language}. Use {currency} for all monetary values. Be balanced and objective.""",

    'brand-review': """You are writing a detailed {vertical_name} review of {brand_name} for users in {geo_name}.
Language: {language}. Currency: {currency}.
Welcome Bonus: {welcome_bonus}

Return a JSON object with:
- "hero_title": string (review headline including brand name)
- "hero_subtitle": string
- "intro_paragraph": string (2-3 sentences overview)
- "rating": float (out of 5)
- "pros": [string] (4-6 pros)
- "cons": [string] (2-4 cons)
- "bonus_section": {{ "title": string, "description": string, "how_to_claim": [string] }}
- "features_review": string (3-4 paragraphs covering key features)
- "user_experience": string (2-3 paragraphs)
- "payment_methods": string (1-2 paragraphs)
- "verdict": string (2-3 sentences final verdict)
- "faq": [{{ "question": string, "answer": string }}] (3-5 FAQs)

Write naturally in {language}. Use {currency} for all monetary values. Be thorough and honest.""",

    'bonus-review': """You are writing a detailed bonus/welcome offer review for {brand_name} ({vertical_name}) for users in {geo_name}.
Language: {language}. Currency: {currency}.
Welcome Bonus: {welcome_bonus}
Bonus Code: {bonus_code}

Return a JSON object with:
- "hero_title": string (bonus-focused headline)
- "hero_subtitle": string
- "bonus_overview": {{ "offer": string, "code": string, "min_deposit": string, "wagering_requirements": string, "validity": string }}
- "how_to_claim": [string] (step-by-step, 4-6 steps)
- "terms_summary": string (2-3 paragraphs on key terms and conditions)
- "pros": [string] (3-5 pros of this bonus)
- "cons": [string] (2-3 cons or limitations)
- "similar_offers": string (1-2 paragraphs comparing to competitors)
- "verdict": string (2-3 sentences)
- "faq": [{{ "question": string, "answer": string }}] (3-5 FAQs)

Write naturally in {language}. Use {currency} for all monetary values.""",

    'evergreen': """You are writing an informational article about "{evergreen_topic}" for a {vertical_name} audience in {geo_name}.
Language: {language}. Currency: {currency}.

This is an evergreen content page — it should be educational, comprehensive, and SEO-friendly.

Return a JSON object with:
- "hero_title": string (SEO-optimized headline)
- "hero_subtitle": string
- "intro_paragraph": string (2-3 sentences)
- "sections": [{{ "heading": string, "content": string }}] (4-6 content sections, each 2-3 paragraphs)
- "key_takeaways": [string] (4-6 bullet points)
- "faq": [{{ "question": string, "answer": string }}] (4-6 FAQs)
- "closing_paragraph": string (1-2 sentences)

Write naturally in {language}. Use {currency} for monetary references. Be educational and authoritative.""",
}


def build_prompt(page_type_slug, geo, vertical, brands=None, brand=None,
                 brand_geo=None, evergreen_topic=None):
    """Construct the LLM prompt for a given page type and context."""
    template = PROMPT_TEMPLATES.get(page_type_slug, '')

    # Build brand list string for multi-brand pages
    brand_list = ''
    if brands:
        parts = []
        for sb in brands:
            bg = next((bg for bg in sb.brand.brand_geos if bg.geo_id == geo.id), None)
            bonus = bg.welcome_bonus if bg else 'N/A'
            parts.append(f"{sb.rank}. {sb.brand.name} (Bonus: {bonus}, Rating: {sb.brand.rating or 'N/A'}/5)")
        brand_list = '\n'.join(parts)

    return template.format(
        geo_name=geo.name,
        language=geo.language,
        currency=geo.currency,
        vertical_name=vertical.name,
        brand_list=brand_list,
        brand_name=brand.name if brand else '',
        welcome_bonus=brand_geo.welcome_bonus if brand_geo else 'N/A',
        bonus_code=brand_geo.bonus_code if brand_geo else 'N/A',
        evergreen_topic=evergreen_topic or '',
    )


def call_openai(prompt, api_key, model='gpt-4o-mini'):
    """Call the OpenAI API and return parsed JSON content."""
    logger.info('Calling OpenAI API (model=%s)', model)
    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {'role': 'system', 'content': 'You are a content writer. Always respond with valid JSON only, no markdown formatting.'},
            {'role': 'user', 'content': prompt},
        ],
        response_format={'type': 'json_object'},
        temperature=0.7,
    )
    content = response.choices[0].message.content
    return json.loads(content)


def generate_page_content(site_page, site, api_key, model='gpt-4o-mini'):
    """Generate content for a single page. Returns the parsed JSON content.

    This function handles prompt construction and the OpenAI call.
    It does NOT write to the DB — the caller handles persistence.
    """
    geo = site.geo
    vertical = site.vertical
    page_type_slug = site_page.page_type.slug

    # Gather context based on page type
    brands = None
    brand = None
    brand_geo = None
    evergreen_topic = None

    if page_type_slug in ('homepage', 'comparison'):
        brands = sorted(site.site_brands, key=lambda sb: sb.rank)
    elif page_type_slug in ('brand-review', 'bonus-review'):
        brand = site_page.brand
        brand_geo = next((bg for bg in brand.brand_geos if bg.geo_id == geo.id), None)
    elif page_type_slug == 'evergreen':
        evergreen_topic = site_page.evergreen_topic

    prompt = build_prompt(
        page_type_slug, geo, vertical,
        brands=brands, brand=brand, brand_geo=brand_geo,
        evergreen_topic=evergreen_topic,
    )

    return call_openai(prompt, api_key, model), prompt


def save_content_to_page(site_page, content_json_data, session):
    """Save generated content to a site_page, with versioning.

    If the page already has content, the old content is saved
    to content_history before being overwritten.
    """
    now = datetime.now(timezone.utc)

    # Content versioning: save old content to history if it exists
    if site_page.content_json and site_page.is_generated:
        max_version = (
            session.query(ContentHistory.version)
            .filter_by(site_page_id=site_page.id)
            .order_by(ContentHistory.version.desc())
            .first()
        )
        next_version = (max_version[0] + 1) if max_version else 1

        history = ContentHistory(
            site_page_id=site_page.id,
            content_json=site_page.content_json,
            generated_at=site_page.generated_at or now,
            version=next_version,
        )
        session.add(history)

    site_page.content_json = json.dumps(content_json_data)
    site_page.is_generated = True
    site_page.generated_at = now


def generate_site_content_background(app, site_id, api_key, model='gpt-4o-mini'):
    """Background thread function to generate content for all pages of a site.

    IMPORTANT: Creates its own app context and DB session — does not
    reuse the request's scoped session.
    """
    with app.app_context():
        site = db.session.get(Site, site_id)
        if not site:
            return

        logger.info('Starting content generation for site %d (%s)', site_id, site.name)
        site.status = 'generating'
        db.session.commit()

        pages = SitePage.query.filter_by(site_id=site_id).all()

        try:
            for i, page in enumerate(pages, 1):
                # Re-fetch to ensure fresh state
                page = db.session.get(SitePage, page.id)
                logger.info('Generating page %d/%d: %s', i, len(pages), page.title)
                content_data, _ = generate_page_content(page, site, api_key, model)
                save_content_to_page(page, content_data, db.session)
                db.session.commit()
        except Exception as e:
            logger.error('Content generation failed for site %d: %s', site_id, e)
            db.session.rollback()
            site = db.session.get(Site, site_id)
            site.status = 'failed'
            db.session.commit()
            return

        logger.info('Content generation complete for site %d', site_id)
        site = db.session.get(Site, site_id)
        site.status = 'generated'
        db.session.commit()


def start_generation(app, site_id, api_key, model='gpt-4o-mini'):
    """Launch content generation in a background thread."""
    thread = threading.Thread(
        target=generate_site_content_background,
        args=(app, site_id, api_key, model),
        daemon=True,
    )
    thread.start()
    return thread
