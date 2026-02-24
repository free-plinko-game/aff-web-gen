import json
import logging
import os

from flask import Blueprint, jsonify, request, abort, Response, send_from_directory, current_app

from ..models import db, Author, Brand, BrandGeo, BrandVertical, Comment, CommentUser, Site, SitePage, PageType
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
        upload_folder = current_app.config.get('UPLOAD_FOLDER', 'uploads')
        return send_from_directory(os.path.join(upload_folder, 'logos'), filename[6:])

    # Check if it's an avatar file — serve from uploads/avatars/
    if filename.startswith('avatars/'):
        upload_folder = current_app.config.get('UPLOAD_FOLDER', 'uploads')
        return send_from_directory(os.path.join(upload_folder, 'avatars'), filename[8:])

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


@bp.route('/sites/<int:site_id>/tips-leagues', methods=['POST'])
def save_tips_leagues(site_id):
    """Save or clear tips league configuration for a site."""
    site = db.session.get(Site, site_id)
    if not site:
        return jsonify({'error': 'Site not found'}), 404

    data = request.get_json(silent=True) or {}
    leagues = data.get('leagues')

    if leagues is not None:
        # Validate JSON structure
        if not isinstance(leagues, list):
            return jsonify({'error': 'leagues must be a JSON array'}), 400
        for item in leagues:
            if not isinstance(item, dict) or 'league_id' not in item:
                return jsonify({'error': 'Each league must have a league_id'}), 400
        site.tips_leagues = json.dumps(leagues)
    else:
        site.tips_leagues = None

    db.session.commit()
    return jsonify({'success': True})


@bp.route('/sites/<int:site_id>/run-tips', methods=['POST'])
def run_tips_pipeline(site_id):
    """Manually trigger the tips pipeline for a site (background thread)."""
    site = db.session.get(Site, site_id)
    if not site:
        return jsonify({'error': 'Site not found'}), 404

    if not site.tips_leagues:
        return jsonify({'error': 'No tips leagues configured for this site'}), 400

    from ..services.tips_pipeline import run_tips_pipeline_background
    run_tips_pipeline_background(current_app._get_current_object(), site.id)

    return jsonify({'success': True, 'message': 'Tips pipeline started in background'})


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


@bp.route('/sites/<int:site_id>/sweep-links', methods=['POST'])
def sweep_links(site_id):
    """Scan (and optionally fix) dead internal links in content_json."""
    site = db.session.get(Site, site_id)
    if not site:
        return jsonify({'error': 'Site not found'}), 404

    mode = request.args.get('mode', 'report')
    fix = mode == 'fix'

    from ..services.link_sweeper import sweep_dead_links
    result = sweep_dead_links(site.id, fix=fix)

    return jsonify({'success': True, **result})


# ── Author CRUD ──────────────────────────────────────────────────────────

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'}


def _slugify(text):
    """Simple slug generator: lowercase, strip non-alnum, collapse hyphens."""
    import re
    s = text.lower().strip()
    s = re.sub(r'[^a-z0-9]+', '-', s)
    return s.strip('-')


def _save_avatar(file, slug):
    """Save an uploaded avatar file. Returns the filename or None."""
    if file and file.filename and '.' in file.filename:
        ext = file.filename.rsplit('.', 1)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            return None
        filename = f"{slug}.{ext}"
        filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], 'avatars', filename)
        file.save(filepath)
        return filename
    return None


@bp.route('/sites/<int:site_id>/authors', methods=['GET'])
def list_authors(site_id):
    """List all authors for a site."""
    site = db.session.get(Site, site_id)
    if not site:
        return jsonify({'error': 'Site not found'}), 404

    authors = Author.query.filter_by(site_id=site_id).order_by(Author.name).all()
    return jsonify({
        'authors': [_author_to_dict(a) for a in authors],
        'default_author_id': site.default_author_id,
    })


@bp.route('/sites/<int:site_id>/authors', methods=['POST'])
def create_author(site_id):
    """Create a new author for a site."""
    site = db.session.get(Site, site_id)
    if not site:
        return jsonify({'error': 'Site not found'}), 404

    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'Name is required'}), 400

    slug = (data.get('slug') or '').strip() or _slugify(name)

    # Check uniqueness
    existing = Author.query.filter_by(site_id=site_id, slug=slug).first()
    if existing:
        return jsonify({'error': f'Author with slug "{slug}" already exists'}), 400

    author = Author(
        site_id=site_id,
        name=name,
        slug=slug,
        role=(data.get('role') or '').strip() or None,
        short_bio=(data.get('short_bio') or '').strip() or None,
        bio=(data.get('bio') or '').strip() or None,
        expertise=json.dumps(data['expertise']) if data.get('expertise') else None,
        social_links=json.dumps(data['social_links']) if data.get('social_links') else None,
    )
    db.session.add(author)
    db.session.commit()

    return jsonify({'success': True, 'author': _author_to_dict(author)})


