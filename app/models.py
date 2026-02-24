from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import validates

db = SQLAlchemy()


class Geo(db.Model):
    __tablename__ = 'geos'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.Text, unique=True, nullable=False)
    name = db.Column(db.Text, nullable=False)
    language = db.Column(db.Text, nullable=False)
    currency = db.Column(db.Text, nullable=False)
    regulation_notes = db.Column(db.Text)

    brand_geos = db.relationship('BrandGeo', back_populates='geo', cascade='all, delete-orphan')
    sites = db.relationship('Site', back_populates='geo')


class Vertical(db.Model):
    __tablename__ = 'verticals'

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.Text, unique=True, nullable=False)
    name = db.Column(db.Text, nullable=False)

    brand_verticals = db.relationship('BrandVertical', back_populates='vertical', cascade='all, delete-orphan')
    sites = db.relationship('Site', back_populates='vertical')


class Brand(db.Model):
    __tablename__ = 'brands'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.Text, nullable=False)
    slug = db.Column(db.Text, unique=True, nullable=False)
    logo_filename = db.Column(db.Text)
    website_url = db.Column(db.Text)
    affiliate_link = db.Column(db.Text)
    description = db.Column(db.Text)
    founded_year = db.Column(db.Integer)
    rating = db.Column(db.Float)
    parent_company = db.Column(db.Text)
    support_methods = db.Column(db.Text)
    support_email = db.Column(db.Text)
    available_languages = db.Column(db.Text)
    has_ios_app = db.Column(db.Boolean, default=False)
    has_android_app = db.Column(db.Boolean, default=False)

    brand_geos = db.relationship('BrandGeo', back_populates='brand', cascade='all, delete-orphan')
    brand_verticals = db.relationship('BrandVertical', back_populates='brand', cascade='all, delete-orphan')
    site_brands = db.relationship('SiteBrand', back_populates='brand', cascade='all, delete-orphan')


class BrandGeo(db.Model):
    __tablename__ = 'brand_geos'
    __table_args__ = (
        db.UniqueConstraint('brand_id', 'geo_id', name='uq_brand_geo'),
    )

    id = db.Column(db.Integer, primary_key=True)
    brand_id = db.Column(db.Integer, db.ForeignKey('brands.id'), nullable=False)
    geo_id = db.Column(db.Integer, db.ForeignKey('geos.id'), nullable=False)
    welcome_bonus = db.Column(db.Text)
    bonus_code = db.Column(db.Text)
    license_info = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    payment_methods = db.Column(db.Text)
    withdrawal_timeframe = db.Column(db.Text)
    rating_bonus = db.Column(db.Float)
    rating_usability = db.Column(db.Float)
    rating_mobile_app = db.Column(db.Float)
    rating_payments = db.Column(db.Float)
    rating_support = db.Column(db.Float)
    rating_licensing = db.Column(db.Float)
    rating_rewards = db.Column(db.Float)

    brand = db.relationship('Brand', back_populates='brand_geos')
    geo = db.relationship('Geo', back_populates='brand_geos')


class BrandVertical(db.Model):
    __tablename__ = 'brand_verticals'
    __table_args__ = (
        db.UniqueConstraint('brand_id', 'vertical_id', name='uq_brand_vertical'),
    )

    id = db.Column(db.Integer, primary_key=True)
    brand_id = db.Column(db.Integer, db.ForeignKey('brands.id'), nullable=False)
    vertical_id = db.Column(db.Integer, db.ForeignKey('verticals.id'), nullable=False)

    brand = db.relationship('Brand', back_populates='brand_verticals')
    vertical = db.relationship('Vertical', back_populates='brand_verticals')


class PageType(db.Model):
    __tablename__ = 'page_types'

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.Text, unique=True, nullable=False)
    name = db.Column(db.Text, nullable=False)
    template_file = db.Column(db.Text, nullable=False)
    content_prompt = db.Column(db.Text)

    site_pages = db.relationship('SitePage', back_populates='page_type')


class Domain(db.Model):
    __tablename__ = 'domains'

    id = db.Column(db.Integer, primary_key=True)
    domain = db.Column(db.Text, unique=True, nullable=False)
    registrar = db.Column(db.Text)
    status = db.Column(db.Text, default='available', nullable=False)
    ssl_provisioned = db.Column(db.Boolean, default=False, nullable=False)

    site = db.relationship('Site', back_populates='domain', uselist=False)


