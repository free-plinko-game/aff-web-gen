# Affiliate Site Factory — Project Plan

## Overview

A Flask-based control panel for generating and deploying static affiliate websites. The operator selects a GEO, vertical, brands, and page types — the system generates LLM-written content, populates pre-built HTML templates, outputs a complete static site folder, and deploys it to a VPS via SSH. After initial creation, the site detail page serves as an ongoing management hub — add new pages, update content with custom LLM directions, manage the sitemap and robots.txt, and redeploy.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend / Control Panel | Flask (Python) |
| Database | SQLite (dev) → PostgreSQL (prod) |
| ORM | SQLAlchemy |
| Templating | Jinja2 (for both the Flask UI and the static site templates) |
| LLM Content Generation | OpenAI API (`gpt-4o` or `gpt-4o-mini`) |
| Static Site Output | Plain HTML/CSS/JS folders |
| Deployment | Fabric (SSH, built on Paramiko) → push to VPS → Nginx + Certbot |
| Background Tasks | Threading (dev) → Celery + Redis (prod, optional) |
| Frontend (Control Panel) | Bootstrap 5 (keep it simple) |

---

## Database Schema

### Constraints & Rules
- All junction tables (`brand_geos`, `brand_verticals`, `site_brands`) must have **unique constraints** on their compound key pairs to prevent duplicate entries.
- `domains.domain` must be **unique**.
- `brands.slug` must be **unique** — it's used for URL generation in output sites.
- `site_pages` uses **three partial unique indexes** (see site_pages table below for details):
  - Brand pages: unique on `(site_id, page_type_id, brand_id)` WHERE `brand_id IS NOT NULL`
  - Evergreen pages: unique on `(site_id, page_type_id, evergreen_topic)` WHERE `evergreen_topic IS NOT NULL`
  - Global pages (homepage, comparison): unique on `(site_id, page_type_id)` WHERE `brand_id IS NULL AND evergreen_topic IS NULL`
- `geos.code` must be **unique**.
- `verticals.slug` must be **unique**.

### `geos`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | Auto |
| code | TEXT UNIQUE | e.g. `gb`, `de`, `br`, `ng` |
| name | TEXT | e.g. `United Kingdom` |
| language | TEXT | e.g. `en`, `de`, `pt` |
| currency | TEXT | e.g. `GBP`, `EUR`, `BRL` |
| regulation_notes | TEXT | Optional — e.g. "UKGC regulated market" |

### `verticals`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | Auto |
| slug | TEXT UNIQUE | `sports-betting`, `casino`, `esports-betting` |
| name | TEXT | Display name |

### `brands`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | Auto |
| name | TEXT | e.g. `Bet365` |
| slug | TEXT UNIQUE | e.g. `bet365` — used in output site URLs |
| logo_filename | TEXT | Filename of uploaded logo in `uploads/logos/`, e.g. `bet365.png` |
| website_url | TEXT | Main site URL |
| affiliate_link | TEXT | Your tracked affiliate link |
| description | TEXT | Short brand description |
| founded_year | INTEGER | Optional |
| rating | FLOAT | e.g. `4.5` out of 5 — headline rating used across all pages |
| parent_company | TEXT | Optional — e.g. `LeoVegas Gaming PLC` |
| support_methods | TEXT | e.g. `Live Chat, Phone, Email` |
| support_email | TEXT | Optional — e.g. `support@betmgm.co.uk` |
| available_languages | TEXT | e.g. `EN, DE, FR` |
| has_ios_app | BOOLEAN | Default False |
| has_android_app | BOOLEAN | Default False |

### `brand_geos`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | Auto |
| brand_id | INTEGER FK | → brands.id |
| geo_id | INTEGER FK | → geos.id |
| welcome_bonus | TEXT | e.g. "Bet £10 Get £30" |
| bonus_code | TEXT | Optional promo code |
| license_info | TEXT | e.g. "UKGC License #12345" |
| is_active | BOOLEAN | Whether brand is live in this GEO |
| payment_methods | TEXT | e.g. "PayPal, Apple Pay, Visa, Mastercard" |
| withdrawal_timeframe | TEXT | e.g. "1–7 Days" |
| rating_bonus | FLOAT | Category rating out of 5 — Bonus & Free Bets |
| rating_usability | FLOAT | Category rating — Usability, Look & Feel |
| rating_mobile_app | FLOAT | Category rating — Mobile App |
| rating_payments | FLOAT | Category rating — Payment Methods |
| rating_support | FLOAT | Category rating — Customer Service |
| rating_licensing | FLOAT | Category rating — Licence & Security |
| rating_rewards | FLOAT | Category rating — Rewards & Loyalty Program |
| **UNIQUE** | | **(brand_id, geo_id)** |

