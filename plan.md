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
- `cta_tables.slug` must be **unique**.
- `cta_table_rows` must have a **unique constraint** on `(cta_table_id, brand_id)`.
- `site_brand_overrides` must have a **unique constraint** on `(site_id, brand_id)`.
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
| ssl_provisioned | BOOLEAN | Default False — set to True after Certbot successfully provisions SSL. Used by deployer to generate SSL-aware Nginx configs on redeploy. |

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
| custom_head | TEXT | Nullable — raw HTML injected into `<head>` on every page of this site (site-wide tracking, analytics, etc.) |
| freshness_threshold_days | INTEGER | Default 30 — pages older than this are flagged as stale on the dashboard |
| tips_leagues | TEXT | Nullable — JSON array of league configs for tips pipeline, e.g. `[{"league_id": 39, "name": "Premier League", "season": 2025}]` |
| default_author_id | INTEGER FK | Nullable → authors.id — auto-assigned to new pages created by tips pipeline |
| comments_enabled | BOOLEAN | Default False — enables the comments widget on article pages |
| comments_api_url | TEXT | Nullable — base URL for comments API (e.g. `http://64.227.131.193:8080`) |

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
| title | TEXT | Page title (used as H1 / display title) |
| meta_title | TEXT | Nullable — SEO `<title>` tag. If null, falls back to `title`. Often different from H1 for keyword targeting. |
| meta_description | TEXT | SEO meta |
| custom_head | TEXT | Nullable — raw HTML injected into `<head>` for this page (tracking pixels, canonical overrides, hreflang tags, etc.) |
| content_json | TEXT | JSON blob of generated content sections |
| is_generated | BOOLEAN | Whether LLM content has been generated |
| generated_at | DATETIME | Nullable — timestamp of last generation |
| regeneration_notes | TEXT | Nullable — custom instructions for the next generation (e.g. "focus on mobile app", "target keyword: best UK betting sites") |
| show_in_nav | BOOLEAN | Default False — whether this page appears in the navigation bar |
| show_in_footer | BOOLEAN | Default False — whether this page appears in the footer |
| nav_order | INTEGER | Default 0 — sort order for navigation menus |
| nav_label | TEXT | Nullable — custom nav/footer label. If null, uses page title |
| nav_parent_id | INTEGER FK | Nullable → site_pages.id — for dropdown sub-menus (max one level deep). Also controls URL nesting for evergreen pages: child pages build to `/{parent.slug}/{child.slug}` |
| menu_updated_at | DATETIME | Nullable — timestamp of last menu settings change (used for rebuild awareness) |
| published_date | DATETIME | Nullable — used for news articles (display and sort order) |
| cta_table_id | INTEGER FK | Nullable → cta_tables.id — assigns a reusable CTA table to this page (survives LLM regeneration) |
| fixture_id | INTEGER | Nullable — API-Football fixture ID for tips pipeline deduplication |
| author_id | INTEGER FK | Nullable → authors.id — page author for byline and E-E-A-T |
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

### `cta_tables`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | Auto |
| name | TEXT | Internal label, e.g. "UK Sports Betting CTA Table" |
| slug | TEXT UNIQUE | Used for referencing in templates, e.g. `uk-sports-main` |
| site_id | INTEGER FK | → sites.id — CTA tables are scoped to a site |
| created_at | DATETIME | Auto |
| updated_at | DATETIME | Auto |

CTA tables are reusable comparison/CTA components that can be embedded on any page within the same site. They're managed independently from page content, so updating a bonus in the CTA table updates it everywhere the table is referenced.

### `cta_table_rows`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | Auto |
| cta_table_id | INTEGER FK | → cta_tables.id |
| brand_id | INTEGER FK | → brands.id |
| rank | INTEGER | Display order |
| custom_bonus_text | TEXT | Nullable — overrides `brand_geos.welcome_bonus` for this table if set |
| custom_cta_text | TEXT | Nullable — e.g. "Claim Free Bets", "Start Playing" (default: "Visit Site") |
| custom_badge | TEXT | Nullable — e.g. "Editor's Pick", "Best Odds", "New" |
| is_visible | BOOLEAN | Default True — toggle rows on/off without deleting |
| **UNIQUE** | | **(cta_table_id, brand_id)** |

### `site_brand_overrides`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | Auto |
| site_id | INTEGER FK | → sites.id |
| brand_id | INTEGER FK | → brands.id |
| custom_description | TEXT | Nullable — overrides `brands.description` for this site |
| custom_selling_points | TEXT | Nullable — JSON array of strings, overrides selling points for this site |
| custom_affiliate_link | TEXT | Nullable — overrides `brands.affiliate_link` for this site (e.g. different sub-ID) |
| custom_welcome_bonus | TEXT | Nullable — overrides `brand_geos.welcome_bonus` for this site |
| custom_bonus_code | TEXT | Nullable — overrides `brand_geos.bonus_code` for this site |
| notes | TEXT | Nullable — internal notes, e.g. "This site focuses on live betting for this brand" |
| **UNIQUE** | | **(site_id, brand_id)** |

This table allows per-site customisation of brand data without changing the global brand record. When `site_builder.py` assembles template data, it checks for overrides and merges them on top of the base brand + brand_geo data. If an override field is null, the global value is used.

