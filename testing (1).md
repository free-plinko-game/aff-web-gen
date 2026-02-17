# Affiliate Site Factory — Testing Guide

## Overview

This document defines tests to run **during and after each build phase**. Claude Code should run the relevant tests after completing each phase before moving to the next. Tests are a mix of automated (pytest) and manual verification steps.

---

## Tech Stack (Testing)

| Layer | Technology |
|---|---|
| Test Framework | pytest |
| Flask Test Client | `app.test_client()` |
| DB Testing | In-memory SQLite (`sqlite:///:memory:`) |
| Coverage (optional) | pytest-cov |

---

## Setup

### Test File Structure

```
tests/
├── conftest.py              ← Shared fixtures (app, client, db, seeded data)
├── test_models.py           ← Schema, constraints, relationships
├── test_brands.py           ← Brand CRUD + logo upload
├── test_domains.py          ← Domain CRUD
├── test_wizard.py           ← Site creation wizard
├── test_content_gen.py      ← Content generation service
├── test_site_builder.py     ← Static site builder
├── test_deployer.py         ← Deployment service
└── test_api.py              ← AJAX / API endpoints
```

### `conftest.py` — Core Fixtures

```python
import pytest
from app import create_app
from app.models import db as _db
from app.seed import seed_all

@pytest.fixture(scope='session')
def app():
    """Create the Flask app with a test config."""
    app = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'WTF_CSRF_ENABLED': False,
        'UPLOAD_FOLDER': '/tmp/test_uploads',
    })
    with app.app_context():
        _db.create_all()
        seed_all()  # Populate GEOs, verticals, page_types
        yield app
        _db.drop_all()

@pytest.fixture(scope='function')
def db(app):
    """Provide a clean DB session per test (rolls back after each)."""
    with app.app_context():
        _db.session.begin_nested()
        yield _db
        _db.session.rollback()

@pytest.fixture(scope='function')
def client(app):
    """Flask test client."""
    return app.test_client()
```

**Note:** Claude Code should create `conftest.py` during Phase 1 and extend it with new fixtures as needed in later phases.

---

## Phase 1: Foundation

### Automated Tests (`test_models.py`)

#### 1.1 — Seed Data Loaded
```
- Assert all 7 GEOs exist in the DB
- Assert all 3 verticals exist
- Assert all 5 page_types exist
- Assert GEO codes match expected values (gb, de, br, ng, ca, in, au)
- Assert vertical slugs match expected values
- Assert page_type slugs match expected values
```

#### 1.2 — Unique Constraints
```
- Insert a brand with slug "bet365" → succeeds
- Insert another brand with slug "bet365" → assert IntegrityError
- Insert a domain "bestbets.co.uk" → succeeds
- Insert another domain "bestbets.co.uk" → assert IntegrityError
- Insert brand_geo (brand_id=1, geo_id=1) → succeeds
- Insert duplicate brand_geo (brand_id=1, geo_id=1) → assert IntegrityError
- Insert brand_vertical (brand_id=1, vertical_id=1) → succeeds
- Insert duplicate brand_vertical (brand_id=1, vertical_id=1) → assert IntegrityError
```

#### 1.3 — Model Relationships
```
- Create a brand → add 2 brand_geos → assert brand.geos relationship returns both
- Create a brand → add 2 brand_verticals → assert brand.verticals relationship returns both
- Create a domain → assert domain.status defaults to "available"
- Create a brand with all new fields (parent_company, support_methods, support_email, available_languages, has_ios_app, has_android_app) → assert all fields saved correctly
- Create a brand_geo with all new fields (payment_methods, withdrawal_timeframe, rating_bonus through rating_rewards) → assert all fields saved correctly
- Create a brand_geo with category ratings as None → assert nullable fields accepted
```

### Automated Tests (`test_brands.py`)

#### 1.4 — Brand CRUD Routes
```
- GET /brands/ → assert 200
- POST /brands/new with valid data → assert redirect, brand exists in DB
- POST /brands/new with duplicate slug → assert error message, no duplicate created
- POST /brands/new with logo file upload → assert file saved to uploads/logos/
- GET /brands/<id>/edit → assert 200, form pre-populated
- POST /brands/<id>/edit with updated data → assert DB updated
- POST /brands/<id>/delete → assert brand removed from DB
```

