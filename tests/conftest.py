import tempfile

import pytest
from sqlalchemy import event

from app import create_app
from app.models import db as _db
from app.seed import seed_all


@pytest.fixture(scope='session')
def app():
    """Create the Flask app with test config."""
    tmp_upload = tempfile.mkdtemp()
    app = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'WTF_CSRF_ENABLED': False,
        'UPLOAD_FOLDER': tmp_upload,
        'SECRET_KEY': 'test-secret',
    })
    with app.app_context():
        seed_all()
        yield app


@pytest.fixture(scope='function')
def db(app):
    """Provide a clean DB session per test.

    Wraps each test in a connection-level transaction that is rolled back
    after the test completes, so route handlers that call db.session.commit()
    don't leak data between tests.
    """
    with app.app_context():
        connection = _db.engine.connect()
        transaction = connection.begin()

        # Bind the session to this specific connection
        _db.session.configure(bind=connection)

        # Make db.session.commit() a no-op inside tests — the outer
        # transaction controls the actual commit/rollback.
        nested = connection.begin_nested()

        @event.listens_for(_db.session, 'after_transaction_end')
        def restart_savepoint(session, trans):
            nonlocal nested
            if trans.nested and not trans._parent.nested:
                nested = connection.begin_nested()

        yield _db

        # Clean up
        _db.session.remove()
        event.remove(_db.session, 'after_transaction_end', restart_savepoint)
        transaction.rollback()
        connection.close()


@pytest.fixture(scope='function')
def client(app, db):
    """Flask test client — depends on db so all changes are rolled back."""
    return app.test_client()
