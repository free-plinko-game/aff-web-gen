import os

from flask import Flask
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect

from .models import db

login_manager = LoginManager()
login_manager.login_view = 'auth.login'
csrf = CSRFProtect()


def create_app(test_config=None):
    app = Flask(__name__)

    if test_config is None:
        from config import Config
        app.config.from_object(Config)
    else:
        app.config.update(test_config)

    # Ensure upload directory exists
    upload_folder = app.config.get('UPLOAD_FOLDER', os.path.join(app.root_path, '..', 'uploads'))
    os.makedirs(os.path.join(upload_folder, 'logos'), exist_ok=True)
    os.makedirs(os.path.join(upload_folder, 'avatars'), exist_ok=True)
    app.config['UPLOAD_FOLDER'] = upload_folder

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        from .models import AdminUser
        return db.session.get(AdminUser, int(user_id))

    with app.app_context():
        db.create_all()
        _auto_migrate(db)
        _seed_page_types(db)
        _seed_admin_user(db, app)
        _reset_stuck_generating(db)

    # Security headers
    @app.after_request
    def set_security_headers(response):
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        return response

    # Register blueprints
    from .routes import register_blueprints
    register_blueprints(app)

    from .routes.auth import bp as auth_bp
    app.register_blueprint(auth_bp)

    # Exempt the public comments API from CSRF (called by external static sites)
    from .routes.comments_api import bp as comments_bp
    csrf.exempt(comments_bp)

    return app


def _seed_admin_user(db, app):
    """Create a default admin user if none exists."""
    from .models import AdminUser
    if AdminUser.query.count() == 0:
        password = os.environ.get('ADMIN_PASSWORD', 'changeme')
        admin = AdminUser(username='admin')
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()
        if password == 'changeme':
            import logging
            logging.getLogger(__name__).warning(
                'Default admin user created with password "changeme". '
                'Set ADMIN_PASSWORD env var or change it immediately!'
            )


def _reset_stuck_generating(db):
    """Reset any sites stuck in 'generating' status from a previous crash."""
    import logging
    from .models import Site
    stuck = Site.query.filter_by(status='generating').all()
    if stuck:
        logger = logging.getLogger(__name__)
        for s in stuck:
            logger.warning('Resetting stuck site %d (%s) from generating to failed', s.id, s.name)
            s.status = 'failed'
        db.session.commit()


def _auto_migrate(db):
    """Add columns that db.create_all() won't add to existing tables."""
    import sqlalchemy
    insp = sqlalchemy.inspect(db.engine)

    site_pages_cols = {c['name'] for c in insp.get_columns('site_pages')}
    if 'menu_updated_at' not in site_pages_cols:
        db.session.execute(sqlalchemy.text(
            'ALTER TABLE site_pages ADD COLUMN menu_updated_at DATETIME'
        ))

    domains_cols = {c['name'] for c in insp.get_columns('domains')}
    if 'ssl_provisioned' not in domains_cols:
        db.session.execute(sqlalchemy.text(
            'ALTER TABLE domains ADD COLUMN ssl_provisioned BOOLEAN NOT NULL DEFAULT 0'
        ))

    if 'published_date' not in site_pages_cols:
        db.session.execute(sqlalchemy.text(
            'ALTER TABLE site_pages ADD COLUMN published_date DATETIME'
        ))

    if 'fixture_id' not in site_pages_cols:
        db.session.execute(sqlalchemy.text(
            'ALTER TABLE site_pages ADD COLUMN fixture_id INTEGER'
        ))

    sites_cols = {c['name'] for c in insp.get_columns('sites')}
    if 'tips_leagues' not in sites_cols:
        db.session.execute(sqlalchemy.text(
            'ALTER TABLE sites ADD COLUMN tips_leagues TEXT'
        ))
    if 'default_author_id' not in sites_cols:
        db.session.execute(sqlalchemy.text(
            'ALTER TABLE sites ADD COLUMN default_author_id INTEGER'
        ))

    if 'author_id' not in site_pages_cols:
        db.session.execute(sqlalchemy.text(
            'ALTER TABLE site_pages ADD COLUMN author_id INTEGER'
        ))

    if 'comments_enabled' not in sites_cols:
        db.session.execute(sqlalchemy.text(
            'ALTER TABLE sites ADD COLUMN comments_enabled BOOLEAN NOT NULL DEFAULT 0'
        ))
    if 'comments_api_url' not in sites_cols:
        db.session.execute(sqlalchemy.text(
            'ALTER TABLE sites ADD COLUMN comments_api_url TEXT'
        ))

    if insp.has_table('comment_users'):
        cu_cols = {c['name'] for c in insp.get_columns('comment_users')}
        if 'email' not in cu_cols:
            db.session.execute(sqlalchemy.text(
                'ALTER TABLE comment_users ADD COLUMN email VARCHAR(254)'
            ))
        if 'is_banned' not in cu_cols:
            db.session.execute(sqlalchemy.text(
                'ALTER TABLE comment_users ADD COLUMN is_banned BOOLEAN NOT NULL DEFAULT 0'
            ))

    if insp.has_table('comments'):
        comments_cols = {c['name'] for c in insp.get_columns('comments')}
        if 'is_hidden' not in comments_cols:
            db.session.execute(sqlalchemy.text(
                'ALTER TABLE comments ADD COLUMN is_hidden BOOLEAN NOT NULL DEFAULT 0'
            ))
        if 'flag_count' not in comments_cols:
            db.session.execute(sqlalchemy.text(
                'ALTER TABLE comments ADD COLUMN flag_count INTEGER NOT NULL DEFAULT 0'
            ))

    db.session.commit()


def _seed_page_types(db):
    """Ensure all required page types exist in the database."""
    from .models import PageType

    required = [
        {'slug': 'news', 'name': 'News Landing', 'template_file': 'news.html'},
        {'slug': 'news-article', 'name': 'News Article', 'template_file': 'news_article.html'},
        {'slug': 'tips', 'name': 'Tips Landing', 'template_file': 'tips.html'},
        {'slug': 'tips-article', 'name': 'Tips Article', 'template_file': 'tips_article.html'},
        {'slug': 'odds-hub', 'name': 'Odds Comparison', 'template_file': 'odds_hub.html'},
    ]

    for pt_data in required:
        existing = PageType.query.filter_by(slug=pt_data['slug']).first()
        if not existing:
            db.session.add(PageType(**pt_data))

    db.session.commit()
