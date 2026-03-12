# Security Fixes Changelog

## Overview
**Files Modified:** 20 &nbsp;|&nbsp; **Files Created:** 2 &nbsp;|&nbsp; **Tests:** 277 passing, 26 failing *(all pre-existing — 2 fewer than before)*

**Dependencies Added:** `Flask-Login==0.6.3`, `Flask-WTF==1.2.2`, `bleach==6.2.0`

---

## 🔴 Critical Fixes

### Hardcoded Secret Key
- **`config.py`** — Now uses `os.urandom(32).hex()` fallback instead of `'dev-secret-key'`

### Debug Mode
- **`run.py`** — Now reads `FLASK_DEBUG` env var instead of hardcoding `True`

### No Authentication
Added Flask-Login with `@bp.before_request` / `@login_required` on all admin blueprints:

| File | Change |
|------|--------|
| `app/__init__.py` | LoginManager setup, admin user seeding, CSRF init |
| `app/models.py` | New `AdminUser` model |
| `app/routes/auth.py` *(new)* | Login/logout routes |
| `app/templates/auth/login.html` *(new)* | Login page |
| `dashboard.py`, `brands.py`, `domains.py`, `sites.py`, `api.py`, `odds_admin.py` | `@login_required` applied to all 6 admin route files |

### Command Injection in Deployer
- **`app/services/deployer.py`** — Added `_validate_domain()` with strict regex, called before all SSH operations

### Domain Validation at Input
- **`app/routes/domains.py`** — Validates domain format on creation

---

## 🟠 High Fixes

### CSRF Protection
- `Flask-WTF` `CSRFProtect` initialized globally
- CSRF token added to meta tag and auto-injected in all `fetch()` calls via `app/templates/base.html`
- Comments API exempted

### DOM XSS via `innerHTML`
- Added `_esc()` HTML-escape helper in `detail.html` and `add_page.html`
- All API data now escaped before insertion: news suggestions, author lists, persona previews, dead link results, page suggestions

### Reflected XSS in Preview Error
- **`app/routes/api.py`** — Exception messages escaped with `html.escape()`

### Path Traversal in Preview
- **`api.py`** — `os.path.basename()` applied to extracted filenames
- **`sites.py`** — `os.path.realpath()` + prefix check added

### Security Headers
**`app/__init__.py`** now sets:
- `X-Frame-Options: DENY`
- `X-Content-Type-Options: nosniff`
- `X-XSS-Protection`
- `Referrer-Policy`

### CORS Restricted
- **`comments_api.py`** — Replaced `@cross_origin()` wildcard with per-site domain-restricted `@bp.after_request` handler

### IP Spoofing
- **`comments_api.py`** — Replaced `X-Forwarded-For` trust with `request.access_route[0]`

---

## 🟡 Medium / Low Fixes

### `|safe` XSS
- **`preview_renderer.py`** and **`site_builder.py`** — `custom_head` and `author.bio` sanitized with `bleach` allowlists

### SVG Upload XSS
- Removed `'svg'` from `ALLOWED_EXTENSIONS` in both `api.py` and `brands.py`

### Info Disclosure
- 4 error endpoints in `api.py` now return generic messages; details logged server-side only

### MD5 Usage
- Replaced with SHA-256 in `comments_api.py` (email hash) and `site_builder.py` (favicon hue)

### Rate Limiter Memory Leak
- Added periodic cleanup of stale entries in `_is_rate_limited()`

### Comment Body Stored XSS
- HTML-escaped before storage in `comments_api.py`

### Avatar Filename Collisions
- Prefixed with `s{site_id}-` in `_save_avatar()`

### Info Leak in `comments.js`
- Removed URL/error details from HTML comments
