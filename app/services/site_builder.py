"""Static site builder service.

Renders generated content into static HTML files using a SEPARATE
Jinja2 Environment pointed at site_templates/ — NOT Flask's render_template.
"""

import json
import os
import shutil
from datetime import datetime, timezone

import jinja2

from ..models import db, Site, SitePage, SiteBrand
from .schema_generator import generate_schema


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
    elif pt_slug in ('comparison', 'evergreen'):
        return f'/{page.slug}'
    elif pt_slug == 'brand-review':
        return f'/reviews/{page.slug}'
    elif pt_slug == 'bonus-review':
        return f'/bonuses/{page.slug}'
    elif pt_slug == 'evergreen':
        return f'/{page.slug}'
    return f'/{page.slug}'


def _build_nav_links(site_pages):
    """Build navigation links from site pages, supporting one level of dropdowns.

    Returns a list of link dicts. Top-level items with children include a
    'children' key. The Home link is always first and never has children.

    show_in_nav controls top-level visibility. Pages with nav_parent_id set
    appear in their parent's dropdown automatically (no show_in_nav needed).
    """
    links = [{'url': '/', 'label': 'Home', 'type': 'homepage'}]

    top_level_pages = [p for p in site_pages if p.show_in_nav and p.nav_parent_id is None]
    child_pages = [p for p in site_pages if p.nav_parent_id is not None]

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
        elif pt_slug == 'evergreen':
            url = f'{page.slug}'
        else:
            continue

        pages.append({
            'url': url,
            'lastmod': page.generated_at.strftime('%Y-%m-%d') if page.generated_at else now,
        })

    return pages


def _build_cta_table_data(cta_table, brand_info_list, geo):
    """Build CTA table data dict for template rendering."""
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
                'affiliate_link': brand_info.get('affiliate_link', brand.affiliate_link or '#'),
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

    common_ctx = {
        'site_name': site.name,
        'language': geo.language,
        'vertical_name': vertical.name,
        'nav_links': nav_links,
        'footer_links': footer_links,
        'site_brands': brand_info_list,
        'brand_lookup': brand_lookup,
        'year': datetime.now().year,
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

        ctx = {
            **common_ctx,
            'content': content,
            'page_title': page.title,
            'meta_title': page.meta_title or '',
            'meta_description': page.meta_description or '',
            'subdirectory': False,
            'cta_table': cta_table_data,
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
                enriched.append(merged)
            ctx['site_brands'] = enriched
        elif pt_slug == 'comparison':
            output_file = os.path.join(version_dir, f'{page.slug}.html')
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
        elif pt_slug == 'evergreen':
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