### `brand_verticals`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | Auto |
| brand_id | INTEGER FK | → brands.id |
| vertical_id | INTEGER FK | → verticals.id |
| **UNIQUE** | | **(brand_id, vertical_id)** |

### `page_types`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | Auto |
| slug | TEXT UNIQUE | e.g. `homepage`, `comparison`, `brand-review`, `bonus-review`, `evergreen` |
| name | TEXT | Display name |
| template_file | TEXT | e.g. `homepage.html` |
| content_prompt | TEXT | Base prompt template for LLM generation (uses placeholders) |

### `domains`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | Auto |
| domain | TEXT UNIQUE | e.g. `bestbets.co.uk` |
| registrar | TEXT | Optional |
| status | TEXT | `available`, `assigned`, `deployed` |

**Note:** The Domain→Site relationship is derived from `sites.domain_id`, not a FK on this table. SQLAlchemy uses `back_populates` with `uselist=False` to give `domain.site` access without a bidirectional FK conflict.

### `sites`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | Auto |
| name | TEXT | Internal label, e.g. "UK Sports Betting Site 1" |
| geo_id | INTEGER FK | → geos.id |
| vertical_id | INTEGER FK | → verticals.id |
| domain_id | INTEGER FK | → domains.id (nullable until assigned) |
| status | TEXT | `draft`, `generating`, `generated`, `building`, `built`, `deploying`, `deployed`, `failed` |
| output_path | TEXT | Local path to the generated static folder |
| created_at | DATETIME | Auto |
| deployed_at | DATETIME | Nullable |
| built_at | DATETIME | Nullable — timestamp of last successful build |
| current_version | INTEGER | Default 1, incremented on each rebuild |
| custom_robots_txt | TEXT | Nullable — if set, used instead of the default robots.txt template during build |

### `site_brands`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | Auto |
| site_id | INTEGER FK | → sites.id |
| brand_id | INTEGER FK | → brands.id |
| rank | INTEGER | Display order in comparison tables |
| **UNIQUE** | | **(site_id, brand_id)** |

### `site_pages`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | Auto |
| site_id | INTEGER FK | → sites.id |
| page_type_id | INTEGER FK | → page_types.id |
| brand_id | INTEGER FK | Nullable — for brand-specific pages (reviews, bonus pages) |
| evergreen_topic | TEXT | Nullable — for evergreen pages, e.g. "How to Bet on Football", "Understanding Odds" |
| slug | TEXT | URL slug for this page |
| title | TEXT | Page title |
| meta_description | TEXT | SEO meta |
| content_json | TEXT | JSON blob of generated content sections |
| is_generated | BOOLEAN | Whether LLM content has been generated |
| generated_at | DATETIME | Nullable — timestamp of last generation |
| regeneration_notes | TEXT | Nullable — custom instructions for the next generation (e.g. "focus on mobile app", "target keyword: best UK betting sites") |
| **UNIQUE (partial indexes)** | | **Brand pages:** `(site_id, page_type_id, brand_id)` WHERE `brand_id IS NOT NULL` |
| | | **Evergreen pages:** `(site_id, page_type_id, evergreen_topic)` WHERE `evergreen_topic IS NOT NULL` |
| | | **Global pages:** `(site_id, page_type_id)` WHERE `brand_id IS NULL AND evergreen_topic IS NULL` |

### `content_history`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | Auto |
| site_page_id | INTEGER FK | → site_pages.id |
| content_json | TEXT | Snapshot of the generated content |
| generated_at | DATETIME | When this version was generated |
| regeneration_notes | TEXT | Nullable — the custom instructions that were used for this generation (copied from site_pages at generation time) |
| version | INTEGER | Auto-incrementing per page |

This table stores previous versions of generated content. Every time content is regenerated for a `site_page`, the old `content_json` is copied here before being overwritten. This enables rollbacks.

---

## File Structure