### `authors`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | Auto |
| site_id | INTEGER FK | → sites.id |
| name | VARCHAR(200) | Author display name |
| slug | VARCHAR(200) | URL slug for author profile page |
| bio | TEXT | Full bio (rendered as HTML) |
| short_bio | VARCHAR(500) | Short bio for cards/bylines |
| role | VARCHAR(100) | e.g. "Senior Sports Analyst" |
| avatar_filename | VARCHAR(300) | Filename in `uploads/avatars/` |
| expertise | TEXT | JSON array of expertise tags |
| social_links | TEXT | JSON object `{ "twitter": "url", ... }` |
| is_active | BOOLEAN | Default True |
| created_at | DATETIME | Auto |
| **UNIQUE** | | **(site_id, slug)** |

### `comment_users`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | Auto |
| site_id | INTEGER FK | → sites.id |
| username | VARCHAR(100) | Forum username |
| display_name | VARCHAR(200) | Display name |
| avatar_style | VARCHAR(50) | DiceBear style (default: `bottts`) |
| avatar_seed | VARCHAR(100) | Seed for procedural avatar generation |
| persona_json | TEXT | AI-generated personality profile |
| is_bot | BOOLEAN | Default True |
| created_at | DATETIME | Auto |
| **UNIQUE** | | **(site_id, username)** |

### `comments`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | Auto |
| site_id | INTEGER FK | → sites.id |
| page_slug | VARCHAR(300) | Matches SitePage.slug |
| user_id | INTEGER FK | → comment_users.id |
| parent_id | INTEGER FK | Nullable → comments.id (single-level replies) |
| body | TEXT | Comment text |
| upvotes | INTEGER | Default 0 |
| downvotes | INTEGER | Default 0 |
| is_pinned | BOOLEAN | Default False |
| created_at | DATETIME | Auto |
| **INDEX** | | **(site_id, page_slug)** |

### `comment_votes`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | Auto |
| comment_id | INTEGER FK | → comments.id |
| user_id | INTEGER FK | → comment_users.id |
| value | INTEGER | +1 or -1 |
| **UNIQUE** | | **(comment_id, user_id)** |

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
│   │   ├── api.py                  ← AJAX endpoints (generation progress, page preview, robots.txt, site rename, menu order, tips pipeline, comments)
│   │   └── comments_api.py        ← Public comments API (CORS-enabled, served to static sites)
│   ├── services/
│   │   ├── __init__.py
│   │   ├── content_generator.py    ← OpenAI API integration (runs in background thread)
│   │   ├── site_builder.py         ← Renders templates → static files (sitemap, robots.txt, linking)
│   │   ├── deployer.py             ← SSH deployment via Fabric (symlink-based versioning)
│   │   ├── preview_renderer.py     ← Renders a single page template for live preview (returns HTML string)
│   │   ├── schema_generator.py     ← Generates JSON-LD structured data for each page type
│   │   ├── api_football.py         ← API-Football HTTP client (fixtures, H2H, odds, stats)
│   │   ├── tips_pipeline.py        ← Automated betting tips pipeline (fetch → generate → publish)
│   │   ├── persona_manager.py      ← AI persona generation for comment system
│   │   └── comment_seeder.py       ← Seeds AI-generated comments on article pages
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
│   │       ├── edit_page.html      ← Structured content editor with live preview + regeneration notes
│   │       ├── cta_tables.html     ← CTA table list + CRUD for a site
│   │       ├── cta_table_form.html ← Create/edit a CTA table and its rows
│   │       ├── brand_overrides.html ← Per-site brand override management
│   │       └── deploy.html
│   └── static/                     ← Control panel static assets
│       ├── css/
│       └── js/
├── uploads/                        ← User-uploaded assets
│   └── logos/                      ← Brand logos (uploaded via brand CRUD)
├── site_templates/                 ← Templates for the GENERATED affiliate sites
│   ├── base.html                   ← Base layout (header, footer, nav — includes site-wide linking + schema block)
│   ├── homepage.html
│   ├── comparison.html
│   ├── brand_review.html
│   ├── bonus_review.html
│   ├── evergreen.html
│   ├── news.html
│   ├── news_article.html
│   ├── tips.html                   ← Tips landing page (lists upcoming match tips)
│   ├── tips_article.html           ← Individual match tip/prediction page
│   ├── author.html                 ← Individual author profile page
│   ├── authors.html                ← Authors landing page (/authors/)
│   ├── _cta_table.html             ← Reusable CTA table partial ({% include '_cta_table.html' %})
│   ├── _byline.html                ← Author byline partial (included in 5 article templates)
│   ├── _comments.html              ← Comments widget partial (included in 5 article templates)
│   ├── sitemap.xml                 ← Jinja2 template for sitemap generation
│   ├── robots.txt                  ← Jinja2 template for robots.txt
│   └── assets/                     ← CSS/JS/images for generated sites
│       ├── css/
│       │   └── style.css
│       ├── js/
│       │   ├── main.js
│       │   └── comments.js         ← Comments widget (fetches + renders from API)
│       └── img/
├── scripts/
│   └── run_tips.py                 ← Cron entry point for daily tips pipeline
└── output/                         ← Generated static sites land here
    └── {site_id}_{slug}/
        ├── v1/                     ← Versioned build folders
        │   ├── index.html
        │   ├── comparison.html
        │   ├── reviews/
        │   │   ├── bet365.html
        │   │   └── ...
        │   ├── bonuses/
        │   │   └── bet365.html
        │   ├── news/
        │   │   ├── index.html             ← News landing page
        │   │   └── article-slug.html
        │   ├── tips/
        │   │   ├── index.html             ← Tips landing page
        │   │   └── 2026-02-24-arsenal-vs-chelsea.html
        │   ├── how-to-deposit/              ← Parent evergreen page creates a folder
        │   │   └── how-to-deposit-opay.html ← Child evergreen pages nest inside
        │   ├── favicon.svg         ← Auto-generated SVG favicon
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
| Evergreen (child) | `/{parent_slug}/{child_slug}.html` | `/how-to-deposit/how-to-deposit-with-opay.html` |
| News Landing | `/news/index.html` | `/news/` |
| News Article | `/news/{article_slug}.html` | `/news/new-betting-regulations-2026.html` |
| Tips Landing | `/tips/index.html` | `/tips/` |
| Tips Article | `/tips/{slug}.html` | `/tips/2026-02-24-arsenal-vs-chelsea.html` |