#### 1.5 — Brand-GEO Association
```
- Add a brand → associate with GEO "gb" with bonus data → assert brand_geo record created
- Assert welcome_bonus, bonus_code, license_info stored correctly
- Attempt duplicate association → assert handled gracefully (error message, not crash)
```

### Automated Tests (`test_domains.py`)

#### 1.6 — Domain CRUD Routes
```
- GET /domains/ → assert 200
- POST /domains/new with valid domain → assert redirect, domain exists with status "available"
- POST /domains/new with duplicate domain → assert error message
- POST /domains/<id>/delete → assert domain removed
```

### Manual Verification
```
- [ ] Run the app: `python run.py` — boots without errors
- [ ] Visit dashboard — page loads, shows summary stats (0 sites, N brands, N domains)
- [ ] Add a brand with a logo — logo appears in the brand list
- [ ] Add a domain — appears in the domain list with "available" status
- [ ] Check DB directly: `sqlite3 factory.db ".tables"` — all tables present
```

### Run
```bash
pytest tests/test_models.py tests/test_brands.py tests/test_domains.py -v
```

---

## Phase 2: Site Configuration Wizard

### Automated Tests (`test_wizard.py`)

#### 2.1 — Wizard Steps Load
```
- GET /sites/create → assert 200
- Assert page contains GEO selection options
- Assert GEOs listed match seeded data
```

#### 2.2 — Site Creation (Happy Path)
```
- POST the full wizard form data:
  - geo_id = 1 (gb)
  - vertical_id = 1 (sports-betting)
  - brand_ids = [1, 2, 3] with ranks [1, 2, 3]
  - page_types = [homepage, comparison, brand-review, bonus-review, evergreen]
  - evergreen_topics = ["How to Bet on Football", "Understanding Odds"]
- Assert site created with status "draft"
- Assert 3 site_brands records created with correct ranks
- Assert site_pages created:
  - 1 homepage
  - 1 comparison
  - 3 brand reviews (one per brand)
  - 3 bonus reviews (one per brand)
  - 2 evergreen pages
  - Total: 10 pages
- Assert evergreen pages have correct evergreen_topic values
- Assert brand review slugs match brand slugs
- Assert evergreen slugs are auto-generated from topics (e.g. "how-to-bet-on-football")
```

#### 2.3 — Duplicate Prevention
```
- Create a site with brand_id=1 in site_brands
- Attempt to manually insert another site_brand with same site_id + brand_id → assert IntegrityError
```

#### 2.4 — Partial Unique Indexes on site_pages
```
- Create a site with homepage page → succeeds
- Attempt to create second homepage for same site → assert IntegrityError (global page constraint)
- Create brand review for brand_id=1 → succeeds
- Attempt duplicate brand review for brand_id=1 on same site → assert IntegrityError (brand page constraint)
- Create evergreen page with topic "How to Bet on Football" → succeeds
- Attempt duplicate evergreen with same topic on same site → assert IntegrityError (evergreen constraint)
- Create two different evergreen pages on same site → succeeds (different topics are allowed)
```

#### 2.5 — Brand Filtering
```
- Create brands: Brand A (gb + sports-betting), Brand B (gb + casino), Brand C (de + sports-betting)
- Start wizard with geo=gb, vertical=sports-betting
- Assert only Brand A appears as selectable (filtered by GEO + vertical)
```

### Manual Verification
```
- [ ] Walk through all wizard steps — UI flows correctly
- [ ] Add evergreen topics via the dynamic "Add Evergreen Page" button
- [ ] Confirm review step shows all selections accurately
- [ ] Submit → site appears on dashboard as "draft"
- [ ] Site detail page shows all configured pages, brands, and their ranks
```

### Run
```bash
pytest tests/test_wizard.py -v
```

---

## Phase 3: Content Generation (OpenAI)