class Site(db.Model):
    __tablename__ = 'sites'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.Text, nullable=False)
    geo_id = db.Column(db.Integer, db.ForeignKey('geos.id'), nullable=False)
    vertical_id = db.Column(db.Integer, db.ForeignKey('verticals.id'), nullable=False)
    domain_id = db.Column(db.Integer, db.ForeignKey('domains.id'), nullable=True)
    status = db.Column(db.Text, default='draft', nullable=False)
    output_path = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    deployed_at = db.Column(db.DateTime)
    built_at = db.Column(db.DateTime)
    current_version = db.Column(db.Integer, default=1)
    custom_robots_txt = db.Column(db.Text)
    freshness_threshold_days = db.Column(db.Integer, default=30)
    custom_head = db.Column(db.Text)  # Site-wide custom HTML for <head>
    tips_leagues = db.Column(db.Text, nullable=True)  # JSON array of league configs for tips pipeline
    default_author_id = db.Column(db.Integer, db.ForeignKey('authors.id'), nullable=True)

    geo = db.relationship('Geo', back_populates='sites')
    vertical = db.relationship('Vertical', back_populates='sites')
    domain = db.relationship('Domain', back_populates='site', foreign_keys=[domain_id])
    site_brands = db.relationship('SiteBrand', back_populates='site', cascade='all, delete-orphan')
    site_pages = db.relationship('SitePage', back_populates='site', cascade='all, delete-orphan')


class SiteBrand(db.Model):
    __tablename__ = 'site_brands'
    __table_args__ = (
        db.UniqueConstraint('site_id', 'brand_id', name='uq_site_brand'),
    )

    id = db.Column(db.Integer, primary_key=True)
    site_id = db.Column(db.Integer, db.ForeignKey('sites.id'), nullable=False)
    brand_id = db.Column(db.Integer, db.ForeignKey('brands.id'), nullable=False)
    rank = db.Column(db.Integer, nullable=False)

    site = db.relationship('Site', back_populates='site_brands')
    brand = db.relationship('Brand', back_populates='site_brands')
    override = db.relationship('SiteBrandOverride', back_populates='site_brand', uselist=False, cascade='all, delete-orphan')


class SiteBrandOverride(db.Model):
    __tablename__ = 'site_brand_overrides'

    id = db.Column(db.Integer, primary_key=True)
    site_brand_id = db.Column(db.Integer, db.ForeignKey('site_brands.id'), unique=True, nullable=False)
    custom_description = db.Column(db.Text)
    custom_selling_points = db.Column(db.Text)  # JSON array of strings
    custom_affiliate_link = db.Column(db.Text)
    custom_welcome_bonus = db.Column(db.Text)
    custom_bonus_code = db.Column(db.Text)
    internal_notes = db.Column(db.Text)

    site_brand = db.relationship('SiteBrand', back_populates='override')


