import os
import re

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, current_app, send_from_directory

from ..models import (
    db, Site, SiteBrand, SitePage, Geo, Vertical, Brand, BrandGeo, BrandVertical, PageType, Domain,
    ContentHistory,
)
from ..services.content_generator import start_generation, generate_page_content, save_content_to_page
from ..services.site_builder import build_site
from ..services.deployer import deploy_site, rollback_site

bp = Blueprint('sites', __name__, url_prefix='/sites')


def _slugify(text):
    """Convert text to a URL-safe slug."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_]+', '-', text)
    text = re.sub(r'-+', '-', text)
    return text.strip('-')


@bp.route('/')
def list_sites():
    sites = Site.query.order_by(Site.created_at.desc()).all()
    return render_template('sites/list.html', sites=sites)


@bp.route('/create', methods=['GET', 'POST'])
def create():
    geos = Geo.query.order_by(Geo.name).all()
    verticals = Vertical.query.order_by(Vertical.name).all()

    if request.method == 'POST':
        site_name = request.form.get('site_name', '').strip()
        geo_id = request.form.get('geo_id', type=int)
        vertical_id = request.form.get('vertical_id', type=int)

        if not site_name or not geo_id or not vertical_id:
            flash('Site name, GEO, and vertical are required.', 'error')
            return render_template('sites/create.html', geos=geos, verticals=verticals)

        # Create the site
        site = Site(name=site_name, geo_id=geo_id, vertical_id=vertical_id, status='draft')
        db.session.add(site)
        db.session.flush()

        # Process brand selections and ranks
        brand_ids = request.form.getlist('brand_ids', type=int)
        for i, brand_id in enumerate(brand_ids):
            rank = request.form.get(f'brand_rank_{brand_id}', type=int) or (i + 1)
            site_brand = SiteBrand(site_id=site.id, brand_id=brand_id, rank=rank)
            db.session.add(site_brand)

        # Process page types
        _create_site_pages(site, brand_ids, request.form)

        db.session.commit()
        flash('Site created successfully.', 'success')
        return redirect(url_for('sites.detail', site_id=site.id))

    return render_template('sites/create.html', geos=geos, verticals=verticals)


@bp.route('/<int:site_id>')
def detail(site_id):
    site = db.session.get(Site, site_id) or abort(404)
    available_domains = Domain.query.filter_by(status='available').order_by(Domain.domain).all()
    return render_template('sites/detail.html', site=site, available_domains=available_domains)


@bp.route('/<int:site_id>/generate', methods=['POST'])
def generate(site_id):
    """Trigger content generation for all pages of a site (background thread)."""
    site = db.session.get(Site, site_id) or abort(404)
    if site.status == 'generating':
        flash('Generation already in progress.', 'warning')
        return redirect(url_for('sites.detail', site_id=site.id))

    api_key = current_app.config.get('OPENAI_API_KEY', '')
    model = current_app.config.get('OPENAI_MODEL', 'gpt-4o-mini')

    site.status = 'generating'
    db.session.commit()

    start_generation(current_app._get_current_object(), site_id, api_key, model)

    flash('Content generation started. Progress will update below.', 'info')
    return redirect(url_for('sites.detail', site_id=site.id))


@bp.route('/<int:site_id>/regenerate/<int:page_id>', methods=['POST'])
def regenerate_page(site_id, page_id):
    """Regenerate content for a single page (synchronous)."""
    site = db.session.get(Site, site_id) or abort(404)
    page = db.session.get(SitePage, page_id) or abort(404)
    if page.site_id != site.id:
        abort(404)

    api_key = current_app.config.get('OPENAI_API_KEY', '')
    model = current_app.config.get('OPENAI_MODEL', 'gpt-4o-mini')

    try:
        content_data, _ = generate_page_content(page, site, api_key, model)
        save_content_to_page(page, content_data, db.session)
        db.session.commit()
        flash(f'Content regenerated for "{page.title}".', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Regeneration failed: {e}', 'error')

    return redirect(url_for('sites.detail', site_id=site.id))


@bp.route('/<int:site_id>/build', methods=['POST'])
def build(site_id):
    """Build the static site from generated content."""
    site = db.session.get(Site, site_id) or abort(404)
    if site.status not in ('generated', 'built'):
        flash('Site must have generated content before building.', 'error')
        return redirect(url_for('sites.detail', site_id=site.id))

    import os
    output_dir = os.path.join(current_app.root_path, '..', 'output')
    upload_folder = current_app.config['UPLOAD_FOLDER']

    try:
        site.status = 'building'
        db.session.commit()

        version_dir = build_site(site, output_dir, upload_folder)

        site.current_version += 1
        db.session.commit()
        flash(f'Site built successfully at v{site.current_version - 1}.', 'success')
    except Exception as e:
        db.session.rollback()
        site.status = 'failed'
        db.session.commit()
        flash(f'Build failed: {e}', 'error')

    return redirect(url_for('sites.detail', site_id=site.id))


@bp.route('/<int:site_id>/assign-domain', methods=['POST'])
def assign_domain(site_id):
    """Assign an available domain to the site."""
    site = db.session.get(Site, site_id) or abort(404)
    domain_id = request.form.get('domain_id', type=int)
    if not domain_id:
        flash('Please select a domain.', 'error')
        return redirect(url_for('sites.detail', site_id=site.id))

    domain = db.session.get(Domain, domain_id) or abort(404)
    if domain.status != 'available':
        flash('That domain is already assigned or deployed.', 'error')
        return redirect(url_for('sites.detail', site_id=site.id))

    # Unassign any previously assigned domain
    if site.domain:
        site.domain.status = 'available'

    site.domain_id = domain.id
    domain.status = 'assigned'
    db.session.commit()
    flash(f'Domain "{domain.domain}" assigned to this site.', 'success')
    return redirect(url_for('sites.detail', site_id=site.id))


@bp.route('/<int:site_id>/deploy', methods=['POST'])
def deploy(site_id):
    """Deploy the built site to the VPS."""
    site = db.session.get(Site, site_id) or abort(404)

    if not site.domain:
        flash('Assign a domain before deploying.', 'error')
        return redirect(url_for('sites.detail', site_id=site.id))

    if site.status not in ('built', 'deployed'):
        flash('Site must be built before deploying.', 'error')
        return redirect(url_for('sites.detail', site_id=site.id))

    try:
        site.status = 'deploying'
        db.session.commit()

        deploy_site(site, current_app.config)
        db.session.commit()
        flash('Site deployed successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        site.status = 'failed'
        db.session.commit()
        flash(f'Deployment failed: {e}', 'error')

    return redirect(url_for('sites.detail', site_id=site.id))


@bp.route('/<int:site_id>/rollback', methods=['POST'])
def rollback(site_id):
    """Rollback the site to the previous version."""
    site = db.session.get(Site, site_id) or abort(404)

    if not site.domain:
        flash('Site has no domain assigned.', 'error')
        return redirect(url_for('sites.detail', site_id=site.id))

    try:
        target_version = rollback_site(site, current_app.config)
        db.session.commit()
        flash(f'Site rolled back to v{target_version}.', 'success')
    except ValueError as e:
        flash(str(e), 'error')
    except Exception as e:
        db.session.rollback()
        flash(f'Rollback failed: {e}', 'error')

    return redirect(url_for('sites.detail', site_id=site.id))


@bp.route('/<int:site_id>/preview/')
@bp.route('/<int:site_id>/preview/<path:filename>')
def preview(site_id, filename='index.html'):
    """Serve built site files for preview."""
    site = db.session.get(Site, site_id) or abort(404)
    if not site.output_path or not os.path.isdir(site.output_path):
        flash('Site must be built before previewing.', 'error')
        return redirect(url_for('sites.detail', site_id=site.id))
    return send_from_directory(site.output_path, filename)


@bp.route('/<int:site_id>/pages/<int:page_id>/history')
def page_history(site_id, page_id):
    """View content history for a page."""
    site = db.session.get(Site, site_id) or abort(404)
    page = db.session.get(SitePage, page_id) or abort(404)
    if page.site_id != site.id:
        abort(404)

    history = (
        ContentHistory.query
        .filter_by(site_page_id=page.id)
        .order_by(ContentHistory.version.desc())
        .all()
    )
    return render_template('sites/page_history.html', site=site, page=page, history=history)


@bp.route('/<int:site_id>/pages/<int:page_id>/restore/<int:history_id>', methods=['POST'])
def restore_content(site_id, page_id, history_id):
    """Restore a previous content version."""
    site = db.session.get(Site, site_id) or abort(404)
    page = db.session.get(SitePage, page_id) or abort(404)
    if page.site_id != site.id:
        abort(404)

    history_entry = db.session.get(ContentHistory, history_id) or abort(404)
    if history_entry.site_page_id != page.id:
        abort(404)

    # Save current content to history before restoring
    from datetime import datetime, timezone
    if page.content_json and page.is_generated:
        max_version = (
            db.session.query(ContentHistory.version)
            .filter_by(site_page_id=page.id)
            .order_by(ContentHistory.version.desc())
            .first()
        )
        next_version = (max_version[0] + 1) if max_version else 1

        new_history = ContentHistory(
            site_page_id=page.id,
            content_json=page.content_json,
            generated_at=page.generated_at or datetime.now(timezone.utc),
            version=next_version,
        )
        db.session.add(new_history)

    # Restore the old content
    page.content_json = history_entry.content_json
    page.generated_at = history_entry.generated_at
    db.session.commit()

    flash(f'Content restored to version {history_entry.version} for "{page.title}".', 'success')
    return redirect(url_for('sites.page_history', site_id=site.id, page_id=page.id))


def _create_site_pages(site, brand_ids, form):
    """Create site_pages records based on wizard selections."""
    page_types_selected = form.getlist('page_types')

    # Global pages
    for pt_slug in ['homepage', 'comparison']:
        if pt_slug in page_types_selected:
            pt = PageType.query.filter_by(slug=pt_slug).first()
            page = SitePage(
                site_id=site.id,
                page_type_id=pt.id,
                slug='index' if pt_slug == 'homepage' else pt_slug,
                title=pt.name,
            )
            db.session.add(page)

    # Brand-specific pages
    for brand_id in brand_ids:
        brand = db.session.get(Brand, brand_id)
        if not brand:
            continue

        if 'brand-review' in page_types_selected:
            pt = PageType.query.filter_by(slug='brand-review').first()
            # Check if this brand is excluded
            excluded = form.getlist('exclude_brand_review')
            if str(brand_id) not in excluded:
                page = SitePage(
                    site_id=site.id,
                    page_type_id=pt.id,
                    brand_id=brand_id,
                    slug=brand.slug,
                    title=f'{brand.name} Review',
                )
                db.session.add(page)

        if 'bonus-review' in page_types_selected:
            pt = PageType.query.filter_by(slug='bonus-review').first()
            excluded = form.getlist('exclude_bonus_review')
            if str(brand_id) not in excluded:
                page = SitePage(
                    site_id=site.id,
                    page_type_id=pt.id,
                    brand_id=brand_id,
                    slug=brand.slug,
                    title=f'{brand.name} Bonus Review',
                )
                db.session.add(page)

    # Evergreen pages
    evergreen_topics = form.getlist('evergreen_topics')
    if evergreen_topics:
        pt = PageType.query.filter_by(slug='evergreen').first()
        for topic in evergreen_topics:
            topic = topic.strip()
            if not topic:
                continue
            page = SitePage(
                site_id=site.id,
                page_type_id=pt.id,
                evergreen_topic=topic,
                slug=_slugify(topic),
                title=topic,
            )
            db.session.add(page)
