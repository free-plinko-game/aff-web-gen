"""Content generation service using OpenAI API.

Handles prompt construction, API calls, content versioning,
and background thread orchestration.

IMPORTANT: Background threads must create their own app context
and DB session — never reuse the request's scoped session.
"""

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
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
- "hero_subtitle": string (2-3 sentences describing what visitors will find on this site)
- "hero_stats": [{{"number": string, "label": string}}] (exactly 3 impressive statistics)
- "trust_items": [string] (exactly 4 short trust signals, e.g. "Expert Reviewed")
- "section_title": string (heading for the brand listing, e.g. "Top Rated Betting Sites")
- "section_subtitle": string (one sentence explaining the ranking criteria)
- "top_brands": [{{"name": string, "slug": string, "bonus": string, "rating": float, "selling_points": [string, string, string]}}]
- "why_trust_us": string (2-3 paragraphs about review methodology)
- "faq": [{{"question": string, "answer": string}}] (4-5 FAQs)
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

NOTE: Factual data (ratings, bonus details, payment methods, company info) comes from the database and will be rendered separately. Focus ONLY on editorial content.

Return a JSON object with:
- "hero_title": string (review headline including brand name, 8-12 words)
- "hero_subtitle": string (15-20 words)
- "intro_paragraphs": [string] (2-3 paragraphs introducing the brand and what makes it notable)
- "pros": [string] (4-6 pros)
- "cons": [string] (2-4 cons)
- "features_sections": [{{ "heading": string, "content": string }}] (3-5 editorial sections, each 2-3 paragraphs covering different aspects like betting markets, live betting, promotions, etc.)
- "verdict": string (2-3 paragraphs final verdict and recommendation)
- "faq": [{{ "question": string, "answer": string }}] (4-6 FAQs)

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


# Max output tokens per model — avoids requesting more than the model supports
MODEL_MAX_TOKENS = {
    'gpt-4o-mini': 16384,
    'gpt-4o': 16384,
}
DEFAULT_MAX_TOKENS = 16384


def call_openai(prompt, api_key, model='gpt-4o-mini', max_retries=2, max_tokens=8192):
    """Call the OpenAI API and return parsed JSON content.

    Retries on JSON parse failures up to max_retries times.
    On finish_reason=length (truncated output), doubles max_tokens for the retry,
    capped at the model's maximum output token limit.
    """
    client = OpenAI(api_key=api_key)
    model_cap = MODEL_MAX_TOKENS.get(model, DEFAULT_MAX_TOKENS)
    current_max_tokens = min(max_tokens, model_cap)

    for attempt in range(1, max_retries + 2):
        logger.info('Calling OpenAI API (model=%s, attempt %d, max_tokens=%d)', model, attempt, current_max_tokens)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {'role': 'system', 'content': 'You are a content writer. Always respond with valid JSON only, no markdown formatting.'},
                {'role': 'user', 'content': prompt},
            ],
            response_format={'type': 'json_object'},
            temperature=0.7,
            max_tokens=current_max_tokens,
        )
        content = response.choices[0].message.content
        finish_reason = response.choices[0].finish_reason

        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.warning(
                'JSON parse failed (attempt %d/%d, finish_reason=%s): %s',
                attempt, max_retries + 1, finish_reason, e,
            )
            if finish_reason == 'length':
                current_max_tokens = min(current_max_tokens * 2, model_cap)
                logger.info('Increasing max_tokens to %d for next attempt', current_max_tokens)
            if attempt > max_retries:
                raise


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


def generate_page_content_with_notes(site_page, site, api_key, model='gpt-4o-mini'):
    """Generate content for a single page, appending regeneration_notes to the prompt.

    Like generate_page_content but incorporates any regeneration_notes from the page.
    Returns the parsed JSON content and the prompt used.
    """
    geo = site.geo
    vertical = site.vertical
    page_type_slug = site_page.page_type.slug

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

    # Append regeneration notes if present
    if site_page.regeneration_notes:
        prompt += f"\n\nAdditional instructions:\n{site_page.regeneration_notes}"

    return call_openai(prompt, api_key, model), prompt


def save_content_to_page_with_notes(site_page, content_json_data, session):
    """Save generated content, archiving regeneration_notes in history, then clearing them."""
    now = datetime.now(timezone.utc)

    # Content versioning: save old content + notes to history
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
            regeneration_notes=site_page.regeneration_notes,
            version=next_version,
        )
        session.add(history)

    site_page.content_json = json.dumps(content_json_data)
    site_page.is_generated = True
    site_page.generated_at = now
    # Clear regeneration notes — they've been consumed and archived
    site_page.regeneration_notes = None


def _generate_single_page_background(app, site_id, page_id, api_key, model='gpt-4o-mini'):
    """Background thread function to regenerate a single page with notes."""
    with app.app_context():
        site = db.session.get(Site, site_id)
        page = db.session.get(SitePage, page_id)
        if not site or not page or page.site_id != site.id:
            return

        try:
            content_data, _ = generate_page_content_with_notes(page, site, api_key, model)
            save_content_to_page_with_notes(page, content_data, db.session)
            db.session.commit()
            logger.info('Single page regeneration complete: page %d (%s)', page_id, page.title)
        except Exception as e:
            logger.error('Single page regeneration failed for page %d: %s', page_id, e)
            db.session.rollback()