@bp.route('/sites/<int:site_id>/authors/<int:author_id>', methods=['PUT'])
def update_author(site_id, author_id):
    """Update an existing author."""
    author = Author.query.filter_by(id=author_id, site_id=site_id).first()
    if not author:
        return jsonify({'error': 'Author not found'}), 404

    data = request.get_json(silent=True) or {}

    if 'name' in data:
        name = (data['name'] or '').strip()
        if not name:
            return jsonify({'error': 'Name cannot be empty'}), 400
        author.name = name

    if 'slug' in data:
        slug = (data['slug'] or '').strip()
        if slug and slug != author.slug:
            dup = Author.query.filter_by(site_id=site_id, slug=slug).first()
            if dup:
                return jsonify({'error': f'Slug "{slug}" already taken'}), 400
            author.slug = slug

    if 'role' in data:
        author.role = (data['role'] or '').strip() or None
    if 'short_bio' in data:
        author.short_bio = (data['short_bio'] or '').strip() or None
    if 'bio' in data:
        author.bio = (data['bio'] or '').strip() or None
    if 'expertise' in data:
        author.expertise = json.dumps(data['expertise']) if data['expertise'] else None
    if 'social_links' in data:
        author.social_links = json.dumps(data['social_links']) if data['social_links'] else None
    if 'is_active' in data:
        author.is_active = bool(data['is_active'])

    db.session.commit()
    return jsonify({'success': True, 'author': _author_to_dict(author)})


@bp.route('/sites/<int:site_id>/authors/<int:author_id>', methods=['DELETE'])
def delete_author(site_id, author_id):
    """Delete an author. Nullifies author_id on linked pages."""
    author = Author.query.filter_by(id=author_id, site_id=site_id).first()
    if not author:
        return jsonify({'error': 'Author not found'}), 404

    # Clear default_author_id if it matches
    site = db.session.get(Site, site_id)
    if site and site.default_author_id == author_id:
        site.default_author_id = None

    # Nullify author_id on any linked pages
    SitePage.query.filter_by(author_id=author_id).update({'author_id': None})

    # Delete avatar file if exists
    if author.avatar_filename:
        avatar_path = os.path.join(
            current_app.config['UPLOAD_FOLDER'], 'avatars', author.avatar_filename
        )
        if os.path.exists(avatar_path):
            os.remove(avatar_path)

    db.session.delete(author)
    db.session.commit()
    return jsonify({'success': True})


@bp.route('/sites/<int:site_id>/authors/<int:author_id>/avatar', methods=['POST'])
def upload_avatar(site_id, author_id):
    """Upload an avatar image for an author."""
    author = Author.query.filter_by(id=author_id, site_id=site_id).first()
    if not author:
        return jsonify({'error': 'Author not found'}), 404

    if 'avatar' not in request.files:
        return jsonify({'error': 'No avatar file provided'}), 400

    file = request.files['avatar']
    filename = _save_avatar(file, author.slug)
    if not filename:
        return jsonify({'error': 'Invalid file type'}), 400

    # Remove old avatar if different filename
    if author.avatar_filename and author.avatar_filename != filename:
        old_path = os.path.join(
            current_app.config['UPLOAD_FOLDER'], 'avatars', author.avatar_filename
        )
        if os.path.exists(old_path):
            os.remove(old_path)

    author.avatar_filename = filename
    db.session.commit()
    return jsonify({'success': True, 'filename': filename})


@bp.route('/sites/<int:site_id>/set-default-author', methods=['POST'])
def set_default_author(site_id):
    """Set or clear the default author for a site."""
    site = db.session.get(Site, site_id)
    if not site:
        return jsonify({'error': 'Site not found'}), 404

    data = request.get_json(silent=True) or {}
    author_id = data.get('author_id')

    if author_id is not None:
        author = Author.query.filter_by(id=author_id, site_id=site_id).first()
        if not author:
            return jsonify({'error': 'Author not found'}), 404

    site.default_author_id = author_id
    db.session.commit()
    return jsonify({'success': True})


@bp.route('/sites/<int:site_id>/assign-author-bulk', methods=['POST'])
def assign_author_bulk(site_id):
    """Assign an author to all pages that don't have one."""
    site = db.session.get(Site, site_id)
    if not site:
        return jsonify({'error': 'Site not found'}), 404

    data = request.get_json(silent=True) or {}
    author_id = data.get('author_id')
    if not author_id:
        return jsonify({'error': 'author_id is required'}), 400

    author = Author.query.filter_by(id=author_id, site_id=site_id).first()
    if not author:
        return jsonify({'error': 'Author not found'}), 404

    updated = SitePage.query.filter_by(site_id=site_id, author_id=None).update(
        {'author_id': author_id}
    )
    db.session.commit()
    return jsonify({'success': True, 'updated': updated})