```
affiliate-factory/
├── .gitignore                      ← MUST include .env, output/, *.db, __pycache__/
├── .env                            ← API keys, SSH creds — NEVER committed
├── .env.example                    ← Template with placeholder values (committed)
├── plan.md                         ← THIS FILE
├── requirements.txt
├── config.py                       ← App config, reads from .env
├── run.py                          ← Entry point
├── app/
│   ├── __init__.py                 ← Flask app factory
│   ├── models.py                   ← SQLAlchemy models
│   ├── seed.py                     ← Seed data (GEOs, verticals, page types)
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── dashboard.py            ← Main dashboard / site list
│   │   ├── brands.py               ← CRUD for brands (including logo upload)
│   │   ├── domains.py              ← CRUD for domains
│   │   ├── sites.py                ← Site config, generation, deployment
│   │   └── api.py                  ← AJAX endpoints (generation progress, page CRUD, robots.txt save)
│   ├── services/
│   │   ├── __init__.py
│   │   ├── content_generator.py    ← OpenAI API integration (runs in background thread)
│   │   ├── site_builder.py         ← Renders templates → static files (sitemap, robots.txt, linking)
│   │   └── deployer.py             ← SSH deployment via Fabric (symlink-based versioning)
│   ├── templates/                  ← Flask control panel templates (Jinja2)
│   │   ├── base.html
│   │   ├── dashboard.html
│   │   ├── brands/
│   │   │   ├── list.html
│   │   │   └── form.html
│   │   ├── domains/
│   │   │   ├── list.html
│   │   │   └── form.html
│   │   └── sites/
│   │       ├── list.html
│   │       ├── create.html         ← The main wizard (GEO → vertical → brands → pages)
│   │       ├── detail.html         ← Site hub: pages list, sitemap, robots.txt, generation & build controls
│   │       ├── add_page.html       ← Add a new page to an existing site
│   │       ├── edit_page.html      ← Edit page settings + regeneration notes
│   │       └── deploy.html
│   └── static/                     ← Control panel static assets
│       ├── css/
│       └── js/
├── uploads/                        ← User-uploaded assets
│   └── logos/                      ← Brand logos (uploaded via brand CRUD)
├── site_templates/                 ← Templates for the GENERATED affiliate sites
│   ├── base.html                   ← Base layout (header, footer, nav — includes site-wide linking)
│   ├── homepage.html
│   ├── comparison.html
│   ├── brand_review.html
│   ├── bonus_review.html
│   ├── evergreen.html
│   ├── sitemap.xml                 ← Jinja2 template for sitemap generation
│   ├── robots.txt                  ← Jinja2 template for robots.txt
│   └── assets/                     ← CSS/JS/images for generated sites
│       ├── css/
│       │   └── style.css
│       ├── js/
│       │   └── main.js
│       └── img/
└── output/                         ← Generated static sites land here
    └── {site_id}_{slug}/
        ├── v1/                     ← Versioned build folders
        │   ├── index.html
        │   ├── comparison.html
        │   ├── reviews/
        │   │   ├── bet365.html
        │   │   └── ...
        │   ├── sitemap.xml
        │   ├── robots.txt
        │   └── assets/
        │       └── logos/          ← Brand logos copied in during build
        └── v2/                     ← Next version on rebuild
```

---

## Internal Linking Strategy

All generated sites follow a consistent URL and navigation structure:

### URL Pattern
| Page Type | URL Pattern | Example |
|---|---|---|
| Homepage | `/index.html` | `/index.html` |
| Comparison | `/comparison.html` | `/comparison.html` |
| Brand Review | `/reviews/{brand_slug}.html` | `/reviews/bet365.html` |
| Bonus Review | `/bonuses/{brand_slug}.html` | `/bonuses/bet365.html` |
| Evergreen | `/{evergreen_slug}.html` | `/how-to-bet-on-football.html` |

### Navigation
- `base.html` renders a nav bar with links to: Homepage, Comparison Page, all Evergreen pages.
- Brand review and bonus review pages are linked from: the comparison table rows, the homepage brand grid, and each other (review ↔ bonus cross-links).
- Every page includes a footer with links to all top-level pages.
- The site builder (`site_builder.py`) generates a `nav_links` list and a `footer_links` list from the site's `site_pages` records and passes them to every template.

---

## Logo / Image Handling