### Automated Tests (`test_content_gen.py`)

**Note:** OpenAI calls should be **mocked** in tests. Use `unittest.mock.patch` to mock the OpenAI client and return predictable JSON responses.

#### 3.1 — Prompt Construction
```
- Call content_generator with a comparison page, GEO=gb, vertical=sports-betting, brands=[Bet365, William Hill]
- Assert the constructed prompt contains: language, currency, GEO name, vertical name, brand names, bonus details
- Assert the prompt requests JSON output in the expected structure
```

#### 3.2 — Content Generation (Mocked)
```
- Mock OpenAI to return a valid JSON response for a comparison page
- Call content_generator → assert it returns parsed JSON with expected keys (hero_title, comparison_rows, faq, etc.)
- Assert site_page.content_json is populated
- Assert site_page.is_generated = True
- Assert site_page.generated_at is set
```

#### 3.3 — Evergreen Content
```
- Mock OpenAI for an evergreen page
- Call content_generator with evergreen_topic="How to Bet on Football"
- Assert the prompt includes the topic
- Assert returned JSON has relevant content structure
```

#### 3.4 — Content Versioning
```
- Generate content for a page (mocked) → content_json = version 1
- Regenerate content for the same page → assert:
  - Old content saved to content_history with version=1
  - New content in site_page.content_json
  - content_history record has correct site_page_id, generated_at, content_json
```

#### 3.5 — Background Processing
```
- Trigger generation for a site → assert site.status = "generating"
- Assert the response returns immediately (not blocked)
- Mock all OpenAI calls to succeed → poll /api/sites/<id>/generation-status
- Assert progress increments (e.g. "1 of 10", "2 of 10", etc.)
- Assert final status = "generated"
```

#### 3.6 — Generation Failure Handling
```
- Mock OpenAI to raise an exception on the 3rd page
- Trigger generation → assert site.status = "failed"
- Assert first 2 pages are still marked as generated
- Assert remaining pages are not marked as generated
```

#### 3.7 — Generation Status API
```
- GET /api/sites/<id>/generation-status → assert 200
- Assert response JSON contains: total_pages, generated_pages, status
```

### Manual Verification
```
- [ ] Click "Generate Content" on a draft site — progress bar appears and updates
- [ ] After completion, inspect content_json for each page — valid JSON with expected sections
- [ ] Regenerate a single page — old version appears in content_history
- [ ] Trigger generation with an invalid API key — site goes to "failed" status with clear error
```

### Run
```bash
pytest tests/test_content_gen.py -v
```

---

## Phase 4: Static Site Builder

### Automated Tests (`test_site_builder.py`)

#### 4.1 — Build Output Structure
```
- Create a site with generated content (use fixture data, not real OpenAI)
- Run site_builder.build(site)
- Assert output directory exists: output/{site_id}_{slug}/v1/
- Assert index.html exists
- Assert comparison.html exists
- Assert reviews/ directory exists with one HTML file per brand
- Assert bonuses/ directory exists with one HTML file per brand
- Assert evergreen HTML files exist at root
- Assert assets/css/style.css exists
- Assert assets/js/main.js exists
- Assert assets/logos/ contains logos for all site brands
- Assert sitemap.xml exists
- Assert robots.txt exists
```

#### 4.2 — HTML Content Rendered
```
- Build a site → open index.html as text
- Assert it contains the hero_title from the homepage content_json
- Assert it contains brand names and affiliate links
- Assert it does NOT contain raw Jinja2 template tags ({{ or {%)
```

#### 4.3 — Internal Linking
```
- Build a site with 3 brands and 2 evergreen pages
- Parse the homepage HTML:
  - Assert nav contains link to comparison.html
  - Assert nav contains links to evergreen pages
  - Assert footer contains links to all top-level pages
- Parse comparison.html:
  - Assert each brand row links to reviews/{brand_slug}.html
- Parse a brand review page:
  - Assert it links to the corresponding bonus page (bonuses/{brand_slug}.html)
- Parse a bonus review page:
  - Assert it links back to the corresponding brand review
```

