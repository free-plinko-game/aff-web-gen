from datetime import datetime, timezone, timedelta

from flask import Blueprint, render_template

from ..models import Brand, Domain, Site

bp = Blueprint('dashboard', __name__)


def _get_stale_sites():
    """Find sites with pages older than their freshness threshold."""
    stale_sites = []
    sites = Site.query.filter(Site.status != 'draft').all()
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    for site in sites:
        if not site.site_pages:
            continue
        threshold = timedelta(days=site.freshness_threshold_days or 30)
        stale_count = sum(
            1 for p in site.site_pages
            if p.is_generated and p.generated_at
            and (now - (p.generated_at.replace(tzinfo=None) if p.generated_at.tzinfo else p.generated_at)) > threshold
        )
        if stale_count > 0:
            stale_sites.append({
                'site': site,
                'stale_count': stale_count,
                'total_count': len(site.site_pages),
                'threshold_days': site.freshness_threshold_days or 30,
            })

    return stale_sites


@bp.route('/')
def index():
    brand_count = Brand.query.count()
    domain_count = Domain.query.count()
    site_count = Site.query.count()
    recent_sites = Site.query.order_by(Site.created_at.desc()).limit(5).all()
    stale_sites = _get_stale_sites()
    return render_template('dashboard.html',
                           brand_count=brand_count,
                           domain_count=domain_count,
                           site_count=site_count,
                           recent_sites=recent_sites,
                           stale_sites=stale_sites)
