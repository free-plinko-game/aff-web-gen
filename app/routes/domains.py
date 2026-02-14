from flask import Blueprint, render_template, request, redirect, url_for, flash, abort

from ..models import db, Domain

bp = Blueprint('domains', __name__, url_prefix='/domains')


@bp.route('/')
def list_domains():
    domains = Domain.query.order_by(Domain.domain).all()
    return render_template('domains/list.html', domains=domains)


@bp.route('/new', methods=['GET', 'POST'])
def create():
    if request.method == 'POST':
        domain_name = request.form.get('domain', '').strip().lower()
        registrar = request.form.get('registrar', '').strip()

        if not domain_name:
            flash('Domain name is required.', 'error')
            return render_template('domains/form.html', domain=None)

        if Domain.query.filter_by(domain=domain_name).first():
            flash(f'Domain "{domain_name}" already exists.', 'error')
            return render_template('domains/form.html', domain=None)

        domain = Domain(
            domain=domain_name,
            registrar=registrar or None,
            status='available',
        )
        db.session.add(domain)
        db.session.commit()
        flash('Domain added successfully.', 'success')
        return redirect(url_for('domains.list_domains'))

    return render_template('domains/form.html', domain=None)


@bp.route('/<int:domain_id>/delete', methods=['POST'])
def delete(domain_id):
    domain = db.session.get(Domain, domain_id) or abort(404)
    if domain.status == 'deployed':
        flash('Cannot delete a deployed domain.', 'error')
        return redirect(url_for('domains.list_domains'))

    db.session.delete(domain)
    db.session.commit()
    flash('Domain deleted successfully.', 'success')
    return redirect(url_for('domains.list_domains'))
