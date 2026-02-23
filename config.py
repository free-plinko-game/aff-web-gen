import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.getenv('FLASK_SECRET_KEY', 'dev-secret-key')
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', 'sqlite:///factory.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max upload

    # OpenAI
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')
    OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-4o-mini')

    # API-Football (Tips Pipeline)
    API_FOOTBALL_KEY = os.getenv('API_FOOTBALL_KEY', '')
    TIPS_MAX_MATCHES_PER_DAY = int(os.getenv('TIPS_MAX_MATCHES_PER_DAY', '20'))

    # VPS Deployment
    VPS_HOST = os.getenv('VPS_HOST', '')
    VPS_USER = os.getenv('VPS_USER', 'deploy')
    VPS_SSH_KEY_PATH = os.getenv('VPS_SSH_KEY_PATH', '~/.ssh/id_rsa')
    VPS_WEB_ROOT = os.getenv('VPS_WEB_ROOT', '/var/www/sites')
    NGINX_SITES_AVAILABLE = os.getenv('NGINX_SITES_AVAILABLE', '/etc/nginx/sites-available')
    NGINX_SITES_ENABLED = os.getenv('NGINX_SITES_ENABLED', '/etc/nginx/sites-enabled')