### Upload Flow
1. Brand CRUD form includes a file upload field for the logo.
2. On upload, the file is saved to `uploads/logos/{brand_slug}.{ext}` (e.g. `uploads/logos/bet365.png`).
3. The `brands.logo_filename` column stores just the filename (e.g. `bet365.png`).
4. The control panel displays logos from `/uploads/logos/` via a Flask static route.

### Build Flow
1. During static site build (`site_builder.py`), logos for all brands assigned to the site are copied from `uploads/logos/` into `output/{site}/v{n}/assets/logos/`.
2. Site templates reference logos at `assets/logos/{logo_filename}`.
3. If a brand has no logo uploaded, templates should fall back to a text-only display.

---

## Build Phases

### Phase 1: Foundation
**Goal:** Flask app boots, DB exists, you can CRUD brands (with logo upload) and domains.

1. Set up Flask app factory (`app/__init__.py`) with SQLAlchemy and config
2. Create `.gitignore` with: `.env`, `output/`, `uploads/logos/`, `*.db`, `__pycache__/`, `*.pyc`
3. Create `.env.example` with placeholder values for all config vars
4. Define all SQLAlchemy models in `models.py` — **including all unique constraints from the schema above**
5. Create `seed.py` to populate GEOs, verticals, and page types
6. Build brand CRUD routes + templates (list, add, edit, delete) — **including logo file upload**
7. Build domain CRUD routes + templates
8. Create the dashboard page showing summary stats

**Test:** You can run the app, add brands with GEO-specific bonuses and logo uploads, manage domains. Try adding a duplicate brand_geo — it should fail cleanly.

---

### Phase 2: Site Configuration Wizard
**Goal:** Walk through the site creation flow — pick GEO, vertical, brands, pages.

1. Build the "Create Site" wizard as a multi-step form:
   - Step 1: Pick a GEO
   - Step 2: Pick a vertical
   - Step 3: Select brands (filtered by GEO + vertical) and set ranking order via drag-and-drop
   - Step 4: Select which page types to generate:
     - **Global pages** (homepage, comparison) — checkboxes, one of each
     - **Brand-specific pages** (brand review, bonus review) — auto-generated per selected brand, with checkboxes to include/exclude per brand
     - **Evergreen pages** — dynamic "Add Evergreen Page" button where the user enters a topic title per page (e.g. "How to Bet on Football"). These populate `site_pages.evergreen_topic`.
   - Step 5: Review & confirm
2. On submit, create the `site`, `site_brands`, and `site_pages` records in DB
3. For brand-specific pages, auto-generate slugs from brand slug (e.g. `bet365` → slug `bet365`, page at `/reviews/bet365.html`)
4. For evergreen pages, auto-generate slugs from the topic (e.g. "How to Bet on Football" → slug `how-to-bet-on-football`)
5. Site lands in `draft` status on the dashboard

**Test:** Walk through the wizard. Add 3 brands and 2 evergreen topics. Verify all `site_pages` records are created with correct types, brand associations, and evergreen topics.

---

### Phase 3: Content Generation (OpenAI)
**Goal:** Generate LLM content for each page of a site, with background processing and progress tracking.

1. Build `content_generator.py` service:
   - Takes a page type, GEO, vertical, brand(s), language, and evergreen_topic (if applicable)
   - Constructs a detailed prompt using the `page_types.content_prompt` template
   - Calls OpenAI API
   - Returns structured content as JSON (sections, headings, body text, comparison table data, pros/cons, etc.)
2. **Background processing:** Content generation runs in a background thread (not the request thread). The flow is:
   - User clicks "Generate Content" → site status set to `generating` → response returns immediately
   - Background thread processes each page sequentially, updating `site_pages.is_generated` and `site_pages.generated_at` as each completes
   - An AJAX endpoint (`/api/sites/<id>/generation-status`) returns current progress (e.g. "4 of 12 pages generated")
   - The site detail page polls this endpoint to show a live progress bar
   - On completion, site status updated to `generated`. On failure, status set to `failed` with error details.