def start_single_page_generation(app, site_id, page_id, api_key, model='gpt-4o-mini'):
    """Launch single-page regeneration in a background thread."""
    thread = threading.Thread(
        target=_generate_single_page_background,
        args=(app, site_id, page_id, api_key, model),
        daemon=True,
    )
    thread.start()
    return thread


# Number of concurrent OpenAI API calls during bulk generation
GENERATION_WORKERS = 5


def generate_site_content_background(app, site_id, api_key, model='gpt-4o-mini',
                                     only_new=False, previous_status='draft'):
    """Background thread function to generate content for all pages of a site.

    Uses a thread pool to make concurrent API calls (GENERATION_WORKERS at a time)
    for much faster generation of large sites. API calls are parallelized but
    all DB reads/writes stay in this single thread to avoid session conflicts.

    If only_new=True, only ungenerated pages are processed and the site
    status is restored to previous_status (e.g. 'built') instead
    of being reset to 'generated'.
    """
    with app.app_context():
        site = db.session.get(Site, site_id)
        if not site:
            return

        logger.info('Starting content generation for site %d (%s)', site_id, site.name)
        site.status = 'generating'
        db.session.commit()

        pages = SitePage.query.filter_by(site_id=site_id).all()
        if only_new:
            pages = [p for p in pages if not p.is_generated]

        # Phase 1: Build all prompts (DB reads — single thread)
        page_prompts = []
        for page in pages:
            page = db.session.get(SitePage, page.id)
            geo = site.geo
            vertical = site.vertical
            pt_slug = page.page_type.slug

            brands = None
            brand = None
            brand_geo = None
            evergreen_topic = None

            if pt_slug in ('homepage', 'comparison'):
                brands = sorted(site.site_brands, key=lambda sb: sb.rank)
            elif pt_slug in ('brand-review', 'bonus-review'):
                brand = page.brand
                brand_geo = next((bg for bg in brand.brand_geos if bg.geo_id == geo.id), None)
            elif pt_slug == 'evergreen':
                evergreen_topic = page.evergreen_topic

            prompt = build_prompt(
                pt_slug, geo, vertical,
                brands=brands, brand=brand, brand_geo=brand_geo,
                evergreen_topic=evergreen_topic,
            )
            page_prompts.append((page.id, page.title, prompt))

        # Phase 2: Make API calls concurrently (no DB access in workers)
        results = {}
        failed = False
        error_msg = ''

        def _call_api(page_id, title, prompt):
            logger.info('Generating page: %s (id=%d)', title, page_id)
            content = call_openai(prompt, api_key, model)
            logger.info('Completed page: %s (id=%d)', title, page_id)
            return page_id, content

        with ThreadPoolExecutor(max_workers=GENERATION_WORKERS) as executor:
            futures = {
                executor.submit(_call_api, pid, title, prompt): pid
                for pid, title, prompt in page_prompts
            }
            for future in as_completed(futures):
                pid = futures[future]
                try:
                    page_id, content_data = future.result()
                    results[page_id] = content_data
                except Exception as e:
                    logger.error('Content generation failed for page %d: %s', pid, e)
                    failed = True
                    error_msg = str(e)
                    for f in futures:
                        f.cancel()
                    break

        # Collect any remaining successfully completed futures
        if failed:
            for future, pid in futures.items():
                if pid not in results and future.done():
                    try:
                        page_id, content_data = future.result()
                        results[page_id] = content_data
                    except Exception:
                        pass

        # Phase 3: Save results to DB (single thread)
        try:
            for page_id, content_data in results.items():
                page = db.session.get(SitePage, page_id)
                save_content_to_page(page, content_data, db.session)
                db.session.commit()
        except Exception as e:
            logger.error('Failed saving content for site %d: %s', site_id, e)
            db.session.rollback()
            site = db.session.get(Site, site_id)
            site.status = 'failed'
            db.session.commit()
            return

        if failed:
            site = db.session.get(Site, site_id)
            site.status = 'failed'
            db.session.commit()
            logger.error('Content generation failed for site %d: %s', site_id, error_msg)
            return

        logger.info('Content generation complete for site %d', site_id)
        site = db.session.get(Site, site_id)
        if only_new and previous_status in ('built', 'deployed'):
            site.status = previous_status
        else:
            site.status = 'generated'
        db.session.commit()


def start_generation(app, site_id, api_key, model='gpt-4o-mini', only_new=False,
                     previous_status='draft'):
    """Launch content generation in a background thread."""
    thread = threading.Thread(
        target=generate_site_content_background,
        args=(app, site_id, api_key, model, only_new, previous_status),
        daemon=True,
    )
    thread.start()
    return thread