### Navigation
- `base.html` renders a nav bar from each page's `show_in_nav` setting — no hardcoded links.
- Brand review and bonus review pages are linked from: the comparison table rows, the homepage brand grid, and each other (review ↔ bonus cross-links).
- Every page includes a footer with links to all pages where `show_in_footer` is True.
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
   - Loads `site_brand_overrides` and merges override data on top of base brand + brand_geo data (see Brand Data Layering in Key Design Decisions)
   - Resolves CTA tables: for pages with a `cta_table_slug` in content_json, loads the corresponding `cta_tables` + `cta_table_rows` data
   - Generates `nav_links` and `footer_links` lists from the site's pages (see Internal Linking Strategy above)
   - For each page, calls `schema_generator.py` to produce JSON-LD structured data
   - For each page, renders the corresponding `site_templates/*.html` with the content data + nav/footer links + CTA table data + schema JSON-LD + custom_head
   - Copies assets (CSS, JS) into the output folder
   - **Copies brand logos** from `uploads/logos/` into `output/{site}/v{n}/assets/logos/` for all brands in the site
   - Generates `sitemap.xml` from the sitemap template (lists all pages with lastmod dates)
   - Generates `robots.txt`: if `sites.custom_robots_txt` is set, uses that verbatim; otherwise renders from the robots.txt Jinja2 template (points to sitemap URL using the assigned domain)
   - Outputs to versioned folder: `output/{site_id}_{slug}/v{version}/`
   - Increments `sites.current_version`
2. Create the Jinja2 site templates in `site_templates/`:
   - `base.html` — responsive layout, nav bar (from `nav_links`), footer (from `footer_links`). Includes `{{ site_custom_head | safe }}`, `{{ page_custom_head | safe }}`, and `{{ schema_json_ld | safe }}` blocks in `<head>`. Uses `{{ meta_title or title }}` for the `<title>` tag.
   - `homepage.html` — hero section, top brands grid with logos + affiliate links, intro content
   - `comparison.html` — comparison table with brand logos, bonuses, ratings, pros/cons, CTA buttons linking to affiliate URLs. Rows link to individual brand review pages.
   - `brand_review.html` — full review with pros/cons, bonus info, CTA buttons. Cross-links to bonus review page for same brand.
   - `bonus_review.html` — focused on the welcome offer, T&Cs, how to claim. Cross-links to full brand review.
   - `evergreen.html` — informational content page, with relevant brand CTAs woven in
   - `sitemap.xml` — standard XML sitemap
   - `robots.txt` — allows all, points to sitemap
3. Add a "Build Site" button on the site detail page — **always visible** (not gated on site status). The build route checks whether any page has `content_json`, not the status string. This ensures a site stuck in `failed` or `deployed` can still be rebuilt.
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
   - Generates and uploads an Nginx server block config. If `domain.ssl_provisioned` is True, the config includes SSL directives (listen 443, ssl_certificate paths, HTTP→HTTPS redirect) so Certbot's modifications are preserved on redeploy. If False, generates an HTTP-only config.
   - Reloads Nginx
   - On first deploy (when `ssl_provisioned` is False): runs Certbot to provision SSL, then sets `domain.ssl_provisioned = True`. Certbot failure is a warning, not fatal. On subsequent deploys: SSL config is baked into the Nginx config directly — Certbot does not need to run again.
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

**Note:** After adding new pages, the site must be **rebuilt** for the sitemap, nav links, and footer to include the new page. The site detail page should show a warning banner if there are pages that were generated/updated after the last build, or if menu settings have changed since the last build (i.e. site needs rebuilding).

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

1. Track the latest `generated_at` and `menu_updated_at` across all `site_pages` for the site
2. Compare against `sites.built_at` (updated by `site_builder.py` on each successful build)
3. If any page was generated after the last build, or any page's menu settings were changed after the last build, show a **warning banner**: "Content has changed since last build. Rebuild to update the static site."
4. The "Rebuild Site" button triggers the existing `site_builder.py` flow — it picks up all current `site_pages` (including newly added ones), regenerates the sitemap and nav links, and outputs a new versioned folder.

**Test:** Add a new evergreen page to an existing site. Generate its content. Verify the warning banner appears. Rebuild. Verify the new page appears in the sitemap, nav, and footer of the rebuilt site. Edit an existing page with regeneration notes, regenerate it, verify the content_history snapshot includes the notes.