#### 4.4 — Sitemap
```
- Build a site → parse sitemap.xml
- Assert it contains URLs for all pages (homepage, comparison, reviews, bonuses, evergreen)
- Assert URLs follow the defined URL pattern
- Assert lastmod dates are present
```

#### 4.5 — Robots.txt
```
- Build a site with domain "bestbets.co.uk" assigned
- Assert robots.txt contains "Sitemap: https://bestbets.co.uk/sitemap.xml"
- Assert it contains "User-agent: *" and "Allow: /"
```

#### 4.6 — Logo Handling
```
- Create a brand with logo_filename = "bet365.png"
- Place a test image at uploads/logos/bet365.png
- Build the site
- Assert output/{site}/v1/assets/logos/bet365.png exists
- Assert homepage HTML references "assets/logos/bet365.png"
```

#### 4.7 — Missing Logo Fallback
```
- Create a brand with logo_filename = None (no logo uploaded)
- Build the site
- Assert brand appears in comparison table with text-only display (no broken image)
```

#### 4.8 — Brand Review Page Rendering
```
- Create a site with a brand that has full data (all new columns populated including category ratings)
- Build the site
- Assert reviews/{brand_slug}.html exists
- Open the review HTML:
  - Assert brand name, rating, bonus offer, bonus code are present
  - Assert category ratings section renders with correct scores
  - Assert pros and cons are present (from content_json)
  - Assert "How to Claim" steps are present
  - Assert FAQ section renders
  - Assert sidebar contains brand info table (parent company, payment methods, withdrawal, etc.)
  - Assert sidebar contains "Other Top Picks" with links to other brand reviews
  - Assert sticky bottom bar contains brand name, bonus, and CTA
  - Assert vertical-aware labels are correct (e.g. "Play Now" for casino, "Bet Now" for sports)
```

#### 4.9 — Brand Review with Partial Data
```
- Create a brand with some category ratings as None and no parent_company
- Build the site
- Assert review page renders without errors
- Assert missing category ratings are NOT rendered (no empty rows)
- Assert parent company row is absent from info table
```

#### 4.10 — Versioned Builds
```
- Build a site → assert output at v1/
- Modify content, rebuild → assert output at v2/
- Assert v1/ still exists (not deleted)
- Assert sites.current_version = 2
```

### Manual Verification
```
- [ ] Build a site → open output folder in browser → all pages render correctly
- [ ] Click through all nav links and footer links — no broken links
- [ ] Click brand CTAs — correct affiliate links
- [ ] Check logos appear in comparison table and review pages
- [ ] Open sitemap.xml — valid XML with all pages listed
- [ ] Check robots.txt — correct sitemap URL
- [ ] Rebuild same site — v2 folder created alongside v1
```

### Run
```bash
pytest tests/test_site_builder.py -v
```

---

## Phase 5: Deployment via SSH

### Automated Tests (`test_deployer.py`)

**Note:** SSH calls should be **mocked** in tests. Use `unittest.mock.patch` to mock Fabric's `Connection` object. We're testing the logic, not actual server connectivity.

#### 5.1 — Deployment Flow (Mocked)
```
- Mock Fabric Connection (put, run, sudo commands)
- Deploy a built site with domain "bestbets.co.uk"
- Assert the following commands were called:
  - mkdir -p /var/www/sites/bestbets.co.uk/releases/v1/
  - File upload to releases/v1/
  - ln -sfn /var/www/sites/bestbets.co.uk/releases/v1 /var/www/sites/bestbets.co.uk/current
  - Nginx config uploaded to sites-available
  - Symlink created in sites-enabled
  - nginx reload called
  - certbot called (first deploy)
- Assert site.status = "deployed"
- Assert site.deployed_at is set
- Assert domain.status = "deployed"
```

#### 5.2 — Re-deploy (Version Update)
```
- Deploy v1 → deploy v2 (mocked)
- Assert symlink updated to v2
- Assert certbot NOT called again (not first deploy)
```

