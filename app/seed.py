from .models import db, Geo, Vertical, PageType


def _get_or_create(model, defaults=None, **kwargs):
    """Get an existing record or create a new one. Idempotent."""
    instance = model.query.filter_by(**kwargs).first()
    if instance:
        return instance
    params = {**kwargs, **(defaults or {})}
    instance = model(**params)
    db.session.add(instance)
    return instance


def seed_geos():
    geos = [
        {'code': 'gb', 'name': 'United Kingdom', 'language': 'en', 'currency': 'GBP'},
        {'code': 'de', 'name': 'Germany', 'language': 'de', 'currency': 'EUR'},
        {'code': 'br', 'name': 'Brazil', 'language': 'pt', 'currency': 'BRL'},
        {'code': 'ng', 'name': 'Nigeria', 'language': 'en', 'currency': 'NGN'},
        {'code': 'ca', 'name': 'Canada', 'language': 'en', 'currency': 'CAD'},
        {'code': 'in', 'name': 'India', 'language': 'en', 'currency': 'INR'},
        {'code': 'au', 'name': 'Australia', 'language': 'en', 'currency': 'AUD'},
    ]
    for geo_data in geos:
        _get_or_create(Geo, code=geo_data['code'], defaults=geo_data)


def seed_verticals():
    verticals = [
        {'slug': 'sports-betting', 'name': 'Sports Betting'},
        {'slug': 'casino', 'name': 'Casino'},
        {'slug': 'esports-betting', 'name': 'Esports Betting'},
    ]
    for v_data in verticals:
        _get_or_create(Vertical, slug=v_data['slug'], defaults=v_data)


def seed_page_types():
    page_types = [
        {'slug': 'homepage', 'name': 'Homepage', 'template_file': 'homepage.html', 'content_prompt': ''},
        {'slug': 'comparison', 'name': 'Comparison Page', 'template_file': 'comparison.html', 'content_prompt': ''},
        {'slug': 'brand-review', 'name': 'Brand Review', 'template_file': 'brand_review.html', 'content_prompt': ''},
        {'slug': 'bonus-review', 'name': 'Brand Bonus Review', 'template_file': 'bonus_review.html', 'content_prompt': ''},
        {'slug': 'evergreen', 'name': 'Evergreen Content', 'template_file': 'evergreen.html', 'content_prompt': ''},
    ]
    for pt_data in page_types:
        _get_or_create(PageType, slug=pt_data['slug'], defaults=pt_data)


def seed_all():
    """Seed all reference data. Safe to call multiple times."""
    seed_geos()
    seed_verticals()
    seed_page_types()
    db.session.commit()