3. **Content versioning:** Before overwriting `content_json` on regeneration, copy the existing content to `content_history` with a version number and timestamp.
4. Define prompt templates for each page type in the seed data. These are critical — they should instruct the LLM to return structured JSON with specific sections. Example for a comparison page:
   ```
   You are writing a {vertical} comparison page for users in {geo_name}.
   Language: {language}. Currency: {currency}.
   
   Brands to compare (in ranked order): {brand_list_with_bonuses}
   
   Return a JSON object with:
   - "hero_title": string
   - "hero_subtitle": string  
   - "intro_paragraph": string (2-3 sentences)
   - "comparison_rows": [{ "brand": string, "bonus": string, "rating": float, "pros": [string], "cons": [string], "verdict": string }]
   - "faq": [{ "question": string, "answer": string }]
   - "closing_paragraph": string
   ```
   For evergreen pages, the prompt receives the `evergreen_topic` and generates content around that topic in the context of the vertical and GEO.
5. Add a "Generate Content" button on the site detail page (with progress bar)
6. Add a "Regenerate" button per individual page (also saves to `content_history` first)
7. **Regeneration with directions:** When regenerating a single page, the operator can provide `regeneration_notes` — custom instructions that are appended to the base prompt before calling the API (e.g. "focus more on the mobile app experience", "target keyword: best UK betting sites 2026", "make the tone more casual"). These notes are stored on the `site_pages` row and also copied into `content_history` alongside the snapshot, so you can always see what instructions produced each version.

**Test:** Hit generate, see progress bar update, inspect JSON output per page. Regenerate a single page and verify the old version is in `content_history`.

---

### Phase 4: Static Site Builder
**Goal:** Render the generated content into actual HTML files, including SEO essentials and proper linking.

1. Build `site_builder.py` service:
   - Loads the site config + all site_pages with their content_json
   - Generates `nav_links` and `footer_links` lists from the site's pages (see Internal Linking Strategy above)
   - For each page, renders the corresponding `site_templates/*.html` with the content data + nav/footer links
   - Copies assets (CSS, JS) into the output folder
   - **Copies brand logos** from `uploads/logos/` into `output/{site}/v{n}/assets/logos/` for all brands in the site
   - Generates `sitemap.xml` from the sitemap template (lists all pages with lastmod dates)
   - Generates `robots.txt`: if `sites.custom_robots_txt` is set, uses that verbatim; otherwise renders from the robots.txt Jinja2 template (points to sitemap URL using the assigned domain)
   - Outputs to versioned folder: `output/{site_id}_{slug}/v{version}/`
   - Increments `sites.current_version`
2. Create the Jinja2 site templates in `site_templates/`:
   - `base.html` — responsive layout, nav bar (from `nav_links`), footer (from `footer_links`)
   - `homepage.html` — hero section, top brands grid with logos + affiliate links, intro content
   - `comparison.html` — comparison table with brand logos, bonuses, ratings, pros/cons, CTA buttons linking to affiliate URLs. Rows link to individual brand review pages.
   - `brand_review.html` — full review with pros/cons, bonus info, CTA buttons. Cross-links to bonus review page for same brand.
   - `bonus_review.html` — focused on the welcome offer, T&Cs, how to claim. Cross-links to full brand review.
   - `evergreen.html` — informational content page, with relevant brand CTAs woven in
   - `sitemap.xml` — standard XML sitemap
   - `robots.txt` — allows all, points to sitemap
3. Add a "Build Site" button on the site detail page
4. Add a preview option (serves the output folder via a temporary Flask route or opens in new tab)

**Test:** Build a site, open the HTML files locally. Check that nav links work, brand logos appear, cross-links between reviews and bonus pages work, sitemap.xml lists all pages, robots.txt is present.

---

### Phase 5: Deployment via SSH
**Goal:** Push the static site live to your VPS using symlink-based versioning for easy rollbacks.

1. Build `deployer.py` service using **Fabric** (not raw Paramiko):
   - Connects to VPS via SSH
   - Creates the site directory structure on the VPS:
     ```
     /var/www/sites/{domain}/
     ├── releases/
     │   ├── v1/          ← uploaded site files
     │   ├── v2/          ← next version
     │   └── ...
     └── current → releases/v2   ← symlink to active version
     ```
   - Uploads the latest versioned build folder to `releases/v{n}/`
   - Updates the `current` symlink to point to the new version
   - Generates and uploads an Nginx server block config (root set to `/var/www/sites/{domain}/current`)
   - Reloads Nginx
   - Runs Certbot to provision SSL for the domain (only on first deploy)
   - Keeps the last 3 versions in `releases/`, deletes older ones
