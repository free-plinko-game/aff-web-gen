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


@bp.route('/import', methods=['GET', 'POST'])
def bulk_import():
    """Bulk import brands from a CSV file.

    Expected CSV columns: name, slug, website_url, affiliate_link, rating
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

            imported = 0
            skipped = 0

            for row in reader:
                name = row.get('name', '').strip()
                slug = row.get('slug', '').strip()

                if not name or not slug:
                    skipped += 1
                    continue

                if Brand.query.filter_by(slug=slug).first():
                    flash(f'Skipped duplicate slug: "{slug}"', 'warning')
                    skipped += 1
                    continue

                brand = Brand(
                    name=name,
                    slug=slug,
                    website_url=row.get('website_url', '').strip() or None,
                    affiliate_link=row.get('affiliate_link', '').strip() or None,
                    rating=float(row['rating']) if row.get('rating', '').strip() else None,
                )
                db.session.add(brand)
                imported += 1

            db.session.commit()
            flash(f'Import complete: {imported} brands imported, {skipped} skipped.', 'success')
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
            )
            db.session.add(brand_geo)


def _save_vertical_associations(brand, form):
    """Save brand-vertical associations from form data."""
    vertical_ids = form.getlist('vertical_ids')
    for vid in vertical_ids:
        bv = BrandVertical(brand_id=brand.id, vertical_id=int(vid))
        db.session.add(bv)
