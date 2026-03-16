"""Authentication routes."""

from urllib.parse import urlparse

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required

from ..models import AdminUser

bp = Blueprint('auth', __name__, url_prefix='/auth')


def _is_safe_redirect_url(target):
    """Only allow redirects to relative paths on the same host."""
    if not target:
        return False
    parsed = urlparse(target)
    # Reject absolute URLs (with scheme or netloc) to prevent open redirect
    if parsed.scheme or parsed.netloc:
        return False
    # Must start with / to be a valid relative path
    return target.startswith('/')


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        user = AdminUser.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            next_page = request.args.get('next')
            if not _is_safe_redirect_url(next_page):
                next_page = None
            return redirect(next_page or url_for('dashboard.index'))

        flash('Invalid username or password.', 'error')

    return render_template('auth/login.html')


@bp.route('/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    flash('Logged out.', 'success')
    return redirect(url_for('auth.login'))
