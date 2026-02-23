"""Static site builder service.

Renders generated content into static HTML files using a SEPARATE
Jinja2 Environment pointed at site_templates/ — NOT Flask's render_template.
"""

import hashlib
import json
import os
import shutil
from datetime import datetime, timezone

import jinja2

from markupsafe import Markup

from ..models import db, Site, SitePage, SiteBrand
from .schema_generator import generate_schema


def _generate_favicon_svg(site_name, vertical_slug):
    """Generate an SVG favicon using site name initials and a colour from the vertical."""
    # Pick initials: first letter of first two words, or first two letters
    words = site_name.split()
    if len(words) >= 2:
        initials = (words[0][0] + words[1][0]).upper()
    else:
        initials = site_name[:2].upper()

    # Derive a hue from the vertical slug for colour variety
    hue = int(hashlib.md5(vertical_slug.encode()).hexdigest()[:4], 16) % 360
    bg_colour = f'hsl({hue}, 55%, 45%)'

    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
<rect width="32" height="32" rx="6" fill="{bg_colour}"/>
<text x="16" y="22" text-anchor="middle" font-size="15" font-weight="700"
      font-family="system-ui, sans-serif" fill="#fff">{initials}</text>
</svg>'''


# Inline SVG payment method icons (monochrome, 28x18)
PAYMENT_ICON_MAP = {
    'visa': Markup('<svg width="28" height="18" viewBox="0 0 28 18" fill="none" xmlns="http://www.w3.org/2000/svg"><rect width="28" height="18" rx="2" fill="#1a1f71" opacity="0.15"/><text x="14" y="12" text-anchor="middle" font-size="7" font-weight="700" font-family="sans-serif" fill="#1a1f71">VISA</text></svg>'),
    'mastercard': Markup('<svg width="28" height="18" viewBox="0 0 28 18" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="11" cy="9" r="6" fill="#eb001b" opacity="0.25"/><circle cx="17" cy="9" r="6" fill="#f79e1b" opacity="0.25"/></svg>'),
    'maestro': Markup('<svg width="28" height="18" viewBox="0 0 28 18" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="11" cy="9" r="6" fill="#0099df" opacity="0.25"/><circle cx="17" cy="9" r="6" fill="#000" opacity="0.15"/></svg>'),
    'bank-transfer': Markup('<svg width="28" height="18" viewBox="0 0 28 18" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M14 2l9 4H5l9-4z" fill="#64748b" opacity="0.4"/><rect x="7" y="7" width="2" height="6" rx="0.5" fill="#64748b" opacity="0.4"/><rect x="13" y="7" width="2" height="6" rx="0.5" fill="#64748b" opacity="0.4"/><rect x="19" y="7" width="2" height="6" rx="0.5" fill="#64748b" opacity="0.4"/><rect x="5" y="14" width="18" height="2" rx="0.5" fill="#64748b" opacity="0.4"/></svg>'),
    'skrill': Markup('<svg width="28" height="18" viewBox="0 0 28 18" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="14" cy="9" r="7" fill="#862165" opacity="0.2"/><text x="14" y="12" text-anchor="middle" font-size="8" font-weight="700" font-family="sans-serif" fill="#862165">S</text></svg>'),
    'neteller': Markup('<svg width="28" height="18" viewBox="0 0 28 18" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="14" cy="9" r="7" fill="#3bab37" opacity="0.2"/><text x="14" y="12" text-anchor="middle" font-size="8" font-weight="700" font-family="sans-serif" fill="#3bab37">N</text></svg>'),
    'paypal': Markup('<svg width="28" height="18" viewBox="0 0 28 18" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="14" cy="9" r="7" fill="#003087" opacity="0.2"/><text x="14" y="12" text-anchor="middle" font-size="7" font-weight="700" font-family="sans-serif" fill="#003087">PP</text></svg>'),
    'bitcoin': Markup('<svg width="28" height="18" viewBox="0 0 28 18" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="14" cy="9" r="7" fill="#f7931a" opacity="0.2"/><text x="14" y="12.5" text-anchor="middle" font-size="9" font-weight="700" font-family="sans-serif" fill="#f7931a">&#x20BF;</text></svg>'),
    'opay': Markup('<svg width="28" height="18" viewBox="0 0 28 18" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="14" cy="9" r="7" fill="#1dcf9f" opacity="0.2"/><text x="14" y="12" text-anchor="middle" font-size="7" font-weight="700" font-family="sans-serif" fill="#1dcf9f">OPay</text></svg>'),
    'palmpay': Markup('<svg width="28" height="18" viewBox="0 0 28 18" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="14" cy="9" r="7" fill="#8b5cf6" opacity="0.2"/><text x="14" y="12" text-anchor="middle" font-size="8" font-weight="700" font-family="sans-serif" fill="#8b5cf6">P</text></svg>'),
    'm-pesa': Markup('<svg width="28" height="18" viewBox="0 0 28 18" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="14" cy="9" r="7" fill="#4caf50" opacity="0.2"/><text x="14" y="12" text-anchor="middle" font-size="8" font-weight="700" font-family="sans-serif" fill="#4caf50">M</text></svg>'),
    'mpesa': Markup('<svg width="28" height="18" viewBox="0 0 28 18" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="14" cy="9" r="7" fill="#4caf50" opacity="0.2"/><text x="14" y="12" text-anchor="middle" font-size="8" font-weight="700" font-family="sans-serif" fill="#4caf50">M</text></svg>'),
    'mtn-mobile-money': Markup('<svg width="28" height="18" viewBox="0 0 28 18" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="14" cy="9" r="7" fill="#ffcc00" opacity="0.25"/><text x="14" y="12" text-anchor="middle" font-size="6" font-weight="700" font-family="sans-serif" fill="#996600">MTN</text></svg>'),
    'mtn': Markup('<svg width="28" height="18" viewBox="0 0 28 18" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="14" cy="9" r="7" fill="#ffcc00" opacity="0.25"/><text x="14" y="12" text-anchor="middle" font-size="6" font-weight="700" font-family="sans-serif" fill="#996600">MTN</text></svg>'),
}


def _get_site_templates_path():
    """Return the absolute path to the site_templates/ directory."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'site_templates')


def _get_jinja_env():
    """Create a Jinja2 Environment for site templates (NOT Flask's)."""
    templates_path = _get_site_templates_path()
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader(templates_path),
        autoescape=jinja2.select_autoescape(['html', 'xml']),
    )


def _page_url_for_link(page):
    """Return the absolute URL string for a page, used in nav/footer links."""
    pt_slug = page.page_type.slug
    if pt_slug == 'homepage':
        return '/'
    elif pt_slug == 'comparison':
        return f'/{page.slug}'
    elif pt_slug == 'evergreen':
        if page.nav_parent_id and page.nav_parent:
            return f'/{page.nav_parent.slug}/{page.slug}'
        return f'/{page.slug}'
    elif pt_slug == 'brand-review':
        return f'/reviews/{page.slug}'
    elif pt_slug == 'bonus-review':
        return f'/bonuses/{page.slug}'
    elif pt_slug == 'news':
        return '/news'
    elif pt_slug == 'news-article':
        return f'/news/{page.slug}'
    elif pt_slug == 'tips':
        return '/tips'
    elif pt_slug == 'tips-article':
        return f'/tips/{page.slug}'
    return f'/{page.slug}'


def _page_display_title(page):
    """Return a human-readable title for a page.

    Prefers nav_label, then hero_title from AI-generated content, then
    page.title. Falls back to a humanised slug if everything else is slug-like.
    """
    if page.nav_label:
        return page.nav_label
    # Try AI-generated hero_title from content_json
    if page.content_json:
        try:
            hero = json.loads(page.content_json).get('hero_title')
            if hero:
                return hero
        except (json.JSONDecodeError, TypeError):
            pass
    return page.title or page.slug


def _build_nav_links(site_pages):
    """Build navigation links from site pages, supporting one level of dropdowns.

    Returns a list of link dicts. Top-level items with children include a
    'children' key. The Home link is always first and never has children.

    show_in_nav is the single source of truth for nav visibility.
    Top-level: show_in_nav=True and no parent.
    Children: show_in_nav=True and nav_parent_id set.
    """
    links = [{'url': '/', 'label': 'Home', 'type': 'homepage'}]

    top_level_pages = [p for p in site_pages if p.show_in_nav and p.nav_parent_id is None]
    child_pages = [p for p in site_pages if p.show_in_nav and p.nav_parent_id is not None]

    if top_level_pages or child_pages:
        # Group children by parent
        children_by_parent = {}
        for p in child_pages:
            children_by_parent.setdefault(p.nav_parent_id, []).append(p)

        top_level_pages.sort(key=lambda p: (p.nav_order, p.id))

        for p in top_level_pages:
            entry = {'url': _page_url_for_link(p), 'label': p.nav_label or p.title, 'type': p.page_type.slug}

            kids = children_by_parent.get(p.id, [])
            if kids:
                kids.sort(key=lambda c: (c.nav_order, c.id))
                entry['children'] = [
                    {'url': _page_url_for_link(c), 'label': c.nav_label or c.title, 'type': c.page_type.slug}
                    for c in kids
                ]

            links.append(entry)
    else:
        # Legacy fallback for unconfigured sites
        comparison = [p for p in site_pages if p.page_type.slug == 'comparison']
        if comparison:
            links.append({'url': f'/{comparison[0].slug}', 'label': 'Compare', 'type': 'comparison'})

        evergreen = [p for p in site_pages if p.page_type.slug == 'evergreen']
        for p in evergreen:
            links.append({'url': f'/{p.slug}', 'label': p.title, 'type': 'evergreen'})

    return links


def _build_footer_links(site_pages):
    """Build structured footer links from site pages.

    If any page has show_in_footer=True (menu configured), returns a categorized
    dict for the 3-column footer. Otherwise returns None for legacy fallback.
    """
    footer_pages = [p for p in site_pages if p.show_in_footer]

    if not footer_pages:
        return None

    footer_pages.sort(key=lambda p: (p.nav_order, p.id))

    brand_reviews = []
    guides = []
    bonuses = []

    for p in footer_pages:
        label = p.nav_label or p.title
        url = _page_url_for_link(p)
        pt_slug = p.page_type.slug
        entry = {'url': url, 'label': label, 'type': pt_slug}
        if pt_slug == 'brand-review':
            brand_reviews.append(entry)
        elif pt_slug == 'bonus-review':
            bonuses.append(entry)
        else:
            guides.append(entry)

    return {
        'brand_reviews': brand_reviews,
        'guides': guides,
        'bonuses': bonuses,
    }


def _build_brand_info_list(site, geo):
    """Build a list of brand info dicts for template use.

    Merges three layers: brand (global) → brand_geo (GEO-specific) → override (site-specific).
    Null override fields fall back to the base value.
    """
    brands = []
    for sb in sorted(site.site_brands, key=lambda sb: sb.rank):
        brand = sb.brand
        bg = next((bg for bg in brand.brand_geos if bg.geo_id == geo.id), None)
        ov = sb.override  # SiteBrandOverride or None

        brands.append({
            'name': brand.name,
            'slug': brand.slug,
            'logo_filename': brand.logo_filename,
            'affiliate_link': (ov.custom_affiliate_link if ov and ov.custom_affiliate_link else None) or brand.affiliate_link or '#',
            'website_url': brand.website_url or '#',
            'rating': brand.rating,
            'welcome_bonus': (ov.custom_welcome_bonus if ov and ov.custom_welcome_bonus else None) or (bg.welcome_bonus if bg else None),
            'bonus_code': (ov.custom_bonus_code if ov and ov.custom_bonus_code else None) or (bg.bonus_code if bg else None),
            'rank': sb.rank,
            'founded_year': brand.founded_year,
            'parent_company': brand.parent_company,
            'support_methods': brand.support_methods,
            'support_email': brand.support_email,
            'available_languages': brand.available_languages,
            'has_ios_app': brand.has_ios_app,
            'has_android_app': brand.has_android_app,
            'description': (ov.custom_description if ov and ov.custom_description else None) or brand.description,
            'license_info': bg.license_info if bg else None,
            'payment_methods': bg.payment_methods if bg else None,
            'withdrawal_timeframe': bg.withdrawal_timeframe if bg else None,
            'rating_bonus': bg.rating_bonus if bg else None,
            'rating_usability': bg.rating_usability if bg else None,
            'rating_mobile_app': bg.rating_mobile_app if bg else None,
            'rating_payments': bg.rating_payments if bg else None,
            'rating_support': bg.rating_support if bg else None,
            'rating_licensing': bg.rating_licensing if bg else None,
            'rating_rewards': bg.rating_rewards if bg else None,
        })
    return brands


def _build_brand_lookup(brand_info_list):
    """Build a dict mapping slug/name to brand info for template lookups."""
    lookup = {}
    for b in brand_info_list:
        lookup[b['slug']] = b
        lookup[b['name']] = b
    return lookup


def _build_sitemap_pages(site_pages, domain):
    """Build sitemap page entries."""
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    pages = []

    for page in site_pages:
        pt_slug = page.page_type.slug
        if pt_slug == 'homepage':
            url = ''
        elif pt_slug == 'comparison':
            url = page.slug
        elif pt_slug == 'brand-review':
            url = f'reviews/{page.slug}'
        elif pt_slug == 'bonus-review':
            url = f'bonuses/{page.slug}'
        elif pt_slug == 'news':
            url = 'news'
        elif pt_slug == 'news-article':
            url = f'news/{page.slug}'
        elif pt_slug == 'tips':
            url = 'tips'
        elif pt_slug == 'tips-article':
            url = f'tips/{page.slug}'
        elif pt_slug == 'evergreen':
            if page.nav_parent_id and page.nav_parent:
                url = f'{page.nav_parent.slug}/{page.slug}'
            else:
                url = f'{page.slug}'
        else:
            continue

        pages.append({
            'url': url,
            'lastmod': page.generated_at.strftime('%Y-%m-%d') if page.generated_at else now,
        })

    return pages


def _build_cta_table_data(cta_table, brand_info_list, geo):
    """Build CTA table data dict for template rendering.

    Includes full brand info so cards render correctly even when
    CTA table brands aren't in the site's SiteBrand list.
    """
    brand_map = {b['slug']: b for b in brand_info_list}
    rows = []
    for row in cta_table.rows:
        if not row.is_visible:
            continue
        brand = row.brand
        brand_info = brand_map.get(brand.slug, {})
        bg = next((bg for bg in brand.brand_geos if bg.geo_id == geo.id), None)
        rows.append({
            'rank': row.rank,
            'brand': {
                'name': brand.name,
                'slug': brand.slug,
                'logo_filename': brand.logo_filename,
                'rating': brand.rating,
                'affiliate_link': brand_info.get('affiliate_link') or (bg.affiliate_link if bg else None) or brand.affiliate_link or '#',
                'bonus_code': brand_info.get('bonus_code') or (bg.bonus_code if bg else None),
                'payment_methods': brand_info.get('payment_methods') or (bg.payment_methods if bg else None),
                'license_info': brand_info.get('license_info') or (bg.license_info if bg else None),
                'has_ios_app': brand.has_ios_app,
                'has_android_app': brand.has_android_app,
                'withdrawal_timeframe': brand_info.get('withdrawal_timeframe') or (bg.withdrawal_timeframe if bg else None),
            },
            'bonus_text': row.custom_bonus_text or (bg.welcome_bonus if bg else ''),
            'cta_text': row.custom_cta_text or 'Visit Site',
            'badge': row.custom_badge,
            'is_visible': row.is_visible,
        })
    return {
        'name': cta_table.name,
        'slug': cta_table.slug,
        'rows': rows,
    }


def build_site(site, output_base_dir, upload_folder):
    """Build a complete static site from generated content.

    Args:
        site: Site model instance (with relationships loaded)
        output_base_dir: Base output directory (e.g. 'output/')
        upload_folder: Path to uploads/ directory (for logo copying)

    Returns:
        str: Path to the built site version folder
    """
    env = _get_jinja_env()
    geo = site.geo
    vertical = site.vertical
    pages = site.site_pages
    version = site.current_version

    # Build output path — per-site isolation by ID
    site_dir = os.path.join(output_base_dir, str(site.id))
    version_dir = os.path.join(site_dir, f'v{version}')
    os.makedirs(version_dir, exist_ok=True)

    # Build shared context
    nav_links = _build_nav_links(pages)
    footer_links = _build_footer_links(pages)
    brand_info_list = _build_brand_info_list(site, geo)
    brand_lookup = _build_brand_lookup(brand_info_list)
    domain = site.domain.domain if site.domain else 'example.com'

    # Build cluster map: parent_id -> [child pages] for sidebar quick links
    cluster_map = {}
    for p in pages:
        if p.nav_parent_id is not None:
            cluster_map.setdefault(p.nav_parent_id, []).append(p)

    common_ctx = {
        'site_name': site.name,
        'language': geo.language,
        'vertical_name': vertical.name,
        'nav_links': nav_links,
        'footer_links': footer_links,
        'site_brands': brand_info_list,
        'brand_lookup': brand_lookup,
        'year': datetime.now().year,
        'payment_icon_map': PAYMENT_ICON_MAP,
    }

    # Render each page
    for page in pages:
        content = json.loads(page.content_json) if page.content_json else {}
        pt_slug = page.page_type.slug
        template_file = page.page_type.template_file

        # Resolve CTA table if assigned (8.2)
        cta_table_data = None
        if page.cta_table_id and page.cta_table:
            cta_table_data = _build_cta_table_data(page.cta_table, brand_info_list, geo)

        # Build cluster sidebar links: if page has a parent, show siblings;
        # if page IS a parent, show its children.
        cluster_links = []
        parent_id = page.nav_parent_id or (page.id if page.id in cluster_map else None)
        if parent_id is not None:
            siblings = cluster_map.get(parent_id, [])
            # Include the parent page itself as the first link
            parent_page = next((p for p in pages if p.id == parent_id), None)
            if parent_page and parent_page.id != page.id:
                cluster_links.append({
                    'url': _page_url_for_link(parent_page),
                    'label': _page_display_title(parent_page),
                })
            for sib in sorted(siblings, key=lambda s: (s.nav_order, s.id)):
                if sib.id != page.id:
                    cluster_links.append({
                        'url': _page_url_for_link(sib),
                        'label': _page_display_title(sib),
                    })

        ctx = {
            **common_ctx,
            'content': content,
            'page_title': page.title,
            'meta_title': page.meta_title or '',
            'meta_description': page.meta_description or '',
            'subdirectory': False,
            'cta_table': cta_table_data,
            'cluster_links': cluster_links,
            'custom_head': (site.custom_head or '') + '\n' + (page.custom_head or ''),
        }

        if pt_slug == 'homepage':
            output_file = os.path.join(version_dir, 'index.html')
            # Merge AI-generated top_brands data into site_brands for richer rendering
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
        elif pt_slug == 'comparison':
            output_file = os.path.join(version_dir, f'{page.slug}.html')
            # Merge AI-generated feature_badges into brand_lookup for comparison cards
            comp_rows = content.get('comparison_rows', [])
            comp_lookup = _build_brand_lookup(brand_info_list)
            for row in comp_rows:
                slug = row.get('slug', '')
                if slug and slug in comp_lookup:
                    comp_lookup[slug]['feature_badges'] = row.get('feature_badges', [])
            ctx['brand_lookup'] = comp_lookup
        elif pt_slug == 'brand-review':
            reviews_dir = os.path.join(version_dir, 'reviews')
            os.makedirs(reviews_dir, exist_ok=True)
            output_file = os.path.join(reviews_dir, f'{page.slug}.html')
            ctx['subdirectory'] = True
            brand_info = brand_lookup.get(page.slug) or brand_lookup.get(page.brand.slug if page.brand else '')
            ctx['brand_info'] = brand_info
            ctx['brand_slug'] = page.slug
            ctx['other_brands'] = [b for b in brand_info_list if b['slug'] != page.slug][:3]
            ctx['vertical_slug'] = vertical.slug
            ctx['geo'] = {'name': geo.name, 'code': geo.code, 'language': geo.language, 'currency': geo.currency}
        elif pt_slug == 'bonus-review':
            bonuses_dir = os.path.join(version_dir, 'bonuses')
            os.makedirs(bonuses_dir, exist_ok=True)
            output_file = os.path.join(bonuses_dir, f'{page.slug}.html')
            ctx['subdirectory'] = True
            brand_info = brand_lookup.get(page.slug) or brand_lookup.get(page.brand.slug if page.brand else '')
            ctx['brand_info'] = brand_info
            ctx['brand_slug'] = page.slug
            ctx['other_brands'] = [b for b in brand_info_list if b['slug'] != page.slug][:4]
        elif pt_slug == 'news':
            output_file = os.path.join(version_dir, 'news.html')
            # Collect news articles for listing
            news_articles = []
            for p in pages:
                if p.page_type.slug == 'news-article' and p.content_json:
                    p_content = json.loads(p.content_json) if p.content_json else {}
                    pub_date = p.published_date.strftime('%d %b %Y') if p.published_date else ''
                    news_articles.append({
                        'slug': p.slug,
                        'title': p.title,
                        'published_date': pub_date,
                        'summary': p_content.get('hero_subtitle', ''),
                    })
            # Sort by published_date descending (newest first)
            news_articles.sort(
                key=lambda a: a['published_date'],
                reverse=True,
            )
            ctx['news_articles'] = news_articles
        elif pt_slug == 'news-article':
            news_dir = os.path.join(version_dir, 'news')
            os.makedirs(news_dir, exist_ok=True)
            output_file = os.path.join(news_dir, f'{page.slug}.html')
            ctx['subdirectory'] = True
            ctx['published_date'] = page.published_date.strftime('%d %b %Y') if page.published_date else ''
        elif pt_slug == 'tips':
            output_file = os.path.join(version_dir, 'tips.html')
            tips_articles = []
            for p in pages:
                if p.page_type.slug == 'tips-article' and p.content_json:
                    p_content = json.loads(p.content_json) if p.content_json else {}
                    pub_date = p.published_date.strftime('%d %b %Y') if p.published_date else ''
                    match_info = p_content.get('match_info', {})
                    prediction = p_content.get('prediction', {})
                    tips_articles.append({
                        'slug': p.slug,
                        'title': p.title,
                        'published_date': pub_date,
                        'summary': p_content.get('hero_subtitle', ''),
                        'competition': match_info.get('competition', ''),
                        'match_date': match_info.get('date', pub_date),
                        'prediction_result': prediction.get('result', ''),
                        'prediction_confidence': prediction.get('confidence', ''),
                    })
            tips_articles.sort(
                key=lambda a: a['match_date'] or a['published_date'],
                reverse=True,
            )
            ctx['tips_articles'] = tips_articles
        elif pt_slug == 'tips-article':
            tips_dir = os.path.join(version_dir, 'tips')
            os.makedirs(tips_dir, exist_ok=True)
            output_file = os.path.join(tips_dir, f'{page.slug}.html')
            ctx['subdirectory'] = True
            ctx['published_date'] = page.published_date.strftime('%d %b %Y') if page.published_date else ''
            ctx['prediction'] = content.get('prediction', {})
            ctx['betting_tips'] = content.get('betting_tips', [])
            ctx['match_info'] = content.get('match_info', {})
        elif pt_slug == 'evergreen':
            if page.nav_parent_id and page.nav_parent:
                parent_dir = os.path.join(version_dir, page.nav_parent.slug)
                os.makedirs(parent_dir, exist_ok=True)
                output_file = os.path.join(parent_dir, f'{page.slug}.html')
                ctx['subdirectory'] = True
            else:
                output_file = os.path.join(version_dir, f'{page.slug}.html')
        else:
            continue

        # Generate JSON-LD schema markup (8.3)
        page_url = _build_sitemap_pages([page], domain)[0]['url'] if page else ''
        brand_info_for_schema = ctx.get('brand_info')
        rating_for_schema = brand_info_for_schema.get('rating') if brand_info_for_schema else None
        ctx['schema_json_ld'] = generate_schema(
            pt_slug, content, page.title, site.name, domain,
            f'/{page_url}', brand_info=brand_info_for_schema,
            rating=rating_for_schema, generated_at=page.generated_at,
        )

        template = env.get_template(template_file)
        html = template.render(**ctx)
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html)

    # Copy assets
    src_assets = os.path.join(_get_site_templates_path(), 'assets')
    dst_assets = os.path.join(version_dir, 'assets')
    if os.path.exists(dst_assets):
        shutil.rmtree(dst_assets)
    shutil.copytree(src_assets, dst_assets)

    # Copy brand logos
    logos_dir = os.path.join(dst_assets, 'logos')
    os.makedirs(logos_dir, exist_ok=True)
    src_logos = os.path.join(upload_folder, 'logos')
    for brand_info in brand_info_list:
        if brand_info['logo_filename']:
            src = os.path.join(src_logos, brand_info['logo_filename'])
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(logos_dir, brand_info['logo_filename']))

    # Generate favicon
    favicon_svg = _generate_favicon_svg(site.name, vertical.slug)
    with open(os.path.join(version_dir, 'favicon.svg'), 'w', encoding='utf-8') as f:
        f.write(favicon_svg)

    # Generate sitemap.xml
    sitemap_pages = _build_sitemap_pages(pages, domain)
    sitemap_template = env.get_template('sitemap.xml')
    sitemap_html = sitemap_template.render(domain=domain, pages=sitemap_pages)
    with open(os.path.join(version_dir, 'sitemap.xml'), 'w', encoding='utf-8') as f:
        f.write(sitemap_html)

    # Generate robots.txt
    if site.custom_robots_txt:
        robots_txt = site.custom_robots_txt
    else:
        robots_template = env.get_template('robots.txt')
        robots_txt = robots_template.render(domain=domain)
    with open(os.path.join(version_dir, 'robots.txt'), 'w', encoding='utf-8') as f:
        f.write(robots_txt)

    # Update site record
    site.output_path = version_dir
    site.status = 'built'
    site.built_at = datetime.now(timezone.utc)

    return version_dir