---

### Phase 8: Content Editor & Advanced Features
**Goal:** Replace raw JSON editing with a structured content editor and live preview, add reusable CTA tables, auto-generated schema markup, per-site brand overrides, and content freshness monitoring.

This phase transforms the edit page experience from a developer-facing JSON editor into a proper CMS-like content management workflow.

#### 8.1 — Structured Content Editor with Live Preview

Replace the raw JSON content display in `edit_page.html` with a two-panel layout: structured form on the left, live preview iframe on the right.

1. **Structured Form (left panel):**
   - Dynamically generated based on the page's `page_type`. Each page type has a known JSON structure (defined in the content generation prompts), so the form fields map directly to the JSON keys.
   - **Homepage** fields: hero_title, hero_subtitle, hero_badge, hero_stats (repeating group), trust_items (repeating list), section_title, section_subtitle, why_trust_us_title, why_trust_us, faq (repeating question/answer pairs)
   - **Comparison** fields: hero_title, hero_subtitle, intro_paragraph, comparison_rows (repeating group: brand, bonus, rating, pros list, cons list, verdict), faq (repeating), closing_paragraph
   - **Brand Review** fields: hero_title, hero_subtitle, intro_paragraphs (repeating), pros (list), cons (list), features_sections (repeating heading/content), user_experience, verdict, faq (repeating)
   - **Bonus Review** fields: hero_title, hero_subtitle, bonus_overview (offer, code, min_deposit, wagering_requirements, validity), how_to_claim (ordered list), terms_summary, pros (list), cons (list), similar_offers, verdict, faq (repeating)
   - **Evergreen** fields: hero_title, hero_subtitle, intro_paragraph, sections (repeating heading/content), key_takeaways (list), faq (repeating), closing_paragraph
   - For repeating fields (FAQ pairs, pros/cons lists, sections), provide "Add" / "Remove" buttons to manage items dynamically.
   - On form change, assemble the JSON from the form fields and POST to the preview endpoint.

2. **Live Preview (right panel):**
   - An `<iframe>` that loads the rendered page from a preview endpoint.
   - **Preview endpoint:** `GET /api/sites/<site_id>/pages/<page_id>/preview` — calls `preview_renderer.py` which renders the page's site template with the current `content_json` and returns full HTML. This uses the same Jinja2 templates as `site_builder.py` but renders in-memory without writing to disk.
   - **Save + Refresh flow:** When the operator clicks "Save", the form data is assembled into JSON, saved to `site_pages.content_json`, and the iframe reloads to show the updated preview.
   - The preview should look identical to the final built page (same CSS, same template). Asset paths in the preview should resolve correctly — `preview_renderer.py` can serve assets from `site_templates/assets/` and logos from `uploads/logos/`.

3. **Form layout:**
   - Use Bootstrap 5 two-column grid: `col-lg-6` for the form, `col-lg-6` for the iframe.
   - The iframe panel should be sticky (stays visible while scrolling the form).
   - On mobile, the iframe stacks below the form with a "Preview" toggle button.

4. **Page settings (above the content form):**
   - Page Title (H1)
   - Meta Title (SEO `<title>` — separate field, falls back to Page Title if empty)
   - Meta Description
   - Slug (with change warning)
   - Custom Head HTML (textarea — for tracking pixels, canonical tags, hreflang, etc.)
   - CTA Table selector (dropdown of available CTA tables for this site — see 8.2)
   - Regeneration Notes (textarea — same as Phase 7.2)

5. **Actions:**
   - "Save" — saves all form fields to DB (page settings + content_json), refreshes preview
   - "Save & Regenerate" — saves page settings + regeneration notes, triggers LLM regeneration (overwrites content_json with fresh LLM output, snapshots old version to content_history)
   - "Cancel" — returns to site detail page

6. **Build `preview_renderer.py`:**
   - Takes a site_page record (or raw content_json + page_type)
   - Loads the corresponding site template from `site_templates/`
   - Builds the same template context that `site_builder.py` would (brand data, nav_links, footer_links, etc.)
   - Renders to an HTML string and returns it
   - Serves brand logos and CSS/JS assets via a Flask route so the preview renders correctly
   - Does NOT write to disk — this is purely for the preview iframe

#### 8.2 — Custom CTA Tables

Reusable comparison/CTA table components that can be embedded on any page and managed independently.

1. **CRUD for CTA tables:** Add a "CTA Tables" tab on the site detail page.
   - List all CTA tables for the site
   - "Create CTA Table" button → `cta_table_form.html`
   - Edit / Delete existing tables

2. **CTA Table Form (`cta_table_form.html`):**
   - Name and slug fields
   - Brand rows section: a sortable list of brands from the site's `site_brands`
   - Per brand row:
     - Rank (drag to reorder)
     - Custom bonus text (optional override of `brand_geos.welcome_bonus`)
     - Custom CTA button text (e.g. "Claim Free Bets" — default: "Visit Site")
     - Custom badge (e.g. "Editor's Pick", "Best Odds", "New")
     - Visibility toggle (show/hide without deleting)
   - "Add Brand" button to include a brand from the site's pool
   - Save creates/updates `cta_tables` + `cta_table_rows` records

