"""Phase 5 tests — Deployment via SSH (all Fabric calls mocked)."""

import json
import os
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, call

import pytest

from app.models import (
    db as _db, Site, SiteBrand, SitePage, Geo, Vertical, Brand, BrandGeo,
    BrandVertical, PageType, Domain,
)
from app.services.deployer import deploy_site, rollback_site, _prune_releases, MAX_RELEASES


def _uid():
    return uuid.uuid4().hex[:8]


def _create_built_site(db, tmp_path, domain_name=None, version=1, deployed_at=None):
    """Helper: create a site with a domain, build output, and return it."""
    uid = _uid()
    geo = Geo.query.filter_by(code='gb').first()
    vertical = Vertical.query.filter_by(slug='sports-betting').first()

    # Create domain
    domain = None
    if domain_name:
        domain = Domain(domain=domain_name, status='assigned')
        db.session.add(domain)
        db.session.flush()

    # Create brand
    brand = Brand(name=f'Brand-{uid}', slug=f'brand-{uid}', rating=4.5)
    db.session.add(brand)
    db.session.flush()

    db.session.add(BrandGeo(brand_id=brand.id, geo_id=geo.id, welcome_bonus='$100'))
    db.session.add(BrandVertical(brand_id=brand.id, vertical_id=vertical.id))

    # Create site
    site = Site(
        name=f'Test Site {uid}',
        geo_id=geo.id,
        vertical_id=vertical.id,
        domain_id=domain.id if domain else None,
        status='built',
        current_version=version,
        deployed_at=deployed_at,
    )
    db.session.add(site)
    db.session.flush()

    # Create site brand
    db.session.add(SiteBrand(site_id=site.id, brand_id=brand.id, rank=1))

    # Create a minimal page
    pt = PageType.query.filter_by(slug='homepage').first()
    page = SitePage(
        site_id=site.id,
        page_type_id=pt.id,
        slug='index',
        title='Home',
        content_json=json.dumps({'hero_title': 'Test'}),
        is_generated=True,
        generated_at=datetime.now(timezone.utc),
    )
    db.session.add(page)

    # Create output directory with a test file
    output_dir = os.path.join(str(tmp_path), f'{site.id}_test-site', f'v{version}')
    os.makedirs(output_dir, exist_ok=True)
    with open(os.path.join(output_dir, 'index.html'), 'w') as f:
        f.write('<html><body>Test</body></html>')
    # Create a subdirectory with a file
    reviews_dir = os.path.join(output_dir, 'reviews')
    os.makedirs(reviews_dir, exist_ok=True)
    with open(os.path.join(reviews_dir, 'test.html'), 'w') as f:
        f.write('<html><body>Review</body></html>')

    site.output_path = output_dir

    db.session.flush()
    return site


def _make_app_config(domain='example.com'):
    """Return a config dict with VPS settings."""
    return {
        'VPS_HOST': '192.168.1.100',
        'VPS_USER': 'deploy',
        'VPS_SSH_KEY_PATH': '~/.ssh/id_rsa',
        'VPS_WEB_ROOT': '/var/www/sites',
        'NGINX_SITES_AVAILABLE': '/etc/nginx/sites-available',
        'NGINX_SITES_ENABLED': '/etc/nginx/sites-enabled',
    }


# ── 5.1  Deployment Flow (Mocked) ──────────────────────────────

@patch('app.services.deployer._get_connection')
def test_deploy_creates_dirs_uploads_and_configures(mock_get_conn, app, db, tmp_path):
    """Full deploy: mkdir, put, symlink, nginx config, nginx reload, certbot."""
    mock_conn = MagicMock()
    mock_conn.run.return_value = MagicMock(stdout='')
    mock_get_conn.return_value = mock_conn

    domain_name = f'deploy-{_uid()}.co.uk'
    site = _create_built_site(db, tmp_path, domain_name=domain_name)
    config = _make_app_config()

    result = deploy_site(site, config)

    # Verify directory creation
    run_calls = [str(c) for c in mock_conn.run.call_args_list]
    assert any(f'mkdir -p /var/www/sites/{domain_name}/releases/v1' in c for c in run_calls)

    # Verify file upload (put called for index.html + reviews/test.html)
    assert mock_conn.put.call_count == 2

    # Verify symlink update
    assert any(f'ln -sfn' in c and 'current' in c for c in run_calls)

    # Verify nginx config uploaded
    sudo_calls = [str(c) for c in mock_conn.sudo.call_args_list]
    assert any(f'mv /tmp/{domain_name}.conf' in c for c in sudo_calls)
    assert any(f'ln -sfn' in c and 'sites-enabled' in c for c in sudo_calls)

    # Verify nginx reload
    assert any('nginx -s reload' in c for c in sudo_calls)

    # Verify certbot called (first deploy — deployed_at was None)
    assert any('certbot' in c and domain_name in c for c in sudo_calls)

    # Verify site status updated
    assert site.status == 'deployed'
    assert site.deployed_at is not None
    assert site.domain.status == 'deployed'


