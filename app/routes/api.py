import json
import logging
import os

from flask import Blueprint, jsonify, request, abort, Response, send_from_directory, current_app

from ..models import db, Brand, BrandGeo, BrandVertical, Site, SitePage, PageType
from ..services.content_generator import call_openai
from ..services.preview_renderer import render_page_preview

logger = logging.getLogger(__name__)

bp = Blueprint('api', __name__, url_prefix='/api')


@bp.route('/brands/filter')
def filter_brands():
    """Return brands filtered by GEO and vertical (for wizard Step 3)."""
    geo_id = request.args.get('geo_id', type=int)
    vertical_id = request.args.get('vertical_id', type=int)

    if not geo_id or not vertical_id:
        return jsonify([])

    # Find brands that are active in the given GEO AND assigned to the given vertical
    brands = (
        Brand.query
        .join(BrandGeo, Brand.id == BrandGeo.brand_id)
        .join(BrandVertical, Brand.id == BrandVertical.brand_id)
        .filter(
            BrandGeo.geo_id == geo_id,
            BrandGeo.is_active.is_(True),
            BrandVertical.vertical_id == vertical_id,
        )
        .order_by(Brand.name)
        .all()
    )

    return jsonify([
        {
            'id': b.id,
            'name': b.name,
            'slug': b.slug,
            'rating': b.rating,
            'logo_filename': b.logo_filename,
        }
        for b in brands
    ])


@bp.route('/sites/<int:site_id>/generation-status')
def generation_status(site_id):
    """Return the current generation progress for a site."""
    site = db.session.get(Site, site_id)
    if not site:
        return jsonify({'error': 'Site not found'}), 404

    total_pages = SitePage.query.filter_by(site_id=site_id).count()
    generated_pages = SitePage.query.filter_by(site_id=site_id, is_generated=True).count()

    return jsonify({
        'site_id': site_id,
        'status': site.status,
        'total_pages': total_pages,
        'generated_pages': generated_pages,
    })


@bp.route('/sites/<int:site_id>/rename', methods=['POST'])
def rename_site(site_id):
    """Rename a site."""
    site = db.session.get(Site, site_id)
    if not site:
        return jsonify({'error': 'Site not found'}), 404
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'Name is required'}), 400
    site.name = name
    db.session.commit()
    return jsonify({'success': True})


@bp.route('/sites/<int:site_id>/robots-txt', methods=['POST'])
def save_robots_txt(site_id):
    """Save or reset custom robots.txt for a site."""
    site = db.session.get(Site, site_id)
    if not site:
        return jsonify({'error': 'Site not found'}), 404

    data = request.get_json()
    if data is None:
        return jsonify({'error': 'Invalid JSON'}), 400

    content = data.get('content')
    site.custom_robots_txt = content  # None = reset to default
    db.session.commit()

    return jsonify({'success': True})


@bp.route('/sites/<int:site_id>/pages/<int:page_id>/preview')
def page_preview(site_id, page_id):
    """Render a live preview of a page (in-memory, no disk write)."""
    site = db.session.get(Site, site_id)
    if not site:
        return jsonify({'error': 'Site not found'}), 404

    page = db.session.get(SitePage, page_id)
    if not page or page.site_id != site.id:
        return jsonify({'error': 'Page not found'}), 404

    asset_prefix = f'/api/sites/{site_id}/preview-assets/'
    try:
        html = render_page_preview(page, site, asset_url_prefix=asset_prefix)
    except Exception as e:
        html = f'<html><body><h1>Preview Error</h1><pre>{e}</pre></body></html>'

    return Response(html, content_type='text/html; charset=utf-8')