3. **Embedding CTA tables in pages:**
   - The edit page form (8.1) includes a "CTA Table" dropdown selector per page
   - Store the selected CTA table as a FK column `site_pages.cta_table_id` → `cta_tables.id` (nullable). This survives LLM regeneration (which overwrites `content_json`) and is queryable. Do NOT store it inside `content_json`.
   - During build, `site_builder.py` checks `site_pages.cta_table_id`, loads the table + rows, and passes the data to the template as a `cta_table` variable
   - Site templates render the CTA table using a shared partial/include (e.g. `site_templates/_cta_table.html`) — a styled comparison block with brand logos, bonuses, badges, and CTA buttons

4. **Benefit:** Update a brand's bonus once in the CTA table → every page using that table reflects the change on next build. No need to regenerate content.

#### 8.3 — Schema Markup / Structured Data

Auto-generate JSON-LD structured data for each page type to improve search engine visibility.

1. **Build `schema_generator.py`:**
   - Takes a page type, content_json, brand data, and site metadata
   - Returns a JSON-LD `<script>` block ready to inject into `<head>`
   - Schema types by page:
     - **Brand Review:** `Review` schema — itemReviewed (Organization), reviewRating (star rating), author, datePublished
     - **Bonus Review:** `Review` schema — focused on the offer, with ratingValue
     - **Comparison:** `ItemList` schema — list of reviewed items with position and ratings
     - **Evergreen:** `Article` schema — headline, datePublished, dateModified, author, publisher
     - **Homepage:** `WebSite` schema — site name, URL, search action (optional)
     - **FAQ sections:** `FAQPage` schema — appended to any page that has FAQ content in its content_json

2. **Integration with site_builder.py:**
   - During build, call `schema_generator.py` for each page
   - Inject the returned JSON-LD into the page's `<head>` section
   - The base site template (`site_templates/base.html`) should include a `{% block schema %}{% endblock %}` or a template variable `{{ schema_json_ld | safe }}` for this

3. **Integration with custom_head:**
   - Auto-generated schema is injected automatically during build
   - If the operator adds manual schema via `custom_head` on a page, it's rendered alongside the auto-generated schema (not replacing it). The operator can disable auto-schema per page if needed via a checkbox in the edit form.

4. **No manual editing required** — schema is derived from existing data (ratings, content, brand info). It just works.

#### 8.4 — Brand Overrides per Site

Allow per-site customisation of brand data without changing the global brand record.

1. **Data model:** `site_brand_overrides` uses a FK to `site_brands.id` (not separate site_id + brand_id columns). This means one override per site-brand pair, and if a brand is removed from a site (`site_brands` row deleted), the override cascades out automatically — no orphans.

2. **Brand Overrides UI:** Add a "Brand Overrides" tab on the site detail page → `brand_overrides.html`
   - Lists all brands assigned to the site (from `site_brands`)
   - Per brand, show the current global values alongside editable override fields:
     - Custom Description (e.g. "For this casino site, emphasise the live dealer games")
     - Custom Selling Points (JSON array of strings)
     - Custom Affiliate Link (e.g. different sub-ID or campaign tag)
     - Custom Welcome Bonus (override the GEO-specific bonus for this site)
     - Custom Bonus Code
     - Internal Notes (never rendered — just for the operator)
   - Fields left blank inherit the global value. Show the global value as placeholder text.

3. **Data flow in `site_builder.py`:**
   - When assembling template context for a page, query `site_brand_overrides` for the site (via `site_brands`)
   - For each brand, merge overrides on top of base brand + brand_geo data:
     ```
     final_description = override.custom_description or brand.description
     final_affiliate_link = override.custom_affiliate_link or brand.affiliate_link
     final_welcome_bonus = override.custom_welcome_bonus or brand_geo.welcome_bonus
     ... etc
     ```
   - Templates receive the merged data — they don't need to know about overrides

4. **Use cases:**
   - Site A is a sports betting site → Bet365's description emphasises live betting and cash-out
   - Site B is a casino site → Bet365's description emphasises live dealer and slots
   - Different affiliate sub-IDs for tracking which site generates conversions
   - A temporary promotional bonus override without changing the master brand record

#### 8.5 — Content Freshness Alerts

Flag pages and sites that haven't been updated recently, so stale content doesn't go unnoticed.

1. **Per-site threshold:** `sites.freshness_threshold_days` (default 30). Configurable from the site detail page settings.

2. **Dashboard freshness widget:**
   - On the main dashboard, show a "Stale Content" alert card
   - Lists sites that have pages older than their threshold
   - Format: "Top Aussie Casinos — 4 pages older than 30 days"
   - Click to go to the site detail page

3. **Site detail page freshness indicators:**
   - In the sitemap viewer (7.3), add a "Freshness" column
   - Pages where `generated_at` is older than `freshness_threshold_days` show a warning badge: "Stale (45 days old)"
   - Pages with no `generated_at` show "Not Generated"
   - Fresh pages show a green indicator
   - Summary at the top: "3 of 12 pages are stale"

4. **Freshness is based on `generated_at`** — not when the page was created, but when its content was last generated or regenerated. This correctly handles pages that exist but haven't been refreshed.

5. **No auto-regeneration** — freshness alerts are informational only. The operator decides when to regenerate. This avoids surprise API costs and unwanted content changes.

**Test:** Create a site with 5 pages. Generate all content. Wait (or manually backdate `generated_at` in the DB). Verify stale indicators appear on the dashboard and site detail page. Set threshold to 7 days, verify thresholds update. Regenerate a stale page, verify it becomes fresh.

