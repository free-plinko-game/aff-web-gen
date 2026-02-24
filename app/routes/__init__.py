from .dashboard import bp as dashboard_bp
from .brands import bp as brands_bp
from .domains import bp as domains_bp
from .sites import bp as sites_bp
from .api import bp as api_bp
from .comments_api import bp as comments_api_bp


def register_blueprints(app):
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(brands_bp)
    app.register_blueprint(domains_bp)
    app.register_blueprint(sites_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(comments_api_bp)
