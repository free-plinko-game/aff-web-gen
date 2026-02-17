"""Schema markup generator for JSON-LD structured data.

Auto-generates JSON-LD blocks for each page type at build time.
Stateless — give it a page type and data, get back a JSON-LD string.
"""

import json
from datetime import datetime


def generate_schema(page_type_slug, content, page_title, site_name, domain,
                    page_url, brand_info=None, rating=None, generated_at=None):
    """Generate JSON-LD structured data for a page.

    Args:
        page_type_slug: e.g. 'homepage', 'brand-review', etc.
        content: parsed content_json dict
        page_title: the page title
        site_name: site name
        domain: the site's domain (e.g. 'bestbets.co.uk')
        page_url: relative page URL (e.g. '/reviews/bet365.html')
        brand_info: dict with brand data (for review pages)
        rating: float rating value (for review pages)
        generated_at: datetime of content generation (for datePublished)

    Returns:
        str: JSON-LD script tag(s) ready for injection into <head>, or empty string.
    """
    schemas = []
    base_url = f'https://{domain}'
    full_url = f'{base_url}{page_url}'
    date_str = generated_at.strftime('%Y-%m-%d') if generated_at else datetime.now().strftime('%Y-%m-%d')

    if page_type_slug == 'homepage':
        schemas.append(_website_schema(site_name, base_url))

    elif page_type_slug == 'brand-review':
        schemas.append(_review_schema(
            content, page_title, full_url, site_name,
            brand_info, rating, date_str,
        ))

    elif page_type_slug == 'bonus-review':
        schemas.append(_review_schema(
            content, page_title, full_url, site_name,
            brand_info, rating, date_str,
        ))

    elif page_type_slug == 'comparison':
        schemas.append(_itemlist_schema(content, full_url, site_name))

    elif page_type_slug == 'evergreen':
        schemas.append(_article_schema(
            content, page_title, full_url, site_name, date_str,
        ))

    # Append FAQPage schema if the content has FAQ data
    faq_schema = _faq_schema(content)
    if faq_schema:
        schemas.append(faq_schema)

    if not schemas:
        return ''

    # Render all schemas as script tags
    parts = []
    for schema in schemas:
        parts.append(
            f'<script type="application/ld+json">{json.dumps(schema, ensure_ascii=False)}</script>'
        )
    return '\n'.join(parts)


def _website_schema(site_name, base_url):
    """WebSite schema for homepage."""
    return {
        '@context': 'https://schema.org',
        '@type': 'WebSite',
        'name': site_name,
        'url': base_url,
    }


def _review_schema(content, page_title, full_url, site_name,
                   brand_info, rating, date_str):
    """Review schema for brand/bonus review pages."""
    schema = {
        '@context': 'https://schema.org',
        '@type': 'Review',
        'name': page_title,
        'url': full_url,
        'author': {
            '@type': 'Organization',
            'name': site_name,
        },
        'datePublished': date_str,
    }

    if brand_info:
        schema['itemReviewed'] = {
            '@type': 'Organization',
            'name': brand_info.get('name', ''),
        }
        if brand_info.get('website_url'):
            schema['itemReviewed']['url'] = brand_info['website_url']

    if rating is not None:
        schema['reviewRating'] = {
            '@type': 'Rating',
            'ratingValue': str(rating),
            'bestRating': '5',
            'worstRating': '1',
        }

    return schema


def _itemlist_schema(content, full_url, site_name):
    """ItemList schema for comparison pages."""
    schema = {
        '@context': 'https://schema.org',
        '@type': 'ItemList',
        'name': content.get('hero_title', 'Comparison'),
        'url': full_url,
    }

    rows = content.get('comparison_rows', [])
    if rows:
        items = []
        for i, row in enumerate(rows, 1):
            item = {
                '@type': 'ListItem',
                'position': i,
                'name': row.get('brand', row.get('name', '')),
            }
            if row.get('rating'):
                item['description'] = f"Rating: {row['rating']}/5"
            items.append(item)
        schema['itemListElement'] = items

    return schema


def _article_schema(content, page_title, full_url, site_name, date_str):
    """Article schema for evergreen content pages."""
    return {
        '@context': 'https://schema.org',
        '@type': 'Article',
        'headline': content.get('hero_title', page_title),
        'url': full_url,
        'datePublished': date_str,
        'dateModified': date_str,
        'author': {
            '@type': 'Organization',
            'name': site_name,
        },
        'publisher': {
            '@type': 'Organization',
            'name': site_name,
        },
    }


def _faq_schema(content):
    """FAQPage schema — appended to any page with FAQ content."""
    faqs = content.get('faq', [])
    if not faqs:
        return None

    items = []
    for faq in faqs:
        q = faq.get('question', '')
        a = faq.get('answer', '')
        if q and a:
            items.append({
                '@type': 'Question',
                'name': q,
                'acceptedAnswer': {
                    '@type': 'Answer',
                    'text': a,
                },
            })

    if not items:
        return None

    return {
        '@context': 'https://schema.org',
        '@type': 'FAQPage',
        'mainEntity': items,
    }