@patch('app.services.deployer._get_connection')
def test_deploy_requires_domain(mock_get_conn, app, db, tmp_path):
    """Deploy without domain raises ValueError."""
    site = _create_built_site(db, tmp_path, domain_name=None)
    config = _make_app_config()

    with pytest.raises(ValueError, match='domain assigned'):
        deploy_site(site, config)


@patch('app.services.deployer._get_connection')
def test_deploy_requires_output_path(mock_get_conn, app, db, tmp_path):
    """Deploy without output_path raises ValueError."""
    domain_name = f'deploy-{_uid()}.co.uk'
    site = _create_built_site(db, tmp_path, domain_name=domain_name)
    site.output_path = None
    config = _make_app_config()

    with pytest.raises(ValueError, match='built before'):
        deploy_site(site, config)


# ── 5.2  Re-deploy (Version Update) ────────────────────────────

@patch('app.services.deployer._get_connection')
def test_redeploy_updates_symlink_no_certbot(mock_get_conn, app, db, tmp_path):
    """Re-deploy (already deployed once): symlink updated, certbot NOT called."""
    mock_conn = MagicMock()
    mock_conn.run.return_value = MagicMock(stdout='')
    mock_get_conn.return_value = mock_conn

    domain_name = f'redeploy-{_uid()}.co.uk'
    # Site was previously deployed (deployed_at is set)
    site = _create_built_site(
        db, tmp_path, domain_name=domain_name, version=2,
        deployed_at=datetime.now(timezone.utc),
    )
    config = _make_app_config()

    deploy_site(site, config)

    # Verify symlink points to v2
    run_calls = [str(c) for c in mock_conn.run.call_args_list]
    assert any('v2' in c and 'ln -sfn' in c for c in run_calls)

    # Verify certbot was NOT called (not first deploy)
    sudo_calls = [str(c) for c in mock_conn.sudo.call_args_list]
    assert not any('certbot' in c for c in sudo_calls)


# ── 5.3  Rollback (Mocked) ─────────────────────────────────────

@patch('app.services.deployer._get_connection')
def test_rollback_updates_symlink(mock_get_conn, app, db, tmp_path):
    """Rollback: symlink updated to previous version, nginx reloaded, no files uploaded."""
    mock_conn = MagicMock()
    mock_get_conn.return_value = mock_conn

    domain_name = f'rollback-{_uid()}.co.uk'
    site = _create_built_site(
        db, tmp_path, domain_name=domain_name, version=2,
        deployed_at=datetime.now(timezone.utc),
    )
    config = _make_app_config()

    result = rollback_site(site, config)

    assert result == 1  # rolled back to v1

    # Verify symlink updated to v1
    run_calls = [str(c) for c in mock_conn.run.call_args_list]
    assert any('v1' in c and 'ln -sfn' in c for c in run_calls)

    # Verify nginx reload
    sudo_calls = [str(c) for c in mock_conn.sudo.call_args_list]
    assert any('nginx -s reload' in c for c in sudo_calls)

    # Verify no files uploaded (no put calls)
    assert mock_conn.put.call_count == 0


@patch('app.services.deployer._get_connection')
def test_rollback_no_previous_version_raises(mock_get_conn, app, db, tmp_path):
    """Rollback from v1 raises ValueError (no previous version)."""
    domain_name = f'norollback-{_uid()}.co.uk'
    site = _create_built_site(
        db, tmp_path, domain_name=domain_name, version=1,
        deployed_at=datetime.now(timezone.utc),
    )
    config = _make_app_config()

    with pytest.raises(ValueError, match='No previous version'):
        rollback_site(site, config)


