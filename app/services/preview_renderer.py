"""In-memory page preview renderer.

Renders a page using the same Jinja2 templates as site_builder.py
but without writing to disk. Used for the live preview iframe.
"""

import json
from datetime import datetime

from .site_builder import (
    _get_jinja_env, _build_nav_links, _build_footer_links,
    _build_brand_info_list, _build_brand_lookup, _build_cta_table_data,
    _page_url_for_link, _page_display_title, PAYMENT_ICON_MAP,
)
from .schema_generator import generate_schema


def render_page_preview(site_page, site, asset_url_prefix=''):
    """Render a page to HTML string for preview.

    Args:
        site_page: SitePage model instance
        site: Site model instance (with relationships loaded)
        asset_url_prefix: URL prefix for assets (e.g. '/api/sites/1/preview-assets/')

    Returns:
        str: Rendered HTML string
    """
    env = _get_jinja_env()
    geo = site.geo
    vertical = site.vertical
    pages = site.site_pages
    domain = site.domain.domain if site.domain else 'example.com'

    nav_links = _build_nav_links(pages)
    footer_links = _build_footer_links(pages)
    brand_info_list = _build_brand_info_list(site, geo)
    brand_lookup = _build_brand_lookup(brand_info_list)

    content = json.loads(site_page.content_json) if site_page.content_json else {}
    pt_slug = site_page.page_type.slug
    template_file = site_page.page_type.template_file

    # For preview, override prefix to point at our asset-serving endpoint
    subdirectory = pt_slug in ('brand-review', 'bonus-review', 'news', 'news-article', 'tips', 'tips-article')

    # CTA table
    cta_table_data = None
    if site_page.cta_table_id and site_page.cta_table:
        cta_table_data = _build_cta_table_data(site_page.cta_table, brand_info_list, geo)

    # Build cluster sidebar links
    cluster_map = {}
    for p in pages:
        if p.nav_parent_id is not None:
            cluster_map.setdefault(p.nav_parent_id, []).append(p)

    cluster_links = []
    parent_id = site_page.nav_parent_id or (site_page.id if site_page.id in cluster_map else None)
    if parent_id is not None:
        siblings = cluster_map.get(parent_id, [])
        parent_page = next((p for p in pages if p.id == parent_id), None)
        if parent_page and parent_page.id != site_page.id:
            cluster_links.append({
                'url': _page_url_for_link(parent_page),
                'label': _page_display_title(parent_page),
            })
        for sib in sorted(siblings, key=lambda s: (s.nav_order, s.id)):
            if sib.id != site_page.id:
                cluster_links.append({
                    'url': _page_url_for_link(sib),
                    'label': _page_display_title(sib),
                })

    # Build sets of brand slugs that have actual pages (for conditional linking)
    review_slugs = {p.slug for p in pages if p.page_type.slug == 'brand-review'}
    bonus_slugs = {p.slug for p in pages if p.page_type.slug == 'bonus-review'}

    # Build author data for byline
    from ..models import Author
    authors = Author.query.filter_by(site_id=site.id, is_active=True).all()
    author_map = {}
    for a in authors:
        author_map[a.id] = {
            'name': a.name, 'slug': a.slug, 'role': a.role,
            'short_bio': a.short_bio, 'bio': a.bio,
            'avatar_filename': a.avatar_filename,
            'expertise': json.loads(a.expertise) if a.expertise else [],
            'social_links': json.loads(a.social_links) if a.social_links else {},
            'initials': ''.join(w[0] for w in a.name.split()[:2]).upper(),
            'color': f'hsl({hash(a.name) % 360}, 45%, 45%)',
        }
    page_author = author_map.get(site_page.author_id) if site_page.author_id else None

    ctx = {
        'site_name': site.name,
        'language': geo.language,
        'vertical_name': vertical.name,
        'nav_links': nav_links,
        'footer_links': footer_links,
        'site_brands': brand_info_list,
        'brand_lookup': brand_lookup,
        'year': datetime.now().year,
        'content': content,
        'page_title': site_page.title,
        'meta_title': site_page.meta_title or '',
        'meta_description': site_page.meta_description or '',
        'subdirectory': False,  # Preview is always served from root-level URL
        'cta_table': cta_table_data,
        'cluster_links': cluster_links,
        'schema_json_ld': '',  # Skip schema in preview
        'custom_head': (site.custom_head or '') + '\n' + (site_page.custom_head or ''),
        'payment_icon_map': PAYMENT_ICON_MAP,
        'review_slugs': review_slugs,
        'bonus_slugs': bonus_slugs,
        'page_author': page_author,
        'has_authors': len(authors) > 0,
        'comments_enabled': getattr(site, 'comments_enabled', False),
        'comments_api_url': getattr(site, 'comments_api_url', '') or '',
        'site_id': site.id,
        'page_slug': site_page.slug,
    }

    # Add page-type-specific context (same as site_builder.py)
    if pt_slug == 'homepage':
        top_brands_ai = content.get('top_brands', [])
        ai_map = {}
        for tb in top_brands_ai:
            if tb.get('slug'):
                ai_map[tb['slug']] = tb
            if tb.get('name'):
                ai_map[tb['name']] = tb
        enriched = []
        for b in brand_info_list:
            merged = dict(b)
            ai = ai_map.get(b['slug']) or ai_map.get(b['name'], {})
            merged['selling_points'] = ai.get('selling_points', [])
            merged['short_description'] = ai.get('short_description', '')
            merged['feature_badges'] = ai.get('feature_badges', [])
            enriched.append(merged)
        ctx['site_brands'] = enriched
        # Update brand_lookup so CTA table rows also get enriched data
        enriched_lookup = _build_brand_lookup(enriched)
        ctx['brand_lookup'] = enriched_lookup

        # --- Homepage hub data ---

        # Tips preview: 4 most recent tips-articles
        tips_preview = []
        for p in pages:
            if p.page_type.slug == 'tips-article' and p.content_json:
                p_content = json.loads(p.content_json)
                match_info = p_content.get('match_info', {})
                prediction = p_content.get('prediction', {})
                tips_preview.append({
                    'slug': p.slug, 'title': p.title,
                    'published_date': p.published_date.strftime('%d %b %Y') if p.published_date else '',
                    'summary': p_content.get('hero_subtitle', ''),
                    'competition': match_info.get('competition', ''),
                    'match_date': match_info.get('date', ''),
                    'prediction_result': prediction.get('result', ''),
                    'prediction_confidence': prediction.get('confidence', ''),
                })
        tips_preview.sort(key=lambda a: a['match_date'] or a['published_date'], reverse=True)
        ctx['tips_preview'] = tips_preview[:4]

        # News preview: 3 most recent news-articles
        news_preview = []
        for p in pages:
            if p.page_type.slug == 'news-article' and p.content_json:
                p_content = json.loads(p.content_json)
                pub_date = p.published_date.strftime('%d %b %Y') if p.published_date else ''
                p_author = author_map.get(p.author_id) if p.author_id else None
                news_preview.append({
                    'slug': p.slug, 'title': p.title, 'published_date': pub_date,
                    'summary': (p_content.get('hero_subtitle', '') or '')[:120],
                    'author_name': p_author['name'] if p_author else None,
                })
        news_preview.sort(key=lambda a: a['published_date'], reverse=True)
        ctx['news_preview'] = news_preview[:3]

        # Authors list with article counts
        hp_authors_list = []
        if authors:
            hp_content_types = {'brand-review', 'bonus-review', 'evergreen', 'news-article', 'tips-article'}
            author_counts = {}
            for p in pages:
                if p.author_id and p.page_type.slug in hp_content_types:
                    author_counts[p.author_id] = author_counts.get(p.author_id, 0) + 1
            for a_id, a_info in author_map.items():
                entry = dict(a_info)
                entry['article_count'] = author_counts.get(a_id, 0)
                hp_authors_list.append(entry)
        ctx['authors_list'] = hp_authors_list

        # Page counts for trust badges
        type_counts = {}
        for p in pages:
            type_counts[p.page_type.slug] = type_counts.get(p.page_type.slug, 0) + 1
        ctx['page_counts'] = {
            'tips': type_counts.get('tips-article', 0),
            'reviews': type_counts.get('brand-review', 0),
            'news': type_counts.get('news-article', 0),
            'brands': len(brand_info_list),
        }

        # Geo name and comparison URL for hero
        ctx['geo_name'] = geo.name
        compare_url = next((l['url'] for l in nav_links if l.get('type') == 'comparison'), None)
        ctx['compare_url'] = compare_url or '/'

    elif pt_slug == 'comparison':
        comp_rows = content.get('comparison_rows', [])
        comp_lookup = _build_brand_lookup(brand_info_list)
        for row in comp_rows:
            slug = row.get('slug', '')
            if slug and slug in comp_lookup:
                comp_lookup[slug]['feature_badges'] = row.get('feature_badges', [])
        ctx['brand_lookup'] = comp_lookup
    elif pt_slug == 'brand-review':
        brand_info = brand_lookup.get(site_page.slug) or brand_lookup.get(
            site_page.brand.slug if site_page.brand else '')
        ctx['brand_info'] = brand_info
        ctx['brand_slug'] = site_page.slug
        ctx['other_brands'] = [b for b in brand_info_list if b['slug'] != site_page.slug][:3]
        ctx['vertical_slug'] = vertical.slug
        ctx['geo'] = {'name': geo.name, 'code': geo.code, 'language': geo.language, 'currency': geo.currency}
    elif pt_slug == 'bonus-review':
        brand_info = brand_lookup.get(site_page.slug) or brand_lookup.get(
            site_page.brand.slug if site_page.brand else '')
        ctx['brand_info'] = brand_info
        ctx['brand_slug'] = site_page.slug
        ctx['other_brands'] = [b for b in brand_info_list if b['slug'] != site_page.slug][:4]
    elif pt_slug == 'news':
        news_articles = []
        for p in pages:
            if p.page_type.slug == 'news-article' and p.content_json:
                p_content = json.loads(p.content_json)
                pub_date = p.published_date.strftime('%d %b %Y') if p.published_date else ''
                news_articles.append({
                    'slug': p.slug,
                    'title': p.title,
                    'published_date': pub_date,
                    'summary': p_content.get('hero_subtitle', ''),
                })
        news_articles.sort(key=lambda a: a['published_date'], reverse=True)
        ctx['news_articles'] = news_articles
    elif pt_slug == 'news-article':
        ctx['published_date'] = site_page.published_date.strftime('%d %b %Y') if site_page.published_date else ''

    elif pt_slug == 'tips':
        tips_articles = []
        for p in pages:
            if p.page_type.slug == 'tips-article' and p.content_json:
                p_content = json.loads(p.content_json)
                pub_date = p.published_date.strftime('%d %b %Y') if p.published_date else ''
                prediction = p_content.get('prediction', {})
                match_info = p_content.get('match_info', {})
                tips_articles.append({
                    'slug': p.slug,
                    'title': p.title,
                    'published_date': pub_date,
                    'summary': p_content.get('hero_subtitle', ''),
                    'competition': match_info.get('competition', ''),
                    'match_date': match_info.get('date', ''),
                    'prediction_result': prediction.get('result', ''),
                    'prediction_confidence': prediction.get('confidence', ''),
                })
        tips_articles.sort(key=lambda a: a['published_date'], reverse=True)
        ctx['tips_articles'] = tips_articles

    elif pt_slug == 'tips-article':
        ctx['published_date'] = site_page.published_date.strftime('%d %b %Y') if site_page.published_date else ''
        ctx['prediction'] = content.get('prediction', {})
        ctx['betting_tips'] = content.get('betting_tips', [])
        ctx['match_info'] = content.get('match_info', {})
        ctx['key_stats'] = content.get('key_stats', [])

    # Override asset prefix for preview
    if asset_url_prefix:
        ctx['preview_asset_prefix'] = asset_url_prefix

    template = env.get_template(template_file)
    return template.render(**ctx)
