"""SSH deployment service using Fabric.

Deploys built static sites to a VPS using symlink-based versioning:
    /var/www/sites/{domain}/
    ├── releases/
    │   ├── v1/
    │   ├── v2/
    │   └── ...
    └── current → releases/v{n}   ← symlink to active version
"""

import logging
import os
import posixpath
from datetime import datetime, timezone

from fabric import Connection

logger = logging.getLogger(__name__)

from ..models import db, Site


# Number of release versions to keep on the server
MAX_RELEASES = 3


def _get_connection(app_config):
    """Create a Fabric SSH connection from app config."""
    host = app_config['VPS_HOST']
    user = app_config.get('VPS_USER', 'deploy')
    key_path = app_config.get('VPS_SSH_KEY_PATH', '~/.ssh/id_rsa')

    connect_kwargs = {}
    if key_path:
        key_path = os.path.expanduser(key_path)
        connect_kwargs['key_filename'] = key_path

    return Connection(host=host, user=user, connect_kwargs=connect_kwargs)


def _generate_nginx_config(domain, web_root, ssl=False, comments_proxy_port=None):
    """Generate an Nginx server block config for a domain.

    Args:
        domain: The domain name
        web_root: VPS web root path
        ssl: If True, generate config with SSL directives (for domains
             where Certbot has already provisioned a certificate)
        comments_proxy_port: If set, add a /comments-api/ proxy to this local port
    """
    site_root = posixpath.join(web_root, domain, 'current')
    static_cache = """
    location ~* \\.(css|js|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot)$ {
        expires 30d;
        add_header Cache-Control "public, immutable";
    }"""

    comments_block = ''
    if comments_proxy_port:
        comments_block = f"""
    location /comments-api/ {{
        proxy_pass http://127.0.0.1:{comments_proxy_port};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }}
"""

    if ssl:
        return f"""server {{
    listen 80;
    listen [::]:80;
    server_name {domain} www.{domain};
    return 301 https://{domain}$request_uri;
}}

server {{
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name {domain} www.{domain};
    root {site_root};
    index index.html;

    ssl_certificate /etc/letsencrypt/live/{domain}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{domain}/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;
{comments_block}
    location / {{
        try_files $uri $uri.html $uri/ =404;
    }}
{static_cache}
}}
"""
    else:
        return f"""server {{
    listen 80;
    listen [::]:80;
    server_name {domain} www.{domain};
    root {site_root};
    index index.html;
{comments_block}
    location / {{
        try_files $uri $uri.html $uri/ =404;
    }}
{static_cache}
}}
"""


