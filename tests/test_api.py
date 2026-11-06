import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app import api
from app.auth import issue_session
from app.db import Base, Brand, Member, Project, User, get_db, make_engine


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'test-token')
    monkeypatch.setenv('OWNER_TELEGRAM_ID', '123')
    monkeypatch.setenv('SESSION_SECRET', 's' * 40)
    engine = make_engine('sqlite:///' + str(tmp_path / 'test.db'))
    monkeypatch.setattr(api, 'engine', engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    def db_override():
        with sessions() as db:
            yield db
    api.app.dependency_overrides[get_db] = db_override
    with TestClient(api.app) as client:
        yield client, sessions
    api.app.dependency_overrides.clear()
    engine.dispose()


def init_data(user_id=123, age=0, token='test-token'):
    values = {'auth_date': str(int(time.time()) - age), 'user': json.dumps({'id': user_id}, separators=(',', ':'))}
    check = '\n'.join(f'{k}={v}' for k, v in sorted(values.items()))
    secret = hmac.new(b'WebAppData', token.encode(), hashlib.sha256).digest()
    values['hash'] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


def test_auth_and_tenant_isolation(service):
    client, sessions = service
    assert client.get('/health/ready').status_code == 200
    assert 'Marketing studiyasi' in client.get('/').text
    assert client.get('/static/app.js').status_code == 200
    assert client.post('/api/v1/auth/telegram', json={'init_data': init_data(age=400)}).status_code == 401
    assert client.post('/api/v1/auth/telegram', json={'init_data': init_data(token='wrong')}).status_code == 401
    assert client.post('/api/v1/auth/telegram', json={'init_data': init_data(456)}).status_code == 403
    r = client.post('/api/v1/auth/telegram', json={'init_data': init_data()})
    assert r.status_code == 200
    owner_headers = {'Authorization': 'Bearer ' + r.json()['access_token']}
    projects = client.get('/api/v1/projects', headers=owner_headers).json()
    assert len(projects) == 3
    assert {p['name'] for p in projects} == {'Tamaddun', 'UC chi', 'UyTor'}
    for project in projects:
        budget = client.get(f"/api/v1/projects/{project['id']}/budget", headers=owner_headers).json()
        assert budget['monthly_limit_cents'] == 3000
        assert budget['paid_generation_enabled'] is False
    tamaddun = next(p for p in projects if p['name'] == 'Tamaddun')
    brand = client.get(f"/api/v1/projects/{tamaddun['id']}/brand", headers=owner_headers).json()
    assert brand['audience'] == 'Talabalar'
    p1, p2 = projects[:2]
    assert client.put(f"/api/v1/projects/{p1['id']}/brand", headers=owner_headers, json={'description': 'only project one'}).status_code == 200
    with sessions() as db:
        viewer = User(telegram_user_id=456)
        db.add(viewer)
        db.flush()
        db.add(Member(project_id=p2['id'], user_id=viewer.id, role='viewer'))
        db.commit()
        viewer_headers = {'Authorization': 'Bearer ' + issue_session(viewer.id)}
    assert client.get(f"/api/v1/projects/{p1['id']}/brand", headers=viewer_headers).status_code == 404
    assert client.get(f"/api/v1/projects/{p2['id']}/brand", headers=viewer_headers).status_code == 200
    assert client.put(f"/api/v1/projects/{p2['id']}/brand", headers=viewer_headers, json={'description':'forbidden'}).status_code == 403
    assert client.get('/api/v1/projects', headers={'Authorization': 'Bearer broken'}).status_code == 401
