import os
import re
from datetime import datetime, timezone, timedelta

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, current_app, send_from_directory

from ..models import (
    db, Site, SiteBrand, SiteBrandOverride, SitePage, Geo, Vertical, Brand, BrandGeo, BrandVertical,
    PageType, Domain, ContentHistory, CTATable, CTATableRow,
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


def _needs_rebuild(site):
    """Check if the site needs rebuilding.

    Returns True if any page was generated/updated after the last build,
    or if there are ungenerated pages.
    """
    if not site.built_at:
        # Never built — need rebuild if any pages are generated
        return any(p.is_generated for p in site.site_pages)

    # Check for ungenerated pages (added but not yet generated)
    if any(not p.is_generated for p in site.site_pages):
        return True

    # Check if any page was generated after the last build
    return any(
        p.generated_at and p.generated_at > site.built_at
        for p in site.site_pages
    )


def _page_url(page):
    """Return the site-relative URL for a page."""
    slug = page.page_type.slug
    if slug == 'homepage':
        return '/index.html'
    elif slug == 'comparison':
        return '/comparison.html'
    elif slug == 'brand-review':
        return f'/reviews/{page.slug}.html'
    elif slug == 'bonus-review':
        return f'/bonuses/{page.slug}.html'
    elif slug == 'evergreen':
        return f'/{page.slug}.html'
    return f'/{page.slug}.html'


@bp.route('/<int:site_id>')
def detail(site_id):
    site = db.session.get(Site, site_id) or abort(404)
    available_domains = Domain.query.filter_by(status='available').order_by(Domain.domain).all()
    rebuild_needed = _needs_rebuild(site)

    # Render default robots.txt for the robots tab preview
    domain_name = site.domain.domain if site.domain else 'example.com'
    default_robots_txt = f"User-agent: *\nAllow: /\n\nSitemap: https://{domain_name}/sitemap.xml"

    # Freshness data (8.5)
    # Strip tzinfo for comparison — SQLite stores naive datetimes
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    threshold = timedelta(days=site.freshness_threshold_days or 30)

    def page_freshness(page):
        if not page.is_generated or not page.generated_at:
            return None
        gen_at = page.generated_at.replace(tzinfo=None) if page.generated_at.tzinfo else page.generated_at
        age = now - gen_at
        return {'days': age.days, 'stale': age > threshold}

    stale_count = sum(
        1 for p in site.site_pages
        if p.is_generated and p.generated_at
        and (now - (p.generated_at.replace(tzinfo=None) if p.generated_at.tzinfo else p.generated_at)) > threshold
    )

    return render_template('sites/detail.html', site=site, available_domains=available_domains,
                           rebuild_needed=rebuild_needed, page_url=_page_url,
                           default_robots_txt=default_robots_txt,
                           page_freshness=page_freshness, stale_count=stale_count)


@bp.route('/<int:site_id>/update-freshness', methods=['POST'])
def update_freshness(site_id):
    """Update the freshness threshold for a site."""
    site = db.session.get(Site, site_id) or abort(404)
    threshold = request.form.get('threshold', type=int)
    if threshold and 1 <= threshold <= 365:
        site.freshness_threshold_days = threshold
        db.session.commit()
        flash(f'Freshness threshold set to {threshold} days.', 'success')
    else:
        flash('Invalid threshold (must be 1-365 days).', 'error')
    return redirect(url_for('sites.detail', site_id=site.id))


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


@bp.route('/<int:site_id>/delete', methods=['POST'])
def delete_site(site_id):
    """Delete a site and all its pages, CTA tables, and brand overrides."""
    site = db.session.get(Site, site_id) or abort(404)

    # Release domain back to available
    if site.domain:
        site.domain.status = 'available'

    # Delete CTA tables (clear FK from pages first, then delete)
    from ..models import CTATable
    for ct in CTATable.query.filter_by(site_id=site.id).all():
        for page in ct.pages:
            page.cta_table_id = None
        db.session.delete(ct)

    name = site.name
    db.session.delete(site)
    db.session.commit()
    flash(f'Site "{name}" deleted.', 'success')
    return redirect(url_for('sites.list_sites'))


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


@bp.route('/<int:site_id>/add-page', methods=['GET', 'POST'])
def add_page(site_id):
    """Add a new page to an existing site."""
    site = db.session.get(Site, site_id) or abort(404)

    if request.method == 'POST':
        page_type_slug = request.form.get('page_type', '').strip()
        pt = PageType.query.filter_by(slug=page_type_slug).first()
        if not pt:
            flash('Invalid page type.', 'error')
            return redirect(url_for('sites.add_page', site_id=site.id))

        try:
            if page_type_slug in ('homepage', 'comparison'):
                # Check if already exists (partial unique constraint)
                existing = SitePage.query.filter_by(
                    site_id=site.id, page_type_id=pt.id, brand_id=None, evergreen_topic=None
                ).first()
                if existing:
                    flash(f'This site already has a {pt.name} page.', 'error')
                    return redirect(url_for('sites.add_page', site_id=site.id))
                page = SitePage(
                    site_id=site.id,
                    page_type_id=pt.id,
                    slug='index' if page_type_slug == 'homepage' else page_type_slug,
                    title=pt.name,
                )

            elif page_type_slug in ('brand-review', 'bonus-review'):
                brand_id = request.form.get('brand_id', type=int)
                if not brand_id:
                    flash('Please select a brand.', 'error')
                    return redirect(url_for('sites.add_page', site_id=site.id))
                brand = db.session.get(Brand, brand_id)
                if not brand:
                    flash('Brand not found.', 'error')
                    return redirect(url_for('sites.add_page', site_id=site.id))
                # Check if brand is assigned to this site
                sb = SiteBrand.query.filter_by(site_id=site.id, brand_id=brand_id).first()
                if not sb:
                    flash('That brand is not assigned to this site.', 'error')
                    return redirect(url_for('sites.add_page', site_id=site.id))
                # Check duplicate
                existing = SitePage.query.filter_by(
                    site_id=site.id, page_type_id=pt.id, brand_id=brand_id
                ).first()
                if existing:
                    flash(f'A {pt.name} for {brand.name} already exists.', 'error')
                    return redirect(url_for('sites.add_page', site_id=site.id))
                title_suffix = 'Review' if page_type_slug == 'brand-review' else 'Bonus Review'
                page = SitePage(
                    site_id=site.id,
                    page_type_id=pt.id,
                    brand_id=brand_id,
                    slug=brand.slug,
                    title=f'{brand.name} {title_suffix}',
                )

            elif page_type_slug == 'evergreen':
                topic = request.form.get('evergreen_topic', '').strip()
                if not topic:
                    flash('Please enter a topic.', 'error')
                    return redirect(url_for('sites.add_page', site_id=site.id))
                slug = _slugify(topic)
                existing = SitePage.query.filter_by(
                    site_id=site.id, page_type_id=pt.id, evergreen_topic=topic
                ).first()
                if existing:
                    flash(f'An evergreen page for "{topic}" already exists.', 'error')
                    return redirect(url_for('sites.add_page', site_id=site.id))
                page = SitePage(
                    site_id=site.id,
                    page_type_id=pt.id,
                    evergreen_topic=topic,
                    slug=slug,
                    title=topic,
                )
            else:
                flash('Unknown page type.', 'error')
                return redirect(url_for('sites.add_page', site_id=site.id))

            db.session.add(page)
            db.session.commit()
            flash(f'Page "{page.title}" added. Generate content when ready.', 'success')
            return redirect(url_for('sites.detail', site_id=site.id))

        except Exception as e:
            db.session.rollback()
            flash(f'Failed to add page: {e}', 'error')
            return redirect(url_for('sites.add_page', site_id=site.id))

    # GET — build context for the form
    page_types = PageType.query.order_by(PageType.name).all()

    # Determine which global page types are available
    existing_global = {
        p.page_type.slug
        for p in site.site_pages
        if p.brand_id is None and p.evergreen_topic is None
    }

    # Determine which brands already have review/bonus pages
    existing_brand_reviews = {
        p.brand_id for p in site.site_pages
        if p.page_type.slug == 'brand-review' and p.brand_id
    }
    existing_bonus_reviews = {
        p.brand_id for p in site.site_pages
        if p.page_type.slug == 'bonus-review' and p.brand_id
    }

    # Brands available for each type
    site_brand_ids = [sb.brand_id for sb in site.site_brands]
    available_review_brands = Brand.query.filter(
        Brand.id.in_(site_brand_ids),
        ~Brand.id.in_(existing_brand_reviews) if existing_brand_reviews else True
    ).order_by(Brand.name).all()
    available_bonus_brands = Brand.query.filter(
        Brand.id.in_(site_brand_ids),
        ~Brand.id.in_(existing_bonus_reviews) if existing_bonus_reviews else True
    ).order_by(Brand.name).all()

    return render_template('sites/add_page.html', site=site, page_types=page_types,
                           existing_global=existing_global,
                           available_review_brands=available_review_brands,
                           available_bonus_brands=available_bonus_brands)


@bp.route('/<int:site_id>/pages/<int:page_id>/edit', methods=['GET', 'POST'])
def edit_page(site_id, page_id):
    """Edit page settings and regeneration notes."""
    site = db.session.get(Site, site_id) or abort(404)
    page = db.session.get(SitePage, page_id) or abort(404)
    if page.site_id != site.id:
        abort(404)

    if request.method == 'POST':
        action = request.form.get('action', 'save')

        page.title = request.form.get('title', page.title).strip()
        page.meta_title = request.form.get('meta_title', '').strip() or None
        page.meta_description = request.form.get('meta_description', '').strip() or None
        page.slug = request.form.get('slug', page.slug).strip()
        page.custom_head = request.form.get('custom_head', '').strip() or None
        page.regeneration_notes = request.form.get('regeneration_notes', '').strip() or None

        # CTA table assignment
        cta_table_id = request.form.get('cta_table_id', type=int)
        page.cta_table_id = cta_table_id if cta_table_id else None

        # Content JSON (from structured editor textarea)
        content_json_raw = request.form.get('content_json', '').strip()
        if content_json_raw:
            import json
            try:
                json.loads(content_json_raw)  # Validate JSON
                page.content_json = content_json_raw
            except json.JSONDecodeError:
                flash('Invalid JSON in content editor. Content was not updated.', 'error')

        db.session.commit()

        if action == 'save_and_regenerate':
            api_key = current_app.config.get('OPENAI_API_KEY', '')
            model = current_app.config.get('OPENAI_MODEL', 'gpt-4o-mini')

            from ..services.content_generator import start_single_page_generation
            start_single_page_generation(
                current_app._get_current_object(), site_id, page_id, api_key, model
            )
            flash(f'Saved and regeneration started for "{page.title}".', 'info')
        else:
            flash(f'Page "{page.title}" updated.', 'success')

        return redirect(url_for('sites.detail', site_id=site.id))

    # GET — load content history and CTA tables
    history = (
        ContentHistory.query
        .filter_by(site_page_id=page.id)
        .order_by(ContentHistory.version.desc())
        .all()
    )
    cta_tables = CTATable.query.filter_by(site_id=site.id).order_by(CTATable.name).all()

    return render_template('sites/edit_page.html', site=site, page=page,
                           history=history, page_url=_page_url, cta_tables=cta_tables)


@bp.route('/<int:site_id>/pages/<int:page_id>/delete', methods=['POST'])
def delete_page(site_id, page_id):
    """Delete a page from the site."""
    site = db.session.get(Site, site_id) or abort(404)
    page = db.session.get(SitePage, page_id) or abort(404)
    if page.site_id != site.id:
        abort(404)

    title = page.title
    db.session.delete(page)
    db.session.commit()
    flash(f'Page "{title}" deleted.', 'success')
    return redirect(url_for('sites.detail', site_id=site.id))


@bp.route('/<int:site_id>/brand-overrides', methods=['GET', 'POST'])
def brand_overrides(site_id):
    """View and edit brand overrides for this site."""
    site = db.session.get(Site, site_id) or abort(404)

    if request.method == 'POST':
        for sb in site.site_brands:
            prefix = f'brand_{sb.id}_'
            custom_desc = request.form.get(f'{prefix}description', '').strip() or None
            custom_sp = request.form.get(f'{prefix}selling_points', '').strip() or None
            custom_aff = request.form.get(f'{prefix}affiliate_link', '').strip() or None
            custom_bonus = request.form.get(f'{prefix}welcome_bonus', '').strip() or None
            custom_code = request.form.get(f'{prefix}bonus_code', '').strip() or None
            internal_notes = request.form.get(f'{prefix}notes', '').strip() or None

            has_any = any([custom_desc, custom_sp, custom_aff, custom_bonus, custom_code, internal_notes])

            if sb.override:
                if has_any:
                    sb.override.custom_description = custom_desc
                    sb.override.custom_selling_points = custom_sp
                    sb.override.custom_affiliate_link = custom_aff
                    sb.override.custom_welcome_bonus = custom_bonus
                    sb.override.custom_bonus_code = custom_code
                    sb.override.internal_notes = internal_notes
                else:
                    # All fields cleared — remove the override
                    db.session.delete(sb.override)
            elif has_any:
                override = SiteBrandOverride(
                    site_brand_id=sb.id,
                    custom_description=custom_desc,
                    custom_selling_points=custom_sp,
                    custom_affiliate_link=custom_aff,
                    custom_welcome_bonus=custom_bonus,
                    custom_bonus_code=custom_code,
                    internal_notes=internal_notes,
                )
                db.session.add(override)

        db.session.commit()
        flash('Brand overrides saved.', 'success')
        return redirect(url_for('sites.detail', site_id=site.id))

    # GET — build context with brand + geo data for placeholders
    brands_data = []
    for sb in sorted(site.site_brands, key=lambda sb: sb.rank):
        bg = next((bg for bg in sb.brand.brand_geos if bg.geo_id == site.geo_id), None)
        brands_data.append({
            'site_brand': sb,
            'brand': sb.brand,
            'brand_geo': bg,
            'override': sb.override,
        })

    return render_template('sites/brand_overrides.html', site=site, brands_data=brands_data)


@bp.route('/<int:site_id>/cta-tables')
def cta_table_list(site_id):
    """List CTA tables for a site."""
    site = db.session.get(Site, site_id) or abort(404)
    tables = CTATable.query.filter_by(site_id=site.id).order_by(CTATable.name).all()
    return render_template('sites/cta_tables.html', site=site, tables=tables)


@bp.route('/<int:site_id>/cta-tables/create', methods=['GET', 'POST'])
def cta_table_create(site_id):
    """Create a new CTA table."""
    site = db.session.get(Site, site_id) or abort(404)

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        slug = _slugify(name) if name else ''
        if not name:
            flash('Name is required.', 'error')
            return redirect(url_for('sites.cta_table_create', site_id=site.id))

        # Check for duplicate slug
        existing = CTATable.query.filter_by(site_id=site.id, slug=slug).first()
        if existing:
            flash(f'A CTA table with slug "{slug}" already exists.', 'error')
            return redirect(url_for('sites.cta_table_create', site_id=site.id))

        table = CTATable(site_id=site.id, name=name, slug=slug)
        db.session.add(table)
        db.session.flush()

        # Process brand rows
        _save_cta_rows(table, site, request.form)

        db.session.commit()
        flash(f'CTA table "{name}" created.', 'success')
        return redirect(url_for('sites.cta_table_list', site_id=site.id))

    site_brands = sorted(site.site_brands, key=lambda sb: sb.rank)
    return render_template('sites/cta_table_form.html', site=site, table=None, site_brands=site_brands)


@bp.route('/<int:site_id>/cta-tables/<int:table_id>/edit', methods=['GET', 'POST'])
def cta_table_edit(site_id, table_id):
    """Edit an existing CTA table."""
    site = db.session.get(Site, site_id) or abort(404)
    table = db.session.get(CTATable, table_id) or abort(404)
    if table.site_id != site.id:
        abort(404)

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        slug = _slugify(name) if name else ''
        if not name:
            flash('Name is required.', 'error')
            return redirect(url_for('sites.cta_table_edit', site_id=site.id, table_id=table.id))

        table.name = name
        table.slug = slug

        # Clear existing rows and re-create
        CTATableRow.query.filter_by(cta_table_id=table.id).delete()
        db.session.flush()
        _save_cta_rows(table, site, request.form)

        db.session.commit()
        flash(f'CTA table "{name}" updated.', 'success')
        return redirect(url_for('sites.cta_table_list', site_id=site.id))

    site_brands = sorted(site.site_brands, key=lambda sb: sb.rank)
    return render_template('sites/cta_table_form.html', site=site, table=table, site_brands=site_brands)


@bp.route('/<int:site_id>/cta-tables/<int:table_id>/delete', methods=['POST'])
def cta_table_delete(site_id, table_id):
    """Delete a CTA table."""
    site = db.session.get(Site, site_id) or abort(404)
    table = db.session.get(CTATable, table_id) or abort(404)
    if table.site_id != site.id:
        abort(404)

    # Clear FK references from pages
    for page in table.pages:
        page.cta_table_id = None

    name = table.name
    db.session.delete(table)
    db.session.commit()
    flash(f'CTA table "{name}" deleted.', 'success')
    return redirect(url_for('sites.cta_table_list', site_id=site.id))


def _save_cta_rows(table, site, form):
    """Save CTA table rows from form data."""
    site_brand_ids = {sb.brand_id for sb in site.site_brands}
    brand_ids = form.getlist('row_brand_ids', type=int)

    for i, brand_id in enumerate(brand_ids):
        if brand_id not in site_brand_ids:
            continue
        row = CTATableRow(
            cta_table_id=table.id,
            brand_id=brand_id,
            rank=i + 1,
            custom_bonus_text=form.get(f'row_{brand_id}_bonus', '').strip() or None,
            custom_cta_text=form.get(f'row_{brand_id}_cta', '').strip() or None,
            custom_badge=form.get(f'row_{brand_id}_badge', '').strip() or None,
            is_visible=form.get(f'row_{brand_id}_visible') == 'on',
        )
        db.session.add(row)


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
