import csv
import io
import os

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, abort
from werkzeug.utils import secure_filename

from ..models import db, Brand, BrandGeo, BrandVertical, Geo, Vertical

bp = Blueprint('brands', __name__, url_prefix='/brands')

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'svg', 'webp'}


def _allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def _save_logo(file, slug):
    """Save an uploaded logo file. Returns the filename or None."""
    if file and file.filename and _allowed_file(file.filename):
        ext = file.filename.rsplit('.', 1)[1].lower()
        filename = f"{slug}.{ext}"
        filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], 'logos', filename)
        file.save(filepath)
        return filename
    return None


@bp.route('/')
def list_brands():
    brands = Brand.query.order_by(Brand.name).all()
    return render_template('brands/list.html', brands=brands)


@bp.route('/new', methods=['GET', 'POST'])
def create():
    geos = Geo.query.order_by(Geo.name).all()
    verticals = Vertical.query.order_by(Vertical.name).all()

    if request.method == 'POST':
        slug = request.form.get('slug', '').strip()
        name = request.form.get('name', '').strip()

        if not name or not slug:
            flash('Name and slug are required.', 'error')
            return render_template('brands/form.html', brand=None, geos=geos, verticals=verticals)

        # Check for duplicate slug
        if Brand.query.filter_by(slug=slug).first():
            flash(f'A brand with slug "{slug}" already exists.', 'error')
            return render_template('brands/form.html', brand=None, geos=geos, verticals=verticals)

        brand = Brand(
            name=name,
            slug=slug,
            website_url=request.form.get('website_url', '').strip(),
            affiliate_link=request.form.get('affiliate_link', '').strip(),
            description=request.form.get('description', '').strip(),
            founded_year=int(request.form['founded_year']) if request.form.get('founded_year') else None,
            rating=float(request.form['rating']) if request.form.get('rating') else None,
            parent_company=request.form.get('parent_company', '').strip() or None,
            support_methods=request.form.get('support_methods', '').strip() or None,
            support_email=request.form.get('support_email', '').strip() or None,
            available_languages=request.form.get('available_languages', '').strip() or None,
            has_ios_app='has_ios_app' in request.form,
            has_android_app='has_android_app' in request.form,
        )

        # Handle logo upload
        logo_file = request.files.get('logo')
        if logo_file:
            filename = _save_logo(logo_file, slug)
            if filename:
                brand.logo_filename = filename

        db.session.add(brand)
        db.session.flush()  # Get brand.id for associations

        # Handle GEO associations
        _save_geo_associations(brand, request.form)

        # Handle vertical associations
        _save_vertical_associations(brand, request.form)

        db.session.commit()
        flash('Brand created successfully.', 'success')
        return redirect(url_for('brands.list_brands'))

    return render_template('brands/form.html', brand=None, geos=geos, verticals=verticals)


@bp.route('/<int:brand_id>/edit', methods=['GET', 'POST'])
def edit(brand_id):
    brand = db.session.get(Brand, brand_id) or abort(404)
    geos = Geo.query.order_by(Geo.name).all()
    verticals = Vertical.query.order_by(Vertical.name).all()

    if request.method == 'POST':
        brand.name = request.form.get('name', '').strip()
        brand.website_url = request.form.get('website_url', '').strip()
        brand.affiliate_link = request.form.get('affiliate_link', '').strip()
        brand.description = request.form.get('description', '').strip()
        brand.founded_year = int(request.form['founded_year']) if request.form.get('founded_year') else None
        brand.rating = float(request.form['rating']) if request.form.get('rating') else None
        brand.parent_company = request.form.get('parent_company', '').strip() or None
        brand.support_methods = request.form.get('support_methods', '').strip() or None
        brand.support_email = request.form.get('support_email', '').strip() or None
        brand.available_languages = request.form.get('available_languages', '').strip() or None
        brand.has_ios_app = 'has_ios_app' in request.form
        brand.has_android_app = 'has_android_app' in request.form

        # Handle logo upload
        logo_file = request.files.get('logo')
        if logo_file and logo_file.filename:
            filename = _save_logo(logo_file, brand.slug)
            if filename:
                brand.logo_filename = filename

        # Update GEO associations
        BrandGeo.query.filter_by(brand_id=brand.id).delete()
        _save_geo_associations(brand, request.form)

        # Update vertical associations
        BrandVertical.query.filter_by(brand_id=brand.id).delete()
        _save_vertical_associations(brand, request.form)

        db.session.commit()
        flash('Brand updated successfully.', 'success')
        return redirect(url_for('brands.list_brands'))

    # Build existing associations for the form
    active_geo_ids = {bg.geo_id for bg in brand.brand_geos}
    geo_data = {bg.geo_id: bg for bg in brand.brand_geos}
    active_vertical_ids = {bv.vertical_id for bv in brand.brand_verticals}

    return render_template('brands/form.html', brand=brand, geos=geos, verticals=verticals,
                           active_geo_ids=active_geo_ids, geo_data=geo_data,
                           active_vertical_ids=active_vertical_ids)