---

### Phase 9: Automated Betting Tips Pipeline
**Goal:** Fully automated daily pipeline that fetches upcoming football fixtures from API-Football, generates AI match tips/predictions, and publishes them as pages under `/tips/`. Runs via daily cron — fully automated after initial config.

#### 9.1 — API-Football Integration

1. **`app/services/api_football.py`** — HTTP client for API-Football (v3, free tier: 100 req/day):
   - `APIFootballClient` class with per-day rate limiting (`_request_count` ceiling at 100)
   - `get_fixtures(league_id, season, next_hours=48)` — upcoming matches (status=NS)
   - `get_h2h(team1_id, team2_id, last=5)` — head-to-head records
   - `get_odds(fixture_id)` — pre-match odds
   - `get_team_stats(team_id, league_id, season)` — season stats + form
   - `build_match_data_package(client, fixture, league_id, season)` — aggregates H2H + odds + stats (3 API calls per match)
   - Custom exceptions: `APIFootballError`, `RateLimitError`
   - **Rate math:** Each match = 3 extra API calls (H2H, odds, stats). 20 matches x 3 + ~6 league fixture calls = ~66 of 100 daily quota.

2. **Config:** `API_FOOTBALL_KEY` and `TIPS_MAX_MATCHES_PER_DAY` in `config.py` / `.env`

#### 9.2 — Content Generation

1. **Prompt template `tips`** — short intro for the landing page
2. **Prompt template `tips-article`** — match preview prompt receiving `{match_data}` JSON. Returns:
   - `hero_title`, `hero_subtitle`, `match_info` (date, venue, competition, round)
   - `sections[]` (heading + content — AI match analysis)
   - `prediction` (result, confidence, reasoning)
   - `betting_tips[]` (market, selection, odds, reasoning)
   - `key_stats[]`, `faq[]`, `closing_paragraph`

#### 9.3 — Pipeline Service