2. **Rollback support:** A "Rollback" button on the site detail page re-points the `current` symlink to the previous version without re-uploading anything.
3. Store VPS connection details in `.env` (host, user, SSH key path)
4. Add deployment controls to the site detail page:
   - Assign a domain from the available pool
   - "Deploy" button
   - "Rollback" button (if previous versions exist)
   - Status indicator (deploying → deployed)
5. Update site and domain status in DB after successful deployment

**Test:** Deploy a site, visit the domain in a browser, see your generated affiliate site live with HTTPS. Rebuild and re-deploy — verify the symlink updates. Rollback — verify the previous version is served.

---

### Phase 6: Polish & QA
**Goal:** Tighten everything up for daily use.

1. Add flash messages / toasts for success/error feedback throughout the UI
2. Add site preview (iframe or new tab) before deployment
3. Add ability to re-deploy (update) an already-deployed site
4. Add bulk brand import (CSV/JSON upload)
5. Add logging for generation and deployment operations
6. Error handling everywhere — API failures, SSH timeouts, etc.
7. Add content history viewer — see previous versions of a page's content with option to restore

---

### Phase 7: Site Management Hub
**Goal:** Turn the site detail page (`/sites/<id>`) into a full management hub for ongoing site operations — adding pages, updating content with custom directions, and managing SEO config.

The site detail page is the central control point for each site. After initial creation (Phase 2), the operator will spend most of their time here. These features make it a proper CMS-like hub rather than a one-shot generator.

#### 7.1 — Add New Pages

Allow adding pages to an existing site without re-running the creation wizard.

1. Add an "Add Page" button on the site detail page that opens `add_page.html`
2. The form presents a page type dropdown:
   - **Evergreen** — shows a text input for the topic title (e.g. "How to Bet on Football"). Slug auto-generated from topic.
   - **Brand Review** — shows a dropdown of site brands (from `site_brands`) that don't already have a review page. Slug auto-generated from brand slug.
   - **Bonus Review** — same as brand review, filtered to brands without a bonus page.
   - **Homepage / Comparison** — only shown if the site doesn't already have one (partial unique constraint enforces this).
3. On submit:
   - Create the `site_pages` record with `is_generated = False`
   - Redirect back to site detail page
   - The new page appears in the page list as "Not Generated" — operator can then hit Generate on it individually
4. **Validation:** Enforce the same partial unique constraints from the schema. If the operator tries to add a duplicate (e.g. a second homepage, or a brand review for a brand that already has one), show a clear error message.

**Note:** After adding new pages, the site must be **rebuilt** for the sitemap, nav links, and footer to include the new page. The site detail page should show a warning banner if there are pages that were generated/updated after the last build (i.e. site needs rebuilding).

#### 7.2 — Update Pages with Directions

Allow the operator to regenerate content for a specific page with custom instructions that steer the LLM output.

1. Add an "Edit / Regenerate" action per page on the site detail page that opens `edit_page.html`
2. The edit page form includes:
   - **Page title** — editable (pre-filled from `site_pages.title`)
   - **Meta description** — editable (pre-filled from `site_pages.meta_description`)
   - **Slug** — editable with caution warning ("changing the slug will break existing links")
   - **Regeneration Notes** — a textarea for custom instructions to the LLM. Examples:
     - "Focus more on the mobile app experience"
     - "Target keyword: best UK betting sites 2026"
     - "Make the tone more casual and conversational"
     - "Add a section about live streaming features"
     - "Mention the new welcome bonus: Bet £20 Get £40"
   - **Current content preview** — read-only JSON viewer or rendered preview of the current `content_json`
   - **Content history** — list of previous versions from `content_history` with timestamps and the regeneration notes used, plus a "Restore" button per version