@bp.route('/<int:brand_id>/delete', methods=['POST'])
def delete(brand_id):
    brand = db.session.get(Brand, brand_id) or abort(404)

    # Delete logo file if exists
    if brand.logo_filename:
        logo_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'logos', brand.logo_filename)
        if os.path.exists(logo_path):
            os.remove(logo_path)

    db.session.delete(brand)
    db.session.commit()
    flash('Brand deleted successfully.', 'success')
    return redirect(url_for('brands.list_brands'))


@bp.route('/bulk-delete', methods=['POST'])
def bulk_delete():
    """Delete multiple brands at once."""
    brand_ids = request.form.getlist('brand_ids', type=int)
    if not brand_ids:
        flash('No brands selected.', 'warning')
        return redirect(url_for('brands.list_brands'))

    deleted = 0
    for brand_id in brand_ids:
        brand = db.session.get(Brand, brand_id)
        if not brand:
            continue
        # Delete logo file if exists
        if brand.logo_filename:
            logo_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'logos', brand.logo_filename)
            if os.path.exists(logo_path):
                os.remove(logo_path)
        db.session.delete(brand)
        deleted += 1

    db.session.commit()
    flash(f'{deleted} brand{"s" if deleted != 1 else ""} deleted.', 'success')
    return redirect(url_for('brands.list_brands'))


def _csv_float(row, key):
    """Parse a float from a CSV row value, returning None if empty."""
    val = row.get(key, '').strip()
    return float(val) if val else None


def _csv_int(row, key):
    """Parse an int from a CSV row value, returning None if empty."""
    val = row.get(key, '').strip()
    return int(val) if val else None


def _csv_bool(row, key):
    """Parse a boolean from a CSV row value (true/1/yes → True)."""
    val = row.get(key, '').strip().lower()
    return val in ('true', '1', 'yes')