#### 5.3 — Rollback (Mocked)
```
- Deploy v1 → deploy v2 → rollback
- Assert symlink updated back to v1
- Assert nginx reload called
- Assert no files uploaded (just symlink change)
```

#### 5.4 — Version Pruning
```
- Deploy v1, v2, v3, v4
- Assert v1 is deleted (only last 3 kept)
- Assert v2, v3, v4 exist
```

#### 5.5 — Domain Assignment
```
- Assign domain (status "available") to a site via sites.domain_id → assert domain.status = "assigned"
- Assert domain.site back_populates correctly (domain.site == the assigned site)
- Attempt to assign an already-assigned domain to another site → assert error
- Deploy → assert domain.status = "deployed"
```

#### 5.6 — Deployment Failure
```
- Mock SSH connection to raise an exception
- Attempt deploy → assert site.status = "failed"
- Assert domain.status remains "assigned" (not "deployed")
```

### Manual Verification
```
- [ ] Deploy a site to your actual VPS — site loads at the domain with HTTPS
- [ ] Rebuild and re-deploy — site updates, previous version still on disk
- [ ] Rollback — previous version served immediately
- [ ] Check Nginx config on VPS — root points to /current symlink
- [ ] Check /var/www/sites/{domain}/releases/ — correct version folders present
```

### Run
```bash
pytest tests/test_deployer.py -v
```

---

## Phase 6: Polish & QA

### Automated Tests (`test_api.py` and integration)

#### 6.1 — Flash Messages
```
- Create a brand → assert flash message "Brand created successfully" in response
- Attempt duplicate slug → assert flash message with error
- Deploy a site → assert flash message "Site deployed successfully"
```

#### 6.2 — Bulk Brand Import
```
- POST a CSV file to the bulk import endpoint with 5 brands
- Assert all 5 brands created in DB
- Assert logos referenced in CSV are handled correctly
- POST a CSV with a duplicate slug → assert it's skipped with a warning, others imported
```

#### 6.3 — Content History Viewer
```
- Generate content for a page 3 times
- GET the content history endpoint for that page
- Assert 2 history records (original + first regen, current is in site_page)
- Restore version 1 → assert site_page.content_json matches version 1 content
- Assert a new history record was created for the content that was replaced
```

### Manual Verification
```
- [ ] Flash messages appear on all create/edit/delete/deploy actions
- [ ] Site preview opens in new tab and renders correctly
- [ ] Re-deploy works on an already-deployed site
- [ ] Bulk import with a CSV — brands appear in list
- [ ] Content history — can view and restore previous versions
- [ ] Error states — API timeout, SSH failure, missing logo — all handled with clear messages
```

### Run
```bash
pytest tests/ -v
```

---

## Running All Tests

```bash
# Run everything
pytest tests/ -v

# Run with coverage
pytest tests/ -v --cov=app --cov-report=term-missing

# Run a specific phase
pytest tests/test_models.py tests/test_brands.py tests/test_domains.py -v  # Phase 1
pytest tests/test_wizard.py -v                                              # Phase 2
pytest tests/test_content_gen.py -v                                         # Phase 3
pytest tests/test_site_builder.py -v                                        # Phase 4
pytest tests/test_deployer.py -v                                            # Phase 5
pytest tests/ -v                                                            # Phase 6 (all)
```

---

## Notes for Claude Code

- **Run the relevant phase tests after completing each phase.** Do not move to the next phase if tests fail.
- **Create `conftest.py` in Phase 1** with the core fixtures. Extend it as needed in later phases.
- **Mock all external services in tests:** OpenAI API calls (Phase 3+), SSH/Fabric connections (Phase 5+). Never make real API or SSH calls in tests.
- **Use fixture data for generated content** in Phase 4 tests — don't depend on OpenAI to test the site builder.
- **Test unique constraints by asserting `IntegrityError`** — wrap in `pytest.raises(IntegrityError)` after importing from `sqlalchemy.exc`.
- **Keep tests independent.** Each test should set up its own data and not depend on state from other tests. The `db` fixture rolls back after each test.
- **Add `pytest` and `pytest-cov` to `requirements.txt`.**