@patch('app.services.deployer._get_connection')
def test_rollback_specific_version(mock_get_conn, app, db, tmp_path):
    """Rollback to a specific version."""
    mock_conn = MagicMock()
    mock_get_conn.return_value = mock_conn

    domain_name = f'specrollback-{_uid()}.co.uk'
    site = _create_built_site(
        db, tmp_path, domain_name=domain_name, version=4,
        deployed_at=datetime.now(timezone.utc),
    )
    config = _make_app_config()

    result = rollback_site(site, config, target_version=2)
    assert result == 2

    run_calls = [str(c) for c in mock_conn.run.call_args_list]
    assert any('v2' in c and 'ln -sfn' in c for c in run_calls)


# ── 5.4  Version Pruning ───────────────────────────────────────

@patch('app.services.deployer._get_connection')
def test_prune_keeps_last_3_versions(mock_get_conn, app, db, tmp_path):
    """Deploy with 4 versions: v1 deleted, v2/v3/v4 kept."""
    mock_conn = MagicMock()
    # Simulate ls showing 4 versions
    mock_conn.run.return_value = MagicMock(stdout='v1\nv2\nv3\nv4\n')
    mock_get_conn.return_value = mock_conn

    _prune_releases(mock_conn, '/var/www/sites/example.com/releases')

    # v1 should be deleted (4 versions, keep 3)
    run_calls = [str(c) for c in mock_conn.run.call_args_list]
    assert any('rm -rf' in c and 'v1' in c for c in run_calls)
    # v2, v3, v4 should NOT be deleted
    assert not any('rm -rf' in c and 'v2' in c for c in run_calls)
    assert not any('rm -rf' in c and 'v3' in c for c in run_calls)
    assert not any('rm -rf' in c and 'v4' in c for c in run_calls)


@patch('app.services.deployer._get_connection')
def test_prune_no_delete_when_within_limit(mock_get_conn, app, db, tmp_path):
    """3 or fewer versions: nothing deleted."""
    mock_conn = MagicMock()
    mock_conn.run.return_value = MagicMock(stdout='v1\nv2\nv3\n')
    mock_get_conn.return_value = mock_conn

    _prune_releases(mock_conn, '/var/www/sites/example.com/releases')

    run_calls = [str(c) for c in mock_conn.run.call_args_list]
    assert not any('rm -rf' in c for c in run_calls)


# ── 5.5  Domain Assignment ─────────────────────────────────────

def test_assign_domain_route(app, db, client, tmp_path):
    """POST assign-domain: domain status changes to 'assigned'."""
    uid = _uid()
    geo = Geo.query.filter_by(code='gb').first()
    vertical = Vertical.query.filter_by(slug='sports-betting').first()

    domain = Domain(domain=f'assign-{uid}.co.uk', status='available')
    db.session.add(domain)
    site = Site(name=f'Site {uid}', geo_id=geo.id, vertical_id=vertical.id, status='built')
    db.session.add(site)
    db.session.flush()

    resp = client.post(f'/sites/{site.id}/assign-domain', data={
        'domain_id': domain.id,
    }, follow_redirects=True)

    assert resp.status_code == 200
    assert domain.status == 'assigned'
    assert site.domain_id == domain.id


def test_assign_already_assigned_domain(app, db, client, tmp_path):
    """Cannot assign a domain that is already assigned."""
    uid = _uid()
    geo = Geo.query.filter_by(code='gb').first()
    vertical = Vertical.query.filter_by(slug='sports-betting').first()

    domain = Domain(domain=f'taken-{uid}.co.uk', status='assigned')
    db.session.add(domain)
    site = Site(name=f'Site {uid}', geo_id=geo.id, vertical_id=vertical.id, status='built')
    db.session.add(site)
    db.session.flush()

    resp = client.post(f'/sites/{site.id}/assign-domain', data={
        'domain_id': domain.id,
    }, follow_redirects=True)

    assert resp.status_code == 200
    assert b'already assigned' in resp.data


@patch('app.routes.sites.deploy_site')
def test_deploy_route_sets_domain_deployed(mock_deploy, app, db, client, tmp_path):
    """Deploy via route: domain.status → 'deployed'."""
    uid = _uid()
    geo = Geo.query.filter_by(code='gb').first()
    vertical = Vertical.query.filter_by(slug='sports-betting').first()

    domain = Domain(domain=f'deploydomain-{uid}.co.uk', status='assigned')
    db.session.add(domain)
    db.session.flush()

    site = Site(
        name=f'Site {uid}', geo_id=geo.id, vertical_id=vertical.id,
        domain_id=domain.id, status='built', output_path='/tmp/fake',
    )
    db.session.add(site)
    db.session.flush()

    def fake_deploy(site_obj, config):
        site_obj.status = 'deployed'
        site_obj.deployed_at = datetime.now(timezone.utc)
        site_obj.domain.status = 'deployed'
        return '/var/www/sites/test/releases/v1'

    mock_deploy.side_effect = fake_deploy

    resp = client.post(f'/sites/{site.id}/deploy', follow_redirects=True)

    assert resp.status_code == 200
    assert domain.status == 'deployed'
    assert site.status == 'deployed'


