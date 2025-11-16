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


def test_admin_user_edit_denied_logs_warning(monkeypatch, client, caplog):
    caplog.set_level('INFO', logger='swglogin')
    # standard user should be denied
    with client.session_transaction() as sess:
        sess['username'] = 'eve'
        sess['accesslevel'] = 'standard'
    resp = client.get('/admin_user_edit')
    assert resp.status_code == 403
    assert any('admin_user_edit denied' in r.getMessage() for r in caplog.records)


def test_admin_user_edit_get_logs_access(monkeypatch, client, caplog):
    caplog.set_level('INFO', logger='swglogin')
    with client.session_transaction() as sess:
        sess['username'] = 'root'
        sess['accesslevel'] = 'superadmin'
    resp = client.get('/admin_user_edit')
    assert resp.status_code == 200
    assert any('admin_user_edit GET' in r.getMessage() for r in caplog.records)


def test_admin_user_edit_invalid_access_level_logs(monkeypatch, client, caplog):
    caplog.set_level('INFO', logger='swglogin')
    with client.session_transaction() as sess:
        sess['username'] = 'root'
        sess['accesslevel'] = 'superadmin'
    resp = client.post('/admin_user_edit', data={
        'username': 'targetuser',
        'password': 'SomePass123!$',
        'accesslevel': 'invalid'
    })
    # Should return 200 (page re-render) and log invalid access level
    assert resp.status_code == 200
    assert any('invalid access level' in r.getMessage() for r in caplog.records)


def test_admin_user_edit_success_update_logs(monkeypatch, client, caplog):
    caplog.set_level('INFO', logger='swglogin')

    class UpdatingCursor(FakeCursor):
        def __init__(self, responses=None, rows=1):
            super().__init__(responses)
            self.rowcount = 0
            self._rows_target = rows

        def execute(self, sql, params=None):
            self._last_query = sql
            # Simulate update affecting rows
            if 'update user_account set password_hash' in sql.lower():
                self.rowcount = self._rows_target

    @contextmanager
    def updating_cursor_context(rows=1):
        cur = UpdatingCursor(rows=rows)
        try:
            yield cur
        finally:
            cur.close()

    # Monkeypatch cursor to return 1 updated row
    monkeypatch.setattr(app_module, 'cursor', lambda conn=None: updating_cursor_context(rows=1))
    with client.session_transaction() as sess:
        sess['username'] = 'root'
        sess['accesslevel'] = 'superadmin'
    resp = client.post('/admin_user_edit', data={
        'username': 'updateduser',
        'password': 'BetterPass123!$',
        'accesslevel': 'standard'
    })
    assert resp.status_code == 200
    assert any('Superadmin updated user: updateduser' in r.getMessage() for r in caplog.records)
    assert any('password complexity grade' in r.getMessage() for r in caplog.records)


def test_admin_user_edit_no_rows_update_logs(monkeypatch, client, caplog):
    caplog.set_level('INFO', logger='swglogin')

    class UpdatingCursor(FakeCursor):
        def __init__(self, responses=None, rows=0):
            super().__init__(responses)
            self.rowcount = 0
            self._rows_target = rows

        def execute(self, sql, params=None):
            self._last_query = sql
            if 'update user_account set password_hash' in sql.lower():
                self.rowcount = self._rows_target

    @contextmanager
    def updating_cursor_context(rows=0):
        cur = UpdatingCursor(rows=rows)
        try:
            yield cur
        finally:
            cur.close()

    monkeypatch.setattr(app_module, 'cursor', lambda conn=None: updating_cursor_context(rows=0))
    with client.session_transaction() as sess:
        sess['username'] = 'root'
        sess['accesslevel'] = 'superadmin'
    resp = client.post('/admin_user_edit', data={
        'username': 'missinguser',
        'password': 'SomePass123!$',
        'accesslevel': 'standard'
    })
    assert resp.status_code == 200
    assert any('no rows updated; user may not exist' in r.getMessage() for r in caplog.records)


def test_health_and_metrics_endpoints(client):
    # Health should return 200 (cursor patched, DB query succeeds trivially)
    h = client.get('/healthz')
    assert h.status_code in (200, 503)  # allow degraded scenario
    m = client.get('/metrics')
    assert m.status_code == 200
    # Basic metric presence
    assert b'swglogin_requests_total' in m.data


# Flask test client fixture
@pytest.fixture
def client():
    app = app_module.app
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c
