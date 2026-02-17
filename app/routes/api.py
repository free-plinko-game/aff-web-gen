import os

from flask import Blueprint, jsonify, request, abort, Response, send_from_directory

from ..models import db, Brand, BrandGeo, BrandVertical, Site, SitePage
from ..services.preview_renderer import render_page_preview

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
    # Serve from site_templates/assets/
    from ..services.site_builder import _get_site_templates_path
    templates_path = _get_site_templates_path()
    assets_dir = os.path.join(templates_path, 'assets')

    # Check if it's a logo file — serve from uploads/logos/ instead
    if filename.startswith('logos/'):
        from flask import current_app
        upload_folder = current_app.config.get('UPLOAD_FOLDER', 'uploads')
        return send_from_directory(os.path.join(upload_folder, 'logos'), filename[6:])

    return send_from_directory(assets_dir, filename)