@bp.route('/sites/<int:site_id>/preview-assets/<path:filename>')
def preview_assets(site_id, filename):
    """Serve static assets (CSS, JS, logos) for the live preview iframe."""
    from ..services.site_builder import _get_site_templates_path, _generate_favicon_svg

    # Generate favicon on the fly for previews
    if filename == 'favicon.svg':
        site = db.session.get(Site, site_id)
        if site:
            svg = _generate_favicon_svg(site.name, site.vertical.slug)
            return Response(svg, content_type='image/svg+xml')
        return '', 404

    # Serve from site_templates/assets/
    templates_path = _get_site_templates_path()
    assets_dir = os.path.join(templates_path, 'assets')

    # Check if it's a logo file — serve from uploads/logos/ instead
    if filename.startswith('logos/'):
        from flask import current_app
        upload_folder = current_app.config.get('UPLOAD_FOLDER', 'uploads')
        return send_from_directory(os.path.join(upload_folder, 'logos'), filename[6:])

    return send_from_directory(assets_dir, filename)


@bp.route('/page-csv-template')
def page_csv_template():
    """Serve a sample CSV template for bulk page upload."""
    csv_content = (
        "page_type,brand_slug,evergreen_topic\n"
        "homepage,,\n"
        "comparison,,\n"
        "brand-review,example-brand,\n"
        "bonus-review,example-brand,\n"
        "evergreen,,How to Choose a Betting Site\n"
        "evergreen,,Beginner Guide to Online Gambling\n"
    )
    return Response(
        csv_content,
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=page_import_template.csv'},
    )


@bp.route('/sites/<int:site_id>/suggest-pages', methods=['POST'])
def suggest_pages(site_id):
    """Analyze a site and suggest missing pages + AI-generated evergreen topics."""
    site = db.session.get(Site, site_id)
    if not site:
        return jsonify({'error': 'Site not found'}), 404

    # --- Gap analysis (pure DB logic) ---
    existing_pages = SitePage.query.filter_by(site_id=site.id).all()

    existing_global = {
        p.page_type.slug for p in existing_pages
        if p.brand_id is None and p.evergreen_topic is None
    }
    existing_brand_reviews = {
        p.brand_id for p in existing_pages
        if p.page_type.slug == 'brand-review' and p.brand_id
    }
    existing_bonus_reviews = {
        p.brand_id for p in existing_pages
        if p.page_type.slug == 'bonus-review' and p.brand_id
    }
    existing_evergreen_topics = [
        p.evergreen_topic for p in existing_pages
        if p.evergreen_topic
    ]

    missing_pages = []

    # Missing homepage / comparison
    if 'homepage' not in existing_global:
        missing_pages.append({
            'page_type': 'homepage',
            'brand_slug': '',
            'brand_name': '',
            'reason': 'Site has no homepage',
        })
    if 'comparison' not in existing_global:
        missing_pages.append({
            'page_type': 'comparison',
            'brand_slug': '',
            'brand_name': '',
            'reason': 'Site has no comparison page',
        })

    # Missing brand reviews / bonus reviews
    for sb in sorted(site.site_brands, key=lambda x: x.rank):
        if sb.brand_id not in existing_brand_reviews:
            missing_pages.append({
                'page_type': 'brand-review',
                'brand_slug': sb.brand.slug,
                'brand_name': sb.brand.name,
                'reason': f'No review page for {sb.brand.name}',
            })
        if sb.brand_id not in existing_bonus_reviews:
            missing_pages.append({
                'page_type': 'bonus-review',
                'brand_slug': sb.brand.slug,
                'brand_name': sb.brand.name,
                'reason': f'No bonus review for {sb.brand.name}',
            })

    # --- AI-generated evergreen suggestions ---
    suggested_evergreen = []
    api_key = current_app.config.get('OPENAI_API_KEY')
    if api_key:
        try:
            geo_name = site.geo.name if site.geo else 'Global'
            vertical_name = site.vertical.name if site.vertical else 'General'
            existing_topics_str = ', '.join(existing_evergreen_topics) if existing_evergreen_topics else 'None yet'

            prompt = (
                f"You are an SEO strategist for a {vertical_name} affiliate site targeting {geo_name}.\n"
                f"The site already has these evergreen content pages: {existing_topics_str}\n\n"
                f"Suggest 6-8 new evergreen article topics that would attract organic search traffic. "
                f"Each should be a compelling, SEO-friendly title.\n\n"
                f"Return a JSON object with:\n"
                f"- \"suggestions\": [{{\"topic\": string, \"keyword\": string, \"reason\": string}}]\n\n"
                f"Where:\n"
                f"- topic: The article title (5-10 words)\n"
                f"- keyword: Target SEO keyword (2-4 words)\n"
                f"- reason: Why this topic is valuable (1 sentence)\n\n"
                f"Do not repeat existing topics. Focus on {vertical_name} in {geo_name}."
            )

            model = current_app.config.get('OPENAI_MODEL', 'gpt-4o-mini')
            result = call_openai(prompt, api_key, model)
            suggested_evergreen = result.get('suggestions', [])
        except Exception as e:
            logger.warning('AI suggestion failed: %s', e)
            # Non-fatal — return gap analysis without AI suggestions

    return jsonify({
        'missing_pages': missing_pages,
        'suggested_evergreen': suggested_evergreen,
    })


