"""Dead internal link sweeper.

Scans content_json for internal links that point to pages that no longer
exist on the site, and optionally removes them (keeping link text).
"""

import json
import logging
import re
from urllib.parse import urlparse

from ..models import db, Site, SitePage
from .site_builder import _page_url_for_link

logger = logging.getLogger(__name__)

# Regex to find <a> tags with internal (absolute-path) hrefs
_LINK_RE = re.compile(
    r'<a\s[^>]*href="(/[^"]*)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)

# Static paths that are always valid (landing pages / section roots)
_STATIC_VALID = {'/', '/reviews', '/bonuses', '/tips', '/news', '/guides'}


def _build_valid_urls(site_pages):
    """Build a set of normalised valid internal URLs from current pages."""
    urls = set(_STATIC_VALID)
    for page in site_pages:
        url = _page_url_for_link(page)
        urls.add(url.rstrip('/'))
    return urls


def _normalise_url(href):
    """Strip trailing slash, query params, and anchors for comparison."""
    parsed = urlparse(href)
    return parsed.path.rstrip('/')


def _walk_json_strings(obj, path=''):
    """Yield (field_path, value) for every string in a nested dict/list."""
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk_json_strings(v, f'{path}.{k}' if path else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk_json_strings(v, f'{path}[{i}]')


def _extract_internal_links(text):
    """Return list of (full_match, href, link_text) for internal links."""
    return [(m.group(0), m.group(1), m.group(2)) for m in _LINK_RE.finditer(text)]


def _remove_dead_links(text, dead_hrefs):
    """Replace <a> tags whose href is in dead_hrefs with their link text."""
    def _replacer(m):
        href = _normalise_url(m.group(1))
        if href in dead_hrefs:
            return m.group(2)  # keep link text, strip tag
        return m.group(0)
    return _LINK_RE.sub(_replacer, text)


def _fix_json_strings(obj, dead_hrefs):
    """Recursively walk obj and remove dead links from all string values.

    Returns (new_obj, changes_count).
    """
    if isinstance(obj, str):
        links = _extract_internal_links(obj)
        dead_in_str = [h for _, h, _ in links if _normalise_url(h) in dead_hrefs]
        if dead_in_str:
            return _remove_dead_links(obj, dead_hrefs), len(dead_in_str)
        return obj, 0
    elif isinstance(obj, dict):
        total = 0
        new = {}
        for k, v in obj.items():
            new[k], n = _fix_json_strings(v, dead_hrefs)
            total += n
        return new, total
    elif isinstance(obj, list):
        total = 0
        new = []
        for v in obj:
            fixed, n = _fix_json_strings(v, dead_hrefs)
            new.append(fixed)
            total += n
        return new, total
    return obj, 0


def sweep_dead_links(site_id, fix=False):
    """Scan a site's content_json for dead internal links.

    Args:
        site_id: The site to scan.
        fix: If True, remove dead <a> tags and save updated content_json.

    Returns:
        dict with keys: dead_links (list), count, fixed, pages_updated.
    """
    site = db.session.get(Site, site_id)
    if not site:
        return {'dead_links': [], 'count': 0, 'fixed': 0, 'pages_updated': 0}

    pages = SitePage.query.filter_by(site_id=site_id).all()
    valid_urls = _build_valid_urls(pages)

    dead_links = []

    for page in pages:
        if not page.content_json:
            continue
        try:
            content = json.loads(page.content_json)
        except (json.JSONDecodeError, TypeError):
            continue

        for field_path, text in _walk_json_strings(content):
            for full_match, href, link_text in _extract_internal_links(text):
                normalised = _normalise_url(href)
                if normalised and normalised not in valid_urls:
                    dead_links.append({
                        'page_id': page.id,
                        'page_title': page.title or page.slug,
                        'page_slug': page.slug,
                        'link_url': href,
                        'link_text': link_text,
                        'field_path': field_path,
                    })

    fixed = 0
    pages_updated = 0

    if fix and dead_links:
        dead_hrefs = {_normalise_url(d['link_url']) for d in dead_links}
        for page in pages:
            if not page.content_json:
                continue
            try:
                content = json.loads(page.content_json)
            except (json.JSONDecodeError, TypeError):
                continue

            new_content, n = _fix_json_strings(content, dead_hrefs)
            if n > 0:
                page.content_json = json.dumps(new_content)
                fixed += n
                pages_updated += 1

        if pages_updated:
            db.session.commit()
            logger.info('Swept %d dead links from %d pages on site %d',
                        fixed, pages_updated, site_id)

    return {
        'dead_links': dead_links,
        'count': len(dead_links),
        'fixed': fixed,
        'pages_updated': pages_updated,
    }
