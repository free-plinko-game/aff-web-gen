from flask import Blueprint, render_template

from ..models import Brand, Domain, Site

bp = Blueprint('dashboard', __name__)


@bp.route('/')
def index():
    brand_count = Brand.query.count()
    domain_count = Domain.query.count()
    site_count = Site.query.count()
    recent_sites = Site.query.order_by(Site.created_at.desc()).limit(5).all()
    return render_template('dashboard.html',
                           brand_count=brand_count,
                           domain_count=domain_count,
                           site_count=site_count,
                           recent_sites=recent_sites)
