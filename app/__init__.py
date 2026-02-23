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

    # Register blueprints
    from .routes import register_blueprints
    register_blueprints(app)

    return app


def _auto_migrate(db):
    """Add columns that db.create_all() won't add to existing tables."""
    import sqlalchemy
    insp = sqlalchemy.inspect(db.engine)
    cols = {c['name'] for c in insp.get_columns('site_pages')}
    if 'menu_updated_at' not in cols:
        db.session.execute(sqlalchemy.text(
            'ALTER TABLE site_pages ADD COLUMN menu_updated_at DATETIME'
        ))
        db.session.commit()