**`app/services/tips_pipeline.py`** — `fetch_and_generate_tips(site_id)`:
1. Load site, parse `tips_leagues` JSON
2. For each league, fetch fixtures via `client.get_fixtures()` (next 48h)
3. For each fixture (skip if `fixture_id` already exists on any site page):
   - `build_match_data_package()` — 3 API calls
   - Build prompt with match data embedded
   - Call OpenAI → get content_json
   - Create SitePage (type: `tips-article`, slug: `{date}-{home}-vs-{away}`, fixture_id set)
   - Auto-parent to tips landing page
   - Commit per page (so failures don't lose earlier work)
4. If any pages created: `build_site()` + `deploy_site()` (if already deployed)

**Key decisions:**
- Dedup by `fixture_id` — idempotent across multiple cron runs
- Slug includes date prefix (`2026-02-24-arsenal-vs-chelsea`) to avoid rematch collisions
- `RateLimitError` breaks loop gracefully — already-created pages are kept

#### 9.4 — Site Templates

- **`tips.html`** — Tips landing page: hero, intro, CTA table, tips listing with competition badge, date, prediction pill (result + confidence), summary, "Read Tip" link
- **`tips_article.html`** — Individual tip: match info card, AI-generated sections, key stats, prediction card (result + confidence bar + reasoning), betting tips table, FAQ, responsible gambling disclaimer, "Back to Tips" nav

#### 9.5 — Admin UI

"Betting Tips Pipeline" collapsible card on site detail page:
- Textarea for `tips_leagues` JSON config (with common league ID hints)
- "Save Config" button → `POST /api/sites/<id>/tips-leagues`
- "Run Tips Pipeline" button → `POST /api/sites/<id>/run-tips` (background thread)
- Article count badge

#### 9.6 — Cron Script

**`scripts/run_tips.py`** — standalone entry point:
- Creates Flask app context
- Queries all sites where `tips_leagues IS NOT NULL`
- Runs `fetch_and_generate_tips(site_id)` for each
- Logs results

Cron entry: `0 6 * * * cd /opt/aff-web-gen && /opt/aff-web-gen/venv/bin/python scripts/run_tips.py >> /var/log/tips-pipeline.log 2>&1`

#### 9.7 — Schema & Model Changes

- `sites.tips_leagues` TEXT nullable — JSON array of league configs
- `site_pages.fixture_id` INTEGER nullable — API-Football fixture ID for deduplication
- Page types seeded: `tips` (Tips Landing, `tips.html`) and `tips-article` (Tips Article, `tips_article.html`)
- Auto-migrated in `_auto_migrate()`

**Test:** On a site detail page, configure tips_leagues JSON and save. Add a "Tips" page. Click "Run Tips Pipeline" — tips-article pages are created. Build site — tips landing shows fixture cards, individual tip pages render. Run `scripts/run_tips.py` — no duplicates (fixture_id dedup). Deploy — `/tips/` and `/tips/{slug}` pages are live.

---

### Phase 10: Author Profiles & E-E-A-T
**Goal:** Add author personas to boost E-E-A-T signals. Authors are site-scoped, AI-generated or manually created, and shown as bylines on articles and on dedicated profile pages.

#### 10.1 — Author Model
- `authors` table: `id`, `site_id` FK, `name`, `slug`, `bio`, `short_bio`, `role`, `avatar_filename`, `expertise` (JSON array), `social_links` (JSON object), `is_active`, `created_at`
- `UQ(site_id, slug)` — author slugs unique per site
- `site_pages.author_id` FK → `authors.id` — nullable, assigns an author to a page
- `sites.default_author_id` FK → `authors.id` — nullable, auto-assigned to new pages (tips pipeline uses this)

#### 10.2 — Author Generation
- Admin UI: "Authors & E-E-A-T" collapsible card on site detail page
- "Generate Authors" button → OpenAI generates 2-4 author personas per site (name, role, bio, expertise, social links)
- Authors listed with edit/delete controls, avatar upload support
- Author auto-assignment UI: dropdown to set default_author_id on site

#### 10.3 — Author Templates
- **`author.html`** — Individual author profile page: hero with avatar, name, role, short_bio; expertise tags; social links; full bio; article list (filtered to content types: brand-review, bonus-review, evergreen, news-article, tips-article)
- **`authors.html`** — Authors landing page (`/authors/`) listing all active authors
- **`_byline.html`** — Byline partial included in 5 article templates inside the content container
- Author avatar upload via API endpoint, stored in `uploads/avatars/`

#### 10.4 — Schema & SEO
- `Person` schema on author profile pages
- `author` field added to Article/Review schemas via schema_generator.py
- Author pages included in sitemap and footer navigation

#### 10.5 — Build Integration
- `site_builder.py` renders author profile pages + landing page, copies avatars to `output/assets/avatars/`
- `author_map` dict built from Author records, injected into all page contexts
- `preview_renderer.py` mirrors same author context

**Implemented:** Commits `46e7c17`, `2930904`

---

### Phase 11: Homepage Redesign — Dynamic Hub
**Goal:** Transform homepage from static SEO page to a dynamic hub showcasing tips, reviews, news, and authors.

#### Layout (6 Full-Width Sections, No Sidebar)
1. **Hero** — title + tagline + 2 CTA buttons ("Today's Tips", "Best Sportsbooks") + dynamic trust badges
2. **Tips Preview** — 4 most recent tip cards (horizontal scroll on mobile) with competition badge, prediction confidence
3. **Top Rated Brands** — top 5 brands as horizontal cards with logo, star rating, bonus, feature badges, CTA
4. **Latest News** — 3 most recent news cards with date + author
5. **Meet Our Experts** — author cards with avatar, role, article count (conditional)
6. **SEO Content** — why_trust_us + FAQ accordion + closing paragraph (below the fold)

#### Data Pipeline
- `site_builder.py` + `preview_renderer.py`: compute `tips_preview`, `news_preview`, `authors_list`, `page_counts`, `geo_name`, `compare_url` inside homepage block
- All data derived from existing `pages`, `author_map`, `nav_links`, `brand_info_list` — no new DB queries
- ~280 lines of `hp-`-prefixed CSS, responsive breakpoints at 1024/768/480px

**Implemented:** Commit `0414d6a`

---

### Phase 12: UGC Comments Module (Phase 1+2)
**Goal:** Dynamic comment system for static article pages. Comments served via Flask API (CORS), rendered by vanilla JS widget. AI personas seed realistic discussion threads.

#### 12.1 — Database Models
- **`comment_users`**: `id`, `site_id` FK, `username`, `display_name`, `avatar_style`, `avatar_seed`, `persona_json`, `is_bot`, `created_at`. `UQ(site_id, username)`
- **`comments`**: `id`, `site_id` FK, `page_slug`, `user_id` FK, `parent_id` FK (self-ref, nullable), `body`, `upvotes`, `downvotes`, `is_pinned`, `created_at`. `IX(site_id, page_slug)`
- **`comment_votes`**: `id`, `comment_id` FK, `user_id` FK, `value` (+1/-1). `UQ(comment_id, user_id)`
- **`sites`** additions: `comments_enabled` (Boolean default False), `comments_api_url` (Text nullable)

#### 12.2 — Comments API
- **`app/routes/comments_api.py`** — Blueprint `/comments-api`, CORS-enabled via `flask-cors`
- `GET /comments-api/<site_id>/<page_slug>` — returns `{ comments, count }` with nested replies, DiceBear avatar URLs, sorted by score (pinned first)
- `GET /comments-api/<site_id>/<page_slug>/count` — lightweight count
- Internal helpers: `seed_comment()`, `seed_votes()`

#### 12.3 — AI Persona Generation
- **`app/services/persona_manager.py`** — `generate_personas(site_id, count)`
- Uses `call_openai()` with geo-aware prompt for culturally-appropriate bot personas
- Creates CommentUser records with DiceBear avatar config + personality profile JSON
- Idempotent: skips existing usernames

#### 12.4 — Comment Seeding
- **`app/services/comment_seeder.py`** — `seed_comments_for_page(site_id, page_slug, page_title)`
- Picks 3-6 random bot personas, generates threaded comments via OpenAI
- Staggered timestamps, vote seeding (3-8 upvotes top-level, 1-3 for replies)
- Idempotent: skips pages with existing comments

#### 12.5 — Widget & Templates
- **`site_templates/assets/js/comments.js`** — Vanilla JS widget, read-only (no posting UI)
- **`site_templates/_comments.html`** — Partial included in 5 article templates, conditional on `comments_enabled`
- ~130 lines of `.comments-` prefixed CSS

#### 12.6 — Build Integration
- `site_builder.py` + `preview_renderer.py`: inject `comments_enabled`, `comments_api_url`, `site_id`, `page_slug` into context
- `comments.js` loaded in `base.html` after main.js

#### 12.7 — Tips Pipeline Hook
- Auto-seeds comments after each new tip is committed if `site.comments_enabled`

#### 12.8 — Admin UI & API
- "Comments" card on site detail page: enable toggle, API URL config, persona generation, seed-all button
- 5 admin endpoints: toggle-comments, save-comments-config, generate-personas, seed-comments, seed-all-comments

#### 12.9 — Dependencies
- `flask-cors==5.0.1`, `COMMENTS_API_URL` env var

**Implemented:** Commit `229b2f6`

---

## Key Design Decisions

### Site Management Hub
The site detail page (`/sites/<id>`) is the operator's primary workspace after initial site creation. It should feel like a lightweight CMS dashboard for that specific site — not just a status page. The Phase 2 wizard handles initial setup, but all ongoing work (adding pages, tweaking content, managing SEO, deploying) happens from the detail page. Design it accordingly.

### Content Structure
LLM-generated content is stored as **JSON blobs** in `site_pages.content_json`. This keeps things flexible — you can add new sections to templates without DB migrations. The site templates read from this JSON to populate the HTML. Previous versions are preserved in `content_history` for rollback.

### Content Editor Philosophy
The structured content editor (Phase 8.1) maps form fields to the known JSON keys for each page type. This means the form structure is tightly coupled to the content generation prompts — if you change what the LLM returns, the form needs to match. Keep the JSON structures stable and documented. The editor supports both **manual editing** (operator types in the fields directly) and **LLM regeneration** (operator provides notes, LLM overwrites the fields). Both flows write to the same `content_json` blob. The live preview iframe ensures the operator always sees the actual rendered output.

### CTA Tables vs Page Content
CTA tables are intentionally separate from `content_json`. Page content is LLM-generated and page-specific. CTA tables are manually curated, reusable across pages, and updated independently. When a bonus changes, you update the CTA table once — not every page. During build, `site_builder.py` merges CTA table data into the template context alongside the content_json data.

### Brand Data Layering
Brand data flows through three layers during build: (1) global `brands` table → (2) GEO-specific `brand_geos` → (3) site-specific `site_brand_overrides`. Each layer overrides the previous for non-null fields. Templates always receive the final merged data and never need to know which layer a value came from.

### Schema Markup
JSON-LD structured data is auto-generated during build, not stored in the DB. It's derived from existing data (ratings, content, brand info) so it stays in sync automatically. The `schema_generator.py` service is stateless — give it a page type and data, get back a JSON-LD block.

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

# API-Football (tips pipeline)
API_FOOTBALL_KEY=your-api-football-key
TIPS_MAX_MATCHES_PER_DAY=20
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
API_FOOTBALL_KEY=your-api-football-key
TIPS_MAX_MATCHES_PER_DAY=20
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
| news | News Landing | news.html |
| news-article | News Article | news_article.html |
| tips | Tips Landing | tips.html |
| tips-article | Tips Article | tips_article.html |

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
- **Rebuild awareness:** After any page is added, updated, regenerated, or has its menu settings changed, the site detail page must show a warning if the site hasn't been rebuilt since. Compare both `site_pages.generated_at` and `site_pages.menu_updated_at` against `sites.built_at`.
- **Build button is always visible** on the site detail page. The build route is gated on whether any page has `content_json` (not on `site.status`). This ensures sites in any status (including `failed`, `deployed`) can be rebuilt.
- **Custom robots.txt:** If `sites.custom_robots_txt` is not null, `site_builder.py` writes it verbatim. Otherwise, render the Jinja2 template as default.
- **Live preview:** `preview_renderer.py` renders pages in-memory using the same Jinja2 templates and context as `site_builder.py`. It does NOT write files to disk. Asset paths in previews must resolve correctly via Flask routes serving `site_templates/assets/` and `uploads/logos/`.
- **Structured editor forms:** The content editor form fields must match the JSON structure returned by the LLM for each page type. If the content prompt changes, the form must be updated to match. Keep these in sync.
- **CTA tables are separate from content_json.** The CTA table assignment is stored as `site_pages.cta_table_id` (FK), NOT inside `content_json` — this ensures it survives LLM regeneration. Resolved at build time by `site_builder.py` and passed to templates as a `cta_table` variable. Templates render them via a shared partial (`site_templates/_cta_table.html`).
- **Brand data layering:** When building template context, always check `site_brand_overrides` (FK to `site_brands.id`) and merge on top of base brand + brand_geo data. Null override fields = use global value. Overrides cascade-delete when the brand is removed from the site.
- **Schema markup:** Auto-generated by `schema_generator.py` at build time. Injected into `<head>` via a template variable (`{{ schema_json_ld | safe }}`). Not stored in the DB.
- **Custom head injection:** Both `sites.custom_head` (site-wide) and `site_pages.custom_head` (per-page) are rendered in the `<head>` section. Site-wide first, then page-specific. Both are raw HTML — no escaping.
- **Meta title fallback:** If `site_pages.meta_title` is null, use `site_pages.title` for the `<title>` tag. Templates should use `{{ meta_title or title }}`.
- **Content freshness is informational only.** Never auto-regenerate. The operator decides when and what to update.
- **`.env` must never be committed.** A `.env.example` with placeholder values is committed instead.
