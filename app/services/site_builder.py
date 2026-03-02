"""Static site builder service.

Renders generated content into static HTML files using a SEPARATE
Jinja2 Environment pointed at site_templates/ — NOT Flask's render_template.
"""

import hashlib
import json
import logging
import os
import shutil
from datetime import datetime, timezone

import jinja2

from markupsafe import Markup

logger = logging.getLogger(__name__)

from ..models import db, Author, Site, SitePage, SiteBrand, OddsConfig, OddsFixture, OddsData
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
    'children' key.

    show_in_nav is the single source of truth for nav visibility.
    Top-level: show_in_nav=True and no parent.
    Children: show_in_nav=True and nav_parent_id set.
    """
    links = []

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
    # Sort by brand rating descending (highest score first)
    rows.sort(key=lambda r: r['brand'].get('rating') or 0, reverse=True)
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
    # Auto-sweep dead internal links before building
    from .link_sweeper import sweep_dead_links
    sweep_result = sweep_dead_links(site.id, fix=True)
    if sweep_result['fixed']:
        logger.info('Pre-build sweep: fixed %d dead link(s) in %d page(s)',
                     sweep_result['fixed'], sweep_result['pages_updated'])

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

    # Build sets of brand slugs that have actual pages (for conditional linking)
    review_slugs = {p.slug for p in pages if p.page_type.slug == 'brand-review'}
    bonus_slugs = {p.slug for p in pages if p.page_type.slug == 'bonus-review'}

    # Build author data for bylines and author pages
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
        'review_slugs': review_slugs,
        'bonus_slugs': bonus_slugs,
        'has_authors': len(authors) > 0,
        'cache_bust': int(datetime.now().timestamp()),
    }

    # Build odds fixture lookup for cross-linking tips → odds
    odds_link_by_fixture_id = {}
    odds_link_by_teams = {}
    odds_config = OddsConfig.query.filter_by(site_id=site.id).first()
    if odds_config and odds_config.enabled:
        for ofx in OddsFixture.query.filter_by(site_id=site.id, status='upcoming').all():
            url = f'/odds/{ofx.league_slug}/{ofx.slug}'
            odds_link_by_fixture_id[ofx.fixture_id] = url
            teams_key = f'{ofx.home_team} vs {ofx.away_team}'.lower()
            odds_link_by_teams[teams_key] = url

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
            'comments_enabled': getattr(site, 'comments_enabled', False),
            'comments_api_url': getattr(site, 'comments_api_url', '') or '',
            'site_id': site.id,
            'page_slug': page.slug,
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
                    if p.author_id and p.author_id in author_map and p.page_type.slug in hp_content_types:
                        author_counts[p.author_id] = author_counts.get(p.author_id, 0) + 1
                for a in authors:
                    entry = dict(author_map[a.id])
                    entry['article_count'] = author_counts.get(a.id, 0)
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
            news_dir = os.path.join(version_dir, 'news')
            os.makedirs(news_dir, exist_ok=True)
            output_file = os.path.join(news_dir, 'index.html')
            ctx['subdirectory'] = True
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
            tips_dir = os.path.join(version_dir, 'tips')
            os.makedirs(tips_dir, exist_ok=True)
            output_file = os.path.join(tips_dir, 'index.html')
            ctx['subdirectory'] = True
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
            # Cross-link to odds page if available
            odds_url = None
            if page.fixture_id:
                odds_url = odds_link_by_fixture_id.get(page.fixture_id)
            if not odds_url:
                odds_url = odds_link_by_teams.get(page.title.lower() if page.title else '')
            ctx['odds_comparison_url'] = odds_url
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

        # Inject author byline
        page_author = author_map.get(page.author_id) if page.author_id else None
        ctx['page_author'] = page_author

        # Generate JSON-LD schema markup (8.3)
        page_url = _build_sitemap_pages([page], domain)[0]['url'] if page else ''
        brand_info_for_schema = ctx.get('brand_info')
        rating_for_schema = brand_info_for_schema.get('rating') if brand_info_for_schema else None
        ctx['schema_json_ld'] = generate_schema(
            pt_slug, content, page.title, site.name, domain,
            f'/{page_url}', brand_info=brand_info_for_schema,
            rating=rating_for_schema, generated_at=page.generated_at,
            author_info=page_author,
        )

        template = env.get_template(template_file)
        html = template.render(**ctx)
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html)

    # Generate author pages
    if authors:
        author_articles = {}
        content_types = {'brand-review', 'bonus-review', 'evergreen', 'news-article', 'tips-article'}
        for p in pages:
            if p.author_id and p.author_id in author_map and p.page_type.slug in content_types:
                date = p.published_date or p.generated_at
                author_articles.setdefault(p.author_id, []).append({
                    'title': p.title, 'slug': p.slug,
                    'url': _page_url_for_link(p).lstrip('/'),
                    'type': p.page_type.slug,
                    'published_date': date.strftime('%d %b %Y') if date else '',
                })

        authors_dir = os.path.join(version_dir, 'authors')
        os.makedirs(authors_dir, exist_ok=True)

        for a in authors:
            info = author_map[a.id]
            author_url = f'/authors/{a.slug}'
            author_ctx = {
                **common_ctx,
                'author': info,
                'author_articles': author_articles.get(a.id, []),
                'subdirectory': True,
                'page_title': f'{a.name} — {a.role or "Author"}',
                'meta_title': f'{a.name} — {info["role"] or "Author"} at {site.name}',
                'meta_description': info['short_bio'] or '',
                'page_author': None, 'cta_table': None, 'cluster_links': [],
                'custom_head': site.custom_head or '',
                'schema_json_ld': generate_schema(
                    'author', info, a.name, site.name, domain, author_url,
                ),
            }
            html = env.get_template('author.html').render(**author_ctx)
            with open(os.path.join(authors_dir, f'{a.slug}.html'), 'w', encoding='utf-8') as f:
                f.write(html)

        author_list = []
        for a in authors:
            entry = dict(author_map[a.id])
            entry['article_count'] = len(author_articles.get(a.id, []))
            author_list.append(entry)

        landing_ctx = {
            **common_ctx,
            'authors_list': author_list,
            'subdirectory': True,
            'page_title': 'Our Experts',
            'meta_title': f'Our Experts — {site.name}',
            'meta_description': f'Meet the team behind {site.name}',
            'page_author': None, 'cta_table': None, 'cluster_links': [],
            'custom_head': site.custom_head or '',
            'schema_json_ld': '',
        }
        html = env.get_template('authors.html').render(**landing_ctx)
        with open(os.path.join(authors_dir, 'index.html'), 'w', encoding='utf-8') as f:
            f.write(html)

    # ── Generate odds comparison pages ──────────────────────────────────
    odds_sitemap_pages = _build_odds_pages(
        env, site, common_ctx, brand_info_list, brand_lookup,
        review_slugs, pages, version_dir, domain,
    )

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

    # Copy author avatars
    if authors:
        avatars_src = os.path.join(upload_folder, 'avatars')
        avatars_dst = os.path.join(dst_assets, 'avatars')
        if os.path.isdir(avatars_src):
            os.makedirs(avatars_dst, exist_ok=True)
            for a in authors:
                if a.avatar_filename:
                    src = os.path.join(avatars_src, a.avatar_filename)
                    if os.path.exists(src):
                        shutil.copy2(src, os.path.join(avatars_dst, a.avatar_filename))

    # Generate favicon
    favicon_svg = _generate_favicon_svg(site.name, vertical.slug)
    with open(os.path.join(version_dir, 'favicon.svg'), 'w', encoding='utf-8') as f:
        f.write(favicon_svg)

    # Generate sitemap.xml
    sitemap_pages = _build_sitemap_pages(pages, domain)

    # Add author pages to sitemap
    if authors:
        now_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        for a in authors:
            sitemap_pages.append({'url': f'authors/{a.slug}', 'lastmod': now_str})
        sitemap_pages.append({'url': 'authors', 'lastmod': now_str})
    # Add odds pages to sitemap
    sitemap_pages.extend(odds_sitemap_pages)

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


# ── Odds comparison page builder ─────────────────────────────────────

MARKET_TITLES = {
    'h2h': 'Match Winner',
    'totals': 'Over/Under 2.5 Goals',
    'btts': 'Both Teams to Score',
    'double_chance': 'Double Chance',
}

MARKET_COLUMNS = {
    'h2h': ['Home', 'Draw', 'Away'],
    'totals': ['Over 2.5', 'Under 2.5'],
    'btts': ['Yes', 'No'],
    'double_chance': ['Home/Draw', 'Home/Away', 'Draw/Away'],
}


def _build_odds_pages(env, site, common_ctx, brand_info_list, brand_lookup,
                      review_slugs, pages, version_dir, domain):
    """Generate static odds hub, league, and fixture pages.

    Returns a list of sitemap entries for the generated odds pages.
    """
    config = OddsConfig.query.filter_by(site_id=site.id).first()
    if not config or not config.enabled:
        return []

    odds_fixtures = (
        OddsFixture.query
        .filter_by(site_id=site.id, status='upcoming')
        .order_by(OddsFixture.kickoff.asc())
        .all()
    )

    if not odds_fixtures:
        return []

    try:
        manual_bookmakers = json.loads(config.manual_bookmakers) if config.manual_bookmakers else []
    except (json.JSONDecodeError, TypeError):
        manual_bookmakers = []

    try:
        configured_markets = json.loads(config.markets) if config.markets else ['h2h']
    except (json.JSONDecodeError, TypeError):
        configured_markets = ['h2h']

    # Build brand lookup for affiliate links of manual bookmakers
    manual_bk_info = []
    for mb in manual_bookmakers:
        brand_slug = mb.get('brand_slug', '')
        brand = brand_lookup.get(brand_slug)
        affiliate_url = brand['affiliate_link'] if brand else '#'
        review_url = f'/reviews/{brand_slug}' if brand_slug in review_slugs else None
        manual_bk_info.append({
            'name': mb.get('name', brand_slug),
            'brand_slug': brand_slug,
            'affiliate_url': affiliate_url,
            'review_url': review_url,
            'is_manual': True,
        })

    # Build tips article lookup for cross-linking (fixture_id -> slug)
    tips_by_fixture_id = {}
    tips_by_teams = {}
    for p in pages:
        if p.page_type.slug == 'tips-article':
            if p.fixture_id:
                tips_by_fixture_id[p.fixture_id] = f'/tips/{p.slug}'
            # Also index by team names for fuzzy matching
            title_lower = (p.title or '').lower()
            tips_by_teams[title_lower] = f'/tips/{p.slug}'

    # Group fixtures by league
    fixtures_by_league = {}
    league_info = {}
    for fx in odds_fixtures:
        ls = fx.league_slug or 'other'
        fixtures_by_league.setdefault(ls, []).append(fx)
        if ls not in league_info:
            league_info[ls] = {'name': fx.league_name, 'slug': ls}

    sitemap_entries = []
    now_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')

    # Create /odds/ directory
    odds_dir = os.path.join(version_dir, 'odds')
    os.makedirs(odds_dir, exist_ok=True)

    # Helper: build fixture display data
    def _fixture_display(fx):
        kickoff_str = ''
        if fx.kickoff:
            kickoff_str = fx.kickoff.strftime('%d %b %Y, %H:%M')

        # Get best h2h odds for inline display
        best_odds = {}
        h2h_data = OddsData.query.filter_by(
            odds_fixture_id=fx.id, market='h2h'
        ).all()
        for od in h2h_data:
            current_best = best_odds.get(od.outcome)
            if current_best is None or od.odds_value > current_best:
                best_odds[od.outcome] = od.odds_value

        best_display = {}
        if best_odds.get('Home'):
            best_display['home'] = f'{best_odds["Home"]:.2f}'
        if best_odds.get('Draw'):
            best_display['draw'] = f'{best_odds["Draw"]:.2f}'
        if best_odds.get('Away'):
            best_display['away'] = f'{best_odds["Away"]:.2f}'

        return {
            'home_team': fx.home_team,
            'away_team': fx.away_team,
            'home_logo': fx.home_logo,
            'away_logo': fx.away_logo,
            'league_name': fx.league_name,
            'league_slug': fx.league_slug,
            'slug': fx.slug,
            'kickoff_display': kickoff_str,
            'best_odds': best_display,
        }

    # Helper: build market tables for a fixture
    def _build_market_tables(fx, configured_markets, manual_bk_info):
        tables = []
        for market_key in configured_markets:
            title = MARKET_TITLES.get(market_key, market_key)
            columns = MARKET_COLUMNS.get(market_key, [])

            odds_records = OddsData.query.filter_by(
                odds_fixture_id=fx.id, market=market_key
            ).all()

            if not odds_records and not manual_bk_info:
                continue

            # Group by bookmaker
            by_bookie = {}
            for od in odds_records:
                bk_key = od.bookmaker_id
                if bk_key not in by_bookie:
                    review_url = None
                    # Try to find review page for this bookmaker
                    bk_slug = od.bookmaker_name.lower().replace(' ', '-').replace("'", '')
                    if bk_slug in review_slugs:
                        review_url = f'/reviews/{bk_slug}'
                    by_bookie[bk_key] = {
                        'name': od.bookmaker_name,
                        'review_url': review_url,
                        'is_manual': False,
                        'odds': {},
                    }
                by_bookie[bk_key]['odds'][od.outcome] = od.odds_value

            rows = list(by_bookie.values())
            rows.sort(key=lambda r: r['name'])

            # Add manual bookmakers at the end
            for mb in manual_bk_info:
                rows.append(mb)

            # Calculate best odds per column
            best = {}
            for col in columns:
                vals = [r['odds'].get(col) for r in rows if not r.get('is_manual') and r.get('odds', {}).get(col)]
                if vals:
                    best[col] = max(vals)

            if rows:
                tables.append({
                    'title': title,
                    'columns': columns,
                    'rows': rows,
                    'best': best,
                })

        return tables

    # ── Generate fixture pages ──
    for fx in odds_fixtures:
        league_dir = os.path.join(odds_dir, fx.league_slug or 'other')
        os.makedirs(league_dir, exist_ok=True)

        fx_display = _fixture_display(fx)
        market_tables = _build_market_tables(fx, configured_markets, manual_bk_info)

        # Cross-link to tips article
        tips_url = tips_by_fixture_id.get(fx.fixture_id)
        if not tips_url:
            match_key = f'{fx.home_team} vs {fx.away_team}'.lower()
            tips_url = tips_by_teams.get(match_key)

        # Find best overall bookmaker (most frequent best odds)
        best_bookmaker = None
        if market_tables:
            bk_counts = {}
            for mt in market_tables:
                for col, best_val in mt['best'].items():
                    for row in mt['rows']:
                        if not row.get('is_manual') and row.get('odds', {}).get(col) == best_val:
                            name = row['name']
                            bk_counts[name] = bk_counts.get(name, 0) + 1
            if bk_counts:
                best_name = max(bk_counts, key=bk_counts.get)
                # Find affiliate URL for this bookmaker
                bk_brand = brand_lookup.get(best_name.lower().replace(' ', '-'))
                best_bookmaker = {
                    'name': best_name,
                    'affiliate_url': bk_brand['affiliate_link'] if bk_brand else '#',
                }

        last_updated = fx.updated_at.strftime('%d %b %Y, %H:%M UTC') if fx.updated_at else now_str

        # SportsEvent schema
        schema = _sports_event_schema(fx, site.name, domain)

        fixture_ctx = {
            **common_ctx,
            'fixture_data': fx_display,
            'market_tables': market_tables,
            'tips_article_url': tips_url,
            'best_bookmaker': best_bookmaker,
            'last_updated': last_updated,
            'subdirectory': True,
            'asset_prefix': '../../',
            'page_title': f'{fx.home_team} vs {fx.away_team} Odds',
            'meta_title': f'{fx.home_team} vs {fx.away_team} Odds Comparison — {site.name}',
            'meta_description': f'Compare betting odds for {fx.home_team} vs {fx.away_team}. Find the best odds from top bookmakers.',
            'page_author': None,
            'cta_table': None,
            'cluster_links': [],
            'custom_head': site.custom_head or '',
            'schema_json_ld': schema,
            'comments_enabled': False,
            'comments_api_url': '',
            'site_id': site.id,
            'page_slug': f'odds-{fx.slug}',
        }

        html = env.get_template('odds_fixture.html').render(**fixture_ctx)
        output_file = os.path.join(league_dir, f'{fx.slug}.html')
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html)

        sitemap_entries.append({
            'url': f'odds/{fx.league_slug}/{fx.slug}',
            'lastmod': now_str,
        })

    # ── Generate league pages ──
    for league_slug, league_fixtures in fixtures_by_league.items():
        league_dir = os.path.join(odds_dir, league_slug)
        os.makedirs(league_dir, exist_ok=True)

        info = league_info[league_slug]
        fx_displays = [_fixture_display(fx) for fx in league_fixtures]

        league_ctx = {
            **common_ctx,
            'league_name': info['name'],
            'league_slug': league_slug,
            'league_fixtures': fx_displays,
            'subdirectory': True,
            'asset_prefix': '../../',
            'page_title': f'{info["name"]} Odds Comparison',
            'meta_title': f'{info["name"]} Odds Comparison — {site.name}',
            'meta_description': f'Compare betting odds for upcoming {info["name"]} fixtures. Best odds from top bookmakers.',
            'page_author': None,
            'cta_table': None,
            'cluster_links': [],
            'custom_head': site.custom_head or '',
            'schema_json_ld': '',
            'comments_enabled': False,
            'comments_api_url': '',
            'site_id': site.id,
            'page_slug': f'odds-{league_slug}',
        }

        html = env.get_template('odds_league.html').render(**league_ctx)
        with open(os.path.join(league_dir, 'index.html'), 'w', encoding='utf-8') as f:
            f.write(html)

        sitemap_entries.append({
            'url': f'odds/{league_slug}',
            'lastmod': now_str,
        })

    # ── Generate odds hub page ──
    odds_leagues = list(league_info.values())
    odds_by_league = {
        ls: [_fixture_display(fx) for fx in fxs]
        for ls, fxs in fixtures_by_league.items()
    }

    hub_ctx = {
        **common_ctx,
        'odds_leagues': odds_leagues,
        'odds_by_league': odds_by_league,
        'odds_fixtures': odds_fixtures,
        'subdirectory': True,
        'page_title': 'Odds Comparison',
        'meta_title': f'Compare Betting Odds — {site.name}',
        'meta_description': f'Compare betting odds from top bookmakers. Find the best value for upcoming football matches.',
        'page_author': None,
        'cta_table': None,
        'cluster_links': [],
        'custom_head': site.custom_head or '',
        'schema_json_ld': '',
        'comments_enabled': False,
        'comments_api_url': '',
        'site_id': site.id,
        'page_slug': 'odds',
    }

    html = env.get_template('odds_hub.html').render(**hub_ctx)
    with open(os.path.join(odds_dir, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(html)

    sitemap_entries.append({'url': 'odds', 'lastmod': now_str})

    logger.info('Generated %d odds pages (%d fixtures, %d leagues)',
                len(sitemap_entries), len(odds_fixtures), len(fixtures_by_league))

    return sitemap_entries


def _sports_event_schema(fixture, site_name, domain):
    """Generate SportsEvent JSON-LD for a fixture odds page."""
    schema = {
        '@context': 'https://schema.org',
        '@type': 'SportsEvent',
        'name': f'{fixture.home_team} vs {fixture.away_team}',
        'startDate': fixture.kickoff.isoformat() if fixture.kickoff else '',
        'homeTeam': {
            '@type': 'SportsTeam',
            'name': fixture.home_team,
        },
        'awayTeam': {
            '@type': 'SportsTeam',
            'name': fixture.away_team,
        },
        'organizer': {
            '@type': 'SportsOrganization',
            'name': fixture.league_name or '',
        },
    }
    return f'<script type="application/ld+json">{json.dumps(schema, ensure_ascii=False)}</script>'
