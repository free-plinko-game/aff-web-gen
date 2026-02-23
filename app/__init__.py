import os

from flask import Flask

from .models import db


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
    app.config['UPLOAD_FOLDER'] = upload_folder

    db.init_app(app)

    with app.app_context():
        db.create_all()
        _auto_migrate(db)
        _seed_page_types(db)
        _reset_stuck_generating(db)

    # Register blueprints
    from .routes import register_blueprints
    register_blueprints(app)

    return app


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

    db.session.commit()


def _seed_page_types(db):
    """Ensure all required page types exist in the database."""
    from .models import PageType

    required = [
        {'slug': 'news', 'name': 'News Landing', 'template_file': 'news.html'},
        {'slug': 'news-article', 'name': 'News Article', 'template_file': 'news_article.html'},
    ]

    for pt_data in required:
        existing = PageType.query.filter_by(slug=pt_data['slug']).first()
        if not existing:
            db.session.add(PageType(**pt_data))

    db.session.commit()
