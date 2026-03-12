Files Modified (20) + Created (2)
Critical Fixes:

Hardcoded secret key — config.py: Now uses os.urandom(32).hex() fallback instead of 'dev-secret-key'
Debug mode — run.py: Now reads FLASK_DEBUG env var instead of hardcoding True
No authentication — Added Flask-Login with @bp.before_request @login_required on all admin blueprints:
app/init.py — LoginManager setup, admin user seeding, CSRF init
app/models.py — New AdminUser model
app/routes/auth.py (new) — Login/logout routes
app/templates/auth/login.html (new) — Login page
All 6 admin route files — dashboard.py, brands.py, domains.py, sites.py, api.py, odds_admin.py
Command injection in deployer — app/services/deployer.py: Added _validate_domain() with strict regex, called before all SSH operations
Domain validation at input — app/routes/domains.py: Validates domain format on creation
High Fixes:

CSRF protection — Flask-WTF CSRFProtect initialized globally; CSRF token in meta tag + auto-injected in all fetch() calls via app/templates/base.html; comments API exempted
DOM XSS (innerHTML) — Added _esc() HTML-escape helper in detail.html and add_page.html; all API data now escaped before insertion: news suggestions, author lists, persona previews, dead link results, page suggestions
Reflected XSS in preview error — app/routes/api.py: Exception escaped with html.escape()
Path traversal in preview — api.py: os.path.basename() on extracted filenames; sites.py: os.path.realpath() + prefix check
Security headers — app/init.py: X-Frame-Options: DENY, X-Content-Type-Options: nosniff, X-XSS-Protection, Referrer-Policy
CORS restricted — comments_api.py: Replaced @cross_origin() wildcard with per-site domain-restricted @bp.after_request handler
IP spoofing — comments_api.py: Replaced X-Forwarded-For trust with request.access_route[0]
Medium/Low Fixes:

|safe XSS — preview_renderer.py + site_builder.py: custom_head and author.bio sanitized with bleach allowlists
SVG upload XSS — Removed 'svg' from ALLOWED_EXTENSIONS in both api.py and brands.py
Info disclosure — 4 error endpoints in api.py now return generic messages, logging details server-side
MD5 usage — Replaced with SHA-256 in comments_api.py (email hash) and site_builder.py (favicon hue)
Rate limiter memory leak — Added periodic cleanup of stale entries in _is_rate_limited()
Comment body stored XSS — HTML-escaped before storage in comments_api.py
Avatar filename collisions — Prefixed with s{site_id}- in _save_avatar()
Info leak in comments.js — Removed URL/error details from HTML comment
Dependencies added: Flask-Login==0.6.3, Flask-WTF==1.2.2, bleach==6.2.0

Tests: 277 passing, 26 failing (all pre-existing — same failures before our changes, actually 2 fewer).
