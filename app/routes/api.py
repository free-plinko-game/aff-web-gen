from flask import Blueprint, jsonify, request, abort

from ..models import db, Brand, BrandGeo, BrandVertical, Site, SitePage

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