class SitePage(db.Model):
    __tablename__ = 'site_pages'
    __table_args__ = (
        # Partial unique indexes to handle the three page categories:
        # 1. Global pages (homepage, comparison): unique per (site, page_type) when no brand or topic
        # 2. Brand pages (reviews): unique per (site, page_type, brand)
        # 3. Evergreen pages: unique per (site, page_type, evergreen_topic)
        db.Index(
            'ix_site_page_global',
            'site_id', 'page_type_id',
            unique=True,
            sqlite_where=db.text('brand_id IS NULL AND evergreen_topic IS NULL'),
            postgresql_where=db.text('brand_id IS NULL AND evergreen_topic IS NULL'),
        ),
        db.Index(
            'ix_site_page_brand',
            'site_id', 'page_type_id', 'brand_id',
            unique=True,
            sqlite_where=db.text('brand_id IS NOT NULL'),
            postgresql_where=db.text('brand_id IS NOT NULL'),
        ),
        db.Index(
            'ix_site_page_evergreen',
            'site_id', 'page_type_id', 'evergreen_topic',
            unique=True,
            sqlite_where=db.text('evergreen_topic IS NOT NULL'),
            postgresql_where=db.text('evergreen_topic IS NOT NULL'),
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    site_id = db.Column(db.Integer, db.ForeignKey('sites.id'), nullable=False)
    page_type_id = db.Column(db.Integer, db.ForeignKey('page_types.id'), nullable=False)
    brand_id = db.Column(db.Integer, db.ForeignKey('brands.id'), nullable=True)
    evergreen_topic = db.Column(db.Text, nullable=True)
    slug = db.Column(db.Text, nullable=False)
    title = db.Column(db.Text, nullable=False)
    meta_title = db.Column(db.Text)  # SEO <title> — falls back to title if null
    meta_description = db.Column(db.Text)
    custom_head = db.Column(db.Text)  # Per-page custom HTML for <head>
    content_json = db.Column(db.Text)
    is_generated = db.Column(db.Boolean, default=False)
    generated_at = db.Column(db.DateTime)
    regeneration_notes = db.Column(db.Text)
    cta_table_id = db.Column(db.Integer, db.ForeignKey('cta_tables.id'), nullable=True)
    published_date = db.Column(db.DateTime, nullable=True)  # For news articles: display date
    fixture_id = db.Column(db.Integer, nullable=True)  # API-Football fixture ID for tips dedup
    author_id = db.Column(db.Integer, db.ForeignKey('authors.id'), nullable=True)

    # Menu management
    show_in_nav = db.Column(db.Boolean, default=False, nullable=False)
    show_in_footer = db.Column(db.Boolean, default=False, nullable=False)
    nav_order = db.Column(db.Integer, default=0, nullable=False)
    nav_label = db.Column(db.Text, nullable=True)  # NULL = use page title
    nav_parent_id = db.Column(db.Integer, db.ForeignKey('site_pages.id', ondelete='SET NULL'), nullable=True)
    menu_updated_at = db.Column(db.DateTime, nullable=True)

    site = db.relationship('Site', back_populates='site_pages')
    page_type = db.relationship('PageType', back_populates='site_pages')
    brand = db.relationship('Brand')
    cta_table = db.relationship('CTATable', back_populates='pages')
    author = db.relationship('Author')
    content_history = db.relationship('ContentHistory', back_populates='site_page', cascade='all, delete-orphan')
    nav_parent = db.relationship('SitePage', remote_side='SitePage.id',
                                 backref=db.backref('nav_children', lazy='select'))

    @validates('nav_parent_id')
    def _validate_nav_parent(self, key, parent_id):
        if parent_id is not None:
            if self.id is not None and parent_id == self.id:
                raise ValueError('A page cannot be its own parent')
            parent = db.session.get(SitePage, parent_id)
            if parent is None:
                raise ValueError(f'Parent page {parent_id} does not exist')
            if parent.nav_parent_id is not None:
                raise ValueError('Cannot nest more than one level deep')
        return parent_id


class ContentHistory(db.Model):
    __tablename__ = 'content_history'

    id = db.Column(db.Integer, primary_key=True)
    site_page_id = db.Column(db.Integer, db.ForeignKey('site_pages.id'), nullable=False)
    content_json = db.Column(db.Text, nullable=False)
    generated_at = db.Column(db.DateTime, nullable=False)
    regeneration_notes = db.Column(db.Text)
    version = db.Column(db.Integer, nullable=False)

    site_page = db.relationship('SitePage', back_populates='content_history')


class Author(db.Model):
    __tablename__ = 'authors'
    __table_args__ = (
        db.UniqueConstraint('site_id', 'slug', name='uq_author_slug'),
    )

    id = db.Column(db.Integer, primary_key=True)
    site_id = db.Column(db.Integer, db.ForeignKey('sites.id'), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(200), nullable=False)
    bio = db.Column(db.Text)
    short_bio = db.Column(db.String(500))
    role = db.Column(db.String(100))
    avatar_filename = db.Column(db.String(300))
    expertise = db.Column(db.Text)      # JSON array
    social_links = db.Column(db.Text)   # JSON object
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    site = db.relationship('Site', backref='authors', foreign_keys=[site_id])


class CTATable(db.Model):
    __tablename__ = 'cta_tables'
    __table_args__ = (
        db.UniqueConstraint('site_id', 'slug', name='uq_cta_table_slug'),
    )

    id = db.Column(db.Integer, primary_key=True)
    site_id = db.Column(db.Integer, db.ForeignKey('sites.id'), nullable=False)
    name = db.Column(db.Text, nullable=False)
    slug = db.Column(db.Text, nullable=False)

    site = db.relationship('Site', backref='cta_tables')
    rows = db.relationship('CTATableRow', back_populates='cta_table', cascade='all, delete-orphan',
                           order_by='CTATableRow.rank')
    pages = db.relationship('SitePage', back_populates='cta_table')


class CTATableRow(db.Model):
    __tablename__ = 'cta_table_rows'
    __table_args__ = (
        db.UniqueConstraint('cta_table_id', 'brand_id', name='uq_cta_row_brand'),
    )

    id = db.Column(db.Integer, primary_key=True)
    cta_table_id = db.Column(db.Integer, db.ForeignKey('cta_tables.id'), nullable=False)
    brand_id = db.Column(db.Integer, db.ForeignKey('brands.id'), nullable=False)
    rank = db.Column(db.Integer, nullable=False)
    custom_bonus_text = db.Column(db.Text)
    custom_cta_text = db.Column(db.Text)  # e.g. "Claim Free Bets" — default: "Visit Site"
    custom_badge = db.Column(db.Text)  # e.g. "Editor's Pick", "Best Odds"
    is_visible = db.Column(db.Boolean, default=True)

    cta_table = db.relationship('CTATable', back_populates='rows')
    brand = db.relationship('Brand')
