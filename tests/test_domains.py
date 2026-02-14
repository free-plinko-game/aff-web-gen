"""Phase 1 tests: Domain CRUD routes."""

from app.models import Domain


# --- 1.6 Domain CRUD Routes ---

class TestDomainCRUD:

    def test_domain_list_page(self, client):
        response = client.get('/domains/')
        assert response.status_code == 200

    def test_create_domain(self, client, db):
        data = {'domain': 'bestbets.co.uk', 'registrar': 'Namecheap'}
        response = client.post('/domains/new', data=data, follow_redirects=True)
        assert response.status_code == 200

        domain = Domain.query.filter_by(domain='bestbets.co.uk').first()
        assert domain is not None
        assert domain.status == 'available'
        assert domain.registrar == 'Namecheap'

    def test_create_duplicate_domain(self, client, db):
        data = {'domain': 'dupe.com'}
        client.post('/domains/new', data=data)

        response = client.post('/domains/new', data=data, follow_redirects=True)
        assert response.status_code == 200
        assert b'already exists' in response.data
        assert Domain.query.filter_by(domain='dupe.com').count() == 1

    def test_delete_domain(self, client, db):
        data = {'domain': 'todelete.com'}
        client.post('/domains/new', data=data)

        domain = Domain.query.filter_by(domain='todelete.com').first()
        response = client.post(f'/domains/{domain.id}/delete', follow_redirects=True)
        assert response.status_code == 200
        assert Domain.query.filter_by(domain='todelete.com').first() is None