# ── 5.6  Deployment Failure ─────────────────────────────────────

@patch('app.routes.sites.deploy_site')
def test_deploy_failure_sets_failed_status(mock_deploy, app, db, client, tmp_path):
    """SSH failure: site.status → 'failed', domain stays 'assigned'."""
    uid = _uid()
    geo = Geo.query.filter_by(code='gb').first()
    vertical = Vertical.query.filter_by(slug='sports-betting').first()

    domain = Domain(domain=f'failsite-{uid}.co.uk', status='assigned')
    db.session.add(domain)
    db.session.flush()

    site = Site(
        name=f'Site {uid}', geo_id=geo.id, vertical_id=vertical.id,
        domain_id=domain.id, status='built', output_path='/tmp/fake',
    )
    db.session.add(site)
    db.session.flush()

    mock_deploy.side_effect = Exception('SSH connection timed out')

    resp = client.post(f'/sites/{site.id}/deploy', follow_redirects=True)

    assert resp.status_code == 200
    assert site.status == 'failed'
    assert domain.status == 'assigned'  # NOT changed to deployed


@patch('app.services.deployer._get_connection')
def test_deploy_service_exception_propagates(mock_get_conn, app, db, tmp_path):
    """Deployer raises when SSH fails."""
    mock_conn = MagicMock()
    mock_conn.run.side_effect = Exception('Connection refused')
    mock_get_conn.return_value = mock_conn

    domain_name = f'sshfail-{_uid()}.co.uk'
    site = _create_built_site(db, tmp_path, domain_name=domain_name)
    config = _make_app_config()

    with pytest.raises(Exception, match='Connection refused'):
        deploy_site(site, config)


# ── Route guard tests ──────────────────────────────────────────

def test_deploy_requires_built_status(app, db, client):
    """Cannot deploy a site that isn't built."""
    uid = _uid()
    geo = Geo.query.filter_by(code='gb').first()
    vertical = Vertical.query.filter_by(slug='sports-betting').first()

    domain = Domain(domain=f'guard-{uid}.co.uk', status='assigned')
    db.session.add(domain)
    db.session.flush()

    site = Site(
        name=f'Site {uid}', geo_id=geo.id, vertical_id=vertical.id,
        domain_id=domain.id, status='generated',
    )
    db.session.add(site)
    db.session.flush()

    resp = client.post(f'/sites/{site.id}/deploy', follow_redirects=True)
    assert resp.status_code == 200
    assert b'must be built' in resp.data


def test_deploy_requires_domain_assigned(app, db, client):
    """Cannot deploy without a domain."""
    uid = _uid()
    geo = Geo.query.filter_by(code='gb').first()
    vertical = Vertical.query.filter_by(slug='sports-betting').first()

    site = Site(
        name=f'Site {uid}', geo_id=geo.id, vertical_id=vertical.id, status='built',
    )
    db.session.add(site)
    db.session.flush()

    resp = client.post(f'/sites/{site.id}/deploy', follow_redirects=True)
    assert resp.status_code == 200
    assert b'Assign a domain' in resp.data


@patch('app.routes.sites.rollback_site')
def test_rollback_route(mock_rollback, app, db, client):
    """Rollback route calls rollback_site and flashes success."""
    uid = _uid()
    geo = Geo.query.filter_by(code='gb').first()
    vertical = Vertical.query.filter_by(slug='sports-betting').first()

    domain = Domain(domain=f'rollbackroute-{uid}.co.uk', status='deployed')
    db.session.add(domain)
    db.session.flush()

    site = Site(
        name=f'Site {uid}', geo_id=geo.id, vertical_id=vertical.id,
        domain_id=domain.id, status='deployed', current_version=2,
        deployed_at=datetime.now(timezone.utc),
    )
    db.session.add(site)
    db.session.flush()

    mock_rollback.return_value = 1

    resp = client.post(f'/sites/{site.id}/rollback', follow_redirects=True)
    assert resp.status_code == 200
    assert mock_rollback.called