3. On "Save" — updates title, meta_description, slug, and regeneration_notes on the `site_pages` row (does NOT regenerate)
4. On "Save & Regenerate" — saves the above, then triggers content generation for this single page in a background thread:
   - Snapshots current `content_json` → `content_history` (with the `regeneration_notes` that produced it)
   - Appends the `regeneration_notes` to the base `page_types.content_prompt` before calling the API
   - Updates `content_json`, `is_generated`, `generated_at`
   - Clears `regeneration_notes` after successful generation (they've been consumed and archived in `content_history`)
5. The site detail page polls for single-page generation progress (reuse the existing AJAX progress endpoint, scoped to one page)

#### 7.3 — Sitemap Viewer

Show the full URL structure of the site on the detail page so the operator can see at a glance what exists and what state it's in.

1. Add a "Site Map" tab/section on the site detail page
2. Display a table or tree view of all `site_pages` for the site, showing:
   - **URL** — the full path as it will appear on the live site (e.g. `/index.html`, `/reviews/bet365.html`, `/how-to-bet-on-football.html`)
   - **Page Type** — homepage, comparison, brand review, bonus review, evergreen
   - **Status** — Not Generated | Generated (with timestamp) | Stale (generated before last page addition)
   - **Actions** — Edit, Regenerate, Delete (with confirmation), Preview
3. If a domain is assigned, show the full live URLs (e.g. `https://bestbets.co.uk/reviews/bet365.html`)
4. Highlight pages that are generated but not yet built (i.e. newer than the last build) with a visual indicator
5. Show a count summary at the top: "12 pages (10 generated, 2 pending)"

#### 7.4 — Robots.txt Editor

Allow the operator to customise the robots.txt for each site directly from the admin.

1. Add a "robots.txt" tab/section on the site detail page
2. Display a textarea pre-filled with:
   - The current `sites.custom_robots_txt` if it exists, OR
   - The default rendered output from the `site_templates/robots.txt` Jinja2 template (as a preview of what would be generated)
3. A "Save Custom robots.txt" button saves the textarea content to `sites.custom_robots_txt`
4. A "Reset to Default" button clears `sites.custom_robots_txt` (sets to NULL), reverting to template-based generation
5. The `site_builder.py` build step checks: if `sites.custom_robots_txt` is not null, write it verbatim to the output folder; otherwise, render the Jinja2 template as before.
6. Show a note: "Custom robots.txt will be used on next build. Hit 'Rebuild Site' to apply changes."

#### 7.5 — Rebuild Awareness

Since pages can now be added or updated independently, the site detail page needs to clearly communicate when a rebuild is needed.

1. Track the latest `generated_at` across all `site_pages` for the site
2. Compare against `sites.built_at` (updated by `site_builder.py` on each successful build)
3. If any page was generated after the last build, show a **warning banner**: "Content has changed since last build. Rebuild to update the static site."
4. The "Rebuild Site" button triggers the existing `site_builder.py` flow — it picks up all current `site_pages` (including newly added ones), regenerates the sitemap and nav links, and outputs a new versioned folder.

**Test:** Add a new evergreen page to an existing site. Generate its content. Verify the warning banner appears. Rebuild. Verify the new page appears in the sitemap, nav, and footer of the rebuilt site. Edit an existing page with regeneration notes, regenerate it, verify the content_history snapshot includes the notes.

---

## Key Design Decisions

### Site Management Hub
The site detail page (`/sites/<id>`) is the operator's primary workspace after initial site creation. It should feel like a lightweight CMS dashboard for that specific site — not just a status page. The Phase 2 wizard handles initial setup, but all ongoing work (adding pages, tweaking content, managing SEO, deploying) happens from the detail page. Design it accordingly.

### Content Structure
LLM-generated content is stored as **JSON blobs** in `site_pages.content_json`. This keeps things flexible — you can add new sections to templates without DB migrations. The site templates read from this JSON to populate the HTML. Previous versions are preserved in `content_history` for rollback.

### Template Separation
There are TWO sets of templates:
- `app/templates/` — the Flask control panel UI (what you see in the browser when managing sites)
- `site_templates/` — the actual affiliate site HTML that gets rendered into static files

Don't mix these up. They serve completely different purposes.

### Prompt Engineering
The quality of generated sites lives or dies on the prompts in `page_types.content_prompt`. Spend time on these. They should:
- Specify the exact JSON structure expected
- Include GEO-specific instructions (language, currency, regulatory tone)
- Include vertical-specific instructions (sports vs casino terminology)
- Request SEO-friendly content (natural keyword usage, proper heading hierarchy)
- Set word count targets per section
- For evergreen pages, incorporate the `evergreen_topic` as the primary content focus

### Deployment Safety
- Always preview before deploying
- Symlink-based versioning: `current` symlink points to the active version, previous versions retained for rollback
- Keep the last 3 versions on the VPS, prune older ones
- Never auto-deploy — always require manual confirmation

### Background Processing
- Content generation runs in a background thread to avoid browser timeouts
- The site detail page polls an API endpoint for progress updates
- Phase 3+ can be upgraded to Celery + Redis in production if needed, but threading is fine for single-user dev use

---

## Environment Variables / Config

```
# .env (NEVER commit this — it's in .gitignore)
FLASK_SECRET_KEY=your-secret-key
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini

# VPS Deployment
VPS_HOST=your-server-ip
VPS_USER=deploy
VPS_SSH_KEY_PATH=~/.ssh/id_rsa
VPS_WEB_ROOT=/var/www/sites
NGINX_SITES_AVAILABLE=/etc/nginx/sites-available
NGINX_SITES_ENABLED=/etc/nginx/sites-enabled

# Database
DATABASE_URL=sqlite:///factory.db
```

```
# .env.example (committed to repo — placeholder values only)
FLASK_SECRET_KEY=change-me
OPENAI_API_KEY=sk-your-key-here
OPENAI_MODEL=gpt-4o-mini
VPS_HOST=0.0.0.0
VPS_USER=deploy
VPS_SSH_KEY_PATH=~/.ssh/id_rsa
VPS_WEB_ROOT=/var/www/sites
NGINX_SITES_AVAILABLE=/etc/nginx/sites-available
NGINX_SITES_ENABLED=/etc/nginx/sites-enabled
DATABASE_URL=sqlite:///factory.db
```

---

## .gitignore

```
# Environment
.env

# Database
*.db

# Python
__pycache__/
*.pyc
*.pyo
venv/

# Generated output
output/

# Uploaded assets
uploads/logos/

# OS
.DS_Store
```

---

## Seed Data

### GEOs (starter set)
| Code | Name | Language | Currency |
|---|---|---|---|
| gb | United Kingdom | en | GBP |
| de | Germany | de | EUR |
| br | Brazil | pt | BRL |
| ng | Nigeria | en | NGN |
| ca | Canada | en | CAD |
| in | India | en | INR |
| au | Australia | en | AUD |

### Verticals
| Slug | Name |
|---|---|
| sports-betting | Sports Betting |
| casino | Casino |
| esports-betting | Esports Betting |

### Page Types
| Slug | Name | Template |
|---|---|---|
| homepage | Homepage | homepage.html |
| comparison | Comparison Page | comparison.html |
| brand-review | Brand Review | brand_review.html |
| bonus-review | Brand Bonus Review | bonus_review.html |
| evergreen | Evergreen Content | evergreen.html |

---

## Notes for Claude Code

- **DEVIATION POLICY: If you need to change anything from this plan (schema, file structure, architecture, tech choices), you MUST explicitly state what you're changing and why BEFORE implementing it.** Do not silently deviate. The operator will confirm or reject the change. This applies to everything — column removals, new dependencies, relationship changes, file reorganization, all of it.
- **Always check this plan before building anything.** It's the source of truth for architecture and naming.
- **Follow the phase order.** Each phase builds on the last.
- **Use the exact file structure above.** Don't reorganize unless asked.
- **Use the exact DB schema above — including all unique constraints.** Don't add or rename columns unless asked.
- **Keep the control panel UI simple.** Bootstrap 5, no custom frontend framework. Functional over pretty.
- **Content generation must run in a background thread** from Phase 3 onward. Never block the request thread with OpenAI calls.
- **Generated site templates should be mobile-responsive** and SEO-friendly out of the box.
- **Use python-dotenv** for environment variables.
- **Use Fabric** (not raw Paramiko) for SSH deployment.
- **Always generate `sitemap.xml` and `robots.txt`** as part of the site build.
- **Logo uploads go to `uploads/logos/`** and are copied into the output folder during build.
- **Symlink-based deployment:** `current` → `releases/v{n}` on the VPS. Never overwrite in-place.
- **Content versioning:** Always snapshot to `content_history` before overwriting `content_json`.
- **Regeneration notes flow:** When regenerating with notes, append them to the base prompt, snapshot the old content + notes to `content_history`, then clear the notes from `site_pages` after successful generation.
- **Rebuild awareness:** After any page is added, updated, or regenerated, the site detail page must show a warning if the site hasn't been rebuilt since. Compare `site_pages.generated_at` against `sites.built_at`.
- **Custom robots.txt:** If `sites.custom_robots_txt` is not null, `site_builder.py` writes it verbatim. Otherwise, render the Jinja2 template as default.
- **`.env` must never be committed.** A `.env.example` with placeholder values is committed instead.