@bp.route('/import', methods=['GET', 'POST'])
def bulk_import():
    """Bulk import brands from a CSV file.

    One row per brand-GEO combination. Brand fields repeat on each row;
    if a brand appears in multiple GEOs it has multiple rows.
    Rows without a ``geo`` value create the brand but no GEO association.

    Required: name, slug
    Brand fields: website_url, affiliate_link, rating, description,
        founded_year, parent_company, support_methods, support_email,
        available_languages, has_ios_app, has_android_app, verticals
    GEO fields: geo, welcome_bonus, bonus_code, license_info,
        payment_methods, withdrawal_timeframe,
        rating_bonus, rating_usability, rating_mobile_app,
        rating_payments, rating_support, rating_licensing, rating_rewards

    Duplicate slugs are skipped with a warning.
    """
    if request.method == 'POST':
        csv_file = request.files.get('csv_file')
        if not csv_file or not csv_file.filename:
            flash('Please select a CSV file.', 'error')
            return render_template('brands/import.html')

        try:
            stream = io.StringIO(csv_file.stream.read().decode('utf-8'))
            reader = csv.DictReader(stream)

            # Group rows by slug so we can create brand once, then add GEOs
            from collections import OrderedDict
            slug_groups = OrderedDict()  # slug → list of rows
            for row in reader:
                slug = row.get('slug', '').strip()
                if not slug:
                    continue
                slug_groups.setdefault(slug, []).append(row)

            # Pre-fetch lookup maps
            geo_map = {g.code.lower(): g for g in Geo.query.all()}
            vertical_map = {v.slug.lower(): v for v in Vertical.query.all()}

            imported = 0
            geo_count = 0
            skipped = 0

            for slug, rows in slug_groups.items():
                first = rows[0]
                name = first.get('name', '').strip()
                if not name:
                    skipped += 1
                    continue

                if Brand.query.filter_by(slug=slug).first():
                    flash(f'Skipped duplicate slug: "{slug}"', 'warning')
                    skipped += 1
                    continue

                brand = Brand(
                    name=name,
                    slug=slug,
                    website_url=first.get('website_url', '').strip() or None,
                    affiliate_link=first.get('affiliate_link', '').strip() or None,
                    description=first.get('description', '').strip() or None,
                    rating=_csv_float(first, 'rating'),
                    founded_year=_csv_int(first, 'founded_year'),
                    parent_company=first.get('parent_company', '').strip() or None,
                    support_methods=first.get('support_methods', '').strip() or None,
                    support_email=first.get('support_email', '').strip() or None,
                    available_languages=first.get('available_languages', '').strip() or None,
                    has_ios_app=_csv_bool(first, 'has_ios_app'),
                    has_android_app=_csv_bool(first, 'has_android_app'),
                )
                db.session.add(brand)
                db.session.flush()

                # Vertical associations (comma-separated slugs from first row)
                verticals_str = first.get('verticals', '').strip()
                if verticals_str:
                    for v_slug in verticals_str.split(','):
                        v_slug = v_slug.strip().lower()
                        vert = vertical_map.get(v_slug)
                        if vert:
                            db.session.add(BrandVertical(brand_id=brand.id, vertical_id=vert.id))

                # GEO associations (one per row that has a geo value)
                seen_geos = set()
                for row in rows:
                    geo_code = row.get('geo', '').strip().lower()
                    if not geo_code or geo_code in seen_geos:
                        continue
                    geo = geo_map.get(geo_code)
                    if not geo:
                        flash(f'Unknown GEO code "{geo_code}" for brand "{slug}" — skipped.', 'warning')
                        continue
                    seen_geos.add(geo_code)
                    bg = BrandGeo(
                        brand_id=brand.id,
                        geo_id=geo.id,
                        is_active=True,
                        welcome_bonus=row.get('welcome_bonus', '').strip() or None,
                        bonus_code=row.get('bonus_code', '').strip() or None,
                        license_info=row.get('license_info', '').strip() or None,
                        payment_methods=row.get('payment_methods', '').strip() or None,
                        withdrawal_timeframe=row.get('withdrawal_timeframe', '').strip() or None,
                        rating_bonus=_csv_float(row, 'rating_bonus'),
                        rating_usability=_csv_float(row, 'rating_usability'),
                        rating_mobile_app=_csv_float(row, 'rating_mobile_app'),
                        rating_payments=_csv_float(row, 'rating_payments'),
                        rating_support=_csv_float(row, 'rating_support'),
                        rating_licensing=_csv_float(row, 'rating_licensing'),
                        rating_rewards=_csv_float(row, 'rating_rewards'),
                    )
                    db.session.add(bg)
                    geo_count += 1

                imported += 1

            db.session.commit()

            parts = [f'{imported} brands imported']
            if geo_count:
                parts.append(f'{geo_count} GEO associations')
            if skipped:
                parts.append(f'{skipped} skipped')
            flash(f'Import complete: {", ".join(parts)}.', 'success')
            return redirect(url_for('brands.list_brands'))

        except Exception as e:
            db.session.rollback()
            flash(f'Import failed: {e}', 'error')
            return render_template('brands/import.html')

    return render_template('brands/import.html')


def _save_geo_associations(brand, form):
    """Save brand-GEO associations from form data."""
    for key in form:
        if key.startswith('geo_active_'):
            geo_id = int(key.split('_')[-1])
            brand_geo = BrandGeo(
                brand_id=brand.id,
                geo_id=geo_id,
                welcome_bonus=form.get(f'geo_bonus_{geo_id}', '').strip(),
                bonus_code=form.get(f'geo_code_{geo_id}', '').strip(),
                license_info=form.get(f'geo_license_{geo_id}', '').strip(),
                is_active=True,
                payment_methods=form.get(f'geo_payment_methods_{geo_id}', '').strip() or None,
                withdrawal_timeframe=form.get(f'geo_withdrawal_timeframe_{geo_id}', '').strip() or None,
                rating_bonus=float(form[f'geo_rating_bonus_{geo_id}']) if form.get(f'geo_rating_bonus_{geo_id}') else None,
                rating_usability=float(form[f'geo_rating_usability_{geo_id}']) if form.get(f'geo_rating_usability_{geo_id}') else None,
                rating_mobile_app=float(form[f'geo_rating_mobile_app_{geo_id}']) if form.get(f'geo_rating_mobile_app_{geo_id}') else None,
                rating_payments=float(form[f'geo_rating_payments_{geo_id}']) if form.get(f'geo_rating_payments_{geo_id}') else None,
                rating_support=float(form[f'geo_rating_support_{geo_id}']) if form.get(f'geo_rating_support_{geo_id}') else None,
                rating_licensing=float(form[f'geo_rating_licensing_{geo_id}']) if form.get(f'geo_rating_licensing_{geo_id}') else None,
                rating_rewards=float(form[f'geo_rating_rewards_{geo_id}']) if form.get(f'geo_rating_rewards_{geo_id}') else None,
            )
            db.session.add(brand_geo)


def _save_vertical_associations(brand, form):
    """Save brand-vertical associations from form data."""
    vertical_ids = form.getlist('vertical_ids')
    for vid in vertical_ids:
        bv = BrandVertical(brand_id=brand.id, vertical_id=int(vid))
        db.session.add(bv)
