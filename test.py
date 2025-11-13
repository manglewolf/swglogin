import json
from contextlib import contextmanager
import types

import pytest

import app as app_module


class FakeCursor:
    def __init__(self, responses=None):
        # responses: dict mapping SQL to return values
        self._responses = responses or {}
        self._last_query = None

    def execute(self, sql, params=None):
        self._last_query = sql

    def fetchone(self):
        # simple behavior: return a configured user for any query that would fetch one
        if 'user' in self._responses:
            return self._responses.get('user')
        # fallback: return a count when appropriate
        if self._last_query and 'count' in (self._last_query or '').lower():
            return {'cnt': 3}
        return None

    def fetchall(self):
        return self._responses.get('all', [])

    def close(self):
        pass


@contextmanager
def fake_cursor_context(responses=None):
    cur = FakeCursor(responses=responses)
    try:
        yield cur
    finally:
        cur.close()


@pytest.fixture(autouse=True)
def patch_db_and_network(monkeypatch):
    """Patch out DB cursor and network port checks used by the app so tests don't require external services."""

    # Patch cursor() in the app module to our fake context manager factory
    def cursor_factory(conn=None, responses=None):
        return fake_cursor_context(responses=responses)

    monkeypatch.setattr(app_module, 'cursor', lambda conn=None: fake_cursor_context(responses={'user': None}))

    # Patch check_port to avoid real network calls
    monkeypatch.setattr(app_module, 'check_port', lambda *a, **k: True)

    yield


def test_index_returns_200(client):
    resp = client.get('/')
    assert resp.status_code == 200
    assert b'Online Players' in resp.data or b'<html' in resp.data


def test_auth_success(monkeypatch, client):
    # Arrange: prepare a user record and patch checkhashSSHA to match
    user = {
        'username': 'alice',
        'password_salt': 'salt',
        'password_hash': 'expectedhash',
        'accesslevel': 'standard',
    }

    def cursor_stub(conn=None):
        return fake_cursor_context(responses={'user': user})

    monkeypatch.setattr(app_module, 'cursor', cursor_stub)
    # Ensure checkhashSSHA returns whatever stored hash we provided for the fake user
    monkeypatch.setattr(app_module, 'checkhashSSHA', lambda salt, pw: user['password_hash'])

    # Act
    resp = client.post('/auth.php', data={'user_name': 'alice', 'user_password': 'pw'})

    # Assert
    assert resp.status_code == 200
    data = resp.get_json()
    assert data and data.get('message') == 'success'


def test_auth_rate_limit(monkeypatch, client):
    # Use a valid user so requests normally succeed
    user = {
        'username': 'bob',
        'password_salt': 's',
        'password_hash': 'h',
        'accesslevel': 'standard',
    }

    def cursor_stub(conn=None):
        return fake_cursor_context(responses={'user': user})

    monkeypatch.setattr(app_module, 'cursor', cursor_stub)
    monkeypatch.setattr(app_module, 'checkhashSSHA', lambda salt, pw: 'h')

    # Make 6 requests; limiter is 5 per minute so the 6th should be 429
    last_status = None
    for i in range(6):
        r = client.post('/auth.php', data={'user_name': 'bob', 'user_password': 'pw'})
        last_status = r.status_code
    assert last_status == 429


def test_post_login_success(monkeypatch, client):
    user = {
        'username': 'charlie',
        'password_salt': 'ss',
        'password_hash': 'hh',
        'accesslevel': 'standard',
    }

    def cursor_stub(conn=None):
        return fake_cursor_context(responses={'user': user})

    monkeypatch.setattr(app_module, 'cursor', cursor_stub)
    monkeypatch.setattr(app_module, 'checkhashSSHA', lambda salt, pw: 'hh')

    r = client.post('/post_login', data={'username': 'charlie', 'password': 'pw'})
    # Successful login redirects to index (302)
    assert r.status_code in (302, 200)


# Flask test client fixture
@pytest.fixture
def client():
    app = app_module.app
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c
