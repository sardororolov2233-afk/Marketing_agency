from fastapi import FastAPI, Depends, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.content_api import create_content_router
from app.content_models import ContentDecision
from app.db import Base, Member, Project, User, get_db, make_engine


def test_durable_versions_approvals_and_project_permissions(tmp_path):
    engine = make_engine('sqlite:///' + str(tmp_path / 'content.db'))
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        owner = User(telegram_user_id=10)
        editor = User(telegram_user_id=11)
        outsider = User(telegram_user_id=12)
        db.add_all([owner, editor, outsider]); db.flush()
        project = Project(name='Test', slug='test', owner_id=owner.id)
        db.add(project); db.flush()
        db.add_all([Member(project_id=project.id, user_id=owner.id, role='owner'), Member(project_id=project.id, user_id=editor.id, role='editor')]); db.commit()
        ids = owner.id, editor.id, outsider.id, project.id
    owner_id, editor_id, outsider_id, project_id = ids

    def db_override():
        with sessions() as db:
            yield db

    def current_user(db=Depends(get_db)):
        return db.get(User, current_user.id)

    def permitted(db, project_id, user, roles=None):
        member = db.get(Member, (project_id, user.id))
        if not member:
            raise HTTPException(404, 'Project not found')
        if roles and member.role not in roles:
            raise HTTPException(403, 'Insufficient permissions')

    current_user.id = owner_id
    app = FastAPI()
    app.dependency_overrides[get_db] = db_override
    app.include_router(create_content_router(current_user, permitted))
    with TestClient(app) as client:
        response = client.post(f'/api/v1/projects/{project_id}/content', json={'channel': 'telegram', 'body': 'First'})
        assert response.status_code == 201, response.text
        draft = response.json(); content_id = draft['id']; v1 = draft['version']
        base = f'/api/v1/content/{content_id}'
        approval = {'version_id': v1['id'], 'checksum': v1['checksum']}
        assert client.post(base + '/decision', json={**approval, 'approved': True}).status_code == 409
        assert client.post(base + '/submit-review', json=approval).status_code == 200
        current_user.id = editor_id
        assert client.post(base + '/decision', json={**approval, 'approved': True}).status_code == 403
        current_user.id = outsider_id
        assert client.get(base).status_code == 404
        assert client.get(f'/api/v1/projects/{project_id}/content').status_code == 404
        current_user.id = owner_id
        assert client.post(base + '/decision', json={**approval, 'approved': True}).json()['state'] == 'approved'
        response = client.post(base + '/revise', json={'expected_version_id': v1['id'], 'body': 'Second'})
        assert response.status_code == 200, response.text
        v2 = response.json()['version']
        assert response.json()['state'] == 'draft' and v2['number'] == 2
        assert client.post(base + '/revise', json={'expected_version_id': v1['id'], 'body': 'Stale'}).status_code == 409
        assert client.post(base + '/decision', json={**approval, 'approved': True}).status_code == 409
        assert client.post(base + '/submit-review', json={'version_id': v2['id'], 'checksum': v1['checksum']}).status_code == 409
        assert [v['body'] for v in client.get(base + '/versions').json()] == ['First', 'Second']
    with sessions() as db:
        decisions = db.query(ContentDecision).all()
        assert len(decisions) == 1 and decisions[0].version_id == v1['id']
    engine.dispose()