def deploy_site(site, app_config):
    """Deploy a built site to the VPS.

    Args:
        site: Site model instance (must have output_path and domain set)
        app_config: Flask app.config dict with VPS settings

    Returns:
        str: The deployed version directory path on the server

    Raises:
        ValueError: If site is missing required fields
        Exception: If SSH operations fail
    """
    if not site.domain:
        raise ValueError('Site must have a domain assigned before deploying.')
    if not site.output_path:
        raise ValueError('Site must be built before deploying.')

    domain = site.domain.domain
    web_root = app_config.get('VPS_WEB_ROOT', '/var/www/sites')
    sites_available = app_config.get('NGINX_SITES_AVAILABLE', '/etc/nginx/sites-available')
    sites_enabled = app_config.get('NGINX_SITES_ENABLED', '/etc/nginx/sites-enabled')

    # Derive version from the local build output path (e.g. "v7")
    # rather than current_version which may be incremented already.
    local_version = os.path.basename(site.output_path)
    site_dir = posixpath.join(web_root, domain)
    releases_dir = posixpath.join(site_dir, 'releases')
    version_dir = posixpath.join(releases_dir, local_version)
    current_link = posixpath.join(site_dir, 'current')

    is_first_deploy = site.deployed_at is None

    logger.info('Deploying site %d to %s (%s, first_deploy=%s)', site.id, domain, local_version, is_first_deploy)
    conn = _get_connection(app_config)

    # Create directory structure
    conn.run(f'mkdir -p {version_dir}')

    # Upload site files
    local_output = site.output_path
    for root, dirs, files in os.walk(local_output):
        for fname in files:
            local_path = os.path.join(root, fname)
            # Compute the relative path from the output directory
            rel_path = os.path.relpath(local_path, local_output)
            # Convert Windows backslashes to POSIX forward slashes
            rel_path_posix = rel_path.replace('\\', '/')
            remote_path = posixpath.join(version_dir, rel_path_posix)
            remote_dir = posixpath.dirname(remote_path)
            conn.run(f'mkdir -p {remote_dir}')
            conn.put(local_path, remote=remote_path)

    # Verify release directory has files before updating symlink
    check = conn.run(f'find {version_dir} -type f | head -1', hide=True)
    if not check.stdout.strip():
        raise RuntimeError(f'Release directory {version_dir} is empty after upload — aborting symlink update')

    # Update current symlink
    conn.run(f'ln -sfn {version_dir} {current_link}')

    # Generate and upload Nginx config
    # If SSL was already provisioned, generate config with SSL directives
    # so we don't wipe Certbot's modifications on redeploy
    comments_port = None
    if getattr(site, 'comments_enabled', False) and getattr(site, 'comments_api_url', ''):
        comments_port = app_config.get('GUNICORN_PORT', 8000)
    nginx_config = _generate_nginx_config(domain, web_root, ssl=site.domain.ssl_provisioned, comments_proxy_port=comments_port)
    nginx_conf_path = posixpath.join(sites_available, domain)
    nginx_enabled_path = posixpath.join(sites_enabled, domain)

    # Write config via heredoc to avoid quoting issues
    conn.run(f"cat > /tmp/{domain}.conf << 'NGINX_EOF'\n{nginx_config}NGINX_EOF")
    conn.sudo(f'mv /tmp/{domain}.conf {nginx_conf_path}')

    # Symlink to sites-enabled
    conn.sudo(f'ln -sfn {nginx_conf_path} {nginx_enabled_path}')

    # Reload Nginx
    conn.sudo('nginx -s reload')

    # Provision SSL on first deploy via Certbot
    if not site.domain.ssl_provisioned:
        try:
            conn.sudo(f'certbot --nginx -d {domain} -d www.{domain} --non-interactive --agree-tos --redirect')
            site.domain.ssl_provisioned = True
            logger.info('SSL provisioned for %s', domain)
        except Exception as e:
            logger.warning('Certbot failed for %s (non-fatal): %s', domain, e)

    # Prune old releases (keep last MAX_RELEASES, never prune active)
    _prune_releases(conn, releases_dir, active_version=local_version)

    # Update site record
    site.status = 'deployed'
    site.deployed_at = datetime.now(timezone.utc)

    # Update domain status
    site.domain.status = 'deployed'

    logger.info('Deployment complete for site %d at %s', site.id, domain)
    return version_dir


def rollback_site(site, app_config, target_version=None):
    """Rollback a site to a previous version by updating the symlink.

    Args:
        site: Site model instance
        app_config: Flask app.config dict
        target_version: Specific version number to roll back to.
                       If None, rolls back to current_version - 1.

    Returns:
        int: The version number that is now active

    Raises:
        ValueError: If no previous version exists
    """
    if not site.domain:
        raise ValueError('Site must have a domain assigned.')

    domain = site.domain.domain
    web_root = app_config.get('VPS_WEB_ROOT', '/var/www/sites')

    if target_version is None:
        target_version = site.current_version - 1

    if target_version < 1:
        raise ValueError('No previous version to roll back to.')

    logger.info('Rolling back site %d to v%d', site.id, target_version)
    site_dir = posixpath.join(web_root, domain)
    releases_dir = posixpath.join(site_dir, 'releases')
    target_dir = posixpath.join(releases_dir, f'v{target_version}')
    current_link = posixpath.join(site_dir, 'current')

    conn = _get_connection(app_config)

    # Update symlink to the target version
    conn.run(f'ln -sfn {target_dir} {current_link}')

    # Reload Nginx
    conn.sudo('nginx -s reload')

    return target_version


def _prune_releases(conn, releases_dir, active_version):
    """Remove old releases, keeping only the last MAX_RELEASES versions.

    Args:
        active_version: The version dir name the symlink points to (e.g. 'v7').
                        This version is never pruned regardless of age.
    """
    result = conn.run(f'ls -1 {releases_dir}', hide=True)
    entries = result.stdout.strip().split('\n') if result.stdout.strip() else []

    # Sort numerically by extracting the number from "v{N}"
    def version_key(name):
        try:
            return int(name.lstrip('v'))
        except ValueError:
            return 0

    versions = sorted(entries, key=version_key)

    if len(versions) > MAX_RELEASES:
        to_delete = versions[:len(versions) - MAX_RELEASES]
        for v in to_delete:
            if v == active_version:
                logger.info('Skipping prune of active release: %s', v)
                continue
            logger.info('Pruning old release: %s', v)
            conn.run(f'rm -rf {posixpath.join(releases_dir, v)}')