@bp.route('/sites/<int:site_id>/suggest-news', methods=['POST'])
def suggest_news(site_id):
    """AI-generate 10 timely news article topic suggestions for a site."""
    site = db.session.get(Site, site_id)
    if not site:
        return jsonify({'error': 'Site not found'}), 404

    api_key = current_app.config.get('OPENAI_API_KEY')
    if not api_key:
        return jsonify({'error': 'OpenAI API key not configured'}), 500

    geo_name = site.geo.name if site.geo else 'Global'
    language = site.geo.language if site.geo else 'English'
    vertical_name = site.vertical.name if site.vertical else 'General'

    # Collect existing news-article topics to avoid duplicates
    existing_articles = [
        p.title for p in site.site_pages
        if p.page_type.slug == 'news-article'
    ]
    existing_str = ', '.join(existing_articles) if existing_articles else 'None yet'

    prompt = (
        f"You are a news editor for a {vertical_name} site targeting {geo_name}.\n"
        f"Language: {language}.\n\n"
        f"Suggest 10 timely, engaging news article topics. Think about:\n"
        f"- Recent regulatory changes affecting {vertical_name} in {geo_name}\n"
        f"- Industry developments, mergers, and market trends\n"
        f"- New product launches, partnerships, or market entries in {geo_name}\n"
        f"- Seasonal events or upcoming tournaments relevant to {vertical_name}\n"
        f"- Consumer tips tied to current events in {geo_name}\n"
        f"- Search trends like \"{geo_name} {vertical_name.lower()} news\", "
        f"\"{geo_name} betting regulation\", \"{geo_name} {vertical_name.lower()} industry\"\n\n"
        f"Already published articles: {existing_str}\n\n"
        f"Return a JSON object with:\n"
        f"{{\"suggestions\": [{{\"topic\": string, \"angle\": string, \"reason\": string}}]}}\n\n"
        f"Where:\n"
        f"- topic: compelling news headline (8-14 words)\n"
        f"- angle: the editorial hook (1 sentence)\n"
        f"- reason: why publish this now (1 sentence)\n\n"
        f"Do not repeat existing articles. Write topics in {language}."
    )

    try:
        model = current_app.config.get('OPENAI_MODEL', 'gpt-4o-mini')
        result = call_openai(prompt, api_key, model, max_tokens=2048)
        suggestions = result.get('suggestions', [])
    except Exception as e:
        logger.warning('News suggestion failed: %s', e)
        return jsonify({'error': f'AI suggestion failed: {e}'}), 500

    return jsonify({'suggestions': suggestions})


@bp.route('/sites/<int:site_id>/save-menu-order', methods=['POST'])
def save_menu_order(site_id):
    """Save nav item ordering from drag-and-drop."""
    from datetime import datetime, timezone

    site = db.session.get(Site, site_id)
    if not site:
        return jsonify({'error': 'Site not found'}), 404

    data = request.get_json()
    if not data or 'order' not in data:
        return jsonify({'error': 'No order data'}), 400

    page_lookup = {p.id: p for p in site.site_pages}

    for item in data['order']:
        page_id = item.get('page_id')
        nav_order = item.get('nav_order', 0)
        page = page_lookup.get(page_id)
        if page:
            page.nav_order = nav_order

    now = datetime.now(timezone.utc)
    for page in site.site_pages:
        page.menu_updated_at = now

    db.session.commit()
    return jsonify({'success': True})
