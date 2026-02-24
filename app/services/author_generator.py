"""AI-powered author persona generator.

Generates culturally appropriate author personas based on site geo,
vertical, and brand context for E-E-A-T signals.
"""

import logging

from flask import current_app

from .content_generator import call_openai

logger = logging.getLogger(__name__)


def generate_author_personas(site, api_key=None):
    """Generate 3 author personas for a site using OpenAI.

    Args:
        site: Site model instance (with geo, vertical, site_brands loaded).
        api_key: OpenAI API key. Falls back to app config if not provided.

    Returns:
        list of dicts: [{name, slug, role, bio, short_bio, expertise}, ...]
    """
    if not api_key:
        api_key = current_app.config.get('OPENAI_API_KEY')
    if not api_key:
        raise ValueError('OpenAI API key not configured')

    geo_name = site.geo.name if site.geo else 'Global'
    language = site.geo.language if site.geo else 'English'
    currency = site.geo.currency if site.geo else 'USD'
    vertical_name = site.vertical.name if site.vertical else 'Betting'

    brand_names = [sb.brand.name for sb in sorted(site.site_brands, key=lambda x: x.rank)[:5]]
    brands_str = ', '.join(brand_names) if brand_names else 'various operators'

    prompt = (
        f"You are creating author personas for a {vertical_name} affiliate website "
        f"targeting {geo_name}. The site covers brands like {brands_str}.\n\n"
        f"Generate exactly 3 fictional author personas:\n"
        f"1. A senior betting/gambling analyst (data-driven, expert tone)\n"
        f"2. A sportsbook/casino reviewer (consumer-focused, practical)\n"
        f"3. A sports/gambling editor or journalist (news-oriented, editorial)\n\n"
        f"Requirements:\n"
        f"- Names MUST be culturally appropriate for {geo_name} "
        f"(e.g. Nigerian names for Nigeria, British names for UK, etc.)\n"
        f"- Bios should reference local context: leagues, regulations, "
        f"popular sports, {currency} currency, local gambling culture\n"
        f"- Each persona should feel authentic and credible\n"
        f"- Expertise tags should include local leagues, sports, and topics\n"
        f"- Write all content in {language}\n\n"
        f"Return a JSON object:\n"
        f'{{"authors": [\n'
        f"  {{\n"
        f'    "name": "Full Name",\n'
        f'    "role": "Job Title (3-5 words)",\n'
        f'    "short_bio": "One-sentence bio for bylines (under 120 chars)",\n'
        f'    "bio": "2-3 paragraph HTML bio with <p> tags. Include experience, '
        f'credentials, and local expertise. Make it feel real and authoritative.",\n'
        f'    "expertise": ["Tag 1", "Tag 2", "Tag 3", "Tag 4", "Tag 5"]\n'
        f"  }}\n"
        f"]}}\n\n"
        f"Return ONLY the JSON, no markdown fences."
    )

    model = current_app.config.get('OPENAI_MODEL', 'gpt-4o-mini')
    result = call_openai(prompt, api_key, model, max_tokens=4096)
    authors = result.get('authors', [])

    # Add slugs
    import re
    for a in authors:
        name = a.get('name', 'author')
        slug = re.sub(r'[^a-z0-9]+', '-', name.lower().strip()).strip('-')
        a['slug'] = slug

    logger.info('Generated %d author personas for site %d (%s)',
                len(authors), site.id, geo_name)

    return authors