@bp.route('/sites/<int:site_id>/generate-authors', methods=['POST'])
def generate_authors(site_id):
    """AI-generate author personas for a site. Returns suggestions (does not save)."""
    site = db.session.get(Site, site_id)
    if not site:
        return jsonify({'error': 'Site not found'}), 404

    api_key = current_app.config.get('OPENAI_API_KEY')
    if not api_key:
        return jsonify({'error': 'OpenAI API key not configured'}), 500

    from ..services.author_generator import generate_author_personas
    try:
        personas = generate_author_personas(site, api_key)
    except Exception as e:
        logger.warning('Author generation failed for site %d: %s', site_id, e)
        return jsonify({'error': f'Generation failed: {e}'}), 500

    return jsonify({'success': True, 'authors': personas})


def _author_to_dict(author):
    """Serialize an Author model to a dict."""
    article_count = SitePage.query.filter_by(author_id=author.id).count()
    return {
        'id': author.id,
        'site_id': author.site_id,
        'name': author.name,
        'slug': author.slug,
        'role': author.role,
        'bio': author.bio,
        'short_bio': author.short_bio,
        'avatar_filename': author.avatar_filename,
        'expertise': json.loads(author.expertise) if author.expertise else [],
        'social_links': json.loads(author.social_links) if author.social_links else {},
        'is_active': author.is_active,
        'article_count': article_count,
    }


# ── Comments Management ─────────────────────────────────────────────

@bp.route('/sites/<int:site_id>/toggle-comments', methods=['POST'])
def toggle_comments(site_id):
    site = db.session.get(Site, site_id) or abort(404)
    site.comments_enabled = not site.comments_enabled
    db.session.commit()
    return jsonify({'success': True, 'enabled': site.comments_enabled})


@bp.route('/sites/<int:site_id>/save-comments-config', methods=['POST'])
def save_comments_config(site_id):
    site = db.session.get(Site, site_id) or abort(404)
    data = request.get_json(force=True)
    site.comments_api_url = (data.get('comments_api_url') or '').strip() or None
    db.session.commit()
    return jsonify({'success': True})


@bp.route('/sites/<int:site_id>/generate-personas', methods=['POST'])
def generate_personas_endpoint(site_id):
    site = db.session.get(Site, site_id) or abort(404)
    data = request.get_json(force=True)
    count = min(int(data.get('count', 10)), 30)

    try:
        from ..services.persona_manager import generate_personas
        created = generate_personas(site.id, count=count)
        return jsonify({'success': True, 'count': created})
    except Exception as e:
        logger.error('Persona generation failed for site %d: %s', site_id, e)
        return jsonify({'error': str(e)}), 500


@bp.route('/sites/<int:site_id>/seed-comments/<path:page_slug>', methods=['POST'])
def seed_comments_endpoint(site_id, page_slug):
    site = db.session.get(Site, site_id) or abort(404)
    page = SitePage.query.filter_by(site_id=site_id, slug=page_slug).first()
    if not page:
        return jsonify({'error': 'Page not found'}), 404

    try:
        from ..services.comment_seeder import seed_comments_for_page
        count = seed_comments_for_page(site.id, page.slug, page.title)
        return jsonify({'success': True, 'count': count})
    except Exception as e:
        logger.error('Comment seeding failed for %s: %s', page_slug, e)
        return jsonify({'error': str(e)}), 500


@bp.route('/sites/<int:site_id>/seed-all-comments', methods=['POST'])
def seed_all_comments(site_id):
    site = db.session.get(Site, site_id) or abort(404)

    # Find article pages with no comments
    content_types = {'brand-review', 'bonus-review', 'evergreen', 'news-article', 'tips-article'}
    pages = SitePage.query.filter_by(site_id=site_id, is_generated=True).all()
    pages = [p for p in pages if p.page_type.slug in content_types]

    # Filter to pages with zero comments
    pages_to_seed = []
    for p in pages:
        count = Comment.query.filter_by(site_id=site_id, page_slug=p.slug).count()
        if count == 0:
            pages_to_seed.append(p)

    from ..services.comment_seeder import seed_comments_for_page

    seeded_pages = 0
    total_comments = 0
    for p in pages_to_seed:
        try:
            count = seed_comments_for_page(site.id, p.slug, p.title)
            if count > 0:
                seeded_pages += 1
                total_comments += count
        except Exception as e:
            logger.warning('Comment seeding failed for %s: %s', p.slug, e)

    return jsonify({
        'success': True,
        'seeded_pages': seeded_pages,
        'total_comments': total_comments,
    })
